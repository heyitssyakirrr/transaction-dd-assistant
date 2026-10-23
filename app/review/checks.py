"""Checks on what the AI wrote: do the transactions, amounts and dates it quotes exist?

Never changes a judgement. A mismatch becomes an issue shown in red beside the text, so the analyst
sees it; an id that does not exist is removed from the evidence table (there is no row to show).
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.account.ingest import Txn

_AMOUNT = re.compile(r"RM\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CENT = Decimal("0.01")


def split_ids(ids: Iterable[str], allowed: set[str]) -> tuple[list[str], list[str]]:
    """(ids that exist, ids that do not), each in the order given."""
    kept, unknown = [], []
    for tid in ids:
        (kept if tid in allowed else unknown).append(tid)
    return kept, unknown


def rm_figures(text: str) -> set[Decimal]:
    """Every "RM x" figure in a text: what the AI was shown in the facts and tool results."""
    figures = set()
    for raw in _AMOUNT.findall(text or ""):
        try:
            figures.add(Decimal(raw.replace(",", "")).quantize(_CENT))
        except InvalidOperation:
            continue
    return figures


def amount_figures(txns: Iterable[Txn]) -> set[Decimal]:
    """The totals a sentence about these transactions may quote: the total, the total in and out, and
    each day's total in and out (a sentence often sums one day's credits)."""
    sums: dict[tuple[object, str], Decimal] = defaultdict(lambda: Decimal("0.00"))
    for t in txns:
        for key in (("all", t.direction), ("all", "any"), (t.day, t.direction), (t.day, "any")):
            sums[key] += t.amount
    return {value.quantize(_CENT) for value in sums.values()}


def text_issues(label: str, text: str, allowed: set[Decimal], period: tuple[date, date]) -> list[str]:
    """Amounts (RM ...) that match no transaction, total or figure the AI was shown, and dates
    (YYYY-MM-DD) outside the statement period. Dates inside it may have no transaction (a quiet
    period is described by its dates)."""
    issues = []
    for raw in _AMOUNT.findall(text or ""):
        try:
            value = Decimal(raw.replace(",", "")).quantize(_CENT)
        except InvalidOperation:
            continue
        if value not in allowed:
            issues.append(f"{label}: quotes RM {raw}, which matches no transaction, total or figure the AI was "
                          "given; check it against the transactions.")
    start, end = (str(day) for day in period)
    for day in _ISO_DATE.findall(text or ""):
        if not start <= day <= end:
            issues.append(f"{label}: mentions {day}, which is outside the statement period {start} to {end}.")
    return list(dict.fromkeys(issues))
