# Transaction Due-Diligence Assistant

An internal UAT application that accepts one customer's bank-transaction CSV,
uses the internal Qwen service to review it for AML-relevant activity, and
returns an evidence-led recommendation for authorised staff.

## Workflow

For a statement larger than one model context window, the service uses an LLM
workflow rather than a Python risk model:

1. The application normalizes and chronologically orders CSV rows only.
2. It sends each 300-row segment to Qwen for a structured material-activity
   review. A shared `asyncio.Semaphore(3)` limits all model calls to three.
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
Copy-Item .env.example app\.env
python -m app.main
```

Edit `app/.env` with your OpenShift LLM loader URL and model. Keep
`LLM_CONCURRENCY=3` unless the platform team confirms higher capacity.

Open `http://127.0.0.1:5000`.

## CSV input

Upload one UTF-8 CSV. Common headers are detected automatically, including:
`Date`, `Transaction Date`, `Description`, `Debit`, `Credit`, `Amount`,
`Balance`, `Reference`, and `Transaction ID`.

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
