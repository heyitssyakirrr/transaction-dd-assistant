from __future__ import annotations

from typing import Any


ANALYST_SYSTEM_PROMPT = """You are an AML transaction-review analyst assisting bank staff.
Use only the supplied transaction data. 
Do not infer or invent customer occupation, income, source of wealth, intent, criminal conduct, external risk data, regulations, 
or facts absent from the statement. An unusual pattern is a review indicator, not proof of money laundering.

Every material finding must cite only supplied transaction IDs. 
Do not cite summaries as evidence. 
Do not report every transaction: report material activity only. Do not report routine, expected activity as a finding; an empty findings list is valid. Keep every text field brief. 
Clearly keep hypotheses separate from verified findings. 
Return JSON only and follow the requested schema exactly.
Return the object described by response_schema directly; never wrap it in a "response_schema" key.

Output format: respond with a single JSON object as compact, single-line JSON —
no line breaks, indentation, or extra whitespace inside it. Do not wrap it in
markdown or code fences. Output nothing before or after the JSON object: no
greeting, no explanation, no closing remark. Stop immediately after the final
closing brace."""


# --------------------------------------------------------------------------
# Shared schema fragments
# --------------------------------------------------------------------------
# "evidence" and "finding" describe the same shape everywhere they appear:
# a finding is only ever reported alongside the transaction IDs that support
# it. chunk_payload, evidence_payload, and final_payload each ask the model
# for a list of findings in this exact shape -- defined once here so the
# three call sites can't drift out of sync with each other over time.

_EVIDENCE_ITEM_SCHEMA: dict[str, Any] = {
    "transaction_ids": ["transaction_id (at most 5)"],
    "statement": "string, maximum 20 words",
}

_FINDING_SCHEMA: dict[str, Any] = {
    "category": "string, maximum 5 words",
    "severity": "low|medium|high|critical",
    "confidence": "number 0 to 1",
    "rationale": "string, maximum 30 words",
    "evidence": [_EVIDENCE_ITEM_SCHEMA],
}


def chunk_payload(chunk_id: int, total_chunks: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the model to review one chronological segment of the statement in
    isolation and flag any material, segment-local AML indicators."""
    task = (
        "Review every transaction in this chronological statement segment. "
        "Identify material patterns visible here, including unusual "
        "amount/frequency, rapid movement of funds, cash activity, "
        "concentrated or repeated counterparties, and other AML-relevant "
        "indicators. Flag only patterns that need comparison with other "
        "segments. Return at most 3 findings."
    )
    response_schema: dict[str, Any] = {
        "chunk_id": chunk_id,
        "material_activity_summary": "string, maximum 60 words",
        "findings": [_FINDING_SCHEMA],
        "entities_of_interest": ["counterparty or entity text, at most 5 entries"],
        "cross_chunk_review_needed": "boolean",
    }
    return {
        "task": task,
        "chunk_id": chunk_id,
        "total_chunks": total_chunks,
        "transactions": rows,
        "response_schema": response_schema,
    }


def synthesis_payload(reports: list[dict[str, Any]], max_selected_chunks: int) -> dict[str, Any]:
    """Ask the model to look across every chunk's report as one case and
    surface only patterns that span multiple segments."""
    task = (
        "Review reports from every chronological statement segment as one "
        "case. Identify only cross-segment patterns supported by the "
        "reports: repeated entities, recurring high-value flows, rapid "
        "in/out behaviour, recurring cash activity, or material changes "
        "over time. Select raw chunks for evidence verification; selected "
        "chunks are not evidence by themselves. Return at most 4 "
        "hypotheses and at most 3 limitations."
    )
    response_schema: dict[str, Any] = {
        "whole_statement_summary": "string, maximum 120 words",
        "case_hypotheses": [
            {
                "hypothesis_id": "H-001",
                "pattern": "string, maximum 20 words",
                "severity": "low|medium|high|critical",
                "related_chunk_ids": [1],
                "rationale": "string, maximum 40 words",
            }
        ],
        "selected_chunk_ids": [1],
        "limitations": ["string, maximum 20 words"],
    }
    return {
        "task": task,
        "chunk_reports": reports,
        "maximum_selected_chunk_ids": max_selected_chunks,
        "response_schema": response_schema,
    }


def evidence_payload(hypotheses: list[dict[str, Any]], raw_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the model to verify or challenge the synthesis stage's hypotheses
    against the original, unsummarised transactions."""
    task = (
        "Verify or challenge the hypotheses against these original raw "
        "transactions. Return a finding only if its cited transaction IDs "
        "directly support it. Do not convert an unverified hypothesis into "
        "a fact. If evidence is insufficient, put it in "
        "disproved_or_uncertain_hypotheses. Return at most 4 verified "
        "findings."
    )
    response_schema: dict[str, Any] = {
        "verified_findings": [_FINDING_SCHEMA],
        "disproved_or_uncertain_hypotheses": ["hypothesis id and explanation, maximum 20 words"],
    }
    return {
        "task": task,
        "hypotheses": hypotheses,
        "raw_chunks": raw_chunks,
        "response_schema": response_schema,
    }


def final_payload(synthesis: dict[str, Any], evidence_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the model to produce the final, human-reviewable AML decision
    from only the verified findings -- never from unverified hypotheses."""
    task = (
        "Produce the final transaction-only AML assessment. Base the "
        "decision only on verified findings, never on unverified "
        "hypotheses. no_action means no material concern is evidenced; "
        "monitor means low concern; request_information means activity "
        "needs explanation; enhanced_due_diligence needs a material, "
        "verified concern; escalate needs a severe, verified concern. This "
        "is a recommendation for authorised human review, never an account "
        "or regulatory decision. Return at most 5 verified findings and at "
        "most 3 limitations."
    )
    response_schema: dict[str, Any] = {
        "decision": "no_action|monitor|request_information|enhanced_due_diligence|escalate",
        "decision_rationale": "string, maximum 60 words",
        "executive_summary": "string, maximum 120 words; material activity only",
        "risk_level": "low|medium|high",
        "verified_findings": [_FINDING_SCHEMA],
        "limitations": ["string, maximum 20 words"],
    }
    return {
        "task": task,
        "whole_case_synthesis": synthesis,
        "verified_raw_evidence_reviews": evidence_reviews,
        "response_schema": response_schema,
    }