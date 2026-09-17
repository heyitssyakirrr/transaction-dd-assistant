import unittest

from app.config import Settings
from app.core.analysis_service import AnalysisService
from app.core.models import AnalyzeTransactionsRequest


class FakeLlm:
    def __init__(self):
        self.calls = []

    def complete_json(self, *, system_prompt, user_payload):
        self.calls.append(user_payload)
        if "chunk" in user_payload:
            return {"candidate_findings": [], "chunk_summary": "Normal subset"}
        return {"decision": "monitor", "decision_rationale": "Review trend.", "executive_summary": "One transaction reviewed.", "findings": []}


class AnalysisServiceTests(unittest.TestCase):
    def test_runs_chunk_and_synthesis(self):
        llm = FakeLlm()
        service = AnalysisService(llm, Settings(max_prompt_tokens=1, max_rows_per_chunk=1))
        request = AnalyzeTransactionsRequest.model_validate({
            "case_id": "C-1", "customer_context": {"customer_id": "masked"},
            "column_mapping": {"transaction_id": "id", "timestamp": "time", "amount": "amount", "direction": "direction"},
            "transactions": [
                {"id": "T1", "time": "2026-01-01T00:00:00", "amount": "10", "direction": "credit"},
                {"id": "T2", "time": "2026-01-02T00:00:00", "amount": "5", "direction": "debit"},
            ],
        })
        result = service.analyze_transactions(request)
        self.assertEqual(result.transactions_processed, 2)
        self.assertEqual(result.chunks_processed, 2)
        self.assertEqual(len(llm.calls), 3)

