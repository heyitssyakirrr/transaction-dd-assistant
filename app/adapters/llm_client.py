from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("app.llm_client")

# Transient failures worth a retry: connection issues, timeouts, and the
# status codes an upstream loader typically returns while overloaded or
# warming up. Anything else (4xx client errors) is not retried, since
# retrying a malformed request just burns one of the loader's few slots.
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.75


class LlmServiceError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Client for the team's configurable, OpenAI-compatible LLM loader.

    Handles the concerns a raw httpx call would otherwise leave to every
    caller: missing configuration surfaced as a clear error (rather than an
    obscure transport failure), bounded retries with backoff for transient
    loader errors, and a one-time fallback for loaders that reject the
    `response_format` field outright.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        if not self._settings.llm_base_url:
            raise LlmServiceError(
                "LLM_BASE_URL is not configured. Copy .env.example to .env in the "
                "project root and set LLM_BASE_URL to the internal loader's address."
            )

        headers = self._build_headers()
        body = self._build_body(system_prompt, user_payload, use_response_format=True)

        try:
            payload = await self._post_with_retries(body, headers)
        except _UnsupportedResponseFormat:
            logger.warning("LLM loader rejected response_format; retrying once without it.")
            fallback_body = self._build_body(system_prompt, user_payload, use_response_format=False)
            payload = await self._post_with_retries(fallback_body, headers)

        content = _extract_content(payload)
        try:
            return json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError as exc:
            raise LlmServiceError("LLM response content was not valid JSON.") from exc

    async def close(self) -> None:
        await self._client.aclose()

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            value = self._settings.llm_api_key
            if self._settings.llm_api_key_header.lower() == "authorization":
                value = f"Bearer {value}"
            headers[self._settings.llm_api_key_header] = value
        return headers

    def _build_body(
        self, system_prompt: str, user_payload: dict[str, Any], *, use_response_format: bool
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ],
            "temperature": 0,
            "max_tokens": self._settings.max_response_tokens,
        }
        if use_response_format:
            body["response_format"] = {"type": "json_object"}
        return body

    async def _post_with_retries(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(self._settings.chat_url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == _MAX_ATTEMPTS:
                    break
                await self._sleep_before_retry(attempt, reason=type(exc).__name__)
                continue

            if response.status_code == 400 and "response_format" in body:
                raise _UnsupportedResponseFormat()

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "LLM loader returned %s on attempt %s/%s; retrying.",
                    response.status_code,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                await self._sleep_before_retry(attempt, reason=f"HTTP {response.status_code}")
                continue

            try:
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                break

        raise LlmServiceError(f"LLM service request failed after {_MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    async def _sleep_before_retry(attempt: int, *, reason: str) -> None:
        delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
        logger.debug("Backing off %.2fs before retry (%s).", delay, reason)
        await asyncio.sleep(delay)


class _UnsupportedResponseFormat(Exception):
    """Internal signal: the loader rejected `response_format`; retry without it."""


def _extract_content(payload: dict[str, Any]) -> str | dict[str, Any]:
    if payload.get("choices"):
        content = payload["choices"][0].get("message", {}).get("content")
        if content is not None:
            return content
    if payload.get("text") is not None:
        return payload["text"]
    raise LlmServiceError("Unrecognised LLM response: expected choices[0].message.content or text")