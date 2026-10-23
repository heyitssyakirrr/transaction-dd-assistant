"""What every AI step shares: the patterns to look for, what the data cannot show, the risk levels and
the rules for writing. To add a pattern, add one entry to PATTERNS; nothing else needs to change.

The AI sees four columns only (date, sequence number, direction, amount), so every pattern here must be
visible from those. What they cannot show is listed in CANNOT_CHECK and reported as "cannot check".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    key: str
    title: str
    looks_like: str
    ordinary: str              # the innocent explanations the analyst should rule out
    needs_time: bool = False   # only checkable when TXN_DATE carries a time of day


PATTERNS: tuple[Pattern, ...] = (
    Pattern("pass_through", "Pass-through",
            "money comes in and most of it leaves soon after (later the same day, which the sequence numbers show, or "
            "within a few days), so little stays in the account",
            "a property or vehicle sale paid on, savings moved between the customer's own accounts, a business settlement"),
    Pattern("many_in_one_out", "Many in, then one out",
            "many credits within a short time, then one or a few large debits that take most of it out",
            "a group collection, family members pooling money, a small business banking its takings"),
    Pattern("one_in_many_out", "One in, then many out",
            "one or a few large credits, then many debits soon after that spread the money out",
            "paying suppliers or wages, sharing an inheritance or family money"),
    Pattern("repeated_amounts", "Repeated identical or round amounts",
            "the same amount, or round figures, again and again in a way the account's ordinary activity does not "
            "explain",
            "a fixed salary, rent, loan instalment, allowance or standing instruction"),
    Pattern("below_reporting_limit", "Amounts just under the reporting limit",
            "several amounts just below the daily reporting limit on the same or nearby days, so each stays under it "
            "(the data does not say whether they are cash)",
            "genuine separate payments that happen to be of that size"),
    Pattern("dormant_then_active", "Quiet, then suddenly active",
            "a long period with little or no activity, then large amounts",
            "a customer returning from abroad, a one-off sale, an account reopened for a specific purpose"),
    Pattern("sudden_change", "Sudden change in activity",
            "amounts or counts far above (or below) this account's own usual level, from a clear point in time",
            "a new job or business, a large one-off event"),
    Pattern("high_value_low_activity", "High value, few transactions",
            "very large amounts moving through an account that otherwise has very few transactions",
            "an account kept for occasional large personal transactions"),
    Pattern("drawdown_after_inflow", "Drawn down after a large inflow",
            "after a large credit, debits steadily empty the account while no new money comes in",
            "spending savings, paying for a large purchase in stages"),
    Pattern("unusual_timing", "Unusual timing",
            "transactions late at night, or many within minutes of each other",
            "shift work, scheduled transfers", needs_time=True),
)
PATTERN_BY_KEY = {p.key: p for p in PATTERNS}
FINDING_KEYS = tuple(p.key for p in PATTERNS) + ("other",)
TITLES = {p.key: p.title for p in PATTERNS} | {"other": "Other pattern"}


@dataclass(frozen=True)
class Limit:
    key: str
    title: str
    reason: str


# What the four columns cannot show: always in the checklist as "cannot check", with the reason.
CANNOT_CHECK: tuple[Limit, ...] = (
    Limit("cash", "Cash or not", "Only date, sequence number, direction and amount are used, so cash cannot be "
          "told apart from transfers or cheques."),
    Limit("counterparties", "Who sent or received the money", "The data has no counterparty, so round trips and "
          "shared senders or receivers cannot be seen."),
    Limit("channel_teller", "Channel and teller patterns", "The channel and teller are not used, so patterns in "
          "where or by whom transactions were made cannot be seen."),
    Limit("customer_profile", "Fit with the customer's profile", "Customer details are not used, so whether the "
          "activity fits the customer cannot be judged."),
)
TIME_LIMIT = Limit("unusual_timing", TITLES["unusual_timing"], "TXN_DATE has no time of day, so the hour of a "
                   "transaction cannot be seen; the sequence number gives only the order within the day.")


def checkable(has_time: bool) -> tuple[Pattern, ...]:
    return tuple(p for p in PATTERNS if has_time or not p.needs_time)


def cannot_check(has_time: bool) -> tuple[Limit, ...]:
    return CANNOT_CHECK if has_time else (TIME_LIMIT, *CANNOT_CHECK)


# DRAFT: replace with the AML team's own definitions.
RISK_DEFINITIONS = """Risk level:
- high: at least one confirmed pattern with strong evidence that moves large sums in a way typical of money
  laundering (pass-through, many in then one out, one in then many out, amounts kept under the reporting limit),
  or several confirmed patterns that together have no ordinary explanation visible in the data.
- medium: a confirmed pattern with moderate evidence, or one that a plausible ordinary explanation could account for
  and that the data cannot rule out.
- low: no confirmed pattern, or only weak indicators that ordinary activity explains."""

HOUSE_RULES = """Rules:
- You see four things per transaction only: date, sequence number within the day, direction and amount. Never guess
  the transaction type (cash, cheque, transfer), who sent or received the money, the channel, the purpose, or anything
  about the customer.
- Cite transaction ids exactly as given (T123). List every id that belongs to what you describe; never write a range
  such as T5-T9.
- Write amounts as RM 1,234.56 and copy them exactly from the rows, the summary or a tool answer. Do not add up amounts
  yourself: quote a total from the summary or a tool, or give the count and the individual amounts instead.
- Write dates as YYYY-MM-DD.
- Write for an AML analyst in plain, neutral words ("consistent with", "indicator"), never "suspicious", "criminal"
  or "laundering" as a conclusion.
- Ordinary activity (salary-like credits, regular bills, small everyday debits) is not a finding. An empty list is a
  valid answer: do not stretch to find something."""


def pattern_list(has_time: bool) -> str:
    """The patterns as the prompts show them, one line each."""
    lines = ["Patterns (key: what it looks like | ordinary explanations to weigh):"]
    lines += [f"- {p.key}: {p.looks_like} | {p.ordinary}" for p in checkable(has_time)]
    lines.append("- other: another clear indicator visible in dates, order, directions and amounts; name it in the note")
    return "\n".join(lines)
