"""Step: COMBINE (big accounts only). One AI call, with tools. It puts together the Summary review's
leads and every group's notes, joins the pieces of a pattern that runs across groups, looks up the rows
behind each lead with the tools, and lists the suspected patterns to check."""
from __future__ import annotations

from pydantic import Field

from app.review.glossary import HOUSE_RULES, pattern_list
from app.review.stages.common import Answer, Ids, PatternKey, Text, answer_format
from app.review.stages.read import ReadNotes
from app.review.stages.summary_review import SummaryNotes


def system_prompt(has_time: bool, max_patterns: int) -> str:
    return f"""You put together the work of several reviewers of one bank account, for an AML analyst, and decide
which suspected patterns are worth checking against the actual rows. One reviewer saw the summary of the whole
period (LEADS); the others each read the raw rows of one group, in time order (GROUP notes).

How to put it together:
- One pattern may show in several groups (the same amount every month), or start in one group and end in the next:
  a LOOSE_END at the end of one group is often completed by a PATTERN at the start of the next. Join them into ONE
  suspected pattern with all their transaction ids.
- A LEAD names dates but often not every transaction id. Use the tools to find the ids (get_transactions for a date
  range, find_repeated_amounts, follow_money to see where money went after credits) before you list it.
- Use the tools whenever a note leaves something open, and to check a figure before you write it. The tools answer
  exactly from all the rows.
- Drop notes about ordinary activity. List at most {max_patterns} suspected patterns, strongest first, each with
  every transaction id that belongs to it.

Write:
- account_story: three or four sentences: how the account is normally used, what changed and when.
- suspected_patterns: pattern key, every transaction id, and why (at most 60 words, with amounts and dates).
- not_seen: the pattern keys that no reviewer saw anywhere.

{pattern_list(has_time)}

{HOUSE_RULES}

{answer_format('{"account_story": "...", "suspected_patterns": [{"pattern": "pass_through", '
               '"transaction_ids": ["T40", "T41"], "why": "..."}], "not_seen": ["below_reporting_limit"]}')}"""


class Suspected(Answer):
    pattern: PatternKey
    transaction_ids: Ids
    why: Text = ""


class CombineResult(Answer):
    account_story: Text = ""
    suspected_patterns: list[Suspected]  # required: an empty list is a valid answer, a missing one is not
    not_seen: list[PatternKey] = Field(default_factory=list)


def build_input(summary: str, summary_notes: SummaryNotes | None,
                group_notes: list[tuple[int, str, ReadNotes | None]]) -> str:
    """``group_notes``: (group number, its dates, its notes or None when that group could not be read)."""
    blocks = ["SUMMARY (exact figures computed from every row)\n" + summary]
    if summary_notes is None:
        blocks.append("LEADS: not available (the Summary review failed).")
    else:
        lines = [f"LEADS (from the Summary review)\nstory: {summary_notes.account_story or 'not given'}"]
        lines += [f"LEAD|{lead.pattern}|{lead.strength}|{lead.start_date} to {lead.end_date}|"
                  f"{','.join(lead.transaction_ids) or 'no ids'}|{lead.note}" for lead in summary_notes.leads]
        if not summary_notes.leads:
            lines.append("no leads")
        blocks.append("\n".join(lines))
    blocks.append("NOTES FROM EACH GROUP, in time order:")
    for number, dates, notes in group_notes:
        if notes is None:
            blocks.append(f"GROUP {number} ({dates}): NOT READ (the call failed). Use the tools to look at it.")
            continue
        lines = [f"GROUP {number} ({dates})", f"normal: {notes.normal_activity or 'not given'}"]
        lines += [f"PATTERN|{p.pattern}|{p.strength}|{','.join(p.transaction_ids)}|{p.note}" for p in notes.patterns]
        lines += [f"LOOSE_END|{','.join(e.transaction_ids)}|{e.note}" for e in notes.loose_ends]
        if len(lines) == 2:
            lines.append("no patterns, no loose ends")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
