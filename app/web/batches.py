"""Batches of accounts for the web page: uploaded files, or files from the account folder.

BATCH_ACCOUNT_CONCURRENCY workers share one queue, so accounts start in the order they were chosen and
at most that many are reviewed at once, across all batches. Each review's AI calls still go through the
shared limit of LLM_CONCURRENCY requests at once (app/llm/ask.py).

A folder file is read only when its turn comes, and a finished file keeps only its report id (the report
itself is on disk), so a long batch holds little in memory. Batches live in memory: they are forgotten
when the app restarts; the saved reports stay in REPORT_DIRECTORY.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("app.web.batches")

FileStatus = Literal["queued", "reviewing", "done", "failed"]
Source = Literal["upload", "folder"]


class FileProblem(Exception):
    """A failure whose message is safe to show on the page, e.g. "The file is missing column(s): AMOUNT."."""


@dataclass
class BatchFile:
    file_name: str
    content: bytes | None = None      # an uploaded file's bytes, dropped once it is reviewed
    path: Path | None = None          # a folder file, read when its turn comes
    status: FileStatus = "queued"
    report_id: str | None = None
    error: str | None = None

    def fail(self, message: str) -> None:
        self.status, self.error, self.content = "failed", message, None


Review = Callable[[BatchFile], Awaitable[str]]   # reviews one file and returns its report id


@dataclass
class Batch:
    batch_id: str
    files: list[BatchFile]
    source: Source
    accounts_at_once: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        """Statuses only: the page fetches each finished report on its own, so polling stays small."""
        counts = {status: 0 for status in ("queued", "reviewing", "done", "failed")}
        for item in self.files:
            counts[item.status] += 1
        return {
            "batch_id": self.batch_id, "source": self.source, "created_at": self.created_at.isoformat(),
            "total": len(self.files), "counts": counts, "finished": counts["queued"] == counts["reviewing"] == 0,
            "accounts_at_once": self.accounts_at_once,
            "files": [{"position": n, "file_name": f.file_name, "status": f.status, "report_id": f.report_id,
                       "error": f.error} for n, f in enumerate(self.files, start=1)],
        }


class BatchRunner:
    def __init__(self, review: Review, *, workers: int, keep_batches: int) -> None:
        self._review = review
        self._workers_wanted = workers
        self._keep = keep_batches
        self._batches: OrderedDict[str, Batch] = OrderedDict()
        self._queue: asyncio.Queue[BatchFile] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._work(n)) for n in range(1, self._workers_wanted + 1)]
        logger.info("Batch runner started: %d account(s) at a time", self._workers_wanted)

    async def close(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    def submit(self, files: list[BatchFile], source: Source) -> Batch:
        batch = Batch(uuid.uuid4().hex[:12], files, source, self._workers_wanted)
        self._batches[batch.batch_id] = batch
        while len(self._batches) > self._keep:   # forget the oldest batches; their reports stay on disk
            self._batches.popitem(last=False)
        for item in files:
            if item.status == "queued":
                self._queue.put_nowait(item)
        logger.info("Batch queued: batch=%s source=%s files=%d waiting=%d", batch.batch_id, source, len(files),
                    self._queue.qsize())
        return batch

    def get(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    async def _work(self, worker: int) -> None:
        while True:
            item = await self._queue.get()
            try:
                item.status = "reviewing"
                logger.info("Review started: worker=%d file=%s", worker, item.file_name)
                item.report_id = await self._review(item)
                item.status, item.content = "done", None
            except FileProblem as exc:
                logger.warning("File could not be reviewed: file=%s problem=%s", item.file_name, exc)
                item.fail(str(exc))
            except Exception:  # one bad file must not stop the rest of the batch; the details are in the log
                logger.exception("Review failed: file=%s", item.file_name)
                item.fail("An unexpected error stopped this review. The details are in the app log.")
            finally:
                self._queue.task_done()
