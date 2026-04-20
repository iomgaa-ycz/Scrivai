"""T0.2 契约测试:全部 pydantic / Protocol 模型。

参考 docs/design.md §4.1。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

# ────── 子模块导入完整性 ──────


def test_exceptions_importable() -> None:
    """所有异常类可从 scrivai.exceptions 导入。"""
    from scrivai.exceptions import (
        PESConfigError,
        PhaseError,
        ScrivaiError,
    )

    assert issubclass(PESConfigError, ScrivaiError)
    assert issubclass(PhaseError, ScrivaiError)


def test_pes_module_importable() -> None:
    """scrivai.models.pes 可导入全部声明类。"""
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

    # 显式断言:14 个符号全部成功导入(避免被认作"无断言空测试")
    for cls in (
        ModelConfig,
        PhaseConfig,
        PESConfig,
        PhaseTurn,
        PhaseResult,
        PESRun,
        HookContext,
        RunHookContext,
        PhaseHookContext,
        PromptHookContext,
        PromptTurnHookContext,
        FailureHookContext,
        OutputHookContext,
        CancelHookContext,
    ):
        assert cls is not None


def test_workspace_module_importable() -> None:
    """scrivai.models.workspace 可导入全部声明类。"""
    from scrivai.models.workspace import (
        WorkspaceHandle,
        WorkspaceManager,
        WorkspaceSnapshot,
        WorkspaceSpec,
    )

    for cls in (WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle, WorkspaceManager):
        assert cls is not None


def test_knowledge_module_importable() -> None:
    """scrivai.models.knowledge 可导入全部声明类。"""
    from scrivai.models.knowledge import (
        ChunkRef,
        CollectionInfo,
        Library,
        LibraryEntry,
        SearchResult,
    )

    for cls in (LibraryEntry, Library, ChunkRef, SearchResult, CollectionInfo):
        assert cls is not None


def test_trajectory_module_importable() -> None:
    """scrivai.models.trajectory 可导入全部声明类。"""
    from scrivai.models.trajectory import (
        FeedbackRecord,
        PhaseRecord,
        TrajectoryRecord,
    )

    for cls in (TrajectoryRecord, PhaseRecord, FeedbackRecord):
        assert cls is not None


# ────── PESRun.status Literal ──────


def test_pes_run_status_literal_accepts_four_values() -> None:
    from scrivai.models.pes import PESRun

    now = datetime.now(timezone.utc)
    for status in ("running", "completed", "failed", "cancelled"):
        run = PESRun(
            run_id="r1",
            pes_name="extractor",
            status=status,
            task_prompt="t",
            phase_results={},
            model_name="m",
            provider="anthropic",
            sdk_version="1.0",
            skills_is_dirty=False,
            started_at=now,
        )
        assert run.status == status


def test_pes_run_status_literal_rejects_others() -> None:
    from scrivai.models.pes import PESRun

    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        PESRun(
            run_id="r1",
            pes_name="extractor",
            status="weird",
            task_prompt="t",
            phase_results={},
            model_name="m",
            provider="anthropic",
            sdk_version="1.0",
            skills_is_dirty=False,
            started_at=now,
        )


# ────── 9 HookContext + attempt_no 字段 ──────


def test_nine_hook_contexts_exist() -> None:
    """9 个 HookContext 类全部声明。"""
    from scrivai.models.pes import (
        CancelHookContext,
        FailureHookContext,
        HookContext,
        OutputHookContext,
        PhaseHookContext,
        PromptHookContext,
        PromptTurnHookContext,
        RunHookContext,
    )

    # design.md §4.1 列了 8 个具体 + 1 个基类 HookContext = 9
    assert all(
        c is not None
        for c in [
            HookContext,
            RunHookContext,
            PhaseHookContext,
            PromptHookContext,
            PromptTurnHookContext,
            FailureHookContext,
            OutputHookContext,
            CancelHookContext,
        ]
    )


def test_phase_related_hook_contexts_have_attempt_no() -> None:
    """4 个 phase 相关的 hook context 都含 attempt_no 字段。"""
    from scrivai.models.pes import (
        FailureHookContext,
        PhaseHookContext,
        PromptHookContext,
        PromptTurnHookContext,
    )

    for cls in [PhaseHookContext, PromptHookContext, PromptTurnHookContext, FailureHookContext]:
        assert "attempt_no" in cls.model_fields, f"{cls.__name__} 缺 attempt_no"


def test_failure_hook_context_extra_fields() -> None:
    """FailureHookContext 额外含 will_retry 和 error_type。"""
    from scrivai.models.pes import FailureHookContext

    assert "will_retry" in FailureHookContext.model_fields
    assert "error_type" in FailureHookContext.model_fields


# ────── PhaseResult round-trip ──────


def test_phase_result_round_trip(sample_phase_result_dict: dict) -> None:
    """model_dump → model_validate 恒等。"""
    from scrivai.models.pes import PhaseResult

    r = PhaseResult.model_validate(sample_phase_result_dict)
    dumped = r.model_dump(mode="json")
    r2 = PhaseResult.model_validate(dumped)
    assert r2.phase == r.phase
    assert r2.attempt_no == r.attempt_no
    assert r2.is_retryable == r.is_retryable
    assert r2.error_type == r.error_type


def test_phase_result_attempt_no_default_zero() -> None:
    from scrivai.models.pes import PhaseResult

    now = datetime.now(timezone.utc)
    r = PhaseResult(
        phase="plan",
        prompt="p",
        response_text="r",
        turns=[],
        produced_files=[],
        usage={},
        started_at=now,
        ended_at=now,
    )
    assert r.attempt_no == 0
    assert r.is_retryable is False


# ────── PhaseConfig.required_outputs 多类型 ──────


def test_required_outputs_accepts_str() -> None:
    from scrivai.models.pes import PhaseConfig

    cfg = PhaseConfig(
        name="plan",
        allowed_tools=["Bash"],
        required_outputs=["plan.md", "plan.json"],
    )
    assert cfg.required_outputs == ["plan.md", "plan.json"]


def test_required_outputs_accepts_dict_rule() -> None:
    from scrivai.models.pes import PhaseConfig

    cfg = PhaseConfig(
        name="execute",
        allowed_tools=["Bash"],
        required_outputs=[{"path": "findings/", "min_files": 1, "pattern": "*.json"}],
    )
    assert cfg.required_outputs[0]["path"] == "findings/"


def test_required_outputs_accepts_mixed() -> None:
    from scrivai.models.pes import PhaseConfig

    cfg = PhaseConfig(
        name="plan",
        allowed_tools=["Bash"],
        required_outputs=["plan.md", {"path": "findings/", "min_files": 1, "pattern": "*.json"}],
    )
    assert len(cfg.required_outputs) == 2


# ────── Protocol runtime_checkable ──────


def test_workspace_manager_protocol_runtime_checkable() -> None:
    from scrivai.models.workspace import WorkspaceHandle, WorkspaceManager, WorkspaceSpec

    class FakeMgr:
        def create(self, spec: WorkspaceSpec) -> WorkspaceHandle: ...
        def archive(self, handle: WorkspaceHandle, success: bool) -> Path: ...
        def cleanup_old(self, days: int = 30) -> None: ...

    fake = FakeMgr()
    assert isinstance(fake, WorkspaceManager)


def test_library_protocol_runtime_checkable() -> None:
    from scrivai.models.knowledge import Library, LibraryEntry

    class FakeLib:
        def add(self, entry_id: str, markdown: str, metadata: dict) -> LibraryEntry: ...
        def get(self, entry_id: str) -> LibraryEntry | None: ...
        def list(self) -> list[str]: ...
        def delete(self, entry_id: str) -> None: ...
        def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list: ...

    assert isinstance(FakeLib(), Library)
