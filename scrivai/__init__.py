"""Scrivai public API — all importable symbols for the framework.

Full public API (frozen at M0.75): see docs/design.md §4.1.
Evolution API (M2): see docs/superpowers/specs/2026-04-17-scrivai-m2-design.md.
"""

from importlib import metadata as _metadata

try:
    __version__: str = _metadata.version("scrivai")
except _metadata.PackageNotFoundError:  # not installed (editable checkout)
    __version__ = "0.1.5"

# qmd re-export (identity re-export, not a copy)
from qmd import ChunkRef, CollectionInfo, SearchResult

# Built-in PES agents (M0.75 placeholder, M1 implementation)
from scrivai.agents import AuditorPES, ExtractorPES, GeneratorPES

# Evolution (M2 self-improving skill evolution)
from scrivai.evolution import (
    CandidateEvaluator,
    EvolutionTrigger,
    LLMCallBudget,
    Proposer,
    SkillVersionStore,
    promote,
    run_evolution,
)

# IO
from scrivai.io import (
    DocxRenderer,
    doc_to_markdown,
    docx_to_markdown,
    pdf_to_markdown,
)

# Knowledge Libraries
from scrivai.knowledge import (
    CaseLibrary,
    RuleLibrary,
    TemplateLibrary,
    build_libraries,
    build_qmd_client_from_config,
)
from scrivai.models.evolution import (
    EvolutionProposal,
    EvolutionRunConfig,
    EvolutionRunRecord,
    EvolutionScore,
    FailureSample,
    SkillVersion,
)

# Models — pydantic
from scrivai.models.knowledge import Library, LibraryEntry
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

# PES core
from scrivai.pes.base import BasePES
from scrivai.pes.config import load_pes_config
from scrivai.pes.hooks import HookManager, hookimpl
from scrivai.pes.phase_log import PhaseLogHook

# Testing helpers re-export
from scrivai.testing import (
    FakeTrajectoryStore,
    MockPES,
    PhaseOutcome,
    TempWorkspaceManager,
)

# Trajectory
from scrivai.trajectory.hooks import TrajectoryRecorderHook
from scrivai.trajectory.store import TrajectoryStore

# Utils
from scrivai.utils import relaxed_json_loads

# Workspace factory
from scrivai.workspace.manager import build_workspace_manager

__all__ = [
    # PES data models
    "PESRun",
    "PESConfig",
    "PhaseConfig",
    "PhaseResult",
    "PhaseTurn",
    "ModelConfig",
    # 9 HookContext types
    "HookContext",
    "RunHookContext",
    "PhaseHookContext",
    "PromptHookContext",
    "PromptTurnHookContext",
    "FailureHookContext",
    "OutputHookContext",
    "CancelHookContext",
    # Workspace
    "WorkspaceSpec",
    "WorkspaceSnapshot",
    "WorkspaceHandle",
    "WorkspaceManager",
    # Knowledge
    "LibraryEntry",
    "Library",
    # Trajectory
    "TrajectoryRecord",
    "PhaseRecord",
    "FeedbackRecord",
    # Abstract base
    "BasePES",
    "HookManager",
    # Built-in PES agents
    "ExtractorPES",
    "AuditorPES",
    "GeneratorPES",
    # Factories
    "build_workspace_manager",
    "build_qmd_client_from_config",
    "build_libraries",
    "load_pes_config",
    # Knowledge libraries
    "RuleLibrary",
    "CaseLibrary",
    "TemplateLibrary",
    # Trajectory
    "TrajectoryStore",
    "TrajectoryRecorderHook",
    "PhaseLogHook",
    # IO
    "docx_to_markdown",
    "doc_to_markdown",
    "pdf_to_markdown",
    "DocxRenderer",
    # qmd re-export
    "ChunkRef",
    "SearchResult",
    "CollectionInfo",
    # Testing re-export
    "MockPES",
    "TempWorkspaceManager",
    "FakeTrajectoryStore",
    "PhaseOutcome",
    # Utils
    "relaxed_json_loads",
    # Hook decorator
    "hookimpl",
    # Evolution(M2)
    "run_evolution",
    "promote",
    "CandidateEvaluator",
    "EvolutionTrigger",
    "LLMCallBudget",
    "Proposer",
    "SkillVersionStore",
    # Evolution data models
    "EvolutionProposal",
    "EvolutionRunConfig",
    "EvolutionRunRecord",
    "EvolutionScore",
    "FailureSample",
    "SkillVersion",
]
