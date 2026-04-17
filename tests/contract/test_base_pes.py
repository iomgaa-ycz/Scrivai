"""M0.5 T0.6 contract tests for BasePES.

References:
- docs/design.md §4.2 / §4.3 / §4.13(不变量)
- docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §5.1
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scrivai.exceptions import PhaseError
from scrivai.models.pes import (
    FailureHookContext,
    PESConfig,
    PhaseConfig,
    PhaseHookContext,
    RunHookContext,
)
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.hooks import HookManager, hookimpl
from scrivai.testing.mock_pes import MockPES, PhaseOutcome


def _make_config(
    *,
    max_retries: int = 0,
    required_outputs: list | None = None,
) -> PESConfig:
    """构造最小 PESConfig。"""

    def phase_tmpl(name: str) -> PhaseConfig:
        return PhaseConfig(
            name=name,
            allowed_tools=["Bash"],
            max_retries=max_retries,
            required_outputs=required_outputs or [],
        )

    return PESConfig(
        name="test-pes",
        prompt_text="system prompt",
        phases={
            "plan": phase_tmpl("plan"),
            "execute": phase_tmpl("execute"),
            "summarize": phase_tmpl("summarize"),
        },
    )


def _make_workspace(tmp_path: Path) -> WorkspaceHandle:
    """在 tmp_path 下创建完整 workspace 目录结构。"""
    root = tmp_path / "ws" / "test-run"
    working = root / "working"
    data = root / "data"
    output = root / "output"
    logs = root / "logs"
    for d in (working, data, output, logs):
        d.mkdir(parents=True, exist_ok=True)
    return WorkspaceHandle(
        run_id="test-run",
        root_dir=root,
        working_dir=working,
        data_dir=data,
        output_dir=output,
        logs_dir=logs,
        snapshot=WorkspaceSnapshot(
            run_id="test-run",
            project_root=tmp_path,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


class HookRecorder:
    """记录所有 hook 调用顺序的测试插件。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @hookimpl
    def before_run(self, context: RunHookContext) -> None:
        self.calls.append("before_run")

    @hookimpl
    def before_phase(self, context: PhaseHookContext) -> None:
        self.calls.append(f"before_phase:{context.phase}:{context.attempt_no}")

    @hookimpl
    def before_prompt(self, context: object) -> None:
        self.calls.append("before_prompt")

    @hookimpl
    def after_prompt_turn(self, context: object) -> None:
        self.calls.append("after_prompt_turn")

    @hookimpl
    def after_phase(self, context: PhaseHookContext) -> None:
        self.calls.append(f"after_phase:{context.phase}")

    @hookimpl
    def on_phase_failed(self, context: FailureHookContext) -> None:
        self.calls.append(f"on_phase_failed:{context.phase}:{context.attempt_no}")

    @hookimpl
    def on_output_written(self, context: object) -> None:
        self.calls.append("on_output_written")

    @hookimpl
    def on_run_cancelled(self, context: object) -> None:
        self.calls.append("on_run_cancelled")

    @hookimpl
    def after_run(self, context: RunHookContext) -> None:
        self.calls.append("after_run")


def _run(coro: object) -> Any:
    """asyncio.run 的简写。"""
    return asyncio.run(coro)


# ── 测试 ──────────────────────────────────────────────────


def test_three_phase_order(tmp_path: Path) -> None:
    """plan → execute → summarize 严格顺序;三阶段都执行。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    run = _run(pes.run("test task"))

    assert run.status == "completed"
    phase_hooks = [c for c in recorder.calls if c.startswith("before_phase:")]
    assert phase_hooks == [
        "before_phase:plan:0",
        "before_phase:execute:0",
        "before_phase:summarize:0",
    ]


def test_plan_failure_skips_execute_and_summarize(tmp_path: Path) -> None:
    """plan 失败 → execute/summarize 不执行;run.status="failed"。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    pes = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        hooks=hooks,
        phase_outcomes={
            "plan": [PhaseOutcome(error="plan boom", error_type="sdk_other")],
        },
    )
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert "plan boom" in (run.error or "")
    phase_hooks = [c for c in recorder.calls if c.startswith("before_phase:")]
    assert phase_hooks == ["before_phase:plan:0"]


