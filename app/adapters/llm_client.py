from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings


class LlmServiceError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Minimal dependency-free client for the team's configurable LLM loader."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
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
        try:
            response = await self._client.post(self._settings.chat_url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise LlmServiceError(f"LLM service request failed: {exc}") from exc
        content = _extract_content(payload)
        try:
            return json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError as exc:
            raise LlmServiceError("LLM response content was not valid JSON") from exc

    async def close(self) -> None:
        await self._client.aclose()


def _extract_content(payload: dict[str, Any]) -> str | dict[str, Any]:
    if payload.get("choices"):
        content = payload["choices"][0].get("message", {}).get("content")
        if content is not None:
            return content
    if payload.get("text") is not None:
        return payload["text"]
    raise LlmServiceError("Unrecognised LLM response: expected choices[0].message.content or text")

