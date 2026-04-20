"""Fault-tolerant JSON parser for LLM output — 5-stage progressive repair pipeline.

Stages (first success returns immediately; all must fail before raising):
  Stage-0: json.loads fast path
  Stage-1: strip envelope (whitespace / Markdown fences / comments)
  Stage-2: normalise punctuation (Chinese/fullwidth quotes, fullwidth commas)
  Stage-3: remove trailing commas
  Stage-4: escape bare inner quotes inside strings
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, overload

from scrivai.exceptions import ScrivaiJSONRepairError

_MAX_MSG_PREVIEW = 200


@dataclass(frozen=True)
class RepairReport:
    """Report produced by the repair pipeline."""

    stages_applied: list[str]
    original: str
    final: str


@overload
def relaxed_json_loads(
    text: str,
    *,
    strict: bool = False,
    return_repair_report: bool = False,
) -> Any: ...


@overload
def relaxed_json_loads(
    text: str,
    *,
    strict: bool = False,
    return_repair_report: bool = True,
) -> tuple[Any, RepairReport]: ...


def relaxed_json_loads(
    text: str,
    *,
    strict: bool = False,
    return_repair_report: bool = False,
) -> Any | tuple[Any, RepairReport]:
    """Fault-tolerant JSON parser for LLM output.

    Args:
        text: Raw LLM output text (may contain Markdown fences).
        strict: When True, skip all repair stages and behave exactly like json.loads.
        return_repair_report: When True, return a (parsed_data, RepairReport) tuple.

    Returns:
        Parsed Python object, or a (object, RepairReport) tuple when return_repair_report is True.

    Raises:
        ScrivaiJSONRepairError: All repair stages failed.
        json.JSONDecodeError: When strict=True, matches json.loads behaviour.
    """
    if strict:
        result = json.loads(text)
        if return_repair_report:
            return result, RepairReport(stages_applied=[], original=text, final=text)
        return result

    # Stage-0: fast path
    try:
        result = json.loads(text)
        if return_repair_report:
            return result, RepairReport(stages_applied=[], original=text, final=text)
        return result
    except json.JSONDecodeError:
        pass

    original = text
    stages_applied: list[str] = []
    last_error: json.JSONDecodeError | None = None

    stages: list[tuple[str, Any]] = [
        ("strip_envelope", _strip_envelope),
        ("normalize_quotes", _normalize_quotes),
        ("remove_trailing_commas", _remove_trailing_commas),
        ("escape_inner_quotes", _escape_inner_quotes),
    ]

    for stage_name, stage_fn in stages:
        text = stage_fn(text)
        stages_applied.append(stage_name)
        try:
            result = json.loads(text)
            if return_repair_report:
                return result, RepairReport(
                    stages_applied=list(stages_applied),
                    original=original,
                    final=text,
                )
            return result
        except json.JSONDecodeError as e:
            last_error = e

    assert last_error is not None
    preview_orig = original[:_MAX_MSG_PREVIEW]
    preview_final = text[:_MAX_MSG_PREVIEW]
    msg = (
        f"JSON repair failed (stages tried: {', '.join(stages_applied)}):\n"
        f"  json.loads error: {last_error}\n"
        f"  original text (first {_MAX_MSG_PREVIEW} chars): {preview_orig}\n"
        f"  repaired text (first {_MAX_MSG_PREVIEW} chars): {preview_final}"
    )
    raise ScrivaiJSONRepairError(
        msg=msg,
        doc=text,
        pos=last_error.pos if last_error.pos is not None else 0,
        original_text=original,
        repaired_text=text,
        stages_applied=stages_applied,
    )


# ── Stage implementations ──────────────────────────────────────────────

_RE_FENCE = re.compile(r"^```(?:json|JSON)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def _strip_envelope(text: str) -> str:
    """Stage-1: Strip leading/trailing whitespace, Markdown fences, and line/block comments."""
    text = text.strip()

    fence = _RE_FENCE.match(text)
    if fence:
        text = fence.group(1).strip()

    text = _remove_comments_outside_strings(text)
    return text


def _remove_comments_outside_strings(text: str) -> str:
    """Remove // line comments and /* */ block comments from syntactic positions, leaving string contents unchanged."""
    result: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]

        if in_string:
            result.append(ch)
            if ch == "\\" and i + 1 < len(text):
                result.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            end = text.find("\n", i)
            if end == -1:
                break
            i = end
            continue

        if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                break
            i = end + 2
            continue

        result.append(ch)
        i += 1

    return "".join(result)


