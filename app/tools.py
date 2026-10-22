"""The tools the AI can use in the Combine and Check steps.

A tool is a small read-only function. The AI picks a tool from this fixed list and fills in its inputs;
the code answers exactly from the account's transactions. The AI chooses every value (dates, amounts,
days); the tools never decide what is unusual.

Answers use the same four-column rows and "RM" figures as the rest of the AI's input, so a tool can never
show the AI anything more. A wrong input returns "error: ..." so the AI can correct it and try again.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app import checks
from app.config import Settings
from app.ingest import Account, Txn
from app.summary import (ROW_HEADER, ZERO, by_day, by_week, group_line, months_between, quiet_periods,
                         repeated_amounts, rm, row_line, totals)

_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_DIRECTION = {"type": "string", "enum": ["C", "D", "both"], "description": "C money in, D money out"}
_IDS = {"type": "array", "items": {"type": "string"}, "description": "transaction ids such as T12"}


def _definition(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


DEFINITIONS: dict[str, dict] = {d["function"]["name"]: d for d in (
    _definition("get_transactions",
                "The rows between two dates (inclusive), optionally one direction and an amount range, with the exact "
                "count and totals of everything that matched.",
                {"start_date": _DATE, "end_date": _DATE, "direction": _DIRECTION,
                 "min_amount": {"type": "number"}, "max_amount": {"type": "number"}},
                ["start_date", "end_date"]),
    _definition("follow_money",
                "What left the account after some credits: the debits from the last given credit (later the same day "
                "by sequence number) up to `days` days after it, their total and their share of the credits, and any "
                "other credits in the same window.",
                {"transaction_ids": _IDS, "days": {"type": "integer", "minimum": 0, "maximum": 90}},
                ["transaction_ids", "days"]),
    _definition("summarise",
                "Count, money in and money out per day, week or month between two dates.",
                {"start_date": _DATE, "end_date": _DATE, "by": {"type": "string", "enum": ["day", "week", "month"]}},
                ["start_date", "end_date", "by"]),
    _definition("compare_periods",
                "Two periods side by side: days, active days, count, money in and out, average credit and debit.",
                {"first_start": _DATE, "first_end": _DATE, "second_start": _DATE, "second_end": _DATE},
                ["first_start", "first_end", "second_start", "second_end"]),
    _definition("find_repeated_amounts",
                "Amounts that occur at least `min_count` times in the same direction over the whole period, with "
                "their dates and ids.",
                {"min_count": {"type": "integer", "minimum": 2}, "min_amount": {"type": "number"},
                 "direction": _DIRECTION},
                ["min_count"]),
    _definition("find_quiet_periods",
                "Every gap of at least `min_days` days between one transaction and the next, longest first.",
                {"min_days": {"type": "integer", "minimum": 1}},
                ["min_days"]),
    _definition("total_of",
                "The exact count, money in, money out, dates and largest amounts of the given transactions.",
                {"transaction_ids": _IDS},
                ["transaction_ids"]),
)}

class ToolError(ValueError):
    """A bad argument; the message goes back to the AI."""



class Toolbox:
    """The tools for one account. ``run`` never raises: a problem comes back as text for the AI."""

    def __init__(self, account: Account, settings: Settings) -> None:
        self._account = account
        self._txns = account.txns
        self._max_rows = settings.tool_max_rows
        # Every "RM" figure a tool has shown the AI: the report's amount check accepts these.
        self.figures: set[Decimal] = set()
        self._tools: dict[str, Callable[..., str]] = {
            "get_transactions": self.get_transactions, "follow_money": self.follow_money,
            "summarise": self.summarise, "compare_periods": self.compare_periods,
            "find_repeated_amounts": self.find_repeated_amounts, "find_quiet_periods": self.find_quiet_periods,
            "total_of": self.total_of,
        }

    def definitions(self) -> list[dict]:
        return list(DEFINITIONS.values())

    def run(self, name: str, arguments: str | dict | None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: there is no tool called {name}; use one of {', '.join(self._tools)}"
        try:
            values = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
            if not isinstance(values, dict):
                raise ToolError("arguments must be a JSON object")
            result = tool(**values)
        except (ToolError, json.JSONDecodeError) as exc:
            return f"error: {exc}"
        except TypeError as exc:  # missing or unexpected argument names
            return f"error: wrong arguments for {name}: {exc}"
        self.figures |= checks.rm_figures(result)
        return result

    # --- the tools ----------------------------------------------------------------------

    def get_transactions(self, start_date: str, end_date: str, direction: str = "both",
                         min_amount: float | None = None, max_amount: float | None = None) -> str:
        start, end = _dates(start_date, end_date)
        side = _direction(direction)
        low, high = _amount(min_amount), _amount(max_amount)
        rows = [t for t in self._txns if start <= t.day <= end and side in ("both", t.direction)
                and (low is None or t.amount >= low) and (high is None or t.amount <= high)]
        return f"MATCHED|{totals(rows).line()}\n" + self._rows(rows)

    def follow_money(self, transaction_ids: list[str], days: int) -> str:
        found, unknown = self._lookup(transaction_ids)
        credits = [t for t in found if t.direction == "C"]
        if not credits:
            return "error: none of these ids is a credit (dir C); give the credits whose money you want to follow"
        days = _whole(days, "days", 0, 90)
        last = max(credits, key=lambda t: (t.when, t.seq))
        end = last.day + timedelta(days=days)
        later = [t for t in self._txns if (t.when, t.seq) > (last.when, last.seq) and t.day <= end]
        debits = [t for t in later if t.direction == "D"]
        other_credits = [t for t in later if t.direction == "C"]
        credit_total = sum((t.amount for t in credits), ZERO)
        debit_total = sum((t.amount for t in debits), ZERO)
        share = (debit_total * 100 / credit_total).quantize(Decimal("0.1"))
        same_day = sum((t.amount for t in debits if t.day == last.day), ZERO)
        header = (f"FOLLOW|credits={rm(credit_total)} ({len(credits)}: {','.join(t.tid for t in credits)})|"
                  f"window={last.day} after {last.tid} to {end}|debits_in_window={rm(debit_total)} ({len(debits)})|"
                  f"share_of_credits={share}%|debits_same_day={rm(same_day)}|"
                  f"other_credits_in_window={rm(sum((t.amount for t in other_credits), ZERO))} ({len(other_credits)})")
        return header + _unknown(unknown) + "\n" + self._rows(debits)

    def summarise(self, start_date: str, end_date: str, by: str = "month") -> str:
        start, end = _dates(start_date, end_date)
        first, last = self._account.first_day, self._account.last_day  # no empty months outside the account's period
        start, end = max(start, first), min(end, last)
        if end < start:
            return f"SUMMARY|no transactions: the account's transactions run from {first} to {last}"
        rows = [t for t in self._txns if start <= t.day <= end]
        if by == "day":
            lines = [group_line("DAY", str(day), group) for day, group in by_day(rows)]
        elif by == "week":
            lines = [group_line("WEEK", str(week), group) for week, group in by_week(rows)]
        elif by == "month":
            grouped = {month: [t for t in rows if t.month == month] for month in months_between(start, end)}
            lines = [group_line("MONTH", month, group) for month, group in grouped.items()]
        else:
            raise ToolError("by must be day, week or month")
        shown = lines[:400]
        note = f"\n(showing the first 400 of {len(lines)} lines; use a shorter period)" if len(lines) > 400 else ""
        return f"SUMMARY|{start} to {end}|by={by}|{totals(rows).line()}\n" + "\n".join(shown) + note

    def compare_periods(self, first_start: str, first_end: str, second_start: str, second_end: str) -> str:
        lines = []
        for label, (start, end) in (("FIRST", _dates(first_start, first_end)), ("SECOND", _dates(second_start, second_end))):
            rows = [t for t in self._txns if start <= t.day <= end]
            t = totals(rows)
            average_in = rm(t.total_in / t.count_in) if t.count_in else "none"
            average_out = rm(t.total_out / t.count_out) if t.count_out else "none"
            lines.append(f"{label}|{start} to {end} ({(end - start).days + 1} days)|count={t.count}|"
                         f"active_days={t.active_days}|in={rm(t.total_in)} ({t.count_in})|out={rm(t.total_out)} "
                         f"({t.count_out})|average_in={average_in}|average_out={average_out}")
        return "\n".join(lines)

    def find_repeated_amounts(self, min_count: int = 2, min_amount: float | None = None, direction: str = "both") -> str:
        found = repeated_amounts(self._txns, _whole(min_count, "min_count", 2, 10_000), _amount(min_amount) or ZERO,
                                 _direction(direction))
        if not found:
            return "REPEATED|none"
        lines = [f"REPEATED|{len(found)} amount(s) occur at least {min_count} times"
                 + (" (showing the 30 most frequent)" if len(found) > 30 else "")]
        for r in found[:30]:
            ids = ",".join(t.tid for t in r.txns[:40]) + (f" and {len(r.txns) - 40} more" if len(r.txns) > 40 else "")
            lines.append(f"AMOUNT|{rm(r.amount)}|{r.direction}|x{len(r.txns)}|total={rm(r.amount * len(r.txns))}|"
                         f"{r.txns[0].day} to {r.txns[-1].day}|ids={ids}")
        return "\n".join(lines)

    def find_quiet_periods(self, min_days: int) -> str:
        gaps = quiet_periods(self._txns, _whole(min_days, "min_days", 1, 10_000))
        if not gaps:
            return f"QUIET|no gap of {min_days} days or more"
        return "\n".join([f"QUIET|{len(gaps)} gap(s) of at least {min_days} days"] + [q.line() for q in gaps[:50]])

    def total_of(self, transaction_ids: list[str]) -> str:
        found, unknown = self._lookup(transaction_ids)
        if not found:
            return "error: none of these ids exists"
        t = totals(found)
        share = f"|out_as_share_of_in={t.out_share_of_in}%" if t.out_share_of_in is not None else ""
        return f"TOTAL|{t.line()}|in_minus_out={rm(t.net)}{share}" + _unknown(unknown)

    # --- helpers ------------------------------------------------------------------------

    def _lookup(self, ids: Any) -> tuple[list[Txn], list[str]]:
        if not isinstance(ids, list) or not ids:
            raise ToolError("transaction_ids must be a non-empty list such as [\"T12\", \"T13\"]")
        found, unknown = [], []
        for tid in dict.fromkeys(str(i).strip().upper() for i in ids):
            (found.append(self._account.by_tid[tid]) if tid in self._account.by_tid else unknown.append(tid))
        return sorted(found, key=lambda t: (t.when, t.seq)), unknown

    def _rows(self, rows: list[Txn]) -> str:
        shown = rows[:self._max_rows]
        note = (f"\n(showing the first {len(shown)} of {len(rows)} rows; the totals above cover all of them. "
                "Narrow the dates or amounts to see the rest.)" if len(rows) > len(shown) else "")
        return "\n".join((ROW_HEADER, *(row_line(self._account, t) for t in shown))) + note


def _dates(start: str, end: str) -> tuple[date, date]:
    try:
        first, last = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError as exc:
        raise ToolError(f"dates must be YYYY-MM-DD ({exc})") from exc
    if last < first:
        raise ToolError("end date is before start date")
    return first, last


def _direction(value: str) -> str:
    side = str(value or "both").strip()
    if side not in {"C", "D", "both"}:
        raise ToolError("direction must be C, D or both")
    return side


def _amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ToolError(f"amount '{value}' is not a number") from exc


def _whole(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{name} must be a whole number") from exc
    if not low <= number <= high:
        raise ToolError(f"{name} must be between {low} and {high}")
    return number


def _unknown(ids: list[str]) -> str:
    return f"\nNOT FOUND (no such transaction): {', '.join(ids)}" if ids else ""
