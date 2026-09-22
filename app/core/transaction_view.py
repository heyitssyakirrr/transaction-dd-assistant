from __future__ import annotations

from typing import Any

from app.core.models import NormalizedTransaction


def compact_row(row: NormalizedTransaction) -> dict[str, Any]:
    """Create the minimal bounded transaction view supplied to the LLM.

    This is a field projection only; it does not derive risk indicators,
    aggregate transactions, or perform transaction analysis.
    """
    return {
        "transaction_id": row.transaction_id,
        "date": row.timestamp.isoformat(),
        "amount": str(row.amount),
        "direction": row.direction,
        "currency": row.currency,
        "counterparty": _bounded_text(row.counterparty, 160),
        "description": _bounded_text(row.description, 240),
        "channel": _bounded_text(row.channel, 80),
        "merchant": _bounded_text(row.merchant_category, 160),
        "balance": str(row.balance) if row.balance is not None else None,
    }


def _bounded_text(value: str | None, limit: int) -> str | None:
    """Keep free-text fields within the prompt budget without changing IDs or amounts."""
    if not value:
        return None
    return value[:limit]