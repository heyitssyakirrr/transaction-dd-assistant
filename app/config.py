from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Small dependency-free dotenv loader; existing environment wins."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
    llm_chat_path: str = os.getenv("LLM_CHAT_PATH", "/chat/completions")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5-vl-7b-instruct")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_api_key_header: str = os.getenv("LLM_API_KEY_HEADER", "Authorization")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
    llm_concurrency: int = int(os.getenv("LLM_CONCURRENCY", "3"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "300"))
    max_target_chunks: int = int(os.getenv("MAX_TARGET_CHUNKS", "6"))
    max_target_chunks_per_review: int = int(os.getenv("MAX_TARGET_CHUNKS_PER_REVIEW", "2"))
    max_response_tokens: int = int(os.getenv("MAX_RESPONSE_TOKENS", "2200"))
    require_human_review: bool = os.getenv("REQUIRE_HUMAN_REVIEW", "true").lower() == "true"

    @property
    def chat_url(self) -> str:
        return f"{self.llm_base_url.rstrip('/')}/{self.llm_chat_path.lstrip('/')}"

