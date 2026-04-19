"""TempWorkspaceManager — tmp-rooted LocalWorkspaceManager for tests.

Reference: docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.4.
"""

from __future__ import annotations

from pathlib import Path

from scrivai.workspace.manager import LocalWorkspaceManager


class TempWorkspaceManager(LocalWorkspaceManager):
    """Anchor a real LocalWorkspaceManager's root under a tmp directory.

    All real behaviour (fcntl locking, shutil.copytree, tar.gz archiving) is
    inherited from the parent class; only workspaces_root and archives_root are
    redirected inside tmp for test isolation.

    Usage (pytest)::

        @pytest.fixture
        def ws_mgr(tmp_path):
            return TempWorkspaceManager(tmp_path)
    """

    def __init__(self, tmp_root: Path) -> None:
        super().__init__(
            workspaces_root=tmp_root / "workspaces",
            archives_root=tmp_root / "archives",
        )
