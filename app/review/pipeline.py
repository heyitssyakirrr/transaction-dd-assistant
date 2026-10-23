"""The AI steps for one account, in order.

  SMALL account (up to ROWS_PER_GROUP rows):
      Read            1 call: every row + the summary          -> the patterns it saw
  BIG account:
      Summary review  1 call: the summary only                  -> leads across months    } at the
      Read            1 call per group: its rows + neighbours   -> patterns, loose ends   } same time
      Combine         1 call, with tools                        -> the suspected patterns
  then, for every account:
      Check           1 call per suspected pattern, at the same time, with tools -> confirmed or rejected
      Decide          1 call                                    -> risk level and the analyst's text

Code only prepares each step's input and checks the transaction ids each answer cites. When a step fails,
the review carries on with what it has, and the report says what was not done.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.account.ingest import Account
from app.account.summary import Group, check_rows, monthly_totals, split_into_groups, summary, totals
from app.config import Settings
from app.llm.ask import Asker, CallFailed, CallRecord
from app.review import checks
from app.review.glossary import TITLES, cannot_check, checkable
from app.review.stages import check, combine, decide, read, summary_review
from app.review.stages.combine import Suspected
from app.review.stages.decide import Finding, Rejected
from app.review.tools import Toolbox

logger = logging.getLogger("app.review.pipeline")
_STRENGTH_ORDER = {"strong": 0, "moderate": 1, "weak": 2}


@dataclass
class Review:
    """Everything one account's review produced; app/report/builder.py turns it into the report."""
    account: Account
    groups: list[Group]
    summary: str                                   # the summary text the AI was given
    toolbox: Toolbox
    stories: list[str] = field(default_factory=list)          # account-story drafts from the earlier steps
    suspected: list[Suspected] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)     # confirmed patterns
    rejected: list[Rejected] = field(default_factory=list)
    assessment: decide.Assessment | None = None
    not_done: list[str] = field(default_factory=list)          # failed or skipped work, in plain words
    issues: list[str] = field(default_factory=list)            # ids the AI cited that do not exist
    calls: list[CallRecord] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)