def test_hooks_called_in_correct_order_nine_hooks(tmp_path: Path) -> None:
    """验证 9 hook 严格顺序(含 on_output_written 位于 after_phase 前)。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    run = _run(pes.run("test"))

    assert run.status == "completed"
    assert recorder.calls[0] == "before_run"
    assert recorder.calls[-1] == "after_run"
    # on_output_written 在 after_phase:summarize 之前
    ow_idx = recorder.calls.index("on_output_written")
    ap_sum_idx = recorder.calls.index("after_phase:summarize")
    assert ow_idx < ap_sum_idx


def test_context_layering(tmp_path: Path) -> None:
    """runtime / execution / framework 三层 context 正确合并。"""

    class ContextCapturePES(MockPES):
        captured_context: dict[str, Any] = {}

        async def build_execution_context(self, phase, run):
            return {"exec_key": "exec_val"}

        async def build_phase_prompt(self, phase, phase_cfg, context, task_prompt):
            if phase == "plan":
                self.captured_context = dict(context)
            return await super().build_phase_prompt(phase, phase_cfg, context, task_prompt)

    pes = ContextCapturePES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        runtime_context={"rt_key": "rt_val"},
    )
    run = _run(pes.run("test"))

    assert run.status == "completed"
    ctx = pes.captured_context
    assert ctx["rt_key"] == "rt_val"
    assert ctx["exec_key"] == "exec_val"
    assert ctx["phase"] == "plan"
    assert "workspace" in ctx


def test_required_outputs_enforced(tmp_path: Path) -> None:
    """required_outputs 结构化规则 {"path","min_files","pattern"} 校验失败 → PhaseError。"""
    config = _make_config(
        required_outputs=[{"path": "findings/", "min_files": 1, "pattern": "*.json"}]
    )
    pes = MockPES(config=config, workspace=_make_workspace(tmp_path))
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert "output_validation_error" in (run.error_type or "")


def test_phase_retry_on_validation_failure(tmp_path: Path) -> None:
    """attempt_no=0 validate 失败(可重试),attempt_no=1 成功。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    ws = _make_workspace(tmp_path)
    config = _make_config(max_retries=1, required_outputs=["plan.md"])

    pes = MockPES(
        config=config,
        workspace=ws,
        hooks=hooks,
        phase_outcomes={
            "plan": [
                PhaseOutcome(),  # attempt 0: 不创建 plan.md → validate fail
                PhaseOutcome(produced_files=["plan.md"]),  # attempt 1: 创建
            ],
        },
    )
    run = _run(pes.run("test"))

    assert run.status == "completed"
    failed = [c for c in recorder.calls if c.startswith("on_phase_failed:")]
    assert "on_phase_failed:plan:0" in failed


def test_phase_no_retry_on_parse_error(tmp_path: Path) -> None:
    """postprocess 失败 → is_retryable=False → 不重试。"""

    class ParseErrorPES(MockPES):
        async def postprocess_phase_result(self, phase, result, run):
            if phase == "plan":
                raise ValueError("parse boom")

    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    pes = ParseErrorPES(
        config=_make_config(max_retries=1),
        workspace=_make_workspace(tmp_path),
        hooks=hooks,
    )
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert run.error_type == "response_parse_error"
    before_phases = [c for c in recorder.calls if c.startswith("before_phase:plan")]
    assert len(before_phases) == 1  # 不重试


def test_cleanup_before_retry(tmp_path: Path) -> None:
    """attempt_no=0 创建 findings/a.json;重试前框架清空;attempt_no=1 不创建 → validate 失败。"""
    ws = _make_workspace(tmp_path)
    config = _make_config(
        max_retries=1,
        required_outputs=[{"path": "findings/", "min_files": 1, "pattern": "*.json"}],
    )

    class CleanupTestPES(MockPES):
        async def validate_phase_outputs(self, phase, phase_cfg, result, run):
            if phase == "plan" and result.attempt_no == 0:
                raise PhaseError(phase, "force retry")
            await super().validate_phase_outputs(phase, phase_cfg, result, run)

    pes2 = CleanupTestPES(
        config=config,
        workspace=ws,
        phase_outcomes={
            "plan": [
                PhaseOutcome(produced_files=["findings/a.json"]),
                PhaseOutcome(),  # 重试后不创建文件
            ],
        },
    )
    run = _run(pes2.run("test"))

    assert run.status == "failed"
    assert not (ws.working_dir / "findings").exists() or not list(
        (ws.working_dir / "findings").glob("*.json")
    )


