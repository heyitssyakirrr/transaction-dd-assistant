"""Answer field types shared by the AI steps. Lenient on form ('T1, T2' instead of a list, 'Strong'
instead of 'strong', an unknown pattern name), strict on content: what the AI cites is checked later."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.glossary import FINDING_KEYS

_ID_OR_RANGE = re.compile(r"T(\d+)(?:\s*(?:-|–|to)\s*T?(\d+))?")


def _ids(value: Any) -> list[str]:
    """['T1', 'T2'], 'T1, T2' or 'T5-T8' -> ids in order, no repeats. The prompts ask for every id, but a
    range such as T5-T8 is read as T5, T6, T7, T8 rather than silently losing the middle."""
    if value is None:
        return []
    text = " ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
    ids: list[str] = []
    for first, last in _ID_OR_RANGE.findall(text.upper()):
        start, end = int(first), int(last or first)
        if end < start or end - start > 5000:   # not a sensible range: keep the first id only
            end = start
        ids += [f"T{n}" for n in range(start, end + 1)]
    return list(dict.fromkeys(ids))


def _pattern(value: Any) -> str:
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in FINDING_KEYS else "other"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _finding_ids(value: Any) -> list[str]:
    """['F1', 'F2'] or 'F1, F2' -> finding ids in order, no repeats."""
    if value is None:
        return []
    text = " ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
    return list(dict.fromkeys(re.findall(r"F\d+", text.upper())))


Ids = Annotated[list[str], BeforeValidator(_ids)]
FindingIds = Annotated[list[str], BeforeValidator(_finding_ids)]
PatternKey = Annotated[str, BeforeValidator(_pattern)]
Text = Annotated[str, BeforeValidator(_text)]


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


Strength = Annotated[Literal["strong", "moderate", "weak"], BeforeValidator(_lower)]
Lower = BeforeValidator(_lower)


class Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")


def answer_format(example: str) -> str:
    return ("Answer with ONE JSON object only, no markdown, in exactly this shape (keys in this order):\n" + example)
