"""Scrivai v3 — Claude Agent 编排框架(M0 / M0.25)。

完整 Public API 在 M0.75 冻结;本里程碑(M0.25)在 M0 5 个符号基础上新增 9 个:
- WorkspaceSpec / WorkspaceSnapshot / WorkspaceHandle / WorkspaceManager / build_workspace_manager
- HookManager / hookimpl(M0.25 T0.5 后填充)
- TrajectoryStore(M0.25 T0.7 后填充)
- TempWorkspaceManager / FakeTrajectoryStore(M0.25 T0.10 后填充)

参考 docs/design.md §4.1。
"""

from qmd import ChunkRef, CollectionInfo, SearchResult

from scrivai.evolution import EvolutionTrigger, run_evolution
from scrivai.models.workspace import (
    WorkspaceHandle,
    WorkspaceManager,
    WorkspaceSnapshot,
    WorkspaceSpec,
)
from scrivai.pes.hooks import HookManager, hookimpl
from scrivai.testing import FakeTrajectoryStore, TempWorkspaceManager
from scrivai.trajectory.store import TrajectoryStore
from scrivai.workspace.manager import build_workspace_manager

__all__ = [
    # qmd re-export
    "ChunkRef",
    "CollectionInfo",
    "SearchResult",
    # Evolution 占位
    "EvolutionTrigger",
    "run_evolution",
    # M0.25 T0.4 — Workspace
    "WorkspaceSpec",
    "WorkspaceSnapshot",
    "WorkspaceHandle",
    "WorkspaceManager",
    "build_workspace_manager",
    # M0.25 T0.5 — Hooks
    "HookManager",
    "hookimpl",
    # M0.25 T0.7 — Trajectory
    "TrajectoryStore",
    # M0.25 T0.10 — Testing helpers
    "FakeTrajectoryStore",
    "TempWorkspaceManager",
]
