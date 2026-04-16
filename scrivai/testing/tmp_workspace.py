"""TempWorkspaceManager — 测试用的 tmp-rooted LocalWorkspaceManager。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.4。
"""

from __future__ import annotations

from pathlib import Path

from scrivai.workspace.manager import LocalWorkspaceManager


class TempWorkspaceManager(LocalWorkspaceManager):
    """把真实 LocalWorkspaceManager 的 root 锚到 tmp 目录。

    所有真行为(fcntl 锁 / shutil.copytree / tar.gz 归档)继承自父类,
    只是 workspaces_root / archives_root 都在 tmp 内,测试隔离。

    用法(pytest):
        @pytest.fixture
        def ws_mgr(tmp_path):
            return TempWorkspaceManager(tmp_path)
    """

    def __init__(self, tmp_root: Path) -> None:
        super().__init__(
            workspaces_root=tmp_root / "workspaces",
            archives_root=tmp_root / "archives",
        )
