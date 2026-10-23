# Transaction review assistant

Reviews one account's transactions for money-laundering patterns and gives the AML analyst a report:
the risk level, the story of the account, each pattern found with its transactions and exact totals,
what to verify first, and questions to ask the customer.

**The AI (gpt-6-luna on AI Foundry) makes every judgement. The code only prepares the data, answers the
AI's tool questions exactly, and checks the AI's answers. The analyst decides the action.**

## What goes in

One account per file (CSV, TSV or Parquet). Only four columns are used:

| Column | Meaning |
|---|---|
| TXN_DATE | Date (DD/MM/YYYY or YYYY-MM-DD, with or without a time) |
| TRANSACTION_SEQ_NO | Order within the day (1 = first) |
| CREDIT_DEBIT_CODE | C = money in, D = money out |
| AMOUNT | Amount in RM |

Every other column is ignored. The names are set in `app/account/columns.py`.

## How a review works

The code sorts the transactions, labels them T1, T2, T3…, and prepares **the summary**: exact totals per
month and per day, the amounts that repeat, the largest transactions and the longest quiet periods.

**Small account (300 rows or fewer), about 5 AI calls:**
1. **Read**: the AI reads every row and the summary, and notes the patterns it sees.
2. **Check**: each suspected pattern gets a second look against the real rows (with tools).
3. **Decide**: the AI sets the risk level and writes the report text.

**Big account (more than 300 rows), about 15 calls for 1,000 rows and 45 for 10,000:**
1. **Summary review**: one AI reads only the summary, to spot patterns across months.
2. **Read**: at the same time, the rows are split into groups of about 300 and one AI reads each group.
3. **Combine**: one AI joins all the notes (with tools), so a pattern split across groups becomes one.
4. **Check**, then 5. **Decide**, as above.

**Tools.** In the Combine and Check steps the AI can ask the code exact questions:
`get_transactions`, `follow_money`, `summarise`, `compare_periods`, `find_repeated_amounts`,
`find_quiet_periods` and `total_of`. Every tool use is listed in the report.

**Checks.** Code checks every transaction ID, RM amount and date the AI writes, and every checklist mark.
Problems are listed in red; nothing is changed or hidden. A failed or blocked AI call is retried once;
if it still fails, the report says what was not done.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env               # fill in LLM_BASE_URL and HELPER_ID

python -m app.main                        # web page on http://127.0.0.1:5000
python -m app.cli path/to/account.csv     # one review from the command line, for quick checks
```

**The web page.** Upload one or more account files, or choose "Read from folder" and a range of files
(by file name) from the server folder in `ACCOUNT_FOLDER_PATH` (blank hides the option). Accounts are
reviewed `BATCH_ACCOUNT_CONCURRENCY` at a time, in order. The results page follows their progress and
shows each report on the page as soon as it is ready; Previous / Next moves between them. A file that
cannot be read shows why, and the others still run.

Reports are saved in `data/reports` as `.html` (open from the results page) and `.json` (for the
production UI).

**The log.** `data/logs/transaction_review.log` (`LOG_DIRECTORY`), a new file each day, kept
`LOG_RETENTION_DAYS` days. Each line names the account file in brackets, so reviews running at the same time
can be told apart. Per review it shows: each AI request (sizes only) and answer (finish reason, tokens),
blocked or cut-off calls and their retry, each tool use, what was not done, the checks' issues, and where the
report was saved. When a report says a step failed, search the log for the file name. To see what a blocked
request contained, set `LLM_SAVE_BLOCKED_REQUESTS=true` (it writes transaction rows to disk: only while
investigating). Batches are kept in memory, so the results page of a batch is gone after a restart; the
saved reports are not.

## Files

```
app/
  config.py                 settings from .env
  service.py                file -> review -> saved report (used by both entry points)
  main.py, cli.py           web page and command line
  account/                  the rows: read the file and compute exact figures
  review/                   the five AI steps, their tools, and the checks on the AI's text
  llm/                      talking to AI Foundry
  report/                   the analyst's report as JSON and HTML
  web/                      the web page: batches, folder, API, pages, scripts and styles
```

| File | What it does |
|---|---|
| `app/account/columns.py` | The four column names |
| `app/account/ingest.py` | Reads the file, checks every row, sorts, labels T1…Tn |
| `app/account/summary.py` | Row format, exact totals, the summary, groups, the rows each Check sees |
| `app/review/pipeline.py` | Runs the steps for one account |
| `app/review/stages/` | One file per AI step: `read`, `summary_review`, `combine`, `check`, `decide` |
| `app/review/glossary.py` | The patterns, what the data cannot show, risk levels (draft), writing rules |
| `app/review/tools.py` | The seven tools |
| `app/review/checks.py` | Checks on the AI's text: transaction IDs, RM amounts, dates |
| `app/llm/client.py` | One request to AI Foundry |
| `app/llm/ask.py` | One AI call: tool rounds, the one retry, the call record |
| `app/report/builder.py` | Builds the report from a finished review |
| `app/report/model.py`, `app/report/html.py` | The report as data (JSON) and as a page (HTML) |
| `app/web/batches.py` | Batches of accounts, reviewed a few at a time, in order |
| `app/web/routes.py` | The web page's API: upload, folder, batch status, reports |
| `app/web/templates/`, `app/web/static/` | The upload and results pages, their scripts and styles |
| `app/config.py` | Settings from `.env` |
| `app/logging_config.py` | The app log: console and a daily file in `LOG_DIRECTORY` |
| `app/service.py`, `app/main.py`, `app/cli.py` | Reviewing and saving one account; web app; command line |

## To do with the senior

1. Replace the draft risk levels in `app/review/glossary.py` with the AML team's.
2. Confirm the RM 25,000 cash reporting limit (`CASH_REPORT_LIMIT`).
3. Confirm whether TXN_DATE has a time of day (both work).