_OPEN_QUOTES = {"\u201c", "\u2018"}  # " '
_CLOSE_QUOTES = {"\u201d", "\u2019"}  # " '
_ALL_FANCY_QUOTES = _OPEN_QUOTES | _CLOSE_QUOTES
_FULLWIDTH_COMMA = "\uff0c"  # ，

# Mapping: opening quote → closing quote
_FANCY_QUOTE_PAIR: dict[str, str] = {
    "\u201c": "\u201d",  # " → "
    "\u2018": "\u2019",  # ' → '
}


def _normalize_quotes(text: str) -> str:
    """Stage-2: Replace syntactic Chinese/fullwidth quotes with ASCII quotes; fullwidth commas with half-width.

    A state machine tracks inside/outside-string position and distinguishes two opening styles:
    - Plain ``"`` open: only ``"`` closes; internal Chinese quotes are preserved.
    - Chinese-quote open: the paired closing quote closes the string; all output is replaced with ``"``.

    Fullwidth commas outside strings are replaced with half-width commas.
    """
    result: list[str] = []
    in_string = False
    fancy_close: str | None = None  # expected Chinese closing quote (None = opened by plain ")
    i = 0

    while i < len(text):
        ch = text[i]

        if in_string:
            if fancy_close is None:
                # string opened by a plain "
                if ch == "\\" and i + 1 < len(text):
                    result.append(ch)
                    result.append(text[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                    result.append(ch)
                    i += 1
                    continue
                # Chinese quotes inside a plain-" string are kept as-is
                result.append(ch)
                i += 1
                continue
            else:
                # string opened by a Chinese quote; wait for the paired close quote
                if ch == fancy_close:
                    in_string = False
                    fancy_close = None
                    result.append('"')
                    i += 1
                    continue
                result.append(ch)
                i += 1
                continue

        # outside a string
        if ch == '"':
            in_string = True
            fancy_close = None
            result.append(ch)
            i += 1
            continue

        if ch in _OPEN_QUOTES:
            result.append('"')
            in_string = True
            fancy_close = _FANCY_QUOTE_PAIR[ch]
            i += 1
            continue

        if ch == _FULLWIDTH_COMMA:
            result.append(",")
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def _remove_trailing_commas(text: str) -> str:
    r"""Stage-3: Remove trailing commas after the last element of objects/arrays.

    A state machine skips string contents; only syntactic ,\s*[}\]] patterns are removed.
    """
    string_ranges: list[tuple[int, int]] = []
    in_string = False
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == '"':
                string_ranges.append((start, i))
                in_string = False
        else:
            if ch == '"':
                in_string = True
                start = i
        i += 1

    def _in_string(pos: int) -> bool:
        for s, e in string_ranges:
            if s <= pos <= e:
                return True
        return False

    trailing = list(re.finditer(r",(\s*[}\]])", text))
    for m in reversed(trailing):
        if not _in_string(m.start()):
            text = text[: m.start()] + m.group(1) + text[m.end() :]

    return text


_JSON_STRUCTURAL = set(":,}] \t\n\r")


def _escape_inner_quotes(text: str) -> str:
    """Stage-4: Escape unescaped double-quotes inside string values.

    Precondition: Stage-2 has already normalised all structural quotes to half-width.
    Heuristic: when a " is encountered inside a string, inspect the next character.
    If the next character is not a JSON structural character → the " is content; escape it as \\".
    If the next character is structural → the " closes the string.
    """
    result: list[str] = []
    i = 0

    while i < len(text):
        ch = text[i]

        if ch != '"':
            result.append(ch)
            i += 1
            continue

        # hit an opening " — scan the string
        result.append('"')
        i += 1
        while i < len(text):
            c = text[i]

            if c == "\\" and i + 1 < len(text):
                result.append(c)
                result.append(text[i + 1])
                i += 2
                continue

            if c == '"':
                next_char = text[i + 1] if i + 1 < len(text) else ""
                if next_char in _JSON_STRUCTURAL or next_char == "":
                    result.append('"')
                    i += 1
                    break
                else:
                    result.append('\\"')
                    i += 1
                    continue

            result.append(c)
            i += 1

    return "".join(result)
