"""Phase 间文件化契约真实验证 (T1.3) — 默认 validate_phase_outputs 检测缺失文件。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scrivai.models.pes import ModelConfig, PESConfig, PhaseConfig
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.base import BasePES
from scrivai.pes.llm_client import LLMResponse


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceHandle:
    """最小可用 workspace — 直接复用 test_base_pes_sdk.py 的 fixture 模式。"""
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


async def test_default_validate_phase_outputs_catches_missing_file(
    workspace: WorkspaceHandle,
) -> None:
    """LLMClient 返回成功但没产出 plan.md → default validate_phase_outputs 抛异常。

    M1.0 契约:T1.3 真实文件契约由 M0.5 默认 validate 实现 + LLMClient 真实接入
    → 端到端覆盖文件契约验证(output_validation_error, is_retryable=True)。
    """
    # Mock LLMClient: success but writes nothing to working/
    mock_llm = MagicMock()
    mock_llm.execute_task = AsyncMock(
        return_value=LLMResponse(result="ok, plan drafted", turns=[], usage={})
    )

    cfg = PESConfig(
        name="test",
        display_name="Test",
        prompt_text="",
        default_skills=[],
        phases={
            "plan": PhaseConfig(
                name="plan",
                allowed_tools=["Bash"],
                max_turns=2,
                max_retries=1,  # 重试 1 次,共 2 attempts
                required_outputs=["plan.md"],  # 必需 plan.md
            ),
            "execute": PhaseConfig(name="execute", allowed_tools=[], max_turns=1),
            "summarize": PhaseConfig(name="summarize", allowed_tools=[], max_turns=1),
        },
    )

    pes = BasePES(
        config=cfg,
        model=ModelConfig(model="glm-5.1"),
        workspace=workspace,
        llm_client=mock_llm,
    )
    run = await pes.run("draft a plan")

    # plan phase 重试 2 次后仍无文件 → run.status=failed,error_type=output_validation_error
    assert run.status == "failed"
    assert run.error_type == "output_validation_error"
    # 重试前清场不影响首次 attempt;两次 attempt 都跑了 SDK
    assert mock_llm.execute_task.call_count == 2
