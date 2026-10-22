"""Review one account file from the command line.

    python -m app.cli "C:\\path\\to\\account.csv"

Prints the risk level and where the report was saved (REPORT_DIRECTORY, data/reports by default).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from app.config import Settings
from app.ingest import FileError
from app.service import ReviewService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Review one account's transactions.")
    parser.add_argument("file", type=Path, help="one account's transactions: CSV, TSV or Parquet")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    if not settings.llm_base_url:
        raise SystemExit("LLM_BASE_URL is not set: copy .env.example to .env and fill in the Foundry settings.")
    service = ReviewService(settings)
    try:
        saved = await service.review_file(args.file.read_bytes(), args.file.name)
    except FileError as exc:
        raise SystemExit(f"The file cannot be reviewed: {exc}") from exc
    finally:
        await service.close()
    report = saved.report
    print(f"\nRisk level: {report.risk_level.upper()} ({report.evidence_strength} evidence) - {report.headline}")
    print(f"Findings: {len(report.findings)} | check issues: {len(report.issues)} | {report.status} | "
          f"{report.total_seconds} s, {len(report.calls)} AI calls, {len(report.tool_uses)} tool uses")
    print(f"Report: {saved.html_path}")


if __name__ == "__main__":
    asyncio.run(main())
