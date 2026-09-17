import unittest

from app.core.models import TransactionColumnMapping
from app.core.transaction_adapter import TransactionValidationError, normalize_transactions


class TransactionAdapterTests(unittest.TestCase):
    mapping = TransactionColumnMapping(transaction_id="id", timestamp="time", amount="amt", direction="flow")

    def test_normalizes_common_direction_codes_and_sorts(self):
        rows = [
            {"id": "2", "time": "2026-01-02T00:00:00+00:00", "amt": "1,000.50", "flow": "DR"},
            {"id": "1", "time": "2026-01-01T00:00:00+00:00", "amt": "20", "flow": "CR"},
        ]
        result = normalize_transactions(rows, self.mapping)
        self.assertEqual(result[0].transaction_id, "1")
        self.assertEqual(result[1].direction, "debit")

    def test_rejects_negative_amount(self):
        with self.assertRaises(TransactionValidationError):
            normalize_transactions([{"id": "1", "time": "2026-01-01T00:00:00", "amt": "-5", "flow": "CR"}], self.mapping)

