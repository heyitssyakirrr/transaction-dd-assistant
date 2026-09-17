from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings


class LlmServiceError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Minimal dependency-free client for the team's configurable LLM loader."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ],
            "temperature": 0,
            "max_tokens": self._settings.max_response_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            value = self._settings.llm_api_key
            if self._settings.llm_api_key_header.lower() == "authorization":
                value = f"Bearer {value}"
            headers[self._settings.llm_api_key_header] = value
        request = Request(self._settings.chat_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self._settings.llm_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise LlmServiceError(f"LLM service returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise LlmServiceError(f"Cannot reach LLM service at {self._settings.chat_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise LlmServiceError("LLM service returned invalid JSON") from exc
        content = _extract_content(payload)
        try:
            return json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError as exc:
            raise LlmServiceError("LLM response content was not valid JSON") from exc


def _extract_content(payload: dict[str, Any]) -> str | dict[str, Any]:
    if payload.get("choices"):
        content = payload["choices"][0].get("message", {}).get("content")
        if content is not None:
            return content
    if payload.get("text") is not None:
        return payload["text"]
    raise LlmServiceError("Unrecognised LLM response: expected choices[0].message.content or text")

