"""Exact figures the code prepares for the AI. Counting only: nothing here decides what is unusual.
Lists are ranked (largest, most repeated, longest), never cut at a threshold, so the AI decides.

  row_line, rows_block    the one row format every AI call sees: the T-label and the four columns
  totals                  counts and sums of any set of transactions
  summary                 the summary of the whole account: account line, months, days, repeated
                          amounts, largest transactions, longest quiet periods
  monthly_totals          the short form: the account line and one line per month
  split_into_groups       the groups the Read step gets for a big account, with neighbouring days
  check_rows              the rows a Check call gets
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from app.account.ingest import Account, Txn
from app.config import Settings

ZERO = Decimal("0.00")


def rm(value: Decimal) -> str:
    return f"RM {value:,.2f}"


# --- the row format --------------------------------------------------------------------------

ROW_HEADER = "id|date|seq|dir|amount_rm"


def row_legend(account: Account) -> str:
    when = "date and time" if account.has_time else "date (no time of day)"
    return (f"Rows: id|date|seq|dir|amount_rm. date = {when}; seq = order within the day (1 = first); "
            "dir C = money in, D = money out. Rows are in time order.")


def row_line(account: Account, txn: Txn) -> str:
    """One transaction as the AI sees it: its label and the four columns, nothing else."""
    return f"{txn.tid}|{account.date_text(txn)}|{txn.seq}|{txn.direction}|{txn.amount:,.2f}"


def rows_block(account: Account, txns: Iterable[Txn]) -> str:
    return "\n".join((ROW_HEADER, *(row_line(account, txn) for txn in txns)))


# --- totals of any set of transactions -------------------------------------------------------

@dataclass(frozen=True)
class Totals:
    count: int
    count_in: int
    total_in: Decimal
    count_out: int
    total_out: Decimal
    first: date | None
    last: date | None
    active_days: int
    largest_in: Txn | None
    largest_out: Txn | None

    @property
    def net(self) -> Decimal:
        return self.total_in - self.total_out

    @property
    def out_share_of_in(self) -> Decimal | None:
        """Money out as a % of money in, or None when nothing came in."""
        return (self.total_out * 100 / self.total_in).quantize(Decimal("0.1")) if self.total_in else None

    def line(self) -> str:
        parts = [f"count={self.count}", f"in={rm(self.total_in)} ({self.count_in})",
                 f"out={rm(self.total_out)} ({self.count_out})"]
        if self.first:
            parts.append(f"from={self.first}|to={self.last}|active_days={self.active_days}")
        if self.largest_in:
            parts.append(f"largest_in={rm(self.largest_in.amount)} ({self.largest_in.tid})")
        if self.largest_out:
            parts.append(f"largest_out={rm(self.largest_out.amount)} ({self.largest_out.tid})")
        return "|".join(parts)


def totals(txns: Iterable[Txn]) -> Totals:
    txns = list(txns)
    ins = [t for t in txns if t.direction == "C"]
    outs = [t for t in txns if t.direction == "D"]
    days = sorted({t.day for t in txns})
    return Totals(
        count=len(txns), count_in=len(ins), total_in=sum((t.amount for t in ins), ZERO),
        count_out=len(outs), total_out=sum((t.amount for t in outs), ZERO),
        first=days[0] if days else None, last=days[-1] if days else None, active_days=len(days),
        largest_in=max(ins, key=lambda t: t.amount, default=None),
        largest_out=max(outs, key=lambda t: t.amount, default=None),
    )


# --- groupings -------------------------------------------------------------------------------

def by_month(account: Account) -> list[tuple[str, list[Txn]]]:
    """Every calendar month from the first to the last transaction, empty months included
    (an empty month is how a quiet period shows)."""
    grouped: dict[str, list[Txn]] = defaultdict(list)
    for txn in account.txns:
        grouped[txn.month].append(txn)
    return [(month, grouped.get(month, [])) for month in months_between(account.first_day, account.last_day)]


def by_day(txns: Iterable[Txn]) -> list[tuple[date, list[Txn]]]:
    grouped: dict[date, list[Txn]] = defaultdict(list)
    for txn in txns:
        grouped[txn.day].append(txn)
    return sorted(grouped.items())


def by_week(txns: Iterable[Txn]) -> list[tuple[date, list[Txn]]]:
    """Keyed by the Monday of each week that has transactions."""
    grouped: dict[date, list[Txn]] = defaultdict(list)
    for txn in txns:
        grouped[txn.day - timedelta(days=txn.day.weekday())].append(txn)
    return sorted(grouped.items())


@dataclass(frozen=True)
class Repeated:
    amount: Decimal
    direction: str
    txns: list[Txn]


def repeated_amounts(txns: Iterable[Txn], min_count: int = 2, min_amount: Decimal = ZERO,
                     direction: str = "both") -> list[Repeated]:
    """Amounts that occur at least ``min_count`` times in one direction; most frequent first."""
    grouped: dict[tuple[Decimal, str], list[Txn]] = defaultdict(list)
    for txn in txns:
        if txn.amount >= min_amount and direction in ("both", txn.direction):
            grouped[(txn.amount, txn.direction)].append(txn)
    found = [Repeated(amount, side, rows) for (amount, side), rows in grouped.items() if len(rows) >= min_count]
    return sorted(found, key=lambda r: (-len(r.txns), -r.amount))


@dataclass(frozen=True)
class Quiet:
    after: Txn       # the last transaction before the quiet period
    before: Txn      # the first transaction after it

    @property
    def days(self) -> int:
        return (self.before.day - self.after.day).days

    def line(self) -> str:
        return (f"QUIET|{self.after.day} ({self.after.tid}) to {self.before.day} ({self.before.tid})|"
                f"{self.days} days between transactions")


def quiet_periods(txns: list[Txn], min_days: int = 1) -> list[Quiet]:
    """Gaps between one transaction and the next of at least ``min_days``; longest first."""
    gaps = [Quiet(a, b) for a, b in zip(txns, txns[1:]) if (b.day - a.day).days >= max(min_days, 1)]
    return sorted(gaps, key=lambda q: (-q.days, q.after.when))


# --- the summary -------------------------------------------------------------------------------

def group_line(label: str, key: str, txns: list[Txn]) -> str:
    t = totals(txns)
    return f"{label}|{key}|count={t.count}|in={rm(t.total_in)} ({t.count_in})|out={rm(t.total_out)} ({t.count_out})"


def account_line(account: Account) -> str:
    t = totals(account.txns)
    first, last = account.first_day, account.last_day
    return (f"ACCOUNT|period={first} to {last} ({(last - first).days + 1} days)|transactions={t.count}|"
            f"active_days={t.active_days}|in={rm(t.total_in)} ({t.count_in})|out={rm(t.total_out)} ({t.count_out})|"
            f"in_minus_out={rm(t.net)}|time_of_day={'given' if account.has_time else 'not given'}")


def monthly_totals(account: Account, settings: Settings) -> str:
    """The short form: the account line, the reporting limit, and one line per month."""
    lines = [account_line(account),
             f"REPORTING_LIMIT|{rm(settings.cash_report_limit)} per account per day applies to cash; the "
             "transaction type is not given, so whether an amount is cash cannot be seen",
             "MONTHS (exact; empty months included):"]
    for month, txns in by_month(account):
        t = totals(txns)
        largest = max(txns, key=lambda x: x.amount, default=None)
        biggest = f"|largest={rm(largest.amount)} {largest.direction} ({largest.tid})" if largest else ""
        lines.append(f"MONTH|{month}|count={t.count}|in={rm(t.total_in)} ({t.count_in})|"
                     f"out={rm(t.total_out)} ({t.count_out}){biggest}")
    return "\n".join(lines)


def summary(account: Account, settings: Settings, *, with_days: bool = True) -> str:
    """The summary of the whole account, about 6,000 tokens even for 10,000 rows, so one AI call can
    see patterns that span months or groups. ``with_days=False`` leaves out the day lines (for Decide)."""
    txns = account.txns
    blocks = [monthly_totals(account, settings)]
    if with_days:
        days = by_day(txns)
        if len(days) <= settings.summary_max_days:
            title = "DAYS (every day with transactions; exact):"
            lines = [group_line("DAY", str(day), rows) for day, rows in days]
        else:
            title = f"WEEKS (week starting Monday; {len(days)} active days are too many to list one by one):"
            lines = [group_line("WEEK", str(week), rows) for week, rows in by_week(txns)]
        blocks.append("\n".join((title, *lines)))
    size = settings.summary_list_size
    repeated = repeated_amounts(txns)[:size]
    largest = sorted(txns, key=lambda t: (-t.amount, t.when, t.seq))[:size]
    quiet = quiet_periods(txns)[:5]
    blocks.append("\n".join(("REPEATED AMOUNTS (same amount and direction, most frequent first):",
                             *(f"AMOUNT|{rm(r.amount)}|{r.direction}|x{len(r.txns)}|{r.txns[0].day} to "
                               f"{r.txns[-1].day}|ids={_ids(r.txns, 12)}" for r in repeated)))
                  if repeated else "REPEATED AMOUNTS: none")
    blocks.append("\n".join(("LARGEST TRANSACTIONS:", *(f"LARGE|{t.tid}|{account.date_text(t)}|{t.seq}|"
                                                        f"{t.direction}|{rm(t.amount)}" for t in largest))))
    blocks.append("\n".join(("LONGEST QUIET PERIODS:", *(q.line() for q in quiet)))
                  if quiet else "LONGEST QUIET PERIODS: none")
    return "\n\n".join(blocks)


def _ids(txns: list[Txn], limit: int) -> str:
    shown = ",".join(t.tid for t in txns[:limit])
    return shown + (f" and {len(txns) - limit} more" if len(txns) > limit else "")


# --- groups for the Read step (big accounts) -----------------------------------------------------

@dataclass(frozen=True)
class Group:
    number: int
    txns: list[Txn]       # the rows this reader is responsible for
    before: list[Txn]     # neighbouring days just before (another group's rows), for context only
    after: list[Txn]      # neighbouring days just after

    @property
    def period(self) -> str:
        return f"{self.txns[0].day} to {self.txns[-1].day}"


def split_into_groups(account: Account, settings: Settings) -> list[Group]:
    """About ``rows_per_group`` rows each, shared equally. A group ends at the end of a day, except a
    day with more rows than one group holds, which is split in sequence order.
    Groups = rows / rows_per_group, rounded up: 1,000 rows give 4 groups of about 250."""
    txns, size = account.txns, settings.rows_per_group
    count = max(1, math.ceil(len(txns) / size))
    target = len(txns) / count
    units: list[list[Txn]] = []           # whole days, or slices of a very busy day
    for _, rows in by_day(txns):
        units.extend(rows[i:i + size] for i in range(0, len(rows), size))
    groups: list[list[Txn]] = [[]]
    taken = 0
    for unit in units:
        if groups[-1] and len(groups[-1]) + len(unit) > size * 1.5:
            groups.append([])             # never let one group grow far past its share
        groups[-1].extend(unit)
        taken += len(unit)
        if taken >= target * len(groups) and len(groups) < count:
            groups.append([])
    groups = [g for g in groups if g]
    result, start = [], 0
    for number, rows in enumerate(groups, start=1):
        end = start + len(rows)
        result.append(Group(number, rows, _neighbours(txns[:start], rows[0].day, settings, before=True),
                            _neighbours(txns[end:], rows[-1].day, settings, before=False)))
        start = end
    return result


def _neighbours(rows: list[Txn], edge: date, settings: Settings, *, before: bool) -> list[Txn]:
    if not settings.neighbour_days or not settings.max_neighbour_rows:
        return []
    if before:
        near = [t for t in rows if t.day >= edge - timedelta(days=settings.neighbour_days)]
        return near[-settings.max_neighbour_rows:]
    near = [t for t in rows if t.day <= edge + timedelta(days=settings.neighbour_days)]
    return near[:settings.max_neighbour_rows]


# --- rows for the Check step ----------------------------------------------------------------------

def check_rows(account: Account, tids: list[str], settings: Settings) -> list[Txn]:
    """The cited rows plus every row within ``check_days`` of any of them, in time order, from the
    whole account. Capped at 1.5 groups' worth: the cited rows always stay, the nearest others first."""
    wanted = set(tids)
    cited = [t for t in account.txns if t.tid in wanted]
    if not cited:
        return []
    days = {t.day for t in cited}
    span = range(-settings.check_days, settings.check_days + 1)
    allowed = {day + timedelta(days=offset) for day in days for offset in span}
    near = [t for t in account.txns if t.tid in wanted or t.day in allowed]
    limit = max(int(settings.rows_per_group * 1.5), len(cited))
    if len(near) <= limit:
        return near
    others = sorted((t for t in near if t.tid not in wanted), key=lambda t: min(abs((t.day - d).days) for d in days))
    keep = wanted | {t.tid for t in others[:limit - len(cited)]}
    return [t for t in near if t.tid in keep]


def months_between(first: date, last: date) -> list[str]:
    months, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
