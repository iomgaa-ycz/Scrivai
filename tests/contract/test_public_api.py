"""M0.75 T0.1 contract test:from scrivai import * 严格对齐 design.md §4.1。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §7.3。
"""

from __future__ import annotations

import pytest

# design.md §4.1 顶层 import 清单
EXPECTED_PUBLIC_API = {
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
    # Knowledge
    "LibraryEntry",
    # Trajectory
    "TrajectoryRecord",
    "PhaseRecord",
    "FeedbackRecord",
    # Evolution
    "EvolutionConfig",
    "EvolutionRun",
    "FeedbackExample",
    # Protocol
    "Library",
    "WorkspaceManager",
    "Evaluator",
    "SkillsRootResolver",
    # 抽象类
    "BasePES",
    "HookManager",
    # 预置 PES (占位)
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
    "EvolutionTrigger",
    "run_evolution",
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
    # Hook 装饰器
    "hookimpl",
    # MockPES 配套
    "PhaseOutcome",
}


def test_import_surface() -> None:
    """from scrivai import * 严格对齐 EXPECTED_PUBLIC_API。"""
    import scrivai

    actual = set(scrivai.__all__)
    missing = EXPECTED_PUBLIC_API - actual
    extra = actual - EXPECTED_PUBLIC_API

    assert not missing, f"scrivai.__all__ 缺符号:{sorted(missing)}"
    assert not extra, f"scrivai.__all__ 多余符号:{sorted(extra)}"


def test_all_symbols_actually_importable() -> None:
    """__all__ 列出的每个符号都必须能被实际访问。"""
    import scrivai

    for sym in scrivai.__all__:
        assert hasattr(scrivai, sym), f"scrivai.__all__ 列了 {sym} 但 attr 不存在"


@pytest.mark.parametrize("preset_name", ["ExtractorPES", "AuditorPES", "GeneratorPES"])
def test_preset_pes_placeholder(preset_name: str) -> None:
    """三个预置 PES 在 M0.75 实例化必须抛 NotImplementedError(M1 实现)。"""
    import scrivai

    cls = getattr(scrivai, preset_name)
    with pytest.raises(NotImplementedError, match="M1"):
        cls()


def test_star_import_only_yields_all() -> None:
    """from scrivai import * 后 dir() 含 __all__ 全部符号。"""
    namespace: dict = {}
    exec("from scrivai import *", namespace)  # noqa: S102
    namespace.pop("__builtins__", None)
    import scrivai

    for sym in scrivai.__all__:
        assert sym in namespace, f"星号导入丢失符号:{sym}"
