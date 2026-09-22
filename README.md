# Transaction Due-Diligence Assistant

An internal UAT application that accepts one customer's bank-transaction CSV,
uses the internal Qwen service to review it for AML-relevant activity, and
returns an evidence-led recommendation for authorised staff.

## Workflow

For a statement larger than one model context window, the service uses an LLM
workflow rather than a Python risk model:

1. The application normalizes and chronologically orders CSV rows only.
2. It sends each 300-row segment to Qwen for a structured material-activity
   review. A shared bounded FIFO queue has three workers, so at most three LLM
   calls are active at once; a large case submits only three chunks at a time,
   leaving shared capacity available for other customer cases.
3. Qwen receives all segment reports to identify case-level hypotheses.
4. Qwen selects up to six original segments for raw-evidence verification.
5. Qwen produces the final recommendation from verified evidence only.

Python does not score customers, detect AML anomalies, or write transaction
summaries. It only moves data, validates response schemas, and removes findings
that cite transaction IDs not present in the supplied raw evidence.

## Decisions

- `no_action`: no material transaction concern was evidenced.
- `monitor`: low concern; staff may monitor according to policy.
- `request_information`: activity requires explanation or supporting documents.
- `enhanced_due_diligence`: material transaction-based concern is verified.
- `escalate`: severe, verified concern; follow internal AML procedure.

These are staff recommendations, not automatic account, regulatory, or case
closure decisions.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
```

Edit `.env` in the project root with your OpenShift LLM loader URL and model.
Keep `LLM_CONCURRENCY=3` unless the platform team confirms higher capacity.
`LLM_QUEUE_MAXSIZE` is intentional backpressure: when it is full the request
receives HTTP 503 rather than growing memory or overwhelming the loader.
Set `REPORT_DIRECTORY` to a path backed by an OpenShift persistent-volume
mount; reports stored only in the container filesystem are lost whenever its
pod is recreated.

## LLM diagnostics

Every LLM call logs its queue wait, worker, safe request size in bytes,
token estimate, configured prompt budget, HTTP status, duration, retry attempt,
and upstream request/correlation ID when available. Transaction values and full
LLM error bodies are deliberately not logged.

Set `LLM_CONTEXT_WINDOW_TOKENS` only to the model context window confirmed by
the platform team. The application reserves `MAX_RESPONSE_TOKENS` and
`LLM_CONTEXT_SAFETY_MARGIN_TOKENS`; a request estimated to exceed the remaining
prompt budget fails clearly with HTTP 422 before it reaches the LLM. If the
loader reports a context-window rejection itself, it is classified, logged, and
also returned as HTTP 422. The estimate is a safety guard, not a replacement
for the model's actual tokenizer.

For approved troubleshooting, set `LLM_LOG_RAW_RESPONSE=true`. Each completed
LLM call then logs the raw model content once; `LLM_LOG_RAW_RESPONSE_MAX_CHARS`
limits its length. Keep this disabled in normal production use because output
can contain transaction-derived personal data.

Run this service with **one Uvicorn worker** when `LLM_CONCURRENCY=3`. The
queue is process-local, so each extra application process has its own three
workers. If this application is scaled to multiple replicas, divide the three
available LLM slots across them or use a shared, durable queue such as Redis.

Open `http://127.0.0.1:5000`.

## CSV input

Upload one UTF-8 CSV. Common headers are detected automatically, including:
`Date`, `Transaction Date`, `Description`, `Debit`, `Credit`, `Amount`,
`Balance`, `Reference`, `Transaction ID`, `Channel`, and `Merchant`.

Each 300-row chunk sent to the LLM contains only these transaction fields:
`transaction_id`, `date`, `amount`, `direction`, `currency`, `counterparty`,
`description`, `channel`, `merchant`, and `balance`.

The auto-mapper generates IDs only where the statement lacks a source
transaction reference. It performs no analysis.

## Reports

Each completed review is saved under `data/reports/` as HTML and JSON. Open the
HTML report and use the browser's **Print → Save as PDF** if a PDF copy is
needed.

## LLM loader contract

The adapter expects an OpenAI-compatible endpoint:

```text
POST {LLM_BASE_URL}{LLM_CHAT_PATH}
```

If your internal loader has a different request/response contract, update only
`app/adapters/llm_client.py`.