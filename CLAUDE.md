# CLAUDE.md

Read this first in every session. It is the agreed design of this project; README.md has the run steps.

## What this is

A tool for Public Bank AML analysts. It reviews ONE account's transactions (one year or less, from a few
dozen up to about 10,000 rows), finds money-laundering patterns, and writes a report that tells the
analyst what to investigate next. The AI is gpt-6-luna on the bank's AI Foundry.

- **The AI makes every judgement:** the patterns, the risk level and all the insight text.
- **The code never judges:** it only prepares the data, computes exact figures, answers the AI's tool
  questions, and checks the AI's answers. No fixed thresholds, no Python-written summaries.
- **The analyst decides the action.**

## Rules

1. **Only 4 columns are used:** TXN_DATE, TRANSACTION_SEQ_NO, CREDIT_DEBIT_CODE, AMOUNT. Every other
   column in the file is ignored when it is read (`app/account/ingest.py`). Do not read, show or send any other
   column.
2. **Don't invent what we don't have:** no code-mapping files or lookups, and no feature, setting or file
   the user did not ask for. If something seems missing, ask first.
3. **Never hide a problem.** A failed or blocked call, a wrong amount or an unknown transaction ID is
   shown in the report. It is never silently fixed or dropped.
4. **The Foundry request** (`app/llm/client.py`):
   - `POST {LLM_BASE_URL}/foundry/chat/completions`;
   - header `X-PBAI-Helper-Id` only (no Authorization header);
   - body: `model`, `messages` (roles system, user, assistant, tool), `max_tokens`, `stream: false`,
     and `tools`;
   - never send temperature, top_p or stop.
5. **No real customer data** in the repo, code or examples.
6. **Do not push to GitHub.** Commit locally only.
7. **Big changes: explain the plan first and wait for the user's OK.**

## How the user wants to work

- Plain English, short sentences, one name for each thing (see "Names" below). Don't give too much at
  once.
- When giving code to copy, give complete files.
- Keep the code simple, readable, maintainable and efficient.
- Compliance and approval questions go to the user's senior developer; data questions go to the data
  senior.

## Names: use these, and only these

| Name | Meaning |
|---|---|
| **the rows** | The transactions as the AI sees them: `T4\|2026-04-24\|3\|D\|150,000.00` |
| **the summary** | Exact totals by code: account line, months, days, repeated amounts, largest transactions, quiet periods |
| **monthly totals** | The short form: the account line and one line per month |
| **group** | About 300 rows that one Read call takes (big accounts only) |
| **Read, Summary review, Combine, Check, Decide** | The five AI steps |
| **suspected pattern** | What Read or Combine hands to Check |
| **finding** | A pattern that Check confirmed (F1, F2…) |
| **tools** | The 7 functions the AI can ask the code to run, in Combine and Check |

## The flow

- **Small account (300 rows or fewer):** Read (every row + the summary) → Check (one call per suspected
  pattern, with tools) → Decide.
- **Big account:**
  1. Summary review (the summary only) and Read (one call per group + 3 neighbouring days), at the same
     time;
  2. Combine (with tools: joins pieces across groups);
  3. Check;
  4. Decide.
- **Then code** checks the AI's text (IDs, RM amounts, dates, checklist) and builds the report as HTML
  and JSON.
- **One retry per call:**
  - blocked → send again;
  - cut off → larger size;
  - bad JSON → ask again.

  If it still fails, the report says what was not done. If no rows could be read at all, the risk
  level is "not assessed".

## Files

Four folders, one job each. Imports go one way: `report` uses `review`, `review` uses `account` and `llm`,
`account` uses nothing else in the app.

| File | Job |
|---|---|
| `app/config.py` | Settings from `.env` |
| `app/service.py`, `app/cli.py`, `app/main.py` | Save reports; command line; web page (the entry points) |
| **`app/account/`** | **The rows: read the file and compute exact figures** |
| `app/account/columns.py` | The 4 column names |
| `app/account/ingest.py` | Read the file, check rows, sort, number T1…Tn |
| `app/account/summary.py` | Row format, totals, the summary, groups, the rows each Check sees |
| **`app/review/`** | **The five AI steps** |
| `app/review/pipeline.py` | Runs the steps |
| `app/review/stages/*.py` | One file per AI step: prompt, input, answer shape |
| `app/review/glossary.py` | Patterns, what the data cannot show, draft risk levels, writing rules |
| `app/review/tools.py` | The 7 tools |
| `app/review/checks.py` | Checks on the AI's text: IDs, RM amounts, dates |
| **`app/llm/`** | **Talking to Foundry** |
| `app/llm/client.py`, `app/llm/ask.py` | One Foundry request; one AI call with tool rounds and the retry |
| **`app/report/`** | **The analyst's report** |
| `app/report/builder.py` | Builds the report from a finished review |
| `app/report/model.py`, `app/report/html.py` | The report as JSON and as the HTML page |

## Status (23 Oct 2026)

- The code is complete. It was checked against a fake Foundry gateway (tool calls, blocked requests, bad
  answers, failures), but **not yet against the real Foundry**.
- **Not yet known:**
  1. Does the Foundry gateway accept `tools`? If not, Combine and Check fail with an HTTP error in the
     report's Processing section. The fallback is to give Check more rows and the exact totals up front.
  2. How good the AI's insight is on real accounts.

## Next steps

1. Run real accounts: `python -m app.cli "path\to\account.csv"`. Read the Processing section first.
2. Compare with 5 to 10 accounts that analysts have already investigated: what did it find, what did it
   miss, would "What to verify first" help them?
3. Run 2 or 3 accounts twice, to see whether the risk level stays the same.
4. Improve the prompts (`app/review/stages/`, `app/review/glossary.py`) based on what fails.

## Open questions for the senior

1. The AML team's risk definitions, to replace the draft in `app/review/glossary.py`.
2. Is the RM 25,000 cash reporting limit right? The AI cannot see cash, so that check is on amounts only.
3. Does the real TXN_DATE have a time of day? The code handles both.
4. Later: could a transaction *type* (cash or transfer) be sent to the AI once a mapping exists? It would
   make the insight sharper. Not built.
