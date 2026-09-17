from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

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
        report_id = result.generated_at.strftime("%Y%m%d-%H%M%S")
        safe_case_id = "".join(
            char if char.isalnum() or char in "-_" else "-"
            for char in result.case_id
        )

        basename = f"{safe_case_id}-{report_id}"
        json_name = f"{basename}.json"
        html_name = f"{basename}.html"

        (self._directory / json_name).write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

        (self._directory / html_name).write_text(
            self._render_html(result),
            encoding="utf-8",
        )

        return SavedReport(html_name=html_name, json_name=json_name)

    def resolve(self, report_name: str) -> Path | None:
        candidate = (self._directory / Path(report_name).name).resolve()

        if candidate.parent != self._directory.resolve():
            return None

        return candidate if candidate.exists() else None

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
  <h2>Recommendation: {html.escape(result.decision.replace("_", " ").title())}</h2>
  <p>{html.escape(result.decision_rationale)}</p>
</section>
<h2>Executive summary</h2>
<p>{html.escape(result.executive_summary)}</p>
<h2>Material findings</h2>
{findings}
<h2>Limitations</h2>
<ul>{''.join(f'<li>{html.escape(item)}</li>' for item in result.limitations)}</ul>
</body>
</html>"""