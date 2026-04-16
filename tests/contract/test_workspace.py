"""M0.25 T0.4 contract tests for LocalWorkspaceManager.

References:
- docs/design.md §4.9 / §5.2
- docs/TD.md T0.4
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.1
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="fcntl 仅 POSIX (T0.4 DoD: Linux + macOS,Windows xfail)",
)


def test_factory_returns_workspace_manager_protocol(tmp_path: Path) -> None:
    """build_workspace_manager 返回的对象必须满足 WorkspaceManager Protocol。"""
    from scrivai import WorkspaceManager, build_workspace_manager

    mgr = build_workspace_manager(
        workspaces_root=tmp_path / "ws",
        archives_root=tmp_path / "archives",
    )
    assert isinstance(mgr, WorkspaceManager)
    assert (tmp_path / "ws").is_dir()
    assert (tmp_path / "archives").is_dir()


@pytest.fixture
def fake_project_root(tmp_path: Path) -> Path:
    """在 tmp 下伪造一个含 skills/ 与 agents/ 的项目根。"""
    project = tmp_path / "fake_project"
    (project / "skills" / "demo-skill").mkdir(parents=True)
    (project / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: a fake skill\n---\nbody.\n",
        encoding="utf-8",
    )
    (project / "agents").mkdir(parents=True)
    (project / "agents" / "fake.yaml").write_text("name: fake\n", encoding="utf-8")
    return project


@pytest.fixture
def ws_mgr(tmp_path: Path):
    """build_workspace_manager 实例,锚到 tmp。"""
    from scrivai import build_workspace_manager

    return build_workspace_manager(
        workspaces_root=tmp_path / "ws",
        archives_root=tmp_path / "archives",
    )


def test_create_directory_structure(ws_mgr, fake_project_root: Path, tmp_path: Path) -> None:
    """create 后:5 类目录全在,meta.json 写盘,WorkspaceHandle 字段正确。"""
    from scrivai import WorkspaceSpec

    data_src = tmp_path / "input.md"
    data_src.write_text("hello", encoding="utf-8")

    handle = ws_mgr.create(
        WorkspaceSpec(
            run_id="run-001",
            project_root=fake_project_root,
            data_inputs={"input.md": data_src},
            extra_env={"FOO": "bar"},
            force=False,
        )
    )

    root = handle.root_dir
    assert root.is_dir()
    assert handle.working_dir == root / "working"
    assert handle.data_dir == root / "data"
    assert handle.output_dir == root / "output"
    assert handle.logs_dir == root / "logs"
    for d in (handle.working_dir, handle.data_dir, handle.output_dir, handle.logs_dir):
        assert d.is_dir()
    assert (handle.working_dir / ".claude" / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert (handle.working_dir / ".claude" / "agents" / "fake.yaml").is_file()
    assert (handle.data_dir / "input.md").read_text(encoding="utf-8") == "hello"

    meta_path = root / "meta.json"
    assert meta_path.is_file()
    import json

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["run_id"] == "run-001"
    assert meta["extra_env"] == {"FOO": "bar"}
    assert "snapshot" in meta


def test_snapshot_preserves_skills(ws_mgr, fake_project_root: Path) -> None:
    """create 后修改 project_root/skills 不影响已创建的 workspace(快照独立)。"""
    from scrivai import WorkspaceSpec

    handle = ws_mgr.create(WorkspaceSpec(run_id="snap-test", project_root=fake_project_root))

    snapshot_skill = handle.working_dir / ".claude" / "skills" / "demo-skill" / "SKILL.md"
    assert "body." in snapshot_skill.read_text(encoding="utf-8")

    src_skill = fake_project_root / "skills" / "demo-skill" / "SKILL.md"
    src_skill.write_text("MUTATED.", encoding="utf-8")

    assert "body." in snapshot_skill.read_text(encoding="utf-8")
    assert "MUTATED." not in snapshot_skill.read_text(encoding="utf-8")


def test_force_recreate(ws_mgr, fake_project_root: Path) -> None:
    """force=False 重复 create 抛错;force=True 删除重建。"""
    from scrivai import WorkspaceSpec
    from scrivai.exceptions import WorkspaceError

    handle1 = ws_mgr.create(WorkspaceSpec(run_id="dup-run", project_root=fake_project_root))
    (handle1.working_dir / "marker.txt").write_text("first", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="workspace already exists"):
        ws_mgr.create(WorkspaceSpec(run_id="dup-run", project_root=fake_project_root, force=False))

    handle2 = ws_mgr.create(
        WorkspaceSpec(run_id="dup-run", project_root=fake_project_root, force=True)
    )
    assert not (handle2.working_dir / "marker.txt").exists()


def test_concurrent_create_rejected(ws_mgr, fake_project_root: Path, monkeypatch) -> None:
    """create() 把 _acquire_lock 抛出的 WorkspaceError 正确向上传播。

    单元层只测"WorkspaceError 传播路径";真实 fcntl 跨进程锁的覆盖
    见 ContractRunner integration smoke (M0.5+)。
    fcntl flock 在同一进程内部多次 acquire 不会阻塞(per-fd 而非 per-process),
    所以 same-process 真锁测试本身就不可行,需要走 multiprocessing/手动验证。
    """
    from scrivai import WorkspaceSpec
    from scrivai.exceptions import WorkspaceError
    from scrivai.workspace.manager import LocalWorkspaceManager

    monkeypatch.setattr(
        LocalWorkspaceManager,
        "_acquire_lock",
        lambda self, run_id: (_ for _ in ()).throw(WorkspaceError(f"workspace {run_id} is locked")),
    )
    with pytest.raises(WorkspaceError, match="is locked"):
        ws_mgr.create(WorkspaceSpec(run_id="lock-test", project_root=fake_project_root))


def test_archive_portability(ws_mgr, fake_project_root: Path, tmp_path: Path) -> None:
    """archive(success=True) 产出可移植 tar.gz;原目录消失;可在异地解压并读到完整内容。"""
    from scrivai import WorkspaceSpec

    handle = ws_mgr.create(WorkspaceSpec(run_id="arch-001", project_root=fake_project_root))
    (handle.output_dir / "report.txt").write_text("done", encoding="utf-8")
    (handle.logs_dir / "plan.json").write_text("{}", encoding="utf-8")

    archive_path = ws_mgr.archive(handle, success=True)

    assert archive_path.suffix == ".gz"
    assert archive_path.name == "arch-001.tar.gz"
    assert archive_path.is_file()
    assert not handle.root_dir.exists()  # 原目录已删

    # 异地解压验证
    extract_to = tmp_path / "extract"
    extract_to.mkdir()
    import tarfile

    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(extract_to)

    extracted_root = extract_to / "arch-001"
    assert (extracted_root / "working" / ".claude" / "skills" / "demo-skill" / "SKILL.md").is_file()
    assert (extracted_root / "output" / "report.txt").read_text(encoding="utf-8") == "done"
    assert (extracted_root / "logs" / "plan.json").is_file()
    assert (extracted_root / "meta.json").is_file()


def test_archive_failure_marker(ws_mgr, fake_project_root: Path) -> None:
    """archive(success=False) 不动目录,只写 .failed 标记。"""
    from scrivai import WorkspaceSpec

    handle = ws_mgr.create(WorkspaceSpec(run_id="fail-001", project_root=fake_project_root))

    marker = ws_mgr.archive(handle, success=False)

    assert handle.root_dir.is_dir()
    assert marker == handle.root_dir / ".failed"
    assert marker.is_file()
    assert (handle.working_dir / ".claude" / "skills" / "demo-skill" / "SKILL.md").is_file()


def test_cleanup_respects_mtime(ws_mgr, fake_project_root: Path, tmp_path: Path) -> None:
    """cleanup_old(30):同时清理 archives 与 .failed workspace,只删 mtime 超过 30 天的。"""
    import os
    import time

    from scrivai import WorkspaceSpec

    # 旧 archive(40 天前)
    h_old = ws_mgr.create(WorkspaceSpec(run_id="old-arch", project_root=fake_project_root))
    arch_old = ws_mgr.archive(h_old, success=True)
    old_ts = time.time() - 40 * 86400
    os.utime(arch_old, (old_ts, old_ts))

    # 新 archive(1 天前)
    h_new = ws_mgr.create(WorkspaceSpec(run_id="new-arch", project_root=fake_project_root))
    arch_new = ws_mgr.archive(h_new, success=True)
    new_ts = time.time() - 86400
    os.utime(arch_new, (new_ts, new_ts))

    # 旧失败 workspace(40 天前)
    h_old_fail = ws_mgr.create(WorkspaceSpec(run_id="old-fail", project_root=fake_project_root))
    ws_mgr.archive(h_old_fail, success=False)
    os.utime(h_old_fail.root_dir / ".failed", (old_ts, old_ts))
    os.utime(h_old_fail.root_dir, (old_ts, old_ts))

    # 新失败 workspace(1 天前)
    h_new_fail = ws_mgr.create(WorkspaceSpec(run_id="new-fail", project_root=fake_project_root))
    ws_mgr.archive(h_new_fail, success=False)

    ws_mgr.cleanup_old(days=30)

    assert not arch_old.exists()
    assert arch_new.exists()
    assert not h_old_fail.root_dir.exists()
    assert h_new_fail.root_dir.exists()
