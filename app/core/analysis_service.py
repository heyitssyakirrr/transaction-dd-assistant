from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.core.models import (
    AnalysisResult,
    AnalyzeTransactionsRequest,
    EvidenceItem,
    Finding,
    LlmClient,
)
from app.core.profiling import build_transaction_profile, compact_row
from app.core.prompts import ANALYST_SYSTEM_PROMPT, statement_payload
from app.core.transaction_adapter import normalize_transactions


class StatementTooLargeError(ValueError):
    """Raised before calling the LLM when the complete statement cannot fit."""


class AnalysisService:
    """Runs a complete-statement due-diligence analysis.

    UAT design: every transaction is included in one LLM request. There is no
    silent chunking, because that could hide relationships across transactions.
    """

    def __init__(self, llm: LlmClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def analyze_transactions(
        self,
        request: AnalyzeTransactionsRequest,
    ) -> AnalysisResult:
        rows = normalize_transactions(
            request.transactions,
            request.column_mapping,
        )

        compact_rows = [compact_row(row) for row in rows]
        self._assert_statement_fits(compact_rows)

        profile = build_transaction_profile(rows)

        final = self._llm.complete_json(
            system_prompt=ANALYST_SYSTEM_PROMPT,
            user_payload=statement_payload(
                request.source_filename,
                profile,
                compact_rows,
            ),
        )

        return self._validated_result(
            case_id=request.case_id,
            final=final,
            profile=profile,
            row_count=len(rows),
            valid_transaction_ids={row.transaction_id for row in rows},
        )

    def _assert_statement_fits(self, rows: list[dict[str, Any]]) -> None:
        compact_json = json.dumps(
            rows,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        # Conservative approximation: one token is approximately four chars.
        estimated_tokens = len(compact_json) // 4

        if estimated_tokens > self._settings.max_prompt_tokens:
            raise StatementTooLargeError(
                "The complete statement is approximately "
                f"{estimated_tokens:,} tokens, above the configured UAT limit "
                f"of {self._settings.max_prompt_tokens:,}. "
                "The statement was not sent to the LLM."
            )

    def _validated_result(
        self,
        case_id: str,
        final: dict[str, Any],
        profile: dict[str, Any],
        row_count: int,
        valid_transaction_ids: set[str],
    ) -> AnalysisResult:
        findings: list[Finding] = []

        for raw_finding in final.get("findings", []):
            evidence: list[EvidenceItem] = []

            for raw_evidence in raw_finding.get("evidence", []):
                transaction_ids = [
                    str(item)
                    for item in raw_evidence.get("transaction_ids", [])
                    if str(item) in valid_transaction_ids
                ]

                statement = str(raw_evidence.get("statement", "")).strip()

                if transaction_ids and statement:
                    evidence.append(
                        EvidenceItem(
                            transaction_ids=transaction_ids,
                            statement=statement,
                        )
                    )

            # Do not show an LLM finding that cannot be traced to a source row.
            if not evidence:
                continue

            findings.append(
                Finding(
                    finding_id=str(uuid4()),
                    category=str(
                        raw_finding.get("category", "uncategorized")
                    ),
                    severity=_safe_severity(raw_finding.get("severity")),
                    confidence=_safe_confidence(
                        raw_finding.get("confidence")
                    ),
                    rationale=str(
                        raw_finding.get(
                            "rationale",
                            "No rationale supplied.",
                        )
                    ),
                    evidence=evidence,
                    follow_up_questions=[
                        str(question)
                        for question in raw_finding.get(
                            "follow_up_questions",
                            [],
                        )
                    ],
                )
            )

        allowed_decisions = {
            "no_action",
            "monitor",
            "request_information",
            "enhanced_due_diligence",
            "escalate",
        }

        decision = final.get("decision", "monitor")
        if decision not in allowed_decisions:
            decision = "monitor"

        # Never allow a severe recommendation without traceable evidence.
        if not findings and decision in {
            "enhanced_due_diligence",
            "escalate",
        }:
            decision = "monitor"

        return AnalysisResult(
            case_id=case_id,
            status=(
                "needs_review"
                if self._settings.require_human_review
                else "completed"
            ),
            decision=decision,
            decision_rationale=str(
                final.get("decision_rationale", "Human review required.")
            ),
            executive_summary=str(
                final.get("executive_summary", "No summary supplied.")
            ),
            findings=findings,
            mitigating_factors=[
                str(item) for item in final.get("mitigating_factors", [])
            ],
            limitations=[
                str(item) for item in final.get("limitations", [])
            ]
            + ["LLM output is decision support and requires human review."],
            transactions_processed=row_count,
            chunks_processed=1,
            profile=profile,
            generated_at=datetime.now(timezone.utc),
        )


def _safe_severity(value: Any) -> str:
    allowed = {"low", "medium", "high", "critical"}
    return value if value in allowed else "medium"


def _safe_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.5