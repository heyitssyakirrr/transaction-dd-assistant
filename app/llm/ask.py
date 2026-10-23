"""One AI call from start to finish.

A call is a short conversation:
    system + user  ->  the AI asks for tools  ->  the tool answers  ->  ...  ->  the AI's JSON answer
After TOOL_MAX_ROUNDS tool rounds, the AI must answer with what it has.

Each call gets ONE retry, chosen by what went wrong:
    blocked by the guardrail  -> the same request again (the filter scores close to its limit);
    answer cut off            -> again with a larger answer size;
    answer not usable JSON    -> the problem is sent back and the AI is asked again.
If the retry also fails, the call fails with a plain reason that the report shows.

At most LLM_CONCURRENCY requests go to Foundry at the same time, across all reviews; the rest wait.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.client import Blocked, CutOff, FoundryClient, LlmError, Reply, first_json_object
from app.review.tools import Toolbox

logger = logging.getLogger("app.llm")
Answer = TypeVar("Answer", bound=BaseModel)


class CallFailed(RuntimeError):
    """A call gave no usable answer; the message says why, for the report."""


@dataclass
class ToolUse:
    tool: str
    asked: str           # the arguments as the AI sent them
    answer: str          # the first line of the tool's answer


@dataclass
class CallRecord:
    """What happened in one AI call, for the report's Processing and "What the AI checked" sections."""
    name: str
    requests: int = 0
    seconds: float = 0.0
    output_tokens: int = 0
    tool_uses: list[ToolUse] = field(default_factory=list)
    problem: str = ""                # empty when the call answered


class Asker:
    def __init__(self, client: FoundryClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._slots = asyncio.Semaphore(settings.llm_concurrency)

    async def ask(self, record: CallRecord, system: str, user: str, answer_shape: type[Answer],
                  answer_tokens: int, toolbox: Toolbox | None = None) -> Answer:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tools = toolbox.definitions() if toolbox else None
        rounds, retried = 0, False
        try:
            while True:
                must_answer = toolbox is not None and rounds >= self._settings.tool_max_rounds
                try:
                    reply = await self._send(record, messages, answer_tokens, tools, must_answer)
                except Blocked as exc:
                    if retried:
                        raise CallFailed(str(exc)) from exc
                    retried = True
                    logger.warning("Blocked by the guardrail, sending once more: call=%s", record.name)
                    continue
                except CutOff as exc:
                    if retried:
                        raise CallFailed(str(exc)) from exc
                    retried, answer_tokens = True, answer_tokens * 2
                    logger.warning("Answer cut off, trying with a larger size: call=%s", record.name)
                    continue
                except LlmError as exc:
                    raise CallFailed(str(exc)) from exc

                if reply.tool_calls:
                    if toolbox is None or must_answer:  # tools not offered, or the rounds are used up
                        if retried:
                            raise CallFailed("the AI kept asking for tools when it had to answer")
                        retried = True
                    if toolbox is None:
                        messages.append({"role": "user", "content": "No tools are available here. Answer with ONE "
                                                                    "JSON object in exactly the shape asked for."})
                        continue
                    messages.append(reply.message)
                    messages += self._run_tools(record, toolbox, reply, allowed=not must_answer)
                    rounds += 1
                    continue

                try:
                    return answer_shape.model_validate(_json(reply.text))
                except (ValueError, ValidationError) as exc:
                    if retried:
                        raise CallFailed(f"no usable answer after one retry: {_short(exc)}") from exc
                    retried = True
                    logger.warning("Answer not usable, asking again: call=%s problem=%s", record.name, _short(exc))
                    messages.append(reply.message)
                    messages.append({"role": "user", "content": f"Your answer could not be used: {_short(exc)}\n"
                                                                "Answer again with ONE JSON object in exactly the "
                                                                "shape asked for."})
        except CallFailed as exc:
            record.problem = str(exc)
            logger.warning("AI call failed: call=%s problem=%s", record.name, exc)
            raise

    async def _send(self, record: CallRecord, messages: list[dict[str, Any]], answer_tokens: int,
                    tools: list[dict[str, Any]] | None, must_answer: bool) -> Reply:
        async with self._slots:
            started = time.monotonic()
            record.requests += 1
            try:
                reply = await self._client.chat(name=record.name, messages=list(messages), answer_tokens=answer_tokens,
                                                tools=tools, must_answer=must_answer)
            finally:
                record.seconds += time.monotonic() - started
        record.output_tokens += reply.output_tokens
        return reply

    @staticmethod
    def _run_tools(record: CallRecord, toolbox: Toolbox, reply: Reply, allowed: bool) -> list[dict[str, Any]]:
        """One tool message per tool call, as the API requires, even when tools are no longer allowed."""
        results = []
        for call in reply.tool_calls:
            function = call.get("function") or {}
            name, arguments = str(function.get("name", "")), function.get("arguments") or "{}"
            if allowed:
                answer = toolbox.run(name, arguments)
            else:
                answer = "error: no more tool calls are allowed. Give your final answer now with what you have."
            asked = arguments if isinstance(arguments, str) else json.dumps(arguments)
            record.tool_uses.append(ToolUse(name, asked[:300], answer.split("\n", 1)[0][:300]))
            logger.info("Tool used: call=%s tool=%s asked=%s", record.name, name, asked[:200])
            results.append({"role": "tool", "tool_call_id": str(call.get("id", "")), "content": answer})
        return results


def _json(text: str) -> dict[str, Any]:
    value = first_json_object(text)
    if value is None:
        raise ValueError("the answer is not a JSON object")
    return value


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'answer'}: {e['msg']}" for e in exc.errors()[:4])
    return str(exc)[:300]
