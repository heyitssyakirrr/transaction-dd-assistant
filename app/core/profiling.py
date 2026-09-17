from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from app.core.models import NormalizedTransaction


def build_transaction_profile(rows: list[NormalizedTransaction]) -> dict[str, Any]:
    """Lossless aggregate evidence used by synthesis to connect all chunks."""
    credits = [row for row in rows if row.direction == "credit"]
    debits = [row for row in rows if row.direction == "debit"]
    total_credits = sum((row.amount for row in credits), Decimal("0"))
    total_debits = sum((row.amount for row in debits), Decimal("0"))
    counterparties = Counter(row.counterparty for row in rows if row.counterparty)
    currencies = sorted({row.currency for row in rows if row.currency})
    return {
        "transaction_count": len(rows),
        "period_start": rows[0].timestamp.isoformat(),
        "period_end": rows[-1].timestamp.isoformat(),
        "currencies": currencies,
        "credits": {"count": len(credits), "total": str(total_credits), "largest": _largest(credits)},
        "debits": {"count": len(debits), "total": str(total_debits), "largest": _largest(debits)},
        "net_flow": str(total_credits - total_debits),
        "unique_counterparties": len(counterparties),
        "most_frequent_counterparties": [
            {"counterparty": name, "transaction_count": count}
            for name, count in counterparties.most_common(10)
        ],
    }


def compact_row(row: NormalizedTransaction) -> dict[str, Any]:
    """Only model-relevant fields; descriptions are bounded to protect prompt size."""
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


def _largest(rows: list[NormalizedTransaction]) -> dict[str, Any] | None:
    if not rows:
        return None
    row = max(rows, key=lambda item: item.amount)
    return {"transaction_id": row.transaction_id, "amount": str(row.amount), "timestamp": row.timestamp.isoformat()}

