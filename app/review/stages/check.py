"""Step: CHECK. One AI call per suspected pattern, all at the same time, with tools. The AI looks at the
real rows around the pattern, asks the tools for exact figures, and confirms or rejects it, giving the
innocent explanation too."""
from __future__ import annotations

from app.account.ingest import Account, Txn
from app.account.summary import row_legend, rows_block
from app.review.glossary import HOUSE_RULES, pattern_list
from app.review.stages.combine import Suspected
from app.review.stages.common import Answer, Ids, PatternKey, Strength, Text, answer_format


def system_prompt(has_time: bool) -> str:
    return f"""You check one suspected pattern in a bank account against the actual transactions, for an AML
analyst. Another reviewer suggested it; you see the real rows: the cited transactions and the days around them.

Work like an investigator:
1. Read the cited rows in order (seq gives the order within a day).
2. Use the tools to test it: follow_money to see where money went after credits, total_of for exact totals of the
   rows you will describe, compare_periods or summarise to compare with the account's usual level,
   get_transactions to look beyond the rows given.
3. Decide whether the pattern is really there, and whether an ordinary explanation fits the rows better.

Then write, in this order:
- what_happened: at most 90 words, the facts in time order with exact amounts and dates (use tool totals; do not add
  up amounts yourself).
- why_it_matters: at most 50 words on why this is (or is not) an AML indicator.
- ordinary_explanation: the most likely innocent reason the analyst should rule out.
- what_to_verify: one or two concrete checks for the analyst, naming the transactions they concern (for example the
  source of a credit, who received a debit, the purpose of a series).
- transaction_ids: the complete, corrected list: add rows that belong to it, remove rows that do not.
- pattern: the pattern key that fits best.
- strength: strong, moderate or weak.
- confirmed: true only when the rows show the pattern; false when ordinary activity explains them.

{pattern_list(has_time)}

{HOUSE_RULES}

{answer_format('{"what_happened": "...", "why_it_matters": "...", "ordinary_explanation": "...", '
               '"what_to_verify": "...", "transaction_ids": ["T40", "T41"], "pattern": "pass_through", '
               '"strength": "strong", "confirmed": true}')}"""


class CheckResult(Answer):
    what_happened: Text = ""
    why_it_matters: Text = ""
    ordinary_explanation: Text = ""
    what_to_verify: Text = ""
    transaction_ids: Ids
    pattern: PatternKey
    strength: Strength = "moderate"
    confirmed: bool


def build_input(account: Account, monthly: str, suspected: Suspected, rows: list[Txn]) -> str:
    return "\n\n".join((
        "MONTHLY TOTALS\n" + monthly,
        f"SUSPECTED PATTERN|pattern={suspected.pattern}|cited={','.join(suspected.transaction_ids)}\n"
        f"Why it was suggested: {suspected.why or 'not given'}",
        row_legend(account),
        f"ROWS (the cited transactions and the days around them, {len(rows)} rows)\n" + rows_block(account, rows),
    ))
