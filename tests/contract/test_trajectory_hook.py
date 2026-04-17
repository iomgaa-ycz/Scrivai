"""M0.5 T0.8 contract tests for TrajectoryRecorderHook.

References:
- docs/design.md §4.3 / §4.13(不变量 #9)
- docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.3
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from scrivai.models.pes import PESConfig, PhaseConfig, PhaseTurn
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.hooks import HookManager
from scrivai.testing import FakeTrajectoryStore
from scrivai.testing.mock_pes import MockPES, PhaseOutcome
from scrivai.trajectory.hooks import TrajectoryRecorderHook


def _make_config() -> PESConfig:
    def phase_tmpl(name: str) -> PhaseConfig:
        return PhaseConfig(name=name, allowed_tools=["Bash"])

    return PESConfig(
        name="traj-test",
        prompt_text="sys",
        phases={
            "plan": phase_tmpl("plan"),
            "execute": phase_tmpl("execute"),
            "summarize": phase_tmpl("summarize"),
        },
    )


def _make_workspace(tmp_path: Path) -> WorkspaceHandle:
    root = tmp_path / "ws" / "traj-run"
    working = root / "working"
    for d in (working, root / "data", root / "output", root / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    return WorkspaceHandle(
        run_id="traj-run",
        root_dir=root,
        working_dir=working,
        data_dir=root / "data",
        output_dir=root / "output",
        logs_dir=root / "logs",
        snapshot=WorkspaceSnapshot(
            run_id="traj-run",
            project_root=tmp_path,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


def _make_turn(index: int, role: str, content_type: str, data: dict) -> PhaseTurn:
    return PhaseTurn(
        turn_index=index,
        role=role,
        content_type=content_type,
        data=data,
        timestamp=datetime.now(timezone.utc),
    )


def test_full_run_recorded(tmp_path: Path) -> None:
    """MockPES 跑一次 → runs / phases / turns 全表有对应记录。"""
    store = FakeTrajectoryStore()
    hooks = HookManager()
    hooks.register(TrajectoryRecorderHook(store))

    turns_plan = [
        _make_turn(0, "assistant", "text", {"text": "planning..."}),
    ]

    pes = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        hooks=hooks,
        trajectory_store=store,
        phase_outcomes={
            "plan": [PhaseOutcome(response_text="plan done", turns=turns_plan)],
        },
    )
    run = asyncio.run(pes.run("test task"))

    assert run.status == "completed"

    rec = store.get_run("traj-run")
    assert rec is not None
    assert rec.status == "completed"
    assert rec.pes_name == "traj-test"

    assert len(rec.phase_records) == 3

    conn = store._memory_conn
    assert conn is not None
    turn_count = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    assert turn_count >= 1


def test_tool_calls_extracted_from_turns(tmp_path: Path) -> None:
    """tool_use / tool_result turn → tool_calls 表有对应记录。"""
    store = FakeTrajectoryStore()
    hooks = HookManager()
    hooks.register(TrajectoryRecorderHook(store))

    turns_with_tools = [
        _make_turn(0, "assistant", "tool_use", {"name": "Bash", "input": {"cmd": "ls"}}),
        _make_turn(1, "user", "tool_result", {"name": "Bash", "content": "file1\n"}),
    ]

    pes = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        hooks=hooks,
        trajectory_store=store,
        phase_outcomes={
            "plan": [PhaseOutcome(turns=turns_with_tools)],
        },
    )
    asyncio.run(pes.run("test"))

    conn = store._memory_conn
    assert conn is not None
    tc_count = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
    assert tc_count == 2

    rows = conn.execute("SELECT tool_name, status FROM tool_calls ORDER BY rowid").fetchall()
    assert rows[0] == ("Bash", "started")
    assert rows[1] == ("Bash", "completed")
