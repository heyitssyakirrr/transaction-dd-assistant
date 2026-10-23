"""The web app: upload account files (or pick them from the account folder), follow the reviews, and read
each report on the results page.

    python -m app.main        # http://127.0.0.1:5000

The pages are app/web/templates, their scripts and styles app/web/static, the JSON API app/web/routes.py.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.logging_config import setup_logging
from app.service import ReviewService
from app.web.batches import BatchRunner
from app.web.routes import build_router, make_review

logger = logging.getLogger("app.main")
WEB_DIR = Path(__file__).resolve().parent / "web"

settings = Settings()
log_file = setup_logging(settings.log_directory, settings.log_retention_days)
service = ReviewService(settings)
runner = BatchRunner(make_review(service), workers=settings.batch_account_concurrency,
                     keep_batches=settings.batch_keep_recent)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.llm_base_url:
        logger.warning("LLM_BASE_URL is not set: copy .env.example to .env and fill in the Foundry settings.")
    logger.info("App started: log file=%s", log_file or "none (console only)")
    logger.info("AI: %s model=%s helper id=%s requests at once=%d reasoning room=%d tokens", settings.chat_url,
                settings.llm_model, "set" if settings.helper_id else "NOT SET", settings.llm_concurrency,
                settings.llm_reasoning_extra_tokens)
    logger.info("Web: accounts at once=%d folder=%s reports=%s", settings.batch_account_concurrency,
                settings.account_folder or "not set", settings.report_directory)
    await runner.start()
    yield
    await runner.close()
    await service.close()


app = FastAPI(title="Transaction review", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
app.include_router(build_router(runner, settings))


@app.middleware("http")
async def always_check_for_newer_pages(request: Request, call_next):
    """Browsers re-check pages and scripts on every visit, so an updated script is never a stale copy."""
    response = await call_next(request)
    if request.url.path in ("/", "/results") or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def upload_page() -> FileResponse:
    return FileResponse(WEB_DIR / "templates" / "index.html")


@app.get("/results", include_in_schema=False)
def results_page() -> FileResponse:
    return FileResponse(WEB_DIR / "templates" / "results.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "ai_configured": bool(settings.llm_base_url), "model": settings.llm_model,
            "folder_configured": settings.account_folder is not None}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=5000)
