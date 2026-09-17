from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class CustomerContext(BaseModel):
    customer_id: str
    occupation: str | None = None
    declared_monthly_income: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    risk_rating: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


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
    customer_context: CustomerContext
    column_mapping: TransactionColumnMapping
    transactions: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


class NormalizedTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)
    transaction_id: str
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
    finding_id: str
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


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
    profile: dict[str, Any]
    generated_at: datetime


class LlmClient(Protocol):
    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]: ...

