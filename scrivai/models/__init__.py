"""Scrivai pydantic + Protocol data models (M0 single source of truth).

See docs/design.md §4.1 for the full list.
"""

from scrivai.models.knowledge import (
    ChunkRef,
    CollectionInfo,
    Library,
    LibraryEntry,
    SearchResult,
)
from scrivai.models.pes import (
    CancelHookContext,
    FailureHookContext,
    HookContext,
    ModelConfig,
    OutputHookContext,
    PESConfig,
    PESRun,
    PhaseConfig,
    PhaseHookContext,
    PhaseResult,
    PhaseTurn,
    PromptHookContext,
    PromptTurnHookContext,
    RunHookContext,
)
from scrivai.models.trajectory import (
    FeedbackRecord,
    PhaseRecord,
    TrajectoryRecord,
)
from scrivai.models.workspace import (
    WorkspaceHandle,
    WorkspaceManager,
    WorkspaceSnapshot,
    WorkspaceSpec,
)

__all__ = [
    # pes
    "ModelConfig",
    "PhaseConfig",
    "PESConfig",
    "PhaseTurn",
    "PhaseResult",
    "PESRun",
    "HookContext",
    "RunHookContext",
    "PhaseHookContext",
    "PromptHookContext",
    "PromptTurnHookContext",
    "FailureHookContext",
    "OutputHookContext",
    "CancelHookContext",
    # workspace
    "WorkspaceSpec",
    "WorkspaceSnapshot",
    "WorkspaceHandle",
    "WorkspaceManager",
    # knowledge
    "LibraryEntry",
    "Library",
    "ChunkRef",
    "SearchResult",
    "CollectionInfo",
    # trajectory
    "TrajectoryRecord",
    "PhaseRecord",
    "FeedbackRecord",
]
