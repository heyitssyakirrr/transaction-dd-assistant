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
from app.service import ReviewService
from app.web.batches import BatchRunner
from app.web.routes import build_router, make_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.main")
WEB_DIR = Path(__file__).resolve().parent / "web"

settings = Settings()
service = ReviewService(settings)
runner = BatchRunner(make_review(service), workers=settings.batch_account_concurrency,
                     keep_batches=settings.batch_keep_recent)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.llm_base_url:
        logger.warning("LLM_BASE_URL is not set: copy .env.example to .env and fill in the Foundry settings.")
    logger.info("AI: %s model=%s requests at once=%d accounts at once=%d folder=%s", settings.chat_url,
                settings.llm_model, settings.llm_concurrency, settings.batch_account_concurrency,
                settings.account_folder or "not set")
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
