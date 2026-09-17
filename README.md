# Transaction Due-Diligence Assistant

An API that sends a UAT-sized customer statement (about 100–1,000 rows) to an
internal, OpenAI-compatible Qwen microservice for anomaly detection and a
traceable due-diligence summary.

The application is deliberately split into reusable layers:

- `app/adapters`: infrastructure boundaries. `OpenAICompatibleClient` is the
  only component that knows how to call the current LLM loader.
- `app/core`: models, validation, profiling, prompt construction and analysis
  orchestration. These are independent of FastAPI and reusable for log data.
- `app/api`: HTTP endpoints and file/JSON request handling.

The next pipeline-log project can reuse `AnalysisService`, `LlmClient`, prompt
execution, chunking, result persistence, audit records and response schemas.
Only a `LogRecordAdapter` and log-specific prompt/profile need to be added.

## Safety boundary

This is an investigator decision-support service. It may recommend a review,
but it does not make an account action, regulatory filing, or final AML/KYC
decision. Outputs must cite source transaction IDs. Do not place production
customer data into the service until it has passed internal security, model
risk, privacy and AML governance.

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and change `LLM_BASE_URL`, `LLM_MODEL`, and
   authentication settings to your team's LLM loader. No source code change is
   required for a normal OpenAI-compatible loader.

3. Run the service:

   ```powershell
   uvicorn app.main:app --host 0.0.0.0 --port 8080
   ```

4. Open `http://localhost:8080/docs` to use the interactive API.

## Required transaction schema

Provide a `column_mapping` because bank source schemas vary. At minimum map:

```json
{
  "transaction_id": "transaction_id",
  "timestamp": "transaction_datetime",
  "amount": "amount",
  "direction": "credit_debit"
}
```

Optional mappings: `currency`, `counterparty`, `description`, `channel`,
`merchant_category`, and `balance`. Amounts must be non-negative; direction
must identify credit/debit (for example `CR`, `DR`, `in`, `out`).

## JSON API example

`POST /v1/transactions/analyze`

```json
{
  "case_id": "UAT-001",
  "customer_context": {
    "customer_id": "masked-customer-42",
    "occupation": "ride-hailing driver",
    "declared_monthly_income": 4500,
    "currency": "MYR"
  },
  "column_mapping": {
    "transaction_id": "id",
    "timestamp": "transaction_date",
    "amount": "amount",
    "direction": "direction",
    "counterparty": "counterparty",
    "description": "narration"
  },
  "transactions": [
    {"id": "T-1", "transaction_date": "2026-08-01T09:00:00Z", "amount": 100.00, "direction": "credit", "counterparty": "Example"}
  ]
}
```

`POST /v1/transactions/analyze-file` accepts a UTF-8 CSV with a JSON
`request` form field containing `case_id`, `customer_context`, and
`column_mapping`.

## Loader compatibility

The client calls:

```text
POST {LLM_BASE_URL}{LLM_CHAT_PATH}
```

with the standard `model`, `messages`, `temperature`, `max_tokens`, and
`response_format` fields. It accepts either `choices[0].message.content` or a
plain `text` response. If your loader differs, edit only
`app/adapters/llm_client.py`.

## Tests

```powershell
py -m unittest discover -s tests -v
```

