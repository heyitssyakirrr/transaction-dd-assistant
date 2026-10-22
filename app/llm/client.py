"""One request to the AI Foundry chat endpoint, in the format the platform team gave:

    POST {LLM_BASE_URL}/foundry/chat/completions
    Authorization: Bearer {LLM_API_KEY}
    X-PBAI-Helper-Id: {HELPER_ID}
    {"model": "gpt-6-luna",
     "messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, {"role": "tool", ...}],
     "max_tokens": ..., "stream": false, "tools": [...]}

No temperature, top_p or stop: the reasoning model rejects them. This module only sends the request and
says clearly what went wrong; tool rounds, retries and reading the JSON answer are in app/llm/ask.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger("app.llm")
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


class LlmError(RuntimeError):
    """The request failed. The message is plain words for the report."""


class Blocked(LlmError):
    """The Foundry guardrail (Azure content filter) refused the request or the answer."""


class CutOff(LlmError):
    """The answer reached max_tokens before it finished (the model's thinking counts too)."""


@dataclass
class Reply:
    message: dict[str, Any]                  # the assistant message, sent back on the next round
    text: str                                # the answer text ('' when the model only asked for tools)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    output_tokens: int = 0


class FoundryClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, verify=settings.llm_verify_ssl,
                                       limits=httpx.Limits(max_connections=settings.llm_concurrency))

    async def close(self) -> None:
        await self._http.aclose()

    async def chat(self, *, name: str, messages: list[dict[str, Any]], answer_tokens: int,
                   tools: list[dict[str, Any]] | None = None, must_answer: bool = False) -> Reply:
        """Send the conversation so far. ``must_answer`` tells the model it may not call more tools."""
        if not self._settings.llm_base_url:
            raise LlmError("LLM_BASE_URL is not set: copy .env.example to .env and fill in the Foundry settings.")
        body: dict[str, Any] = {"model": self._settings.llm_model, "messages": messages,
                                "max_tokens": self._settings.max_tokens(answer_tokens), "stream": False}
        if tools:
            body["tools"] = tools
            if must_answer:
                body["tool_choice"] = "none"
        payload = await self._post(name, body)

        choice = (payload.get("choices") or [{}])[0]
        usage = payload.get("usage") or {}
        finish = choice.get("finish_reason")
        logger.info("AI answer: call=%s finish_reason=%s prompt_tokens=%s output_tokens=%s", name, finish,
                    usage.get("prompt_tokens"), usage.get("completion_tokens"))
        if finish == "content_filter":
            # The gateway answers 200 with a stock refusal; prompt_tokens=0 means the request itself was refused.
            where = "request" if usage.get("prompt_tokens") == 0 else "answer"
            self._save_blocked(name, body)
            raise Blocked(f"blocked by the Foundry guardrail (content filter) on the {where}")
        message = choice.get("message") or {}
        tool_calls = [call for call in message.get("tool_calls") or [] if isinstance(call, dict)]
        text = message.get("content") or ""
        if self._settings.llm_log_answers:
            logger.info("AI answer text: call=%s text=%s", name, text[:20000])
        if finish == "length" and not tool_calls and first_json_object(text) is None:
            raise CutOff("the answer was cut off at max_tokens; raise LLM_REASONING_EXTRA_TOKENS or the step's "
                         "answer size")
        if not text.strip() and not tool_calls:
            raise LlmError("the answer was empty")
        reply: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            reply["tool_calls"] = tool_calls
        return Reply(reply, text, tool_calls, usage.get("completion_tokens") or 0)

    async def _post(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST once; a timeout, a dropped connection or a busy server (429/5xx) is tried once more."""
        for attempt in (1, 2):
            try:
                response = await self._http.post(self._settings.chat_url, headers=self._headers(), json=body)
            except httpx.HTTPError as exc:
                if attempt == 1:
                    logger.warning("AI request failed, trying again: call=%s error=%s", name, type(exc).__name__)
                    await asyncio.sleep(2)
                    continue
                raise LlmError(f"could not reach Foundry ({type(exc).__name__})") from exc
            if response.status_code in _TRANSIENT_STATUS and attempt == 1:
                logger.warning("Foundry busy (HTTP %s), trying again: call=%s", response.status_code, name)
                await asyncio.sleep(2)
                continue
            if response.status_code >= 400:
                detail = _error_detail(response)
                if response.status_code == 400 and ("content_filter" in detail or "content management" in detail):
                    self._save_blocked(name, body)
                    raise Blocked("blocked by the Foundry guardrail (content filter) on the request")
                raise LlmError(f"Foundry returned HTTP {response.status_code}: {detail}")
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise LlmError("Foundry returned something that is not JSON") from exc
        raise LlmError("could not reach Foundry")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            key = self._settings.llm_api_key
            if self._settings.llm_api_key_header.lower() == "authorization":
                key = f"Bearer {key}"
            headers[self._settings.llm_api_key_header] = key
        if self._settings.helper_id:
            headers["X-PBAI-Helper-Id"] = self._settings.helper_id
        return headers

    def _save_blocked(self, name: str, body: dict[str, Any]) -> None:
        """Keep a blocked request to investigate (LLM_SAVE_BLOCKED_REQUESTS=true only). It holds transaction
        rows, never the API key."""
        if not self._settings.llm_save_blocked_requests:
            return
        try:
            folder = self._settings.log_directory / "blocked_requests"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{re.sub(r'[^A-Za-z0-9]+', '_', name)}.json"
            path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
            logger.warning("Blocked request saved: %s", path)
        except OSError as exc:
            logger.warning("Could not save the blocked request: %s", exc)


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:300]
    error = payload.get("error", payload) if isinstance(payload, dict) else payload
    if isinstance(error, dict):
        return f"{error.get('code', '')} {error.get('message', '')}".strip()[:500]
    return str(error)[:500]


def first_json_object(text: str) -> dict[str, Any] | None:
    """The JSON object the answer starts with, or None. A ```json fence before it, and anything after it
    (a repeat or a sentence), are ignored. Nothing is ever filled in or repaired."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
