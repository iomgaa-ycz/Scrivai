"""LLMClient — thin adapter layer for claude-agent-sdk 0.1.61 (M1.0).

References:
- docs/design.md §5.3.7
- docs/superpowers/specs/2026-04-17-scrivai-m1.0-design.md §4
- Herald2 core/llm.py (pending_tool_calls pairing pattern + _text_from_content helper)
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

# ── Module-internal exceptions (not exposed to the business layer) ───────


class _MaxTurnsError(Exception):
    """Raised when ResultMessage.stop_reason == 'max_turns'.

    BasePES._call_sdk_query maps this to sdk_other → max_turns_exceeded.
    """

    def __init__(self, num_turns: int) -> None:
        self.num_turns = num_turns
        super().__init__(f"max_turns reached at {num_turns}")


class _SDKExecutionError(Exception):
    """Raised when ResultMessage.is_error is True and stop_reason is not max_turns. Mapped to sdk_other by BasePES._call_sdk_query."""

    def __init__(self, stop_reason: str | None, errors: list[str]) -> None:
        self.stop_reason = stop_reason
        self.errors = errors
        super().__init__(f"stop_reason={stop_reason} errors={errors}")


# ── Data structures ─────────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """Unified return value from an SDK call. BasePES._call_sdk_query unpacks it into (result, usage, turns)."""

    result: str
    turns: list[PhaseTurn]
    usage: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    session_id: str | None = None


# ── Utility functions ───────────────────────────────────────────────────


def _text_from_content(content: str | list[dict[str, Any]] | None) -> str:
    """Extract plain text from ToolResultBlock.content (adapted from Herald2 helper).

    In SDK 0.1.61, ToolResultBlock.content may be str, list[dict], or None.
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


# ── LLMClient ───────────────────────────────────────────────────────────


class LLMClient:
    """Thin wrapper around claude_agent_sdk.query().

    Responsibilities:
    - Build ClaudeAgentOptions (inject ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN via env)
    - Consume the message stream and translate it into a list of PhaseTurn objects
    - Pair tool_use ↔ tool_result across messages (pending_tool_calls dict)
    - Map ResultMessage.is_error → _MaxTurnsError / _SDKExecutionError

    Not responsible for:
    - Internal retries (L2 retries are handled by BasePES._run_phase_with_retry)
    - Error categorisation (error_type translation is done by BasePES._call_sdk_query)
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
        """Build ClaudeAgentOptions; ModelConfig.base_url/api_key are injected via env."""
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
        """Convert an AssistantMessage to a single PhaseTurn.

        - Multiple TextBlocks are concatenated into data["text"]
        - Multiple ToolUseBlocks are collected into data["tool_uses"] and recorded in pending
        - ThinkingBlocks are ignored (MVP)
        - Empty messages (no text, no tools) return None
        """
        text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})
                pending[block.id] = {
                    "name": block.name,
                    "input": block.input,
                    "result": None,
                    "is_error": None,
                }
            elif isinstance(block, ThinkingBlock):
                pass  # ignored in MVP
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
        """Convert a UserMessage (tool result) to a single PhaseTurn.

        - Only list-form content is processed (str content is not constructed in MVP)
        - Pairs with the pending dict via tool_use_id to synthesise stdout/stderr/exit_code (Herald2 pattern)
        - Also backfills pending[id]["result"] / ["is_error"] (internal state, not written to turn)
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
        """Execute a single SDK query. No internal retry; SDK exceptions propagate naturally."""
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
        assistant_turn_count = 0

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn = self._parse_assistant_turn(message, len(turns), pending_tool_calls)
                if turn is not None:
                    turns.append(turn)
                    if on_turn:
                        on_turn(turn)
                    # In some permission_mode values the SDK does not count rejected tool
                    # calls against max_turns; track assistant turns manually to prevent loops.
                    assistant_turn_count += 1
                    if assistant_turn_count > max_turns:
                        raise _MaxTurnsError(assistant_turn_count)

            elif isinstance(message, UserMessage):
                turn = self._parse_user_turn(message, len(turns), pending_tool_calls)
                if turn is not None:
                    turns.append(turn)
                    if on_turn:
                        on_turn(turn)

            elif isinstance(message, ResultMessage):
                # stop_sequence / end_turn are normal termination reasons (private gateways may set is_error=True)
                _NORMAL_STOP_REASONS = {"end_turn", "stop_sequence"}
                is_normal = (not message.is_error) or (message.stop_reason in _NORMAL_STOP_REASONS)
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

            # SystemMessage / StreamEvent / RateLimitEvent: ignored (MVP)

        if result_response is None:
            raise RuntimeError("No ResultMessage received from SDK")
        return result_response

    async def simple_query(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_prompt: str = "You are a helpful assistant.",
        max_turns: int = 1,
    ) -> str:
        """Thin wrapper for tool-free, single-turn, plain-text queries.

        Used by Proposer and similar callers that only need to send a prompt and receive text.
        The model argument is currently ignored (ModelConfig is fixed at construction time)
        and is retained only so callers can document their intent explicitly.
        """
        import tempfile
        from pathlib import Path as _Path

        _ = model  # ignored; actual model is determined by self.model at construction time
        with tempfile.TemporaryDirectory(prefix="scrivai-simple-query-") as tmp:
            resp = await self.execute_task(
                prompt=prompt,
                system_prompt=system_prompt,
                allowed_tools=[],
                max_turns=max_turns,
                permission_mode="default",
                cwd=_Path(tmp),
            )
        return resp.result
