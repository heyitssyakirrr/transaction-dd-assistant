import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.llm_client import OpenAICompatibleClient
from app.api.routes import build_router
from app.config import Settings
from app.core.analysis_service import AnalysisService
from app.core.report_store import ReportStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

settings = Settings()

if not settings.llm_base_url:
    logger.warning(
        "LLM_BASE_URL is not set. Copy .env.example to '.env' in the project "
        "root (next to Dockerfile/README.md, not inside app/) and set your "
        "loader's URL before analysing statements."
    )
else:
    logger.info(
        "LLM loader configured: %s (model=%s, concurrency=%s)",
        settings.chat_url,
        settings.llm_model,
        settings.llm_concurrency,
    )

llm_client = OpenAICompatibleClient(settings)
service = AnalysisService(llm_client, settings)

report_store = ReportStore(PROJECT_DIR / "data" / "reports")

app = FastAPI(
    title="Transaction Due-Diligence Assistant",
    version="0.3.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

app.include_router(build_router(service, report_store))


@app.get("/", include_in_schema=False)
def workspace() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.llm_model,
        "llm_configured": bool(settings.llm_base_url),
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again or contact support."},
    )


@app.on_event("shutdown")
async def close_llm_client() -> None:
    await llm_client.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=5000, reload=True)