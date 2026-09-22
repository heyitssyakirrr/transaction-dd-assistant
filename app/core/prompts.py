from __future__ import annotations

from typing import Any


ANALYST_SYSTEM_PROMPT = """You are an AML transaction-review analyst assisting bank staff.
Use only the supplied transaction data. 
Do not infer or invent customer occupation, income, source of wealth, intent, criminal conduct, external risk data, regulations, 
or facts absent from the statement. An unusual pattern is a review indicator, not proof of money laundering.

Every material finding must cite only supplied transaction IDs. 
Do not cite summaries as evidence. 
Do not report every transaction: report material activity only. 
Clearly keep hypotheses separate from verified findings. 
Return JSON only and follow the requested schema exactly."""


def chunk_payload(chunk_id: int, total_chunks: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"task": "Review every transaction in this chronological statement segment. Identify material patterns visible here, including unusual amount/frequency, rapid movement of funds, cash activity, concentrated or repeated counterparties, and other AML-relevant indicators. Flag only patterns that need comparison with other segments.", "chunk_id": chunk_id, "total_chunks": total_chunks, "transactions": rows, "response_schema": {"chunk_id": chunk_id, "material_activity_summary": "string, maximum 250 words", "findings": [{"category": "string", "severity": "low|medium|high|critical", "confidence": "number 0 to 1", "rationale": "string", "evidence": [{"transaction_ids": ["transaction_id"], "statement": "string"}]}], "entities_of_interest": ["counterparty or entity text"], "cross_chunk_review_needed": "boolean"}}


def synthesis_payload(reports: list[dict[str, Any]], max_selected_chunks: int) -> dict[str, Any]:
    return {"task": "Review reports from every chronological statement segment as one case. Identify only cross-segment patterns supported by the reports: repeated entities, recurring high-value flows, rapid in/out behaviour, recurring cash activity, or material changes over time. Select raw chunks for evidence verification; selected chunks are not evidence by themselves.", "chunk_reports": reports, "maximum_selected_chunk_ids": max_selected_chunks, "response_schema": {"whole_statement_summary": "string, maximum 350 words", "case_hypotheses": [{"hypothesis_id": "H-001", "pattern": "string", "severity": "low|medium|high|critical", "related_chunk_ids": [1], "rationale": "string"}], "selected_chunk_ids": [1], "limitations": ["string"]}}


def evidence_payload(hypotheses: list[dict[str, Any]], raw_chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"task": "Verify or challenge the hypotheses against these original raw transactions. Return a finding only if its cited transaction IDs directly support it. Do not convert an unverified hypothesis into a fact. If evidence is insufficient, put it in disproved_or_uncertain_hypotheses.", "hypotheses": hypotheses, "raw_chunks": raw_chunks, "response_schema": {"verified_findings": [{"category": "string", "severity": "low|medium|high|critical", "confidence": "number 0 to 1", "rationale": "string", "evidence": [{"transaction_ids": ["transaction_id"], "statement": "string"}]}], "disproved_or_uncertain_hypotheses": ["hypothesis id and brief explanation"]}}


def final_payload(synthesis: dict[str, Any], evidence_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    return {"task": "Produce the final transaction-only AML assessment. Base the decision only on verified findings, never on unverified hypotheses. no_action means no material concern is evidenced; monitor means low concern; request_information means activity needs explanation; enhanced_due_diligence needs a material, verified concern; escalate needs a severe, verified concern. This is a recommendation for authorised human review, never an account or regulatory decision.", "whole_case_synthesis": synthesis, "verified_raw_evidence_reviews": evidence_reviews, "response_schema": {"decision": "no_action|monitor|request_information|enhanced_due_diligence|escalate", "decision_rationale": "string, maximum 250 words", "executive_summary": "string, maximum 350 words; material activity only", "risk_level": "low|medium|high", "verified_findings": [{"category": "string", "severity": "low|medium|high|critical", "confidence": "number 0 to 1", "rationale": "string", "evidence": [{"transaction_ids": ["transaction_id"], "statement": "string"}]}], "limitations": ["string"]}}
