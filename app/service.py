"""Wiring: file -> account -> AI steps -> report, saved as JSON and HTML. The web page and the command line
both use this, so they behave the same."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.ingest import Account, read_bytes
from app.llm.ask import Asker
from app.llm.client import FoundryClient
from app.pipeline import Pipeline
from app.report import Report
from app.report_builder import build_report
from app.report_html import render

logger = logging.getLogger("app.service")


@dataclass(frozen=True)
class SavedReport:
    report: Report
    json_path: Path
    html_path: Path


class ReviewService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = FoundryClient(settings)
        self.pipeline = Pipeline(Asker(self.client, settings), settings)

    async def close(self) -> None:
        await self.client.close()

    async def review_file(self, data: bytes, file_name: str) -> SavedReport:
        return await self.review(read_bytes(data, file_name))

    async def review(self, account: Account) -> SavedReport:
        report = build_report(await self.pipeline.run(account), self.settings)
        return self.save(report)

    def save(self, report: Report) -> SavedReport:
        folder = self.settings.report_directory
        folder.mkdir(parents=True, exist_ok=True)
        json_path = folder / f"{report.report_id}.json"
        html_path = folder / f"{report.report_id}.html"
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        html_path.write_text(render(report), encoding="utf-8")
        logger.info("Report saved: %s risk=%s findings=%d", html_path.name, report.risk_level, len(report.findings))
        return SavedReport(report, json_path, html_path)
