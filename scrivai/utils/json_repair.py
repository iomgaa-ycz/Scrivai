"""LLM 输出 JSON 容错解析 — 5 阶段渐进修复管线。

阶段顺序(任意一步成功即返回;全部失败才抛):
  Stage-0: json.loads 快路径
  Stage-1: 剥壳(空白 / Markdown 围栏 / 注释)
  Stage-2: 标点归一(中文引号 / 全角逗号)
  Stage-3: 尾逗号删除
  Stage-4: 字符串内裸引号转义
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
    """JSON 修复报告。"""

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
    """LLM 输出 JSON 容错解析。

    参数:
        text: LLM 原始输出文本（可能含 Markdown 围栏）。
        strict: True 时跳过所有修复，行为与 json.loads 完全一致。
        return_repair_report: True 时返回 (parsed_data, RepairReport) 元组。

    返回:
        解析后的 Python 对象；或 (对象, RepairReport) 元组。

    异常:
        ScrivaiJSONRepairError: 所有修复阶段均失败。
        json.JSONDecodeError: strict=True 时，与 json.loads 行为一致。
    """
    if strict:
        result = json.loads(text)
        if return_repair_report:
            return result, RepairReport(stages_applied=[], original=text, final=text)
        return result

    # Stage-0: 快路径
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
        f"JSON 修复失败(已尝试: {', '.join(stages_applied)}):\n"
        f"  json.loads 错误: {last_error}\n"
        f"  原始文本(前{_MAX_MSG_PREVIEW}字符): {preview_orig}\n"
        f"  修复后文本(前{_MAX_MSG_PREVIEW}字符): {preview_final}"
    )
    raise ScrivaiJSONRepairError(
        msg=msg,
        doc=text,
        pos=last_error.pos if last_error.pos is not None else 0,
        original_text=original,
        repaired_text=text,
        stages_applied=stages_applied,
    )


# ── Stage 实现 ──

_RE_FENCE = re.compile(r"^```(?:json|JSON)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def _strip_envelope(text: str) -> str:
    """Stage-1: 去除前后空白、Markdown 围栏、行/块注释。"""
    text = text.strip()

    fence = _RE_FENCE.match(text)
    if fence:
        text = fence.group(1).strip()

    text = _remove_comments_outside_strings(text)
    return text


def _remove_comments_outside_strings(text: str) -> str:
    """去除 JSON 语法位置的 // 行注释和 /* */ 块注释,保留字符串内容不变。"""
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

# 对应关系：开引号 → 关引号
_FANCY_QUOTE_PAIR: dict[str, str] = {
    "\u201c": "\u201d",  # " → "
    "\u2018": "\u2019",  # ' → '
}


def _normalize_quotes(text: str) -> str:
    """Stage-2: 语法位置的中文/全角引号 → 半角,全角逗号 → 半角。

    状态机追踪字符串内/外,区分两种开启方式:
    - 普通 `"` 开启: 只有 `"` 关闭,内部中文引号保留不动。
    - 中文引号开启: 对应的配对关闭引号关闭,输出全部替换为 `"`。

    全角逗号在字符串外替换为半角逗号。
    """
    result: list[str] = []
    in_string = False
    fancy_close: str | None = None  # 当前期望的中文关闭引号(None=由"开启)
    i = 0

    while i < len(text):
        ch = text[i]

        if in_string:
            if fancy_close is None:
                # 由普通 `"` 开启的字符串
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
                # 中文引号在此保留原样
                result.append(ch)
                i += 1
                continue
            else:
                # 由中文引号开启的字符串,等待对应关闭引号
                if ch == fancy_close:
                    in_string = False
                    fancy_close = None
                    result.append('"')
                    i += 1
                    continue
                result.append(ch)
                i += 1
                continue

        # 字符串外
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
    """Stage-3: 删除对象/数组最后一个元素后的多余逗号。

    状态机跳过字符串内容,仅对语法位置的 ,\\s*[}\\]] 模式执行删除。
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
    """Stage-4: 字符串值内未转义的双引号 → 转义。

    前置条件:Stage-2 已将所有结构性引号归一为半角。
    启发式:遇到字符串内的 " 时,检查紧随其后的字符是否为 JSON 结构字符。
    若不是 → 此 " 是字符串内容,需转义为 \\"。
    若是 → 此 " 是字符串闭合符。
    """
    result: list[str] = []
    i = 0

    while i < len(text):
        ch = text[i]

        if ch != '"':
            result.append(ch)
            i += 1
            continue

        # 遇到 " — 开始扫描字符串
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
