from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.models import NormalizedTransaction, TransactionColumnMapping


class TransactionValidationError(ValueError):
    pass


_CREDIT = {"credit", "cr", "c", "in", "incoming", "deposit"}
_DEBIT = {"debit", "dr", "d", "out", "outgoing", "withdrawal"}


def normalize_transactions(
    rows: list[dict[str, Any]], mapping: TransactionColumnMapping
) -> list[NormalizedTransaction]:
    """Convert a bank-specific schema into the one analysis schema."""
    normalized: list[NormalizedTransaction] = []
    for row_number, row in enumerate(rows, start=1):
        try:
            direction = _normalize_direction(_required(row, mapping.direction, row_number))
            normalized.append(
                NormalizedTransaction(
                    transaction_id=str(_required(row, mapping.transaction_id, row_number)),
                    timestamp=_parse_datetime(_required(row, mapping.timestamp, row_number), row_number),
                    amount=_parse_decimal(_required(row, mapping.amount, row_number), row_number, "amount"),
                    direction=direction,
                    currency=_optional_text(row, mapping.currency),
                    counterparty=_optional_text(row, mapping.counterparty),
                    description=_optional_text(row, mapping.description),
                    channel=_optional_text(row, mapping.channel),
                    merchant_category=_optional_text(row, mapping.merchant_category),
                    balance=_optional_decimal(row, mapping.balance, row_number, "balance"),
                )
            )
        except (ValueError, TypeError) as exc:
            raise TransactionValidationError(f"Row {row_number}: {exc}") from exc
    if len({row.transaction_id for row in normalized}) != len(normalized):
        raise TransactionValidationError("transaction_id values must be unique within a case")
    return sorted(normalized, key=lambda item: item.timestamp)


def _required(row: dict[str, Any], column: str, row_number: int) -> Any:
    value = row.get(column)
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing required column/value '{column}'")
    return value


def _optional_text(row: dict[str, Any], column: str | None) -> str | None:
    if not column or row.get(column) is None:
        return None
    value = str(row[column]).strip()
    return value or None


def _optional_decimal(row: dict[str, Any], column: str | None, row_number: int, label: str) -> Decimal | None:
    if not column or row.get(column) in (None, ""):
        return None
    return _parse_decimal(row[column], row_number, label)


def _parse_decimal(value: Any, row_number: int, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"invalid {label} '{value}'") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be non-negative; use direction to indicate flow")
    return parsed


def _parse_datetime(value: Any, row_number: int) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp '{value}'") from exc


def _normalize_direction(value: Any) -> str:
    text = str(value).strip().lower()
    if text in _CREDIT:
        return "credit"
    if text in _DEBIT:
        return "debit"
    raise ValueError(f"unsupported direction '{value}'")

