"""Scrivai pydantic + Protocol 数据模型(M0 单一真相)。

完整列表参考 docs/design.md §4.1。
"""

from scrivai.models.evolution import (
    Evaluator,
    EvolutionConfig,
    EvolutionRun,
    FeedbackExample,
    SkillsRootResolver,
)
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
    # evolution
    "EvolutionConfig",
    "EvolutionRun",
    "FeedbackExample",
    "Evaluator",
    "SkillsRootResolver",
]
