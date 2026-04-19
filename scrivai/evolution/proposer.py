"""Proposer — uses an LLM to generate N candidate SKILL.md revisions from failure samples.

See docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.2 / §6.2
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from scrivai.evolution.budget import LLMCallBudget
from scrivai.models.evolution import EvolutionProposal, FailureSample
from scrivai.pes.llm_client import LLMClient
from scrivai.utils import relaxed_json_loads


class ProposerError(RuntimeError):
    """Raised when Proposer cannot parse the LLM output or the output format is invalid."""


_SAMPLE_TRUNCATE = 800
_K_SAMPLES_IN_PROMPT = 5
_MAX_REJECTED_IN_PROMPT = 3


def _trunc(s: str, n: int = _SAMPLE_TRUNCATE) -> str:
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + " … " + s[-half:]


_SYSTEM_PROMPT = (
    "你是 SKILL.md 修订专家。你的工作是基于失败案例提出 N 个改进版 SKILL.md 候选。"
    "每个候选必须是完整 SKILL.md 内容(不是 diff),可沿用大部分原文。"
    "输出严格 JSON,不要附加任何说明文字。"
)


def _build_prompt(
    current_snapshot: dict[str, str],
    failures: list[FailureSample],
    rejected: list[EvolutionProposal],
    n: int,
) -> str:
    current_md = current_snapshot.get("SKILL.md", "(missing SKILL.md)")
    failures_blk: list[str] = []
    for i, f in enumerate(failures[:_K_SAMPLES_IN_PROMPT]):
        lines = [
            f"### 样本 {i + 1}",
            f"- 输入: {_trunc(f.question, 400)}",
            f"- 期望: {_trunc(f.ground_truth_str)}",
            f"- 当前 Agent 输出: {_trunc(f.draft_output_str)}",
            f"- 得分: {f.baseline_score:.2f}",
            "- 执行过程摘要:",
        ]
        for phase in ("plan", "execute", "summarize"):
            if phase in f.trajectory_summary:
                lines.append(f"  - {phase}: {_trunc(f.trajectory_summary[phase], 500)}")
        failures_blk.append("\n".join(lines))
    failures_text = "\n".join(failures_blk) or "(无失败样本)"

    rejected_blk: list[str] = []
    for i, r in enumerate(rejected[:_MAX_REJECTED_IN_PROMPT]):
        rejected_blk.append(f"- [{i + 1}] {r.change_summary}")
    rejected_text = "\n".join(rejected_blk) or "(无)"

    return f"""{_SYSTEM_PROMPT}

## 当前 SKILL.md 全文
```
{current_md}
```

## 失败样本(共 {len(failures)} 条,下展示前 {min(len(failures), _K_SAMPLES_IN_PROMPT)})
{failures_text}

## 历史被拒候选(展示 change_summary)
{rejected_text}

## 要求
请提出 {n} 个不同方向的改进方案。每个方案要:
1. 针对失败样本的具体问题
2. 不重复已被拒的方向
3. 完整替换 SKILL.md 内容

严格以下 JSON 格式返回(不附加任何说明):
{{
  "proposals": [
    {{
      "change_summary": "一句话概括改动方向",
      "reasoning": "为什么这个改动能解决失败样本",
      "new_content": {{"SKILL.md": "<完整新 SKILL.md>"}}
    }}
  ]
}}
"""


_RE_FENCE_SEARCH = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _find_json_object(text: str) -> str | None:
    """Extract the first complete JSON object using balanced-bracket scanning."""
    in_string = False
    escape = False
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    return None


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM output.

    The evolution prompt LLM output may contain leading prose or a Markdown fence.
    First attempt to isolate the JSON portion, then delegate to relaxed_json_loads
    for syntax fault-tolerance.

    Args:
        text: Raw LLM output.

    Returns:
        Parsed dict.

    Raises:
        ProposerError: If parsing fails or the result is not a dict.
    """
    stripped = text.strip()

    # Candidate texts: fence content -> bracket scan -> raw text
    candidates: list[str] = []
    fence = _RE_FENCE_SEARCH.search(stripped)
    if fence:
        candidates.append(fence.group(1).strip())
    obj_str = _find_json_object(stripped)
    if obj_str is not None:
        candidates.append(obj_str)
    candidates.append(stripped)

    for cand in candidates:
        try:
            parsed = relaxed_json_loads(cand)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, Exception):
            pass

    raise ProposerError(f"JSON parse failed; snippet: {text[:300]}")


class Proposer:
    """LLM-based candidate SKILL.md generator."""

    def __init__(self, llm_client: LLMClient, model: str = "glm-5.1") -> None:
        self.llm_client = llm_client
        self.model = model

    async def propose(
        self,
        current_skill_snapshot: dict[str, str],
        failures: list[FailureSample],
        rejected_proposals: list[EvolutionProposal],
        n: int = 3,
        budget: Optional[LLMCallBudget] = None,
    ) -> list[EvolutionProposal]:
        """Generate N candidate SKILL.md revisions from failure samples.

        Args:
            current_skill_snapshot: Current SKILL.md content snapshot {"SKILL.md": ...}.
            failures: List of failure samples.
            rejected_proposals: Previously rejected candidates (to avoid repeating directions).
            n: Expected number of candidate proposals.
            budget: LLM call budget guard (optional).

        Returns:
            List of EvolutionProposal with length >= 1.

        Raises:
            ProposerError: If parsing still fails after retries or no valid candidates remain.
            BudgetExceededError: If the budget is exceeded.
        """
        base_prompt = _build_prompt(current_skill_snapshot, failures, rejected_proposals, n)
        last_error: Optional[Exception] = None

        for attempt in (0, 1):  # at most 2 attempts (initial + 1 retry)
            if budget is not None:
                budget.consume(1)  # Budget is not waived for retries
            prompt = (
                base_prompt
                if attempt == 0
                else base_prompt
                + (
                    "\n\n[严格化提示]你上次输出无法解析,请严格按上面的 JSON 模板返回,"
                    "不要附加任何说明文字,不要用 markdown 代码块包裹。"
                )
            )
            raw = await self.llm_client.simple_query(prompt, model=self.model)
            try:
                parsed = _extract_json(raw)
            except ProposerError as e:
                last_error = e
                continue
            proposals_raw = parsed.get("proposals", [])
            if not isinstance(proposals_raw, list) or len(proposals_raw) == 0:
                last_error = ProposerError(f"no proposals in LLM response: {parsed}")
                continue
            out: list[EvolutionProposal] = []
            for p in proposals_raw:
                if not isinstance(p, dict):
                    continue
                new_content = p.get("new_content", {})
                if not isinstance(new_content, dict) or "SKILL.md" not in new_content:
                    continue
                out.append(
                    EvolutionProposal(
                        new_content_snapshot=new_content,
                        change_summary=p.get("change_summary", ""),
                        reasoning=p.get("reasoning", ""),
                    )
                )
            if out:
                return out
            last_error = ProposerError(f"0 valid proposals in LLM response: {parsed}")

        raise ProposerError(f"proposer failed after 2 attempts: {last_error}")
