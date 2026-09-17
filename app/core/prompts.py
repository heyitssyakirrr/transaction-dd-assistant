from typing import Any


ANALYST_SYSTEM_PROMPT = """You are a bank transaction due-diligence assistant.

Analyse only the supplied customer context and transaction statement. Do not
invent transactions, facts, regulations, customer intentions, crimes, or
evidence. A detected pattern is an alert for human review, not proof of
wrongdoing.

Every finding must cite one or more transaction IDs supplied in the statement.
Do not summarize every transaction. Extract and summarize only material
transactions or groups, such as unusually large values, unusual frequency,
rapid movement of funds, concentrated/new counterparties, or transactions
relevant to a finding.

A lack of sufficient evidence is a valid conclusion. Return valid JSON only.
"""


def statement_payload(
    customer_context: dict[str, Any],
    profile: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task": (
            "Review the complete customer statement for unusual patterns and "
            "recommend whether human customer due diligence is needed."
        ),
        "customer_context": customer_context,
        "statement_profile": profile,
        "transactions": rows,
        "response_schema": {
            "decision": (
                "no_action|monitor|request_information|"
                "enhanced_due_diligence|escalate"
            ),
            "decision_rationale": "string",
            "executive_summary": (
                "string; summarize only material activity and uncertainty"
            ),
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