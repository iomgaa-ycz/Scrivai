"""BasePES SDK integration tests — mock LLMClient + 1 real SDK smoke (M1.0)。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from claude_agent_sdk import CLIConnectionError

from scrivai.models.pes import (
    ModelConfig,
    PESConfig,
    PhaseConfig,
)
from scrivai.models.workspace import (
    WorkspaceHandle,
    WorkspaceSnapshot,
)
from scrivai.pes.base import BasePES
from scrivai.pes.llm_client import _MaxTurnsError


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceHandle:
    """最小可用 workspace。"""
    project = tmp_path / "project"
    project.mkdir()
    ws_dir = tmp_path / "ws"
    for sub in ("working", "data", "output", "logs"):
        (ws_dir / sub).mkdir(parents=True)
    return WorkspaceHandle(
        run_id="r1",
        root_dir=ws_dir,
        working_dir=ws_dir / "working",
        data_dir=ws_dir / "data",
        output_dir=ws_dir / "output",
        logs_dir=ws_dir / "logs",
        snapshot=WorkspaceSnapshot(
            run_id="r1",
            project_root=project,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


def _minimal_config() -> PESConfig:
    """最简 PESConfig:三阶段都允许 Bash + 没有 required_outputs。"""
    return PESConfig(
        name="test",
        display_name="Test PES",
        prompt_text="You are a test assistant.",
        default_skills=[],
        phases={
            "plan": PhaseConfig(name="plan", allowed_tools=["Bash"], max_turns=2),
            "execute": PhaseConfig(name="execute", allowed_tools=["Bash"], max_turns=2),
            "summarize": PhaseConfig(name="summarize", allowed_tools=["Bash"], max_turns=2),
        },
    )


async def test_call_sdk_query_translates_max_turns(workspace: WorkspaceHandle) -> None:
    """_MaxTurnsError → PhaseError(error_type='max_turns_exceeded', is_retryable=True)。"""
    mock_llm = MagicMock()
    mock_llm.execute_task = AsyncMock(side_effect=_MaxTurnsError(num_turns=2))

    pes = BasePES(
        config=_minimal_config(),
        model=ModelConfig(model="glm-5.1"),
        workspace=workspace,
        llm_client=mock_llm,
    )
    run = await pes.run("test task")

    # max_retries=1 → tries twice → both fail → run.status=failed
    assert run.status == "failed"
    assert run.error_type == "max_turns_exceeded"
    assert mock_llm.execute_task.call_count == 2


async def test_call_sdk_query_translates_sdk_error(workspace: WorkspaceHandle) -> None:
    """CLIConnectionError → PhaseError(error_type='sdk_other', is_retryable=True)。"""
    mock_llm = MagicMock()
    mock_llm.execute_task = AsyncMock(side_effect=CLIConnectionError("connection refused"))

    pes = BasePES(
        config=_minimal_config(),
        model=ModelConfig(model="glm-5.1"),
        workspace=workspace,
        llm_client=mock_llm,
    )
    run = await pes.run("test task")

    assert run.status == "failed"
    assert run.error_type == "sdk_other"
    # is_retryable=True (M1.0 改动) → 跑了 max_retries+1 = 2 次
    assert mock_llm.execute_task.call_count == 2


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_AUTH_TOKEN"),
    reason="real SDK smoke; requires ANTHROPIC_AUTH_TOKEN in .env",
)
async def test_real_sdk_smoke_minimal_phase(workspace) -> None:
    """真实 SDK smoke: BasePES + 真 LLMClient + GLM-5.1 跑通最简 plan phase。

    验证:
    - working/plan.md 文件被 Agent 真实写入
    - PhaseResult.usage 含 token 数
    - PESRun.status = "completed"
    - 至少 1 个 PhaseTurn(Agent 至少响应一次)
    """
    cfg = PESConfig(
        name="smoke",
        display_name="Smoke Test PES",
        prompt_text=(
            "You are a test assistant. Follow instructions exactly and write files when asked."
        ),
        default_skills=[],
        phases={
            "plan": PhaseConfig(
                name="plan",
                additional_system_prompt=(
                    "Write a file `working/plan.md` containing exactly two lines:\n"
                    "Line 1: hello\nLine 2: world\nThen respond 'done'."
                ),
                allowed_tools=["Write"],
                max_turns=4,
                max_retries=0,
                required_outputs=["plan.md"],
            ),
            "execute": PhaseConfig(
                name="execute",
                additional_system_prompt="Just respond 'skip' immediately, write nothing.",
                allowed_tools=[],
                max_turns=1,
                max_retries=0,
                required_outputs=[],
            ),
            "summarize": PhaseConfig(
                name="summarize",
                additional_system_prompt="Just respond 'skip' immediately, write nothing.",
                allowed_tools=[],
                max_turns=1,
                max_retries=0,
                required_outputs=[],
            ),
        },
    )

    model = ModelConfig(
        model=os.getenv("SCRIVAI_DEFAULT_MODEL") or "glm-5.1",
        provider=os.getenv("SCRIVAI_DEFAULT_PROVIDER") or "glm",
    )

    pes = BasePES(config=cfg, model=model, workspace=workspace)
    run = await pes.run("Initialize the working directory.")

    assert run.status == "completed", f"run failed: {run.error_type} {run.error}"
    plan_md = workspace.working_dir / "plan.md"
    assert plan_md.exists(), f"Agent didn't write plan.md to {plan_md}"
    assert plan_md.read_text(encoding="utf-8").strip(), "plan.md is empty"

    plan_result = run.phase_results["plan"]
    assert plan_result.usage, "PhaseResult.usage should contain token stats"
    assert len(plan_result.turns) >= 1, "at least one Agent turn expected"
