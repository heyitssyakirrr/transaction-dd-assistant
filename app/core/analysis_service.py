from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core.models import AnalysisResult, AnalyzeTransactionsRequest, CaseSynthesis, ChunkReport, EvidenceItem, EvidenceReview, Finding, LlmClient
from app.core.prompts import ANALYST_SYSTEM_PROMPT, chunk_payload, evidence_payload, final_payload, synthesis_payload
from app.core.transaction_adapter import normalize_transactions
from app.core.transaction_view import compact_row


class ModelOutputError(ValueError):
    """Raised when the LLM response is not valid for the required stage schema."""


ModelType = TypeVar("ModelType", bound=BaseModel)


class AnalysisService:
    """LLM-led AML workflow: chunk review, synthesis, verification, final result.

    Application code only normalizes, orders, partitions and routes data. It
    does not calculate an AML score, detect anomalies or write a summary.
    """

    def __init__(self, llm: LlmClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings
        # main.py creates this once, so the limit is global across all uploads.
        self._semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def analyze_transactions(self, request: AnalyzeTransactionsRequest) -> AnalysisResult:
        normalized = normalize_transactions(request.transactions, request.column_mapping)
        rows = [compact_row(row) for row in normalized]
        chunks = self._split(rows)

        reports = await asyncio.gather(*[
            self._review_chunk(index + 1, len(chunks), chunk)
            for index, chunk in enumerate(chunks)
        ])
        synthesis = await self._ask(
            synthesis_payload([report.model_dump(mode="json") for report in reports], self._settings.max_target_chunks),
            CaseSynthesis,
        )
        selected = self._valid_chunk_ids(synthesis.selected_chunk_ids, len(chunks))
        reviews = await asyncio.gather(*[
            self._verify_evidence(synthesis, group, chunks)
            for group in self._groups(selected, self._settings.max_target_chunks_per_review)
        ])
        final = await self._ask(
            final_payload(synthesis.model_dump(mode="json"), [review.model_dump(mode="json") for review in reviews]),
            _FinalOutput,
        )

        verified_ids = {
            transaction_id
            for review in reviews
            for finding in review.verified_findings
            for evidence in finding.evidence
            for transaction_id in evidence.transaction_ids
        }
        findings = self._validated_findings(final.verified_findings, verified_ids)
        decision, rationale = final.decision, final.decision_rationale
        if decision in {"enhanced_due_diligence", "escalate"} and not findings:
            decision = "monitor"
            rationale = "No material final finding was retained without verified raw-transaction evidence. Authorised human review is required."

        return AnalysisResult(
            case_id=request.case_id,
            status="needs_review",
            decision=decision,
            decision_rationale=rationale,
            executive_summary=final.executive_summary,
            findings=findings,
            mitigating_factors=[],
            limitations=list(dict.fromkeys(final.limitations + synthesis.limitations + [
                "Assessment uses only the uploaded transaction statement.",
                "LLM output is decision support and requires authorised human review.",
            ])),
            transactions_processed=len(rows),
            chunks_processed=len(chunks),
            risk_level=final.risk_level,
            generated_at=datetime.now(timezone.utc),
        )

    async def _review_chunk(self, chunk_id: int, total: int, chunk: list[dict[str, object]]) -> ChunkReport:
        report = await self._ask(chunk_payload(chunk_id, total, chunk), ChunkReport)
        report.chunk_id = chunk_id
        report.findings = self._validated_findings(report.findings, {str(row["id"]) for row in chunk})
        return report

    async def _verify_evidence(self, synthesis: CaseSynthesis, chunk_ids: list[int], chunks: list[list[dict[str, object]]]) -> EvidenceReview:
        hypotheses = [item.model_dump(mode="json") for item in synthesis.case_hypotheses if set(item.related_chunk_ids).intersection(chunk_ids)]
        raw_chunks = [{"chunk_id": chunk_id, "transactions": chunks[chunk_id - 1]} for chunk_id in chunk_ids]
        review = await self._ask(evidence_payload(hypotheses, raw_chunks), EvidenceReview)
        valid_ids = {str(row["id"]) for raw_chunk in raw_chunks for row in raw_chunk["transactions"]}
        review.verified_findings = self._validated_findings(review.verified_findings, valid_ids)
        return review

    async def _ask(self, payload: dict[str, object], model: type[ModelType]) -> ModelType:
        async with self._semaphore:
            raw = await self._llm.complete_json(system_prompt=ANALYST_SYSTEM_PROMPT, user_payload=payload)
        try:
            return model.model_validate(raw)
        except ValidationError as exc:
            raise ModelOutputError(f"LLM JSON does not match the required schema: {exc}") from exc

    def _split(self, rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
        if not rows:
            raise ValueError("The statement contains no valid transactions.")
        return [rows[index:index + self._settings.chunk_size] for index in range(0, len(rows), self._settings.chunk_size)]

    def _valid_chunk_ids(self, proposed: list[int], total: int) -> list[int]:
        selected: list[int] = []
        for chunk_id in proposed:
            if isinstance(chunk_id, int) and 1 <= chunk_id <= total and chunk_id not in selected:
                selected.append(chunk_id)
        return selected[:self._settings.max_target_chunks]

    @staticmethod
    def _groups(values: list[int], size: int) -> list[list[int]]:
        return [values[index:index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _validated_findings(findings: list[Finding], allowed_ids: set[str]) -> list[Finding]:
        retained: list[Finding] = []
        for finding in findings:
            evidence = [
                EvidenceItem(transaction_ids=item.transaction_ids, statement=item.statement)
                for item in finding.evidence
                if item.transaction_ids and set(item.transaction_ids).issubset(allowed_ids)
            ]
            if evidence:
                finding.finding_id = finding.finding_id or str(uuid4())
                finding.evidence = evidence
                retained.append(finding)
        return retained


class _FinalOutput(BaseModel):
    decision: Literal["no_action", "monitor", "request_information", "enhanced_due_diligence", "escalate"]
    decision_rationale: str
    executive_summary: str
    risk_level: Literal["low", "medium", "high"]
    verified_findings: list[Finding]
    limitations: list[str]
