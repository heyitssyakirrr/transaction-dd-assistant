"""Build the analyst's report from a finished review.

The AI's words are used exactly as written. Code adds the exact figures and the transactions behind each
finding, fills in what the data cannot show, and lists as issues anything the checks could not match.
It never changes the AI's risk level or findings: an inconsistency (say, high risk with no confirmed
pattern) is shown, not corrected.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.account.ingest import Txn
from app.account.summary import by_month, quiet_periods, totals
from app.config import Settings
from app.report.model import (CallRow, ChecklistRow, Figures, FindingCard, Glance, MonthRow, RejectedRow, Report,
                              ToolRow, TxnRow, VerifyItem)
from app.review import checks
from app.review.glossary import TITLES, cannot_check, checkable
from app.review.pipeline import Review

FOUR_COLUMNS = ("Only four columns were used: date, sequence number, direction (in or out) and amount. Every other "
                "column in the file was ignored.")


class _Builder:
    def __init__(self, review: Review, settings: Settings) -> None:
        self.review = review
        self.account = review.account
        self.period = (self.account.first_day, self.account.last_day)
        self.issues = list(review.issues)
        # Every amount the AI may quote: any transaction, any figure it was shown (the summary and the tool
        # answers), the reporting limit, and the totals of the rows each finding cites.
        self.allowed = ({t.amount for t in self.account.txns} | checks.rm_figures(review.summary)
                        | review.toolbox.figures | {settings.cash_report_limit.quantize(Decimal("0.01"))})
        for f in review.findings:
            self.allowed |= checks.amount_figures(self.txns(f.result.transaction_ids))

    def txns(self, ids: list[str]) -> list[Txn]:
        return [self.account.by_tid[tid] for tid in ids if tid in self.account.by_tid]

    def rows(self, ids: list[str]) -> list[TxnRow]:
        return [TxnRow.of(self.account, t) for t in self.txns(ids)]

    def check(self, label: str, text: str, extra: set[Decimal] = frozenset()) -> list[str]:
        return checks.text_issues(label, text, self.allowed | extra, self.period)

    # --- sections --------------------------------------------------------------------------

    def findings(self) -> list[FindingCard]:
        """In the AI's order of importance, then any confirmed finding it left out of that order."""
        assessment = self.review.assessment
        by_id = {f.fid: f for f in self.review.findings}
        order = list(assessment.finding_order) if assessment else []
        for fid in order:
            if fid not in by_id:
                self.issues.append(f"Finding order: mentions {fid}, which is not a confirmed finding.")
        order = [fid for fid in order if fid in by_id] + [fid for fid in by_id if fid not in order]
        cards = []
        for fid in order:
            finding = by_id[fid]
            r = finding.result
            card_issues = []
            for label, text in (("What happened", r.what_happened), ("Why it matters", r.why_it_matters),
                                ("Ordinary explanation", r.ordinary_explanation), ("What to verify", r.what_to_verify)):
                card_issues += self.check(label, text)
            cards.append(FindingCard(
                finding_id=fid, pattern=r.pattern, title=TITLES.get(r.pattern, r.pattern), strength=r.strength,
                what_happened=r.what_happened, why_it_matters=r.why_it_matters,
                ordinary_explanation=r.ordinary_explanation, what_to_verify=r.what_to_verify,
                figures=Figures.of(finding.figures), transactions=self.rows(r.transaction_ids), issues=card_issues))
        return cards

    def verify_first(self) -> list[VerifyItem]:
        items = []
        for item in (self.review.assessment.verify_first if self.review.assessment else []):
            kept, unknown = checks.split_ids(item.transaction_ids, set(self.account.by_tid))
            item_issues = [f"Mentions {', '.join(unknown[:5])}, which do not exist."] if unknown else []
            item_issues += self.check("Check", item.action, checks.amount_figures(self.txns(kept)))
            items.append(VerifyItem(action=item.action, transactions=self.rows(kept), issues=item_issues))
        return items

    def checklist(self) -> list[ChecklistRow]:
        """Every pattern once, as the AI marked it, then what the data cannot show. A pattern the AI left out
        shows as "not reported"; a mark that contradicts the confirmed findings is an issue."""
        assessment = self.review.assessment
        given = {}
        for item in (assessment.checklist if assessment else []):
            given.setdefault(item.pattern, item)
        confirmed = {f.result.pattern for f in self.review.findings}
        rows = []
        for pattern in checkable(self.account.has_time):
            item = given.get(pattern.key)
            if item is None:
                if assessment:
                    self.issues.append(f"Checklist: {pattern.title} was not reported.")
                rows.append(ChecklistRow(pattern=pattern.key, title=pattern.title, status="not_reported"))
                continue
            if item.status == "found" and pattern.key not in confirmed:
                self.issues.append(f"Checklist: {pattern.title} is marked found, but no confirmed finding is of "
                                   "that pattern.")
            if item.status == "not_found" and pattern.key in confirmed:
                self.issues.append(f"Checklist: {pattern.title} is marked not found, but a confirmed finding is "
                                   "of that pattern.")
            self.issues += self.check(f"Checklist ({pattern.title})", item.note)
            rows.append(ChecklistRow(pattern=pattern.key, title=pattern.title, status=item.status, note=item.note))
        rows += [ChecklistRow(pattern=limit.key, title=limit.title, status="cannot_check", note=limit.reason)
                 for limit in cannot_check(self.account.has_time)]
        return rows

    def months(self) -> list[MonthRow]:
        notes = {n.month.strip()[:7]: n.note for n in (self.review.assessment.monthly_notes
                                                       if self.review.assessment else [])}
        rows = []
        for month, txns in by_month(self.account):
            t = totals(txns)
            note = notes.get(month, "")
            self.issues += self.check(f"Month note {month}", note)
            rows.append(MonthRow(month=month, count=t.count, count_in=t.count_in, total_in=t.total_in,
                                 count_out=t.count_out, total_out=t.total_out, note=note))
        return rows

    def glance(self) -> Glance:
        txns = self.account.txns
        t = totals(txns)
        quiet = quiet_periods(txns)
        credits = [x for x in txns if x.direction == "C"]
        first, last = self.period
        return Glance(
            transactions=t.count, active_days=t.active_days, days_in_period=(last - first).days + 1,
            count_in=t.count_in, total_in=t.total_in, count_out=t.count_out, total_out=t.total_out, in_minus_out=t.net,
            largest_in=TxnRow.of(self.account, t.largest_in) if t.largest_in else None,
            largest_out=TxnRow.of(self.account, t.largest_out) if t.largest_out else None,
            longest_quiet=f"{quiet[0].after.day} to {quiet[0].before.day} ({quiet[0].days} days)" if quiet else None,
            last_credit=str(credits[-1].day) if credits else None,
            months_without_activity=[month for month, rows in by_month(self.account) if not rows],
        )

    def limitations(self) -> list[str]:
        items = [FOUR_COLUMNS]
        if self.account.blank_lines_skipped:
            items.append(f"{self.account.blank_lines_skipped} blank line(s) in the file were skipped.")
        items += self.review.not_done
        return list(dict.fromkeys(items))


