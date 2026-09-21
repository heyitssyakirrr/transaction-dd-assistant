from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.adapters.llm_client import LlmServiceError
from app.core.analysis_service import AnalysisService, ModelOutputError
from app.core.auto_csv import CsvSchemaError, build_request_from_csv
from app.core.report_store import ReportStore
from app.core.transaction_adapter import TransactionValidationError


def build_router(
    service: AnalysisService,
    report_store: ReportStore,
) -> APIRouter:
    router = APIRouter(prefix="/v1/transactions", tags=["transactions"])

    @router.post("/analyze-file")
    async def analyze_file(file: UploadFile = File(...)) -> dict:
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(
                status_code=415,
                detail="Please upload a CSV bank transaction statement.",
            )

        try:
            content = (await file.read()).decode("utf-8-sig")
            request = build_request_from_csv(content, file.filename or "statement.csv")
            result = await service.analyze_transactions(request)
            saved = report_store.save(result)
            return {
                **result.model_dump(mode="json"),
                "report_html": f"/v1/transactions/reports/{saved.html_name}",
                "report_json": f"/v1/transactions/reports/{saved.json_name}",
            }
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="CSV must be saved as UTF-8.",
            ) from exc
        except CsvSchemaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except TransactionValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ModelOutputError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except LlmServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/reports/{report_name}")
    def download_report(report_name: str) -> FileResponse:
        report_path = report_store.resolve(report_name)

        if report_path is None:
            raise HTTPException(status_code=404, detail="Report not found.")

        media_type = (
            "application/json"
            if report_path.suffix == ".json"
            else "text/html"
        )

        return FileResponse(
            report_path,
            media_type=media_type,
            filename=report_path.name,
        )

    return router
