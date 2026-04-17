"""LLMClient 契约测试 — mock claude_agent_sdk.query 消息流。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from scrivai.models.pes import ModelConfig
from scrivai.pes.llm_client import (
    LLMClient,
    LLMResponse,
    _MaxTurnsError,
    _SDKExecutionError,
)


def _client() -> LLMClient:
    return LLMClient(ModelConfig(model="glm-5.1", provider="glm"))


def test_assistant_text_only() -> None:
    """单 AssistantMessage(只含 TextBlock)→ 1 个 PhaseTurn(content_type='text')。"""
    msg = AssistantMessage(
        content=[TextBlock(text="hello world")],
        model="glm-5.1",
        parent_tool_use_id=None,
        error=None,
        usage={"input_tokens": 10, "output_tokens": 2},
        message_id="msg_1",
        stop_reason="end_turn",
        session_id="sess_1",
        uuid="uuid_1",
    )
    pending: dict = {}
    turn = _client()._parse_assistant_turn(msg, turn_index=0, pending=pending)
    assert turn is not None
    assert turn.role == "assistant"
    assert turn.content_type == "text"
    assert turn.data["text"] == "hello world"
    assert turn.data["tool_uses"] == []
    assert turn.data["model"] == "glm-5.1"
    assert pending == {}, "no tool_use → pending stays empty"


def test_assistant_with_tool_use() -> None:
    """AssistantMessage(TextBlock + ToolUseBlock).

    → PhaseTurn(content_type='tool_use'),pending 记录。
    """
    msg = AssistantMessage(
        content=[
            TextBlock(text="I'll list files."),
            ToolUseBlock(id="tu_1", name="Bash", input={"command": "ls"}),
        ],
        model="glm-5.1",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        message_id="msg_2",
        stop_reason="tool_use",
        session_id="sess_1",
        uuid="uuid_2",
    )
    pending: dict = {}
    turn = _client()._parse_assistant_turn(msg, turn_index=1, pending=pending)
    assert turn is not None
    assert turn.role == "assistant"
    assert turn.content_type == "tool_use"
    assert turn.data["text"] == "I'll list files."
    assert turn.data["tool_uses"] == [
        {"id": "tu_1", "name": "Bash", "input": {"command": "ls"}}
    ]
    assert "tu_1" in pending
    assert pending["tu_1"] == {
        "name": "Bash",
        "input": {"command": "ls"},
        "result": None,
        "is_error": None,
    }


def test_assistant_empty_message_returns_none() -> None:
    """AssistantMessage 无 text 也无 tool_use → 返回 None(不构造空 turn)。"""
    msg = AssistantMessage(
        content=[],
        model="glm-5.1",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        message_id="msg_e",
        stop_reason=None,
        session_id="sess_1",
        uuid="uuid_e",
    )
    pending: dict = {}
    turn = _client()._parse_assistant_turn(msg, turn_index=0, pending=pending)
    assert turn is None


def test_user_tool_result_pairing() -> None:
    """UserMessage(ToolResultBlock)通过 tool_use_id 配对 pending,合成 stdout/stderr/exit_code。"""
    pending: dict = {
        "tu_1": {
            "name": "Bash",
            "input": {"command": "ls"},
            "result": None,
            "is_error": None,
        }
    }
    msg = UserMessage(
        content=[
            ToolResultBlock(
                tool_use_id="tu_1",
                content="file1.txt\nfile2.txt",
                is_error=False,
            )
        ],
        uuid="uuid_3",
        parent_tool_use_id=None,
        tool_use_result={"stdout": "file1.txt\nfile2.txt", "stderr": ""},
    )
    turn = _client()._parse_user_turn(msg, turn_index=2, pending=pending)
    assert turn is not None
    assert turn.role == "user"
    assert turn.content_type == "tool_result"
    assert len(turn.data["tool_results"]) == 1
    tr = turn.data["tool_results"][0]
    assert tr["tool_use_id"] == "tu_1"
    assert tr["tool_name"] == "Bash"
    assert tr["stdout"] == "file1.txt\nfile2.txt"
    assert tr["stderr"] == ""
    assert tr["exit_code"] == 0
    assert tr["is_error"] is False
    # pending 内部状态也被回填
    assert pending["tu_1"]["result"] == "file1.txt\nfile2.txt"
    assert pending["tu_1"]["is_error"] is False


def test_user_string_content_returns_none() -> None:
    """UserMessage.content 是 str(非 list)→ 返回 None(MVP 不构造此类 turn)。"""
    msg = UserMessage(
        content="plain string",
        uuid="uuid_s",
        parent_tool_use_id=None,
        tool_use_result=None,
    )
    pending: dict = {}
    turn = _client()._parse_user_turn(msg, turn_index=2, pending=pending)
    assert turn is None


async def _async_iter(items: list):
    """Helper: turn a list into async iterator (for mocking query())."""
    for item in items:
        yield item


async def test_result_message_success() -> None:
    """完整消息流(2 turn + ResultMessage success)→ LLMResponse 正确填充。"""
    messages = [
        AssistantMessage(
            content=[
                TextBlock(text="Listing files."),
                ToolUseBlock(id="tu_1", name="Bash", input={"command": "ls"}),
            ],
            model="glm-5.1",
            parent_tool_use_id=None,
            error=None,
            usage=None,
            message_id="m1",
            stop_reason="tool_use",
            session_id="s1",
            uuid="u1",
        ),
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id="tu_1", content="a.txt\nb.txt", is_error=False)
            ],
            uuid="u2",
            parent_tool_use_id=None,
            tool_use_result={"stdout": "a.txt\nb.txt", "stderr": ""},
        ),
        AssistantMessage(
            content=[TextBlock(text="Done. Found 2 files.")],
            model="glm-5.1",
            parent_tool_use_id=None,
            error=None,
            usage={"input_tokens": 100, "output_tokens": 20},
            message_id="m3",
            stop_reason="end_turn",
            session_id="s1",
            uuid="u3",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=1234,
            duration_api_ms=1000,
            is_error=False,
            num_turns=3,
            session_id="s1",
            stop_reason="end_turn",
            total_cost_usd=0.0012,
            usage={"input_tokens": 100, "output_tokens": 20},
            result="Done. Found 2 files.",
            structured_output=None,
            model_usage={},
            permission_denials=None,
            errors=None,
            uuid="ur",
        ),
    ]

    captured_turns: list = []

    with patch(
        "scrivai.pes.llm_client.query",
        return_value=_async_iter(messages),
    ):
        resp = await _client().execute_task(
            prompt="list files",
            system_prompt="you are helpful",
            allowed_tools=["Bash"],
            max_turns=5,
            permission_mode="default",
            cwd=Path("/tmp"),
            on_turn=captured_turns.append,
        )

    assert isinstance(resp, LLMResponse)
    assert resp.result == "Done. Found 2 files."
    assert resp.usage == {"input_tokens": 100, "output_tokens": 20}
    assert resp.duration_ms == 1234
    assert resp.session_id == "s1"
    assert len(resp.turns) == 3
    assert resp.turns[0].role == "assistant" and resp.turns[0].content_type == "tool_use"
    assert resp.turns[1].role == "user" and resp.turns[1].content_type == "tool_result"
    assert resp.turns[2].role == "assistant" and resp.turns[2].content_type == "text"
    assert len(captured_turns) == 3, "on_turn callback fired for each turn"


async def test_result_message_max_turns() -> None:
    """ResultMessage(is_error=True, stop_reason='max_turns') → raise _MaxTurnsError(num_turns)。"""
    messages = [
        ResultMessage(
            subtype="error",
            duration_ms=500,
            duration_api_ms=400,
            is_error=True,
            num_turns=10,
            session_id="s2",
            stop_reason="max_turns",
            total_cost_usd=None,
            usage=None,
            result=None,
            structured_output=None,
            model_usage=None,
            permission_denials=None,
            errors=["max_turns reached"],
            uuid="ur2",
        ),
    ]
    with patch("scrivai.pes.llm_client.query", return_value=_async_iter(messages)):
        with pytest.raises(_MaxTurnsError) as exc_info:
            await _client().execute_task(
                prompt="x",
                system_prompt="x",
                allowed_tools=[],
                max_turns=10,
                permission_mode="default",
                cwd=Path("/tmp"),
            )
    assert exc_info.value.num_turns == 10


async def test_result_message_other_error() -> None:
    """ResultMessage(is_error=True, 非 max_turns) → raise _SDKExecutionError。"""
    messages = [
        ResultMessage(
            subtype="error",
            duration_ms=300,
            duration_api_ms=200,
            is_error=True,
            num_turns=2,
            session_id="s3",
            stop_reason="error",
            total_cost_usd=None,
            usage=None,
            result=None,
            structured_output=None,
            model_usage=None,
            permission_denials=None,
            errors=["server error 500"],
            uuid="ur3",
        ),
    ]
    with patch("scrivai.pes.llm_client.query", return_value=_async_iter(messages)):
        with pytest.raises(_SDKExecutionError) as exc_info:
            await _client().execute_task(
                prompt="x",
                system_prompt="x",
                allowed_tools=[],
                max_turns=10,
                permission_mode="default",
                cwd=Path("/tmp"),
            )
    assert exc_info.value.stop_reason == "error"
    assert exc_info.value.errors == ["server error 500"]


async def test_no_result_message_raises() -> None:
    """消息流耗尽未见 ResultMessage → raise RuntimeError('未收到 ResultMessage')。"""
    messages = [
        AssistantMessage(
            content=[TextBlock(text="hi")],
            model="glm-5.1",
            parent_tool_use_id=None,
            error=None,
            usage=None,
            message_id="m1",
            stop_reason="end_turn",
            session_id="s4",
            uuid="u1",
        ),
    ]
    with patch("scrivai.pes.llm_client.query", return_value=_async_iter(messages)):
        with pytest.raises(RuntimeError, match="未收到 ResultMessage"):
            await _client().execute_task(
                prompt="x",
                system_prompt="x",
                allowed_tools=[],
                max_turns=10,
                permission_mode="default",
                cwd=Path("/tmp"),
            )