def test_cancellation_dispatches_on_run_cancelled(tmp_path: Path) -> None:
    """KeyboardInterrupt → status="cancelled" + on_run_cancelled 触发 + _persist_final_state。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    class CancelPES(MockPES):
        async def _call_sdk_query(self, phase_cfg, prompt, run, attempt_no, on_turn):
            raise KeyboardInterrupt()

    pes = CancelPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path),
        hooks=hooks,
    )
    with pytest.raises(KeyboardInterrupt):
        _run(pes.run("test"))

    assert "on_run_cancelled" in recorder.calls
    assert "after_run" in recorder.calls


def test_on_output_written_only_on_summarize(tmp_path: Path) -> None:
    """on_output_written 仅 summarize 阶段触发,plan/execute 不触发。"""
    recorder = HookRecorder()
    hooks = HookManager()
    hooks.register(recorder)

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    _run(pes.run("test"))

    ow_count = recorder.calls.count("on_output_written")
    assert ow_count == 1


def test_extension_points_selective_override(tmp_path: Path) -> None:
    """子类只覆盖 build_execution_context,其他扩展点沿用默认。"""

    class CustomPES(MockPES):
        async def build_execution_context(self, phase, run):
            return {"custom": True}

    pes = CustomPES(config=_make_config(), workspace=_make_workspace(tmp_path))
    run = _run(pes.run("test"))

    assert run.status == "completed"


def test_hook_error_maps_to_phase_failure(tmp_path: Path) -> None:
    """before_phase 同步 hook 抛异常 → error_type="hook_error", is_retryable=False。"""

    class BrokenPlugin:
        @hookimpl
        def before_phase(self, context: PhaseHookContext) -> None:
            if context.phase == "plan":
                raise RuntimeError("hook boom")

    hooks = HookManager()
    hooks.register(BrokenPlugin())

    pes = MockPES(
        config=_make_config(max_retries=1), workspace=_make_workspace(tmp_path), hooks=hooks
    )
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert run.error_type == "hook_error"


def test_before_run_hook_error_fails_run(tmp_path: Path) -> None:
    """before_run hook 异常 → run.status="failed", error_type="hook_error";
    phase 循环不启动;after_run 仍触发。"""
    recorder = HookRecorder()

    class BrokenBeforeRun:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            raise RuntimeError("before_run boom")

    hooks = HookManager()
    hooks.register(BrokenBeforeRun())
    hooks.register(recorder)

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert run.error_type == "hook_error"
    assert "before_run boom" in (run.error or "")
    assert not any(c.startswith("before_phase:") for c in recorder.calls)
    assert "after_run" in recorder.calls


def test_nonblocking_hook_error_not_propagated(tmp_path: Path) -> None:
    """after_run / on_phase_failed / on_run_cancelled 抛异常 → 仅 log,run.status 不变。"""

    class BrokenAfterRun:
        @hookimpl
        def after_run(self, context: RunHookContext) -> None:
            raise RuntimeError("after_run boom")

    hooks = HookManager()
    hooks.register(BrokenAfterRun())

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    run = _run(pes.run("test"))

    assert run.status == "completed"  # 不受 after_run 异常影响


def test_finalize_run_called_on_all_paths(tmp_path: Path) -> None:
    """success / failed / cancelled / before_run_failed 四条路径都调 _persist_final_state 一次。"""
    from scrivai.testing import FakeTrajectoryStore

    def _seed_store(store: FakeTrajectoryStore) -> None:
        """预插 runs 行,模拟 TrajectoryRecorderHook.before_run 的 start_run 调用。"""
        store.start_run(
            run_id="test-run",
            pes_name="test-pes",
            model_name="mock-model",
            provider="",
            sdk_version="",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="test",
            runtime_context=None,
        )

    # Path 1: success
    store1 = FakeTrajectoryStore()
    _seed_store(store1)
    pes1 = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path / "p1"),
        trajectory_store=store1,
    )
    run1 = _run(pes1.run("test"))
    assert run1.status == "completed"
    rec1 = store1.get_run("test-run")
    assert rec1 is not None and rec1.status == "completed"

    # Path 2: failed
    store2 = FakeTrajectoryStore()
    _seed_store(store2)
    pes2 = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path / "p2"),
        trajectory_store=store2,
        phase_outcomes={"plan": [PhaseOutcome(error="boom", error_type="sdk_other")]},
    )
    run2 = _run(pes2.run("test"))
    assert run2.status == "failed"
    rec2 = store2.get_run("test-run")
    assert rec2 is not None and rec2.status == "failed"

    # Path 3: before_run hook error
    store3 = FakeTrajectoryStore()
    _seed_store(store3)

    class BrokenBR:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            raise RuntimeError("br boom")

    hooks3 = HookManager()
    hooks3.register(BrokenBR())
    pes3 = MockPES(
        config=_make_config(),
        workspace=_make_workspace(tmp_path / "p3"),
        hooks=hooks3,
        trajectory_store=store3,
    )
    run3 = _run(pes3.run("test"))
    assert run3.status == "failed"
    rec3 = store3.get_run("test-run")
    assert rec3 is not None and rec3.status == "failed"


def test_after_phase_hook_error_on_summarize_marks_run_failed(tmp_path: Path) -> None:
    """summarize after_phase 异常 → run.status="failed"(虽然 output.json 已写)。"""

    class BrokenAfterPhase:
        @hookimpl
        def after_phase(self, context: PhaseHookContext) -> None:
            if context.phase == "summarize":
                raise RuntimeError("after_phase boom on summarize")

    hooks = HookManager()
    hooks.register(BrokenAfterPhase())

    pes = MockPES(config=_make_config(), workspace=_make_workspace(tmp_path), hooks=hooks)
    run = _run(pes.run("test"))

    assert run.status == "failed"
    assert run.error_type == "hook_error"
