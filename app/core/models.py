from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _as_list(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


# Small models sometimes return a single string where the schema asks for a list.
StrList = Annotated[list[str], BeforeValidator(_as_list)]


class TransactionColumnMapping(BaseModel):
    transaction_id: str
    timestamp: str
    amount: str
    direction: str
    currency: str | None = None
    counterparty: str | None = None
    description: str | None = None
    channel: str | None = None
    merchant_category: str | None = None
    balance: str | None = None


class AnalyzeTransactionsRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    source_filename: str = Field(min_length=1, max_length=255)
    column_mapping: TransactionColumnMapping
    transactions: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=10_000,
    )


class NormalizedTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)
    transaction_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    amount: Decimal = Field(ge=0)
    direction: Literal["credit", "debit"]
    currency: str | None = None
    counterparty: str | None = None
    description: str | None = None
    channel: str | None = None
    merchant_category: str | None = None
    balance: Decimal | None = None


class EvidenceItem(BaseModel):
    transaction_ids: list[str] = Field(default_factory=list)
    statement: str


class Finding(BaseModel):
    finding_id: str = ""
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ChunkReport(BaseModel):
    chunk_id: int = Field(ge=1)
    material_activity_summary: str = Field(min_length=1, max_length=1_400)
    findings: list[Finding] = Field(default_factory=list, max_length=8)
    entities_of_interest: StrList = Field(default_factory=list, max_length=20)
    cross_chunk_review_needed: bool


class CaseHypothesis(BaseModel):
    hypothesis_id: str = Field(min_length=1, max_length=40)
    pattern: str = Field(min_length=1, max_length=500)
    severity: Literal["low", "medium", "high", "critical"]
    related_chunk_ids: list[int] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1, max_length=900)


class CaseSynthesis(BaseModel):
    whole_statement_summary: str = Field(min_length=1, max_length=1_800)
    case_hypotheses: list[CaseHypothesis] = Field(default_factory=list, max_length=10)
    selected_chunk_ids: list[int] = Field(default_factory=list, max_length=6)
    limitations: StrList = Field(default_factory=list, max_length=8)


class EvidenceReview(BaseModel):
    verified_findings: list[Finding] = Field(default_factory=list, max_length=10)
    disproved_or_uncertain_hypotheses: StrList = Field(default_factory=list, max_length=10)


class AnalysisResult(BaseModel):
    case_id: str
    status: Literal["completed", "needs_review"]
    decision: Literal["no_action", "monitor", "request_information", "enhanced_due_diligence", "escalate"]
    decision_rationale: str
    executive_summary: str
    findings: list[Finding]
    mitigating_factors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    transactions_processed: int
    chunks_processed: int
    risk_level: Literal["low", "medium", "high"]
    generated_at: datetime


class LlmClient(Protocol):
    async def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]: ...