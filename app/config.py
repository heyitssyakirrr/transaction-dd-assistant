"""All settings, read once from .env (values already in the environment win).

Four groups: the AI Foundry connection, the review (groups, checks, tools, answer sizes), the web page, and
files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """KEY=value lines; the existing environment wins. Quotes around values are removed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() == "true"


def _path(name: str, default: str) -> Path:
    path = Path(_env(name, default))
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    # --- AI Foundry connection --------------------------------------------------------------
    llm_base_url: str = _env("LLM_BASE_URL", "")
    llm_chat_path: str = _env("LLM_CHAT_PATH", "/foundry/chat/completions")
    llm_model: str = _env("LLM_MODEL", "gpt-6-luna")
    helper_id: str = _env("HELPER_ID", "")                 # sent as the X-PBAI-Helper-Id header
    llm_timeout_seconds: int = _int("LLM_TIMEOUT_SECONDS", 180)
    llm_verify_ssl: bool = _flag("LLM_VERIFY_SSL", False)   # the internal gateway's certificate
    # Requests to Foundry at the same time, across all reviews; the others wait their turn.
    llm_concurrency: int = _int("LLM_CONCURRENCY", 9)
    # gpt-6-luna thinks before it answers, and the thinking counts inside max_tokens:
    # this much is added to every step's answer size.
    llm_reasoning_extra_tokens: int = _int("LLM_REASONING_EXTRA_TOKENS", 4000)
    # Keep these off except when investigating a problem: they write transaction rows to disk.
    llm_log_answers: bool = _flag("LLM_LOG_ANSWERS", False)
    llm_save_blocked_requests: bool = _flag("LLM_SAVE_BLOCKED_REQUESTS", False)

    # --- The review --------------------------------------------------------------------------
    # Accounts with more rows than this are read in groups of about this size.
    rows_per_group: int = _int("ROWS_PER_GROUP", 300)
    # Days before and after a group that its reader also sees, and the most rows taken each side.
    neighbour_days: int = _int("NEIGHBOUR_DAYS", 3)
    max_neighbour_rows: int = _int("MAX_NEIGHBOUR_ROWS", 60)
    # Suspected patterns checked per account (one Check call each).
    max_patterns_to_check: int = _int("MAX_PATTERNS_TO_CHECK", 8)
    # Days around a suspected pattern's transactions that its Check call sees.
    check_days: int = _int("CHECK_DAYS", 3)
    # Cash reporting limit, RM per account per day; confirm the figure with compliance.
    cash_report_limit: Decimal = Decimal(_env("CASH_REPORT_LIMIT", "25000"))
    # The summary: one line per day up to this many active days, else one line per week.
    summary_max_days: int = _int("SUMMARY_MAX_DAYS", 400)
    # Length of the summary's lists (repeated amounts, largest transactions).
    summary_list_size: int = _int("SUMMARY_LIST_SIZE", 10)
    # Tool rounds the AI may use in one call, and rows one tool answer may show.
    tool_max_rounds: int = _int("TOOL_MAX_ROUNDS", 6)
    tool_max_rows: int = _int("TOOL_MAX_ROWS", 100)
    # Answer size (tokens) of each step, before the reasoning room is added.
    read_tokens: int = _int("READ_TOKENS", 2000)
    summary_review_tokens: int = _int("SUMMARY_REVIEW_TOKENS", 3000)
    combine_tokens: int = _int("COMBINE_TOKENS", 3000)
    check_tokens: int = _int("CHECK_TOKENS", 1500)
    decide_tokens: int = _int("DECIDE_TOKENS", 4000)

    # --- The web page ---------------------------------------------------------------------------
    # Accounts reviewed at the same time; their AI calls share LLM_CONCURRENCY.
    batch_account_concurrency: int = _int("BATCH_ACCOUNT_CONCURRENCY", 3)
    # Most files in one upload, and finished batches kept for the results page.
    batch_max_files: int = _int("BATCH_MAX_FILES", 20)
    batch_keep_recent: int = _int("BATCH_KEEP_RECENT", 20)
    # "Read from folder": a server folder of account files (CSV, TSV or Parquet; one account per file).
    # Blank hides the option.
    account_folder: Path | None = _path("ACCOUNT_FOLDER_PATH", "") if _env("ACCOUNT_FOLDER_PATH", "") else None

    # --- Files ----------------------------------------------------------------------------------
    report_directory: Path = _path("REPORT_DIRECTORY", "data/reports")
    log_directory: Path = _path("LOG_DIRECTORY", "data/logs")

    def __post_init__(self) -> None:
        must_be_positive = {
            "LLM_TIMEOUT_SECONDS": self.llm_timeout_seconds, "LLM_CONCURRENCY": self.llm_concurrency,
            "ROWS_PER_GROUP": self.rows_per_group,
            "MAX_PATTERNS_TO_CHECK": self.max_patterns_to_check, "CASH_REPORT_LIMIT": self.cash_report_limit,
            "SUMMARY_MAX_DAYS": self.summary_max_days, "SUMMARY_LIST_SIZE": self.summary_list_size,
            "TOOL_MAX_ROWS": self.tool_max_rows, "READ_TOKENS": self.read_tokens,
            "SUMMARY_REVIEW_TOKENS": self.summary_review_tokens, "COMBINE_TOKENS": self.combine_tokens,
            "CHECK_TOKENS": self.check_tokens, "DECIDE_TOKENS": self.decide_tokens,
            "BATCH_ACCOUNT_CONCURRENCY": self.batch_account_concurrency, "BATCH_MAX_FILES": self.batch_max_files,
            "BATCH_KEEP_RECENT": self.batch_keep_recent,
        }
        wrong = [name for name, value in must_be_positive.items() if value <= 0]
        if wrong:
            raise ValueError(f"These settings must be greater than zero: {', '.join(wrong)}")
        if min(self.neighbour_days, self.max_neighbour_rows, self.check_days, self.tool_max_rounds,
               self.llm_reasoning_extra_tokens) < 0:
            raise ValueError("NEIGHBOUR_DAYS, MAX_NEIGHBOUR_ROWS, CHECK_DAYS, TOOL_MAX_ROUNDS and "
                             "LLM_REASONING_EXTRA_TOKENS must be zero or more")

    @property
    def chat_url(self) -> str:
        return f"{self.llm_base_url.rstrip('/')}/{self.llm_chat_path.lstrip('/')}"

    def max_tokens(self, answer_tokens: int) -> int:
        """What is sent as max_tokens: the step's answer size plus room for the model's thinking."""
        return answer_tokens + self.llm_reasoning_extra_tokens
