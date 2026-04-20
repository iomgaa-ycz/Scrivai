"""M0.5 T0.9 contract tests for MockPES.

References:
- docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.2
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from scrivai.models.pes import (
    PESConfig,
    PhaseConfig,
)
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.testing.mock_pes import MockPES, PhaseOutcome


def _make_config(max_retries: int = 0) -> PESConfig:
    def phase_tmpl(name: str) -> PhaseConfig:
        return PhaseConfig(name=name, allowed_tools=["Bash"], max_retries=max_retries)

    return PESConfig(
        name="extractor",
        prompt_text="sys",
        phases={
            "plan": phase_tmpl("plan"),
            "execute": phase_tmpl("execute"),
            "summarize": phase_tmpl("summarize"),
        },
    )


def _make_workspace(tmp_path: Path) -> WorkspaceHandle:
    root = tmp_path / "ws" / "mock-run"
    working = root / "working"
    for d in (working, root / "data", root / "output", root / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    return WorkspaceHandle(
        run_id="mock-run",
        root_dir=root,
        working_dir=working,
        data_dir=root / "data",
        output_dir=root / "output",
        logs_dir=root / "logs",
        snapshot=WorkspaceSnapshot(
            run_id="mock-run",
            project_root=tmp_path,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


def test_happy_path_three_phases(tmp_path: Path) -> None:
    """默认 outcomes → 三阶段正常完成;run.status='completed'。"""
    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path))
    run = asyncio.run(pes.run("hello"))

    assert run.status == "completed"
    assert set(run.phase_results.keys()) == {"plan", "execute", "summarize"}


def test_injected_failure_triggers_retry(tmp_path: Path) -> None:
    """plan attempt 0 注入 error(is_retryable=True) → attempt 1 成功。"""
    pes = MockPES(
        config=_make_config(max_retries=1),
        workspace=_make_workspace(tmp_path),
        phase_outcomes={
            "plan": [
                PhaseOutcome(
                    error="flaky",
                    error_type="output_validation_error",
                    is_retryable=True,
                ),
                PhaseOutcome(response_text="plan ok"),
            ],
        },
    )
    run = asyncio.run(pes.run("test"))

    assert run.status == "completed"
    assert run.phase_results["plan"].attempt_no == 1


def test_default_outcome_when_not_specified(tmp_path: Path) -> None:
    """outcomes 为空 → 返回 ("", {}, []) 的 happy path。"""
    pes = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        phase_outcomes={},
    )
    run = asyncio.run(pes.run("test"))

    assert run.status == "completed"
    assert run.phase_results["plan"].response_text == ""


def test_produced_files_created_in_workspace(tmp_path: Path) -> None:
    """PhaseOutcome.produced_files 指定的文件自动创建到 workspace。"""
    ws = _make_workspace(tmp_path)
    pes = MockPES(
        config=_make_config(),
        workspace=ws,
        phase_outcomes={
            "plan": [PhaseOutcome(produced_files=["plan.md", "plan.json"])],
        },
    )
    run = asyncio.run(pes.run("test"))

    assert run.status == "completed"
    assert (ws.working_dir / "plan.md").is_file()
    assert (ws.working_dir / "plan.json").is_file()