def build_report(review: Review, settings: Settings) -> Report:
    b = _Builder(review, settings)
    account, assessment = review.account, review.assessment
    findings, verify_first, checklist, months = b.findings(), b.verify_first(), b.checklist(), b.months()
    story_draft = next((s for s in review.stories if s), "")
    if assessment:
        risk_level, strength = assessment.risk_level, assessment.evidence_strength
        headline, risk_reason = assessment.headline, assessment.risk_reason
        story, questions = assessment.account_story or story_draft, assessment.customer_questions
        for label, text in (("Headline", headline), ("Account story", story), ("Risk reason", risk_reason),
                            *(("Question", q) for q in questions)):
            b.issues += b.check(label, text)
        if risk_level in {"medium", "high"} and not review.findings:
            b.issues.append(f"The risk level is {risk_level}, but no pattern was confirmed against the rows.")
    else:
        risk_level, strength, questions, story = "not_assessed", "none", [], story_draft
        headline = ("The AI could not finish the assessment; the confirmed findings are below." if review.findings
                    else "The AI could not finish the assessment.")
        risk_reason = "No risk level was set: see Limitations for the step that failed. Review the account directly."
    return Report(
        report_id=f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}",
        generated_at=datetime.now(timezone.utc), file_name=account.file_name,
        period_start=str(account.first_day), period_end=str(account.last_day), transactions=len(account.txns),
        groups=len(review.groups), status="complete" if assessment and not review.not_done else "incomplete",
        risk_level=risk_level, evidence_strength=strength, headline=headline, risk_reason=risk_reason,
        account_story=story, glance=b.glance(), verify_first=verify_first, customer_questions=questions,
        findings=findings, checklist=checklist, months=months,
        rejected=[RejectedRow(title=r.title, reason=r.reason) for r in review.rejected],
        limitations=b.limitations(), issues=list(dict.fromkeys(b.issues)),
        tool_uses=[ToolRow(step=c.name, tool=u.tool, asked=u.asked, answer=u.answer)
                   for c in review.calls for u in c.tool_uses],
        calls=[CallRow(step=c.name, status="failed" if c.problem else "answered", seconds=round(c.seconds, 1),
                       requests=c.requests, tool_uses=len(c.tool_uses), output_tokens=c.output_tokens,
                       problem=c.problem) for c in review.calls],
        total_seconds=round(time.monotonic() - review.started, 1),
    )
