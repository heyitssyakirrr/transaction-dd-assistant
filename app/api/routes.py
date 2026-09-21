import logging
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.adapters.llm_client import LlmServiceError
from app.core.analysis_service import AnalysisService, ModelOutputError
from app.core.auto_csv import CsvSchemaError, build_request_from_csv
from app.core.report_store import ReportStore
from app.core.transaction_adapter import TransactionValidationError

logger = logging.getLogger("app.api")

# Generous enough for a real customer statement, small enough to fail fast
# before it reaches the LLM chunking pipeline.
_MAX_UPLOAD_BYTES = 15 * 1024 * 1024


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

        raw = await file.read()
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The CSV exceeds the 15 MB upload limit for this workspace.",
            )

        started_at = time.monotonic()
        case_id = "unknown"
        try:
            content = raw.decode("utf-8-sig")
            request = build_request_from_csv(content, file.filename or "statement.csv")
            case_id = request.case_id
            logger.info("Starting analysis: case=%s rows=%s", case_id, len(request.transactions))

            result = await service.analyze_transactions(request)
            saved = report_store.save(result)

            logger.info(
                "Analysis complete: case=%s decision=%s risk=%s duration=%.1fs",
                case_id,
                result.decision,
                result.risk_level,
                time.monotonic() - started_at,
            )
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
            logger.error("Model output did not match schema: case=%s error=%s", case_id, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except LlmServiceError as exc:
            logger.error("LLM service call failed: case=%s error=%s", case_id, exc)
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