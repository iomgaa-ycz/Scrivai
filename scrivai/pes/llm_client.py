"""LLMClient — claude-agent-sdk 0.1.61 适配层(M1.0)。

参考:
- docs/design.md §5.3.7
- docs/superpowers/specs/2026-04-17-scrivai-m1.0-design.md §4
- Herald2 core/llm.py(借鉴 pending_tool_calls 配对模式 + _text_from_content helper)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

from scrivai.models.pes import ModelConfig, PhaseTurn

# ── 模块内部异常(不暴露给业务层) ─────────────────────────


class _MaxTurnsError(Exception):
    """ResultMessage.stop_reason == 'max_turns' 触发。

    BasePES._call_sdk_query 翻译为 sdk_other → max_turns_exceeded。
    """

    def __init__(self, num_turns: int) -> None:
        self.num_turns = num_turns
        super().__init__(f"max_turns reached at {num_turns}")


class _SDKExecutionError(Exception):
    """ResultMessage.is_error 且非 max_turns。BasePES._call_sdk_query 翻译为 sdk_other。"""

    def __init__(self, stop_reason: str | None, errors: list[str]) -> None:
        self.stop_reason = stop_reason
        self.errors = errors
        super().__init__(f"stop_reason={stop_reason} errors={errors}")


# ── 数据结构 ─────────────────────────────────────────────


@dataclass
class LLMResponse:
    """SDK 调用的统一返回。BasePES._call_sdk_query 解包成 (result, usage, turns)。"""

    result: str
    turns: list[PhaseTurn]
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    session_id: str | None = None


# ── 工具函数 ─────────────────────────────────────────────


def _text_from_content(content: str | list[dict[str, Any]] | None) -> str:
    """从 ToolResultBlock.content 提取纯文本(借 Herald2 helper)。

    SDK 0.1.61 的 ToolResultBlock.content 可能是 str、list[dict]、或 None。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


# ── LLMClient ────────────────────────────────────────────


class LLMClient:
    """对 claude_agent_sdk.query() 的薄封装。

    职责:
    - 构造 ClaudeAgentOptions(env 注入 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN)
    - 消费消息流,翻译为 PhaseTurn 列表
    - tool_use ↔ tool_result 跨 message 配对(pending_tool_calls dict)
    - ResultMessage.is_error → _MaxTurnsError / _SDKExecutionError

    不职责:
    - 内部重试(L2 由 BasePES._run_phase_with_retry 负责)
    - 错误细分(error_type 由 BasePES._call_sdk_query 翻译)
    """

    def __init__(self, model: ModelConfig) -> None:
        self.model = model

    def _build_options(
        self,
        *,
        system_prompt: str,
        allowed_tools: list[str],
        max_turns: int,
        permission_mode: str,
        cwd: Path,
        extra_env: dict[str, str] | None,
    ) -> ClaudeAgentOptions:
        """构造 ClaudeAgentOptions;ModelConfig.base_url/api_key 通过 env 注入。"""
        env: dict[str, str] = dict(extra_env or {})
        if self.model.base_url:
            env["ANTHROPIC_BASE_URL"] = self.model.base_url
        if self.model.api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = self.model.api_key
        return ClaudeAgentOptions(
            model=self.model.model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            max_turns=max_turns,
            permission_mode=permission_mode,  # type: ignore[arg-type]
            cwd=str(cwd),
            env=env,
            mcp_servers={},
            setting_sources=["project"],
        )

    def _parse_assistant_turn(
        self,
        msg: AssistantMessage,
        turn_index: int,
        pending: dict[str, dict[str, Any]],
    ) -> PhaseTurn | None:
        """AssistantMessage → 1 个 PhaseTurn。

        - 多 TextBlock 拼接为 data["text"]
        - 多 ToolUseBlock 收集到 data["tool_uses"];同时填 pending dict
        - ThinkingBlock MVP 忽略
        - 空消息(无 text 无 tool)→ 返回 None
        """
        text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_uses.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )
                pending[block.id] = {
                    "name": block.name,
                    "input": block.input,
                    "result": None,
                    "is_error": None,
                }
            elif isinstance(block, ThinkingBlock):
                pass  # MVP 忽略
        if not text_parts and not tool_uses:
            return None
        return PhaseTurn(
            turn_index=turn_index,
            role="assistant",
            content_type="tool_use" if tool_uses else "text",
            data={
                "text": "".join(text_parts),
                "tool_uses": tool_uses,
                "model": msg.model,
                "stop_reason": msg.stop_reason,
                "usage": msg.usage,
            },
            timestamp=datetime.now(timezone.utc),
        )

    def _parse_user_turn(
        self,
        msg: UserMessage,
        turn_index: int,
        pending: dict[str, dict[str, Any]],
    ) -> PhaseTurn | None:
        """UserMessage(tool result)→ 1 个 PhaseTurn。

        - 仅处理 list 形式 content(str content MVP 不构造)
        - 通过 tool_use_id 配对 pending dict,合成 stdout/stderr/exit_code(Herald2 模式)
        - 同时回填 pending[id]["result"] / ["is_error"](内部状态,不写 turn)
        """
        if not isinstance(msg.content, list):
            return None
        cli_result: dict[str, Any] = (
            msg.tool_use_result if isinstance(msg.tool_use_result, dict) else {}
        )
        tool_results: list[dict[str, Any]] = []
        for block in msg.content:
            if not isinstance(block, ToolResultBlock):
                continue
            target = pending.get(block.tool_use_id)
            tool_results.append(
                {
                    "tool_use_id": block.tool_use_id,
                    "tool_name": target["name"] if target else None,
                    "content": block.content,
                    "is_error": block.is_error,
                    "stdout": cli_result.get("stdout") or _text_from_content(block.content),
                    "stderr": cli_result.get("stderr", ""),
                    "exit_code": 1 if block.is_error else 0,
                }
            )
            if target is not None:
                target["result"] = block.content
                target["is_error"] = block.is_error
        if not tool_results:
            return None
        return PhaseTurn(
            turn_index=turn_index,
            role="user",
            content_type="tool_result",
            data={"tool_results": tool_results},
            timestamp=datetime.now(timezone.utc),
        )

    async def execute_task(
        self,
        *,
        prompt: str,
        system_prompt: str,
        allowed_tools: list[str],
        max_turns: int,
        permission_mode: str,
        cwd: Path,
        extra_env: dict[str, str] | None = None,
        on_turn: Callable[[PhaseTurn], None] | None = None,
    ) -> LLMResponse:
        """单次 SDK query。无内部重试,SDK 异常自然冒泡。"""
        options = self._build_options(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            max_turns=max_turns,
            permission_mode=permission_mode,
            cwd=cwd,
            extra_env=extra_env,
        )

        turns: list[PhaseTurn] = []
        pending_tool_calls: dict[str, dict[str, Any]] = {}
        result_response: LLMResponse | None = None

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn = self._parse_assistant_turn(message, len(turns), pending_tool_calls)
                if turn is not None:
                    turns.append(turn)
                    if on_turn:
                        on_turn(turn)

            elif isinstance(message, UserMessage):
                turn = self._parse_user_turn(message, len(turns), pending_tool_calls)
                if turn is not None:
                    turns.append(turn)
                    if on_turn:
                        on_turn(turn)

            elif isinstance(message, ResultMessage):
                # stop_sequence / end_turn 是正常终止原因(私有网关可能将 is_error 置 True)
                _NORMAL_STOP_REASONS = {"end_turn", "stop_sequence"}
                is_normal = (not message.is_error) or (
                    message.stop_reason in _NORMAL_STOP_REASONS
                )
                if not is_normal:
                    if message.stop_reason == "max_turns":
                        raise _MaxTurnsError(message.num_turns)
                    raise _SDKExecutionError(
                        stop_reason=message.stop_reason,
                        errors=message.errors or [],
                    )
                result_response = LLMResponse(
                    result=message.result or "",
                    turns=turns,
                    usage=message.usage or {},
                    duration_ms=message.duration_ms,
                    session_id=message.session_id,
                )

            # SystemMessage / StreamEvent / RateLimitEvent: 忽略(MVP)

        if result_response is None:
            raise RuntimeError("未收到 ResultMessage")
        return result_response
