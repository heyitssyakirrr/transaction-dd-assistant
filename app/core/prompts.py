from typing import Any


ANALYST_SYSTEM_PROMPT = """You are a bank transaction due-diligence assistant.

Analyse only the supplied bank transaction statement. Do not assume or invent
occupation, salary, source of wealth, customer identity, customer intent,
external risk profile, crimes, regulations, or information not present in the
statement.

A detected pattern is an alert for human review, not proof of wrongdoing.
Every finding must cite transaction IDs supplied in the statement.

Do not summarize every transaction. Extract and summarize only material
transactions or groups, such as unusually large values, unusual frequency,
rapid movement of funds, concentrated counterparties, or transactions directly
relevant to a finding.

Your recommendation must be based only on transaction activity:
- no_action
- monitor
- request_information
- enhanced_due_diligence
- escalate

Return valid JSON only.
"""


def statement_payload(
    source_filename: str,
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task": (
            "Review this complete bank transaction statement. Summarize material "
            "activity, identify transaction-based anomalies, and recommend whether "
            "customer due diligence should be considered by a human reviewer."
        ),
        "source_filename": source_filename,
        "statement_profile": profile,
        "transactions": rows,
        "response_schema": {
            "decision": (
                "no_action|monitor|request_information|"
                "enhanced_due_diligence|escalate"
            ),
            "decision_rationale": "string",
            "executive_summary": "string",
            "findings": [
                {
                    "category": "string",
                    "severity": "low|medium|high|critical",
                    "confidence": "number between 0 and 1",
                    "rationale": "string",
                    "evidence": [
                        {
                            "transaction_ids": ["transaction-id"],
                            "statement": "string",
                        }
                    ],
                    "follow_up_questions": ["string"],
                }
            ],
            "mitigating_factors": ["string"],
            "limitations": ["string"],
        },
    }