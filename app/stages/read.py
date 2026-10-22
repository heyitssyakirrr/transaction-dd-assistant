"""Step: READ. The AI reads the raw rows and notes the patterns it sees.

Small account: one call reads every row, together with the summary.
Big account: one call per group of about 300 rows, all at the same time. Each also sees a few
neighbouring days and the monthly totals, and notes anything left open at its edges ("loose ends")
so the Combine step can join a pattern that runs from one group into the next.
"""
from __future__ import annotations

from pydantic import Field

from app.glossary import HOUSE_RULES, pattern_list
from app.ingest import Account
from app.stages.common import Answer, Ids, PatternKey, Strength, Text, answer_format
from app.summary import Group, row_legend, rows_block


def system_prompt(has_time: bool) -> str:
    return f"""You read a bank account's transactions row by row for an AML analyst. A long account is split into
groups that other reviewers read at the same time; a later step joins your notes with theirs, so be precise.

Read every row under ROWS. Rows under NEIGHBOURING DAYS belong to other groups: use them only to understand your
rows (for example, money that leaves just after your group ends). Never report a pattern that lies only in
neighbouring rows. The summary or the monthly totals show what is usual for this account.

How to read: follow the money day by day. Within a day, seq gives the order, so you can see whether money came in
and then went out. Look for identical or round amounts, many credits followed by one large debit (or the reverse),
sudden jumps against the usual level, quiet periods, and amounts just under the reporting limit.

Write:
- normal_activity: one or two sentences on the ordinary activity (how often, typical amounts, regular amounts).
- patterns: each pattern you see, with its key, EVERY transaction id involved (neighbouring ids only when they
  complete a pattern that starts in your rows), a note of at most 60 words with amounts, dates and order, and its
  strength (strong, moderate or weak).
- loose_ends: anything open at either edge of your group that another group may complete, for example a large
  credit near the end not yet seen going out. Give the ids and a short note. Leave it empty if you read every row
  of the account.

{pattern_list(has_time)}

{HOUSE_RULES}

{answer_format('{"normal_activity": "...", "patterns": [{"pattern": "pass_through", "transaction_ids": ["T12", "T13"], '
               '"note": "...", "strength": "moderate"}], "loose_ends": [{"transaction_ids": ["T40"], "note": "..."}]}')}"""


class SeenPattern(Answer):
    pattern: PatternKey
    transaction_ids: Ids
    note: Text = ""
    strength: Strength = "moderate"


class LooseEnd(Answer):
    transaction_ids: Ids
    note: Text = ""


class ReadNotes(Answer):
    normal_activity: Text = ""
    patterns: list[SeenPattern]  # required: an empty list is a valid answer, a missing one is not
    loose_ends: list[LooseEnd] = Field(default_factory=list)


def build_input(account: Account, group: Group, total_groups: int, background: str) -> str:
    """``background``: the full summary for a small account, the monthly totals for a big one."""
    if total_groups == 1:
        heading = f"ROWS: every transaction of the account, {len(group.txns)} rows."
    else:
        heading = f"ROWS: group {group.number} of {total_groups}, {group.period}, {len(group.txns)} rows."
    blocks = [("SUMMARY\n" if total_groups == 1 else "MONTHLY TOTALS\n") + background, row_legend(account)]
    if group.before:
        blocks.append("NEIGHBOURING DAYS BEFORE (another group's rows, for context only)\n"
                      + rows_block(account, group.before))
    blocks.append(heading + "\n" + rows_block(account, group.txns))
    if group.after:
        blocks.append("NEIGHBOURING DAYS AFTER (another group's rows, for context only)\n"
                      + rows_block(account, group.after))
    return "\n\n".join(blocks)
