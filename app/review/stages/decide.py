"""Step: DECIDE. One AI call, no tools. From the confirmed patterns (each with exact figures computed by
code), the rejected ones and the summary, the AI sets the risk level and writes what the analyst reads
first: the headline, the story, what to verify first and the questions for the customer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from app.account.summary import Totals, rm
from app.review.glossary import HOUSE_RULES, RISK_DEFINITIONS, TITLES, Limit, Pattern, pattern_list
from app.review.stages.check import CheckResult
from app.review.stages.common import Answer, FindingIds, Ids, Lower, Strength, Text, answer_format


def system_prompt(has_time: bool) -> str:
    return f"""You write the assessment an AML analyst reads first, and decide the account's risk level. The analyst
decides what action to take; your job is to give them clear insight and the next steps to investigate. Each
confirmed pattern below was checked against the actual rows, and its FIGURES were computed exactly by code: quote
those. Rejected patterns are listed so you know what was ruled out.

Write, in this order:
- headline: one line (at most 120 characters) with the most important point and its key figure.
- account_story: three or four sentences: how the account is used, its usual level, what changed and when.
- finding_order: the finding ids (F1, F2...) from most to least important for the analyst.
- verify_first: two to four concrete checks, most useful first, each naming its transactions: what to pull or
  confirm (for example the source of the credits on a date, who received a large debit, supporting documents).
  These are checks to make, not actions to take on the account.
- customer_questions: two to four questions the analyst could ask the customer or relationship manager, each about
  specific amounts and dates.
- checklist: EVERY pattern key in CHECKLIST once, with status found (a confirmed pattern shows it) or not_found,
  and a short note.
- monthly_notes: a short line only for months that stand out (skip ordinary months).
- evidence_strength: strong, moderate or weak, for the assessment as a whole.
- risk_reason: two or three sentences explaining the risk level from the findings and the figures.
- risk_level: low, medium or high.

{RISK_DEFINITIONS}

{pattern_list(has_time)}

{HOUSE_RULES}

{answer_format('{"headline": "...", "account_story": "...", "finding_order": ["F1"], '
               '"verify_first": [{"action": "...", "transaction_ids": ["T40"]}], "customer_questions": ["..."], '
               '"checklist": [{"pattern": "pass_through", "status": "found", "note": "..."}], '
               '"monthly_notes": [{"month": "2026-07", "note": "..."}], "evidence_strength": "moderate", '
               '"risk_reason": "...", "risk_level": "medium"}')}"""


class VerifyFirst(Answer):
    action: Text
    transaction_ids: Ids = Field(default_factory=list)


class ChecklistItem(Answer):
    pattern: Annotated[str, Lower]
    status: Annotated[Literal["found", "not_found"], Lower]
    note: Text = ""


class MonthNote(Answer):
    month: Text
    note: Text = ""


class Assessment(Answer):
    headline: Text
    account_story: Text = ""
    finding_order: FindingIds = Field(default_factory=list)
    verify_first: list[VerifyFirst] = Field(default_factory=list)
    customer_questions: list[Text] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    monthly_notes: list[MonthNote] = Field(default_factory=list)
    evidence_strength: Strength = "moderate"
    risk_reason: Text
    risk_level: Annotated[Literal["low", "medium", "high"], Lower]


@dataclass(frozen=True)
class Finding:
    """A confirmed pattern: F1, F2... with the Check step's answer and exact figures from code."""
    fid: str
    result: CheckResult
    figures: Totals


@dataclass(frozen=True)
class Rejected:
    title: str
    reason: str


def figures_line(t: Totals) -> str:
    share = f"|out_as_share_of_in={t.out_share_of_in}%" if t.out_share_of_in is not None else ""
    return (f"count={t.count}|in={rm(t.total_in)} ({t.count_in})|out={rm(t.total_out)} ({t.count_out})|"
            f"from={t.first}|to={t.last}|days={(t.last - t.first).days + 1}{share}")


def build_input(summary: str, stories: list[str], findings: list[Finding], rejected: list[Rejected],
                not_done: list[str], checklist: tuple[Pattern, ...], cannot_check: tuple[Limit, ...]) -> str:
    blocks = ["SUMMARY\n" + summary,
              "ACCOUNT STORY (from the earlier steps)\n" + ("\n".join(f"- {s}" for s in stories if s) or "not available")]
    if findings:
        lines = ["CONFIRMED PATTERNS"]
        for f in findings:
            r = f.result
            ids = ",".join(r.transaction_ids[:40]) + (f" and {len(r.transaction_ids) - 40} more"
                                                      if len(r.transaction_ids) > 40 else "")
            lines.append(f"{f.fid}|{r.pattern} ({TITLES.get(r.pattern, r.pattern)})|strength={r.strength}|ids={ids}\n"
                         f"  FIGURES|{figures_line(f.figures)}\n  what happened: {r.what_happened}\n"
                         f"  why it matters: {r.why_it_matters}\n  ordinary explanation: {r.ordinary_explanation}\n"
                         f"  to verify: {r.what_to_verify}")
        blocks.append("\n".join(lines))
    else:
        blocks.append("CONFIRMED PATTERNS\nnone")
    if rejected:
        blocks.append("REJECTED (ruled out against the rows)\n" + "\n".join(f"- {r.title}: {r.reason}" for r in rejected))
    if not_done:
        blocks.append("NOT DONE (steps that failed; say so if it limits your assessment)\n"
                      + "\n".join(f"- {item}" for item in not_done))
    blocks.append("CHECKLIST (each key once): " + ", ".join(p.key for p in checklist))
    blocks.append("THE DATA CANNOT SHOW (already listed for the analyst; leave out of the checklist): "
                  + "; ".join(limit.title for limit in cannot_check))
    return "\n\n".join(blocks)
