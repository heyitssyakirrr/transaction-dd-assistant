"""The web page's JSON API. The pages themselves are app/web/templates; their scripts are app/web/static.

    POST /v1/batches                 upload one or more account files -> a batch
    GET  /v1/folder                  what the account folder holds (ACCOUNT_FOLDER_PATH)
    POST /v1/folder-batches          folder files "start" to "end", by file name -> a batch
    GET  /v1/batches/{batch_id}      each file's status (the results page polls this)
    GET  /v1/reports/{report_id}     one finished report, as JSON
    GET  /reports/{name}             a saved report file (.html or .json), to open or download
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from app.account.ingest import FileError, read_bytes, read_file
from app.config import Settings
from app.service import ReviewService
from app.web.batches import Batch, BatchFile, BatchRunner, FileProblem

logger = logging.getLogger("app.web.routes")

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
FILE_TYPES = (".csv", ".tsv", ".txt", ".parquet")


class FolderBatchRequest(BaseModel):
    """Folder files ``start`` to ``end`` (1-based, both included), in file-name order."""
    start: int = Field(default=1, ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _start_not_after_end(self) -> "FolderBatchRequest":
        if self.start > self.end:
            raise ValueError("start must not be after end")
        return self


def make_review(service: ReviewService):
    """Reviews one batch file and returns its report id. Reading the file is blocking, so it runs in a thread."""
    async def review(item: BatchFile) -> str:
        try:
            if item.path is not None:
                account = await asyncio.to_thread(read_file, item.path)
            else:
                account = await asyncio.to_thread(read_bytes, item.content or b"", item.file_name)
        except (FileError, OSError) as exc:
            raise FileProblem(str(exc)) from exc
        return (await service.review(account)).report.report_id
    return review


def upload_problem(file_name: str, size: int) -> str | None:
    if not file_name.lower().endswith(FILE_TYPES):
        return "Not a CSV, TSV or Parquet file."
    if size > MAX_UPLOAD_BYTES:
        return f"Larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
    return None


def folder_files(folder: Path) -> list[Path]:
    """The account files directly in ``folder`` (not subfolders), sorted by name."""
    if not folder.is_dir():
        raise HTTPException(502, f"The account folder {folder} does not exist or is not a folder.")
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in FILE_TYPES),
                  key=lambda p: p.name)


def build_router(runner: BatchRunner, settings: Settings) -> APIRouter:
    router = APIRouter()

    def account_folder() -> Path:
        if settings.account_folder is None:
            raise HTTPException(404, "Reading from a folder is not set up (ACCOUNT_FOLDER_PATH).")
        return settings.account_folder

    def find_batch(batch_id: str) -> Batch:
        batch = runner.get(batch_id)
        if batch is None:
            raise HTTPException(404, "Batch not found. Batches are kept in memory and are forgotten when the "
                                     "app restarts; saved reports are still in the report folder.")
        return batch

    def report_path(name: str) -> Path:
        """A file in REPORT_DIRECTORY, and nothing outside it."""
        folder = settings.report_directory.resolve()
        path = (folder / name).resolve()
        if path.parent != folder or path.suffix not in {".html", ".json"} or not path.exists():
            raise HTTPException(404, "Report not found.")
        return path

    @router.post("/v1/batches", status_code=202)
    async def upload_batch(files: list[UploadFile] = File(...)) -> dict:
        if len(files) > settings.batch_max_files:
            raise HTTPException(413, f"Upload at most {settings.batch_max_files} files at a time; "
                                     f"{len(files)} were chosen.")
        items = []
        for upload in files:
            data = await upload.read(MAX_UPLOAD_BYTES + 1)
            item = BatchFile(upload.filename or "upload.csv", content=data)
            if problem := upload_problem(item.file_name, len(data)):
                logger.warning("Upload refused: file=%s problem=%s", item.file_name, problem)
                item.fail(problem)   # shown on its page; the other files still run
            items.append(item)
        return runner.submit(items, "upload").as_dict()

    @router.get("/v1/folder")
    async def folder_summary() -> dict:
        folder = account_folder()
        files = await asyncio.to_thread(folder_files, folder)
        return {"folder": str(folder), "total_files": len(files), "accounts_at_once": settings.batch_account_concurrency}

    @router.post("/v1/folder-batches", status_code=202)
    async def folder_batch(request: FolderBatchRequest) -> dict:
        files = await asyncio.to_thread(folder_files, account_folder())
        if request.start > len(files):
            raise HTTPException(422, f"Start {request.start} is after the last file ({len(files)}).")
        chosen = files[request.start - 1:min(request.end, len(files))]
        return runner.submit([BatchFile(p.name, path=p) for p in chosen], "folder").as_dict()

    @router.get("/v1/batches/{batch_id}")
    def batch_status(batch_id: str) -> dict:
        return find_batch(batch_id).as_dict()

    @router.get("/v1/reports/{report_id}")
    def report_json(report_id: str) -> dict:
        return json.loads(report_path(f"{report_id}.json").read_text(encoding="utf-8"))

    @router.get("/reports/{name}")
    def report_file(name: str) -> FileResponse:
        return FileResponse(report_path(name))

    return router
