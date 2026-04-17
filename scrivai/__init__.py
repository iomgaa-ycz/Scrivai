"""Scrivai v3 — Claude Agent 编排框架(M0 / M0.25 / M0.5)。

完整 Public API 在 M0.75 冻结;本里程碑(M0.5)在 M0.25 基础上新增:
- BasePES(三阶段执行引擎抽象基类)
- MockPES / PhaseOutcome(测试替身)
- TrajectoryRecorderHook(自动轨迹落盘 hook)
- PhaseLogHook(phase 日志 dump hook)

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
from scrivai.pes.base import BasePES
from scrivai.pes.hooks import HookManager, hookimpl
from scrivai.pes.phase_log import PhaseLogHook
from scrivai.testing import FakeTrajectoryStore, MockPES, PhaseOutcome, TempWorkspaceManager
from scrivai.trajectory.hooks import TrajectoryRecorderHook
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
    # M0.5 T0.6 — BasePES
    "BasePES",
    # M0.5 T0.8 — Trajectory hooks
    "TrajectoryRecorderHook",
    "PhaseLogHook",
    # M0.5 T0.9 — MockPES
    "MockPES",
    "PhaseOutcome",
]
