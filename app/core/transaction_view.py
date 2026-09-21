from __future__ import annotations

from typing import Any

from app.core.models import NormalizedTransaction


def compact_row(row: NormalizedTransaction) -> dict[str, Any]:
    """Create the minimal lossless transaction view supplied to the LLM.

    This is a field projection only; it does not derive risk indicators,
    aggregate transactions, or perform transaction analysis.
    """
    return {
        "id": row.transaction_id,
        "time": row.timestamp.isoformat(),
        "amount": str(row.amount),
        "direction": row.direction,
        "currency": row.currency,
        "counterparty": row.counterparty,
        "description": (row.description or "")[:240] or None,
        "channel": row.channel,
        "merchant_category": row.merchant_category,
        "balance": str(row.balance) if row.balance is not None else None,
    }
