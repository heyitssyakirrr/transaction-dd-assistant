from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.adapters.llm_client import OpenAICompatibleClient
from app.api.routes import build_router
from app.config import Settings
from app.core.analysis_service import AnalysisService
from app.core.report_store import ReportStore


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

settings = Settings()
service = AnalysisService(
    OpenAICompatibleClient(settings),
    settings,
)

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
def healthz() -> dict[str, str]:
    return {"status": "ok", "model": settings.llm_model}