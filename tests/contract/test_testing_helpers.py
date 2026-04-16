"""M0.25 T0.10 contract tests for testing helpers.

References:
- docs/TD.md T0.10
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.4
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="TempWorkspaceManager 继承 fcntl 行为(POSIX only)",
)


@pytest.fixture
def fake_project_root(tmp_path: Path) -> Path:
    project = tmp_path / "fake_project"
    (project / "skills").mkdir(parents=True)
    (project / "agents").mkdir(parents=True)
    return project


def test_temp_workspace_creates_and_cleans(tmp_path: Path, fake_project_root: Path) -> None:
    """TempWorkspaceManager 在 tmp_path 下能 create / archive,目录隔离于真实 ~/.scrivai。"""
    from scrivai import TempWorkspaceManager, WorkspaceSpec

    mgr = TempWorkspaceManager(tmp_path)
    handle = mgr.create(WorkspaceSpec(run_id="t1", project_root=fake_project_root))

    assert handle.root_dir.is_relative_to(tmp_path)
    arch = mgr.archive(handle, success=True)
    assert arch.is_relative_to(tmp_path)


def test_temp_workspace_inherits_fcntl_lock(
    tmp_path: Path, fake_project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发 create 同 run_id 仍触发 lock(行为继承自父类)。"""
    from scrivai import TempWorkspaceManager, WorkspaceSpec
    from scrivai.exceptions import WorkspaceError
    from scrivai.workspace.manager import LocalWorkspaceManager

    mgr = TempWorkspaceManager(tmp_path)

    monkeypatch.setattr(
        LocalWorkspaceManager,
        "_acquire_lock",
        lambda self, run_id: (_ for _ in ()).throw(WorkspaceError(f"workspace {run_id} is locked")),
    )
    with pytest.raises(WorkspaceError, match="is locked"):
        mgr.create(WorkspaceSpec(run_id="t-lock", project_root=fake_project_root))


def test_fake_trajectory_inherits_schema() -> None:
    """FakeTrajectoryStore 与 TrajectoryStore 表结构完全一致(继承)。"""
    from scrivai import FakeTrajectoryStore
    from scrivai.trajectory.schema import ALL_TABLES

    store = FakeTrajectoryStore()
    conn = store._memory_conn
    assert conn is not None
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    for t in ALL_TABLES:
        assert t in names


def test_fake_trajectory_is_isolated() -> None:
    """两个 FakeTrajectoryStore 实例的数据互不可见(独立 :memory: conn)。"""
    import asyncio

    from scrivai import FakeTrajectoryStore

    s1 = FakeTrajectoryStore()
    s2 = FakeTrajectoryStore()

    asyncio.run(
        s1.start_run(
            run_id="iso-1",
            pes_name="x",
            model_name="m",
            provider="p",
            sdk_version="0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )

    assert asyncio.run(s1.get_run("iso-1")) is not None
    assert asyncio.run(s2.get_run("iso-1")) is None
