"""scrivai.testing.contract — pytest plugin 提供下游可复用的 fixtures。

下游通过 `pytest --pyargs scrivai.testing.contract` 即可跑全套契约测试。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §7.1。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from scrivai.knowledge import CaseLibrary, RuleLibrary, TemplateLibrary
    from scrivai.workspace.manager import LocalWorkspaceManager


@pytest.fixture
def scrivai_workspace_manager(tmp_path: Path) -> "LocalWorkspaceManager":
    """tmp_path 锚定的 LocalWorkspaceManager。"""
    from scrivai import build_workspace_manager

    return build_workspace_manager(
        workspaces_root=tmp_path / "ws",
        archives_root=tmp_path / "archives",
    )


@pytest.fixture
def scrivai_qmd_client(tmp_path: Path):
    """tmp_path 锚定的 qmd client。"""
    from scrivai.knowledge import build_qmd_client_from_config

    return build_qmd_client_from_config(tmp_path / "qmd.db")


@pytest.fixture
def scrivai_libraries(
    scrivai_qmd_client,
) -> "tuple[RuleLibrary, CaseLibrary, TemplateLibrary]":
    """三兄弟 Library。"""
    from scrivai.knowledge import build_libraries

    return build_libraries(scrivai_qmd_client)


@pytest.fixture
def scrivai_trajectory_store(tmp_path: Path):
    """tmp_path 锚定的 TrajectoryStore。"""
    from scrivai import TrajectoryStore

    return TrajectoryStore(tmp_path / "traj.db")
