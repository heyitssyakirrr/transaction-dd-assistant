"""Step: SUMMARY REVIEW (big accounts only). One AI call reads only the summary, at the same time as
the Read calls, to spot patterns that only show across months or across groups."""
from __future__ import annotations

from pydantic import Field

from app.glossary import HOUSE_RULES, pattern_list
from app.stages.common import Answer, Ids, PatternKey, Strength, Text, answer_format


def system_prompt(has_time: bool) -> str:
    return f"""You review the summary of one bank account for an AML analyst. The summary covers the whole period:
every month, every day with activity, the amounts that repeat, the largest transactions and the longest quiet
periods. Other reviewers read the raw rows in groups at the same time; you see what they cannot: the whole period.

Look for patterns that only show across days, weeks or months, for example: money in and out on the same day or
nearby days; the same amount repeated across many months; a long quiet period then large amounts; a clear change in
the level of activity from some date; an account emptied after a large inflow; very large amounts in an account
with few transactions; several amounts just under the reporting limit on nearby days. Judge against this account's
own usual level, which the months show.

Write:
- account_story: three or four sentences on how the account was used over time, in phases with dates and amounts.
- leads: each pattern worth checking against the raw rows, with its key, the first and last date it covers, the
  transaction ids the summary gives for it (AMOUNT, LARGE and QUIET lines name ids; give none rather than guess), a
  note of at most 60 words with the figures that show it, and its strength (strong, moderate or weak).
  The Combine step will look up the rows for each lead, so the dates matter most.

{pattern_list(has_time)}

{HOUSE_RULES}

{answer_format('{"account_story": "...", "leads": [{"pattern": "pass_through", "start_date": "2026-04-24", '
               '"end_date": "2026-04-24", "transaction_ids": ["T4"], "note": "...", "strength": "strong"}]}')}"""


class Lead(Answer):
    pattern: PatternKey
    start_date: Text = ""
    end_date: Text = ""
    transaction_ids: Ids = Field(default_factory=list)
    note: Text = ""
    strength: Strength = "moderate"


class SummaryNotes(Answer):
    account_story: Text = ""
    leads: list[Lead]  # required: an empty list is a valid answer, a missing one is not


def build_input(summary: str) -> str:
    return "SUMMARY (exact figures computed from every row)\n" + summary
