from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any

from app.core.models import (
    AnalyzeTransactionsRequest,
    CustomerContext,
    TransactionColumnMapping,
)


class CsvSchemaError(ValueError):
    pass


ALIASES = {
    "transaction_id": [
        "transaction_id",
        "transaction id",
        "reference",
        "reference_no",
        "reference number",
        "id",
    ],
    "timestamp": [
        "transaction_datetime",
        "transaction date",
        "transaction_date",
        "date",
        "datetime",
        "date time",
        "posting date",
        "value date",
    ],
    "amount": [
        "amount",
        "transaction amount",
        "txn amount",
        "value",
    ],
    "direction": [
        "direction",
        "credit_debit",
        "credit debit",
        "transaction type",
        "type",
        "dr cr",
    ],
    "debit": [
        "debit",
        "withdrawal",
        "withdrawal amount",
        "debit amount",
        "dr",
    ],
    "credit": [
        "credit",
        "deposit",
        "deposit amount",
        "credit amount",
        "cr",
    ],
    "description": [
        "description",
        "narration",
        "remarks",
        "transaction description",
        "details",
        "particulars",
    ],
    "counterparty": [
        "counterparty",
        "beneficiary",
        "sender",
        "recipient",
        "merchant",
        "payee",
    ],
    "balance": [
        "balance",
        "running balance",
        "available balance",
    ],
    "currency": [
        "currency",
        "ccy",
        "transaction currency",
    ],
}


def build_request_from_csv(
    csv_content: str,
    filename: str,
) -> AnalyzeTransactionsRequest:
    rows = list(csv.DictReader(io.StringIO(csv_content)))

    if not rows:
        raise CsvSchemaError("The CSV contains no transaction rows.")

    if not rows[0]:
        raise CsvSchemaError("The CSV header row could not be read.")

    mapping = _detect_mapping(list(rows[0].keys()))
    normalized_rows = _prepare_rows(rows, mapping)

    generated_case_id = (
        f"{_safe_filename(filename)}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    )

    return AnalyzeTransactionsRequest(
        case_id=generated_case_id,
        customer_context=CustomerContext(
            customer_id=f"Derived from file: {filename}",
            extra={
                "source_file": filename,
                "analysis_scope": (
                    "Transaction-only analysis. No occupation, income, "
                    "or external customer profile was supplied."
                ),
            },
        ),
        column_mapping=TransactionColumnMapping(
            transaction_id="_generated_transaction_id",
            timestamp=mapping["timestamp"],
            amount="_generated_amount",
            direction="_generated_direction",
            currency=mapping.get("currency"),
            counterparty=mapping.get("counterparty"),
            description=mapping.get("description"),
            balance=mapping.get("balance"),
        ),
        transactions=normalized_rows,
    )


def _detect_mapping(headers: list[str]) -> dict[str, str]:
    cleaned = {_normalise_header(header): header for header in headers}

    detected: dict[str, str] = {}

    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                detected[field] = cleaned[alias]
                break

    if "timestamp" not in detected:
        raise CsvSchemaError(
            "Could not identify a transaction date column. "
            "Use a header such as Date, Transaction Date, or Posting Date."
        )

    has_amount = "amount" in detected
    has_debit_credit = "debit" in detected or "credit" in detected

    if not has_amount and not has_debit_credit:
        raise CsvSchemaError(
            "Could not identify an amount column. Use Amount, Debit, or Credit."
        )

    return detected


def _prepare_rows(
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        amount, direction = _derive_amount_and_direction(row, mapping)

        if amount is None:
            continue

        prepared.append(
            {
                **row,
                "_generated_transaction_id": (
                    row.get(mapping.get("transaction_id", ""), "")
                    or f"ROW-{index:06d}"
                ),
                "_generated_amount": amount,
                "_generated_direction": direction,
            }
        )

    if not prepared:
        raise CsvSchemaError(
            "No valid transaction amount was found after reading the CSV."
        )

    return prepared


def _derive_amount_and_direction(
    row: dict[str, Any],
    mapping: dict[str, str],
) -> tuple[str | None, str]:
    debit = _parse_number(row.get(mapping.get("debit", ""), ""))
    credit = _parse_number(row.get(mapping.get("credit", ""), ""))

    if credit is not None and credit > 0:
        return str(credit), "credit"

    if debit is not None and debit > 0:
        return str(debit), "debit"

    amount = _parse_number(row.get(mapping.get("amount", ""), ""))

    if amount is None:
        return None, "debit"

    explicit_direction = str(
        row.get(mapping.get("direction", ""), "")
    ).strip().lower()

    if amount < 0:
        return str(abs(amount)), "debit"

    if explicit_direction in {"credit", "cr", "c", "in"}:
        return str(amount), "credit"

    return str(amount), "debit"


def _parse_number(value: Any) -> float | None:
    text = str(value).strip()

    if not text:
        return None

    cleaned = re.sub(r"[^0-9.-]", "", text)

    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalise_header(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", filename.rsplit(".", 1)[0])