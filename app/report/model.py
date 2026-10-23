"""The report the analyst receives, as data. It is saved as JSON (for the production UI) and drawn as an
HTML page by app/report/html.py.

Two kinds of content, never mixed: what the AI wrote (shown as written), and what the code computed
(exact figures, and the transactions behind each finding).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.account.ingest import Account, Txn
from app.account.summary import Totals


class TxnRow(BaseModel):
    """One transaction: its label and the four columns."""
    tid: str
    date: str
    seq: int
    direction: Literal["C", "D"]
    amount: Decimal

    @classmethod
    def of(cls, account: Account, txn: Txn) -> "TxnRow":
        return cls(tid=txn.tid, date=account.date_text(txn), seq=txn.seq, direction=txn.direction, amount=txn.amount)


class Figures(BaseModel):
    """Exact figures over a set of transactions, computed by code."""
    count: int
    count_in: int
    total_in: Decimal
    count_out: int
    total_out: Decimal
    first_date: str | None
    last_date: str | None
    days: int | None                        # from the first to the last date, both included
    out_share_of_in: Decimal | None = None  # money out as a % of money in; None when nothing came in

    @classmethod
    def of(cls, t: Totals) -> "Figures":
        return cls(count=t.count, count_in=t.count_in, total_in=t.total_in, count_out=t.count_out,
                   total_out=t.total_out, first_date=str(t.first) if t.first else None,
                   last_date=str(t.last) if t.last else None,
                   days=(t.last - t.first).days + 1 if t.first and t.last else None, out_share_of_in=t.out_share_of_in)


class FindingCard(BaseModel):
    finding_id: str
    pattern: str
    title: str
    strength: str
    what_happened: str              # AI
    why_it_matters: str = ""        # AI
    ordinary_explanation: str = ""  # AI
    what_to_verify: str = ""        # AI
    figures: Figures                # code
    transactions: list[TxnRow]      # code
    issues: list[str] = Field(default_factory=list)   # checks that failed on this card's text


class VerifyItem(BaseModel):
    action: str
    transactions: list[TxnRow] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ChecklistRow(BaseModel):
    pattern: str
    title: str
    status: Literal["found", "not_found", "cannot_check", "not_reported"]
    note: str = ""


class MonthRow(BaseModel):
    month: str
    count: int
    count_in: int
    total_in: Decimal
    count_out: int
    total_out: Decimal
    note: str = ""                  # the AI's note, only for months that stand out


class Glance(BaseModel):
    """The account at a glance, computed by code."""
    transactions: int
    active_days: int
    days_in_period: int
    count_in: int
    total_in: Decimal
    count_out: int
    total_out: Decimal
    in_minus_out: Decimal
    largest_in: TxnRow | None = None
    largest_out: TxnRow | None = None
    longest_quiet: str | None = None        # e.g. "2026-02-24 to 2026-04-24 (59 days)"
    last_credit: str | None = None
    months_without_activity: list[str] = Field(default_factory=list)


class RejectedRow(BaseModel):
    title: str
    reason: str


class ToolRow(BaseModel):
    step: str
    tool: str
    asked: str
    answer: str


class CallRow(BaseModel):
    step: str
    status: Literal["answered", "failed"]
    seconds: float
    requests: int
    tool_uses: int
    output_tokens: int
    problem: str = ""


class Report(BaseModel):
    report_id: str
    generated_at: datetime
    file_name: str
    period_start: str
    period_end: str
    transactions: int
    groups: int
    # complete: every step answered; incomplete: something was not done (see limitations)
    status: Literal["complete", "incomplete"]
    # --- the AI's assessment
    risk_level: Literal["low", "medium", "high", "not_assessed"]
    evidence_strength: str
    headline: str
    risk_reason: str
    account_story: str
    # --- the details
    glance: Glance
    verify_first: list[VerifyItem]
    customer_questions: list[str]
    findings: list[FindingCard]
    checklist: list[ChecklistRow]
    months: list[MonthRow]
    rejected: list[RejectedRow]
    limitations: list[str]
    issues: list[str]          # failed checks outside the finding cards (headline, story, checklist...)
    tool_uses: list[ToolRow]
    calls: list[CallRow]
    total_seconds: float