class Pipeline:
    def __init__(self, asker: Asker, settings: Settings) -> None:
        self._asker = asker
        self._settings = settings

    async def run(self, account: Account) -> Review:
        settings = self._settings
        review = Review(account, split_into_groups(account, settings), summary(account, settings),
                        Toolbox(account, settings))
        logger.info("Review started: file=%s rows=%d groups=%d", account.file_name, len(account.txns),
                    len(review.groups))

        if len(review.groups) == 1:   # small account: one Read call sees everything
            notes = [await self._read(review, review.groups[0], review.summary)]
            if notes[0] is not None:
                review.stories.append(notes[0].normal_activity)
                review.suspected = _join(notes[0].patterns)
        else:                          # big account
            monthly = monthly_totals(account, settings)
            summary_notes, *notes = await asyncio.gather(
                self._summary_review(review), *(self._read(review, g, monthly) for g in review.groups))
            if any(notes):
                review.suspected = await self._combine(review, summary_notes, notes)

        if not any(notes):
            review.not_done.append("No group of transactions could be read, so the account was not assessed.")
        else:
            review.suspected = self._keep_unique(review, review.suspected)
            await self._check(review)
            await self._decide(review)
        logger.info("Review finished: suspected=%d confirmed=%d rejected=%d not_done=%d seconds=%.1f",
                    len(review.suspected), len(review.findings), len(review.rejected), len(review.not_done),
                    time.monotonic() - review.started)
        return review

    async def _call(self, review: Review, name: str, *args, **kwargs):
        record = CallRecord(name)
        review.calls.append(record)
        return await self._asker.ask(record, *args, **kwargs)

    # --- Read and Summary review ---------------------------------------------------------------

    async def _summary_review(self, review: Review) -> summary_review.SummaryNotes | None:
        try:
            notes = await self._call(review, "Summary review", summary_review.system_prompt(review.account.has_time),
                                     summary_review.build_input(review.summary), summary_review.SummaryNotes,
                                     self._settings.summary_review_tokens)
        except CallFailed as exc:
            review.not_done.append(f"Summary review was not done ({exc}); patterns across months rely on the "
                                   "groups' notes and the Combine step's tools.")
            return None
        for lead in notes.leads:
            lead.transaction_ids = self._known(review, "Summary review", lead.transaction_ids,
                                               set(review.account.by_tid))
        review.stories.append(notes.account_story)
        return notes

    async def _read(self, review: Review, group: Group, background: str) -> read.ReadNotes | None:
        total = len(review.groups)
        name = "Read" if total == 1 else f"Read group {group.number} ({group.period})"
        try:
            notes = await self._call(review, name, read.system_prompt(review.account.has_time),
                                     read.build_input(review.account, group, total, background), read.ReadNotes,
                                     self._settings.read_tokens)
        except CallFailed as exc:
            what = "The transactions" if total == 1 else f"Group {group.number} ({group.period}, {len(group.txns)} rows)"
            review.not_done.append(f"{what} could not be read: {exc}")
            return None
        allowed = {t.tid for t in (*group.before, *group.txns, *group.after)}
        for item in (*notes.patterns, *notes.loose_ends):
            item.transaction_ids = self._known(review, name, item.transaction_ids, allowed)
        notes.patterns = [p for p in notes.patterns if p.transaction_ids]
        notes.loose_ends = [e for e in notes.loose_ends if e.transaction_ids]
        return notes

    # --- Combine ------------------------------------------------------------------------------

    async def _combine(self, review: Review, summary_notes: summary_review.SummaryNotes | None,
                       notes: list[read.ReadNotes | None]) -> list[Suspected]:
        review.stories += [n.normal_activity for n in notes if n and n.normal_activity]
        group_notes = [(g.number, g.period, n) for g, n in zip(review.groups, notes)]
        try:
            result = await self._call(
                review, "Combine", combine.system_prompt(review.account.has_time, self._settings.max_patterns_to_check),
                combine.build_input(review.summary, summary_notes, group_notes), combine.CombineResult,
                self._settings.combine_tokens, toolbox=review.toolbox)
            review.stories.insert(0, result.account_story)
            return result.suspected_patterns
        except CallFailed as exc:
            # Without Combine, check the groups' patterns (joined where they share transactions) and any
            # Summary review lead that names transactions.
            review.not_done.append(f"The Combine step failed ({exc}); patterns across groups were joined only "
                                   "where the groups' notes share transactions.")
            seen = [p for n in notes if n for p in n.patterns]
            if summary_notes:
                seen += [read.SeenPattern(pattern=lead.pattern, transaction_ids=lead.transaction_ids, note=lead.note,
                                          strength=lead.strength) for lead in summary_notes.leads if lead.transaction_ids]
            return _join(seen)

    def _keep_unique(self, review: Review, suspected: list[Suspected]) -> list[Suspected]:
        """Real ids only; no pattern that repeats another's transactions; at most MAX_PATTERNS_TO_CHECK."""
        allowed = set(review.account.by_tid)
        kept: list[Suspected] = []
        for item in suspected:
            item.transaction_ids = self._known(review, "Combine", item.transaction_ids, allowed)
            ids = set(item.transaction_ids)
            if ids and not any(k.pattern == item.pattern and ids <= set(k.transaction_ids) for k in kept):
                kept.append(item)
        limit = self._settings.max_patterns_to_check
        if len(kept) > limit:
            left_out = ", ".join(TITLES.get(k.pattern, k.pattern) for k in kept[limit:])
            review.not_done.append(f"{len(kept) - limit} weaker suspected pattern(s) were not checked "
                                   f"(MAX_PATTERNS_TO_CHECK={limit}): {left_out}.")
        return kept[:limit]

    # --- Check -----------------------------------------------------------------------------

    async def _check(self, review: Review) -> None:
        account = review.account
        monthly = monthly_totals(account, self._settings)

        async def one(number: int, item: Suspected) -> check.CheckResult | None:
            title = TITLES.get(item.pattern, item.pattern)
            name = f"Check {number} ({title})"
            rows = check_rows(account, item.transaction_ids, self._settings)
            try:
                result = await self._call(review, name, check.system_prompt(account.has_time),
                                          check.build_input(account, monthly, item, rows), check.CheckResult,
                                          self._settings.check_tokens, toolbox=review.toolbox)
            except CallFailed as exc:
                review.not_done.append(f"Suspected pattern {number} ({title}) was not checked: {exc}")
                return None
            # The AI may add rows it found with the tools, so any real id is accepted.
            result.transaction_ids = self._known(review, name, result.transaction_ids, set(account.by_tid))
            if result.confirmed and not result.transaction_ids:
                review.issues.append(f"{name}: confirmed, but cited no transaction that exists; treated as not "
                                     "confirmed.")
                result.confirmed = False
            return result

        results = await asyncio.gather(*(one(n, item) for n, item in enumerate(review.suspected, start=1)))
        for result in results:
            if result is None:
                continue
            if not result.confirmed:
                review.rejected.append(Rejected(TITLES.get(result.pattern, result.pattern),
                                                result.what_happened or result.why_it_matters))
            elif all(set(result.transaction_ids) != set(f.result.transaction_ids) for f in review.findings):
                txns = [account.by_tid[tid] for tid in result.transaction_ids]
                review.findings.append(Finding(f"F{len(review.findings) + 1}", result, totals(txns)))

    # --- Decide ----------------------------------------------------------------------------

    async def _decide(self, review: Review) -> None:
        account = review.account
        try:
            review.assessment = await self._call(
                review, "Decide", decide.system_prompt(account.has_time),
                decide.build_input(summary(account, self._settings, with_days=False), review.stories,
                                   review.findings, review.rejected, review.not_done,
                                   checkable(account.has_time), cannot_check(account.has_time)),
                decide.Assessment, self._settings.decide_tokens)
        except CallFailed as exc:
            review.not_done.append(f"The Decide step failed, so no risk level was set: {exc}")

    @staticmethod
    def _known(review: Review, name: str, ids: list[str], allowed: set[str]) -> list[str]:
        kept, unknown = checks.split_ids(ids, allowed)
        if unknown:
            review.issues.append(f"{name}: cited {len(unknown)} transaction id(s) that do not exist or are not in "
                                 f"its rows ({', '.join(unknown[:5])}); they were left out.")
        return kept


def _join(patterns: list[read.SeenPattern]) -> list[Suspected]:
    """Patterns as suspected patterns, strongest first; the same pattern seen twice with shared
    transactions (for example in two neighbouring groups) becomes one."""
    joined: list[tuple[str, set[str], list[str], int]] = []   # pattern, ids, notes, best strength
    for p in patterns:
        ids, rank = set(p.transaction_ids), _STRENGTH_ORDER[p.strength]
        for i, (key, other, notes, best) in enumerate(joined):
            if key == p.pattern and ids & other:
                joined[i] = (key, other | ids, notes + [p.note], min(best, rank))
                break
        else:
            joined.append((p.pattern, ids, [p.note], rank))
    joined.sort(key=lambda item: item[3])
    return [Suspected(pattern=key, transaction_ids=sorted(ids, key=lambda t: int(t[1:])),
                      why=" ".join(n for n in notes if n)[:600]) for key, ids, notes, _ in joined]
