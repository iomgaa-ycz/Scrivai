"""Scrivai v3 — Claude Agent 编排框架。

完整 Public API(M0.75 冻结):参考 docs/design.md §4.1。
M2 Evolution API:参考 docs/superpowers/specs/2026-04-17-scrivai-m2-design.md。
"""

# qmd re-export(身份相等,非副本)
from qmd import ChunkRef, CollectionInfo, SearchResult

# 预置 PES(M0.75 占位,M1 实现)
from scrivai.agents import AuditorPES, ExtractorPES, GeneratorPES

# Evolution(M2 自研 Skill 进化)
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

# PES 核心
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

# Workspace 工厂
from scrivai.workspace.manager import build_workspace_manager

__all__ = [
    # PES 数据模型
    "PESRun",
    "PESConfig",
    "PhaseConfig",
    "PhaseResult",
    "PhaseTurn",
    "ModelConfig",
    # 9 个 HookContext
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
    # 抽象类
    "BasePES",
    "HookManager",
    # 预置 PES
    "ExtractorPES",
    "AuditorPES",
    "GeneratorPES",
    # 工厂
    "build_workspace_manager",
    "build_qmd_client_from_config",
    "build_libraries",
    "load_pes_config",
    # 知识库
    "RuleLibrary",
    "CaseLibrary",
    "TemplateLibrary",
    # 轨迹
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
    # Hook 装饰器
    "hookimpl",
    # Evolution(M2)
    "run_evolution",
    "promote",
    "CandidateEvaluator",
    "EvolutionTrigger",
    "LLMCallBudget",
    "Proposer",
    "SkillVersionStore",
    # Evolution 数据模型
    "EvolutionProposal",
    "EvolutionRunConfig",
    "EvolutionRunRecord",
    "EvolutionScore",
    "FailureSample",
    "SkillVersion",
]
