"""The web page: upload one account's transactions, wait for the review, read the report.

    python -m app.main        # http://127.0.0.1:5000

A review runs in the background; its page refreshes every 5 seconds until the report is ready. Reports
are files in REPORT_DIRECTORY and are listed on the home page.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from html import escape

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.config import Settings
from app.ingest import FileError, read_bytes
from app.service import ReviewService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.main")
settings = Settings()
service = ReviewService(settings)
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


@dataclass
class Job:
    file_name: str
    rows: int
    started: float = field(default_factory=time.monotonic)
    report_id: str | None = None
    error: str | None = None


jobs: dict[str, Job] = {}
_running: set[asyncio.Task] = set()   # keeps each background review alive until it ends


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.llm_base_url:
        logger.warning("LLM_BASE_URL is not set: copy .env.example to .env and fill in the Foundry settings.")
    logger.info("AI: %s model=%s requests at once=%d", settings.chat_url, settings.llm_model, settings.llm_concurrency)
    yield
    await service.close()


app = FastAPI(title="Transaction review", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return _page("Transaction review", f"""
<section><h2>Review an account</h2>
<form action='/reviews' method='post' enctype='multipart/form-data'>
<p>One account's transactions (CSV, TSV or Parquet) with the columns TXN_DATE, TRANSACTION_SEQ_NO,
CREDIT_DEBIT_CODE and AMOUNT. Other columns are ignored.</p>
<input type='file' name='file' accept='.csv,.tsv,.txt,.parquet' required> <button type='submit'>Start review</button>
</form></section>
<section><h2>Recent reports</h2>{_recent_reports()}</section>""")


@app.post("/reviews")
async def start_review(file: UploadFile = File(...)) -> RedirectResponse:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 30 MB.")
    file_name = file.filename or "upload.csv"
    try:
        account = read_bytes(data, file_name)   # a bad file is reported straight away
    except FileError as exc:
        raise HTTPException(400, str(exc)) from exc
    job_id = uuid.uuid4().hex[:12]
    job = jobs[job_id] = Job(file_name, len(account.txns))

    async def run() -> None:
        try:
            job.report_id = (await service.review(account)).report.report_id
        except Exception as exc:  # shown on the job page; the details are in the log
            logger.exception("Review failed: job=%s", job_id)
            job.error = f"{type(exc).__name__}: {exc}"

    task = asyncio.create_task(run())
    _running.add(task)
    task.add_done_callback(_running.discard)
    return RedirectResponse(f"/reviews/{job_id}", status_code=303)


@app.get("/reviews/{job_id}", response_class=HTMLResponse)
def review_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such review (reviews in progress are forgotten when the app restarts).")
    if job.report_id:
        return RedirectResponse(f"/reports/{job.report_id}.html", status_code=303)
    if job.error:
        return _page("Review failed", f"<section><h2>The review of {escape(job.file_name)} failed</h2>"
                                      f"<p>{escape(job.error)}</p><p><a href='/'>Back</a></p></section>")
    seconds = int(time.monotonic() - job.started)
    return _page("Reviewing", f"<section><h2>Reviewing {escape(job.file_name)}</h2><p>{job.rows:,} transactions, "
                              f"{seconds} s so far. This page refreshes every 5 seconds.</p></section>", refresh=5)


@app.get("/reports/{name}")
def report_file(name: str) -> FileResponse:
    folder = settings.report_directory.resolve()
    path = (folder / name).resolve()
    if path.parent != folder or path.suffix not in {".html", ".json"} or not path.exists():
        raise HTTPException(404, "No such report.")
    return FileResponse(path)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "ai_configured": bool(settings.llm_base_url), "model": settings.llm_model,
            "reviews_running": sum(1 for job in jobs.values() if not (job.report_id or job.error))}


def _recent_reports(limit: int = 20) -> str:
    folder = settings.report_directory
    files = sorted(folder.glob("*.json"), reverse=True)[:limit] if folder.exists() else []
    rows = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append(f"<tr><td><a href='/reports/{path.stem}.html'>{escape(str(data.get('file_name', '')))}</a></td>"
                    f"<td>{escape(str(data.get('risk_level', '')).replace('_', ' ').upper())}</td>"
                    f"<td>{escape(str(data.get('headline', '')))}</td>"
                    f"<td>{escape(str(data.get('generated_at', ''))[:16].replace('T', ' '))}</td></tr>")
    if not rows:
        return "<p class='muted'>No reports yet.</p>"
    return ("<table><thead><tr><th>File</th><th>Risk</th><th>Headline</th><th>Generated (UTC)</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _page(title: str, body: str, refresh: int | None = None) -> str:
    meta = f"<meta http-equiv='refresh' content='{refresh}'>" if refresh else ""
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>{meta}<title>{escape(title)}</title>
<style>body{{margin:0;background:#f6f7f9;color:#1d2433;font:14px/1.5 system-ui,sans-serif}}main{{max-width:1040px;
margin:0 auto;padding:24px 16px}}section{{background:#fff;border:1px solid #e3e6eb;border-radius:8px;padding:16px 18px;
margin:0 0 14px}}h1{{font-size:20px}}h2{{font-size:16px;margin:0 0 10px}}table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #eceef2}}th{{background:#f2f4f7}}.muted{{color:#5b6475}}
</style></head><body><main><h1>Transaction review</h1>{body}</main></body></html>"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=5000)
