"""Wiring: file -> account -> AI steps -> report, saved as JSON and HTML. The web page and the command line
both use this, so they behave the same."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.account.ingest import Account, read_bytes
from app.config import Settings
from app.llm.ask import Asker
from app.llm.client import FoundryClient
from app.logging_config import current_review
from app.report.builder import build_report
from app.report.html import render
from app.report.model import Report
from app.review.pipeline import Pipeline

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
        token = current_review.set(account.file_name)   # every log line of this review names the file
        try:
            review = await self.pipeline.run(account)
            report = build_report(review, self.settings)
            # What the report shows in red, also in the log, so a problem can be followed without the report.
            for item in review.not_done:
                logger.warning("Not done: %s", item)
            for issue in report.issues + [i for card in report.findings for i in card.issues]:
                logger.warning("Check issue: %s", issue)
            return self.save(report)
        finally:
            current_review.reset(token)

    def save(self, report: Report) -> SavedReport:
        folder = self.settings.report_directory
        folder.mkdir(parents=True, exist_ok=True)
        json_path = folder / f"{report.report_id}.json"
        html_path = folder / f"{report.report_id}.html"
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        html_path.write_text(render(report), encoding="utf-8")
        logger.info("Report saved: %s status=%s risk=%s findings=%d", html_path.name, report.status,
                    report.risk_level, len(report.findings))
        return SavedReport(report, json_path, html_path)
