from __future__ import annotations

import html
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.models import AnalysisResult


@dataclass(frozen=True)
class SavedReport:
    html_name: str
    json_name: str


class ReportStore:
    """Stores local, auditable analysis reports."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)

    def save(self, result: AnalysisResult) -> SavedReport:
        # A timestamp alone collides when the same customer CSV is processed
        # twice in one second. The random suffix makes report names safe for
        # concurrent requests without exposing source data in the filename.
        report_id = f"{result.generated_at.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:12]}"
        safe_case_id = "".join(
            char if char.isalnum() or char in "-_" else "-"
            for char in result.case_id
        )

        basename = f"{safe_case_id}-{report_id}"
        json_name = f"{basename}.json"
        html_name = f"{basename}.html"

        self._atomic_write(json_name, result.model_dump_json(indent=2))
        self._atomic_write(html_name, self._render_html(result))

        return SavedReport(html_name=html_name, json_name=json_name)

    def resolve(self, report_name: str) -> Path | None:
        candidate = (self._directory / Path(report_name).name).resolve()

        if candidate.parent != self._directory.resolve():
            return None

        return candidate if candidate.exists() else None

    def _atomic_write(self, filename: str, content: str) -> None:
        """Publish a report only after its complete content is on disk."""
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._directory,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                temp_path = Path(stream.name)
            os.replace(temp_path, self._directory / filename)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _render_html(self, result: AnalysisResult) -> str:
        findings = "".join(
            f"""
            <article class="finding">
              <h3>{html.escape(finding.category)} · {html.escape(finding.severity)}</h3>
              <p>{html.escape(finding.rationale)}</p>
              <ul>
                {''.join(
                    f'<li><strong>{html.escape(", ".join(item.transaction_ids))}</strong>: '
                    f'{html.escape(item.statement)}</li>'
                    for item in finding.evidence
                )}
              </ul>
            </article>
            """
            for finding in result.findings
        ) or "<p>No traceable material findings were returned.</p>"

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Due-Diligence Assessment</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 48px auto; color: #243b53; }}
h1, h2, h3 {{ color: #102a43; }}
header {{ border-bottom: 4px solid #b62025; padding-bottom: 18px; }}
.decision {{ background: #fff7f7; border-left: 4px solid #b62025; padding: 16px; }}
.finding {{ border: 1px solid #d9e2ec; margin: 14px 0; padding: 14px; }}
small {{ color: #627d98; }}
</style>
</head>
<body>
<header>
  <h1>Transaction Due-Diligence Assessment</h1>
  <small>Case: {html.escape(result.case_id)}</small>
</header>
<section class="decision">
  <h2>Recommendation: {html.escape(result.decision.replace("_", " ").title())} ({html.escape(result.risk_level.title())} risk)</h2>
  <p>{html.escape(result.decision_rationale)}</p>
</section>
<h2>Executive summary</h2>
<p>{html.escape(result.executive_summary)}</p>
<p><small>{result.transactions_processed} transactions reviewed across {result.chunks_processed} LLM segments.</small></p>
<h2>Material findings</h2>
{findings}
<h2>Limitations</h2>
<ul>{''.join(f'<li>{html.escape(item)}</li>' for item in result.limitations)}</ul>
</body>
</html>"""