"""scrivai.testing.contract — pytest plugin providing reusable fixtures for downstream projects.

Downstream consumers run the full contract test suite via
``pytest --pyargs scrivai.testing.contract``.

Reference: docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §7.1.
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
    """LocalWorkspaceManager rooted at tmp_path."""
    from scrivai import build_workspace_manager

    return build_workspace_manager(
        workspaces_root=tmp_path / "ws",
        archives_root=tmp_path / "archives",
    )


@pytest.fixture
def scrivai_qmd_client(tmp_path: Path):
    """qmd client rooted at tmp_path."""
    from scrivai.knowledge import build_qmd_client_from_config

    return build_qmd_client_from_config(tmp_path / "qmd.db")


@pytest.fixture
def scrivai_libraries(
    scrivai_qmd_client,
) -> "tuple[RuleLibrary, CaseLibrary, TemplateLibrary]":
    """The three sibling Library instances (Rule, Case, Template)."""
    from scrivai.knowledge import build_libraries

    return build_libraries(scrivai_qmd_client)


@pytest.fixture
def scrivai_trajectory_store(tmp_path: Path):
    """TrajectoryStore rooted at tmp_path."""
    from scrivai import TrajectoryStore

    return TrajectoryStore(tmp_path / "traj.db")
