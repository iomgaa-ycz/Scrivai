"""TrajectoryRecorderHook — 订阅 9 个 hook 触点,sync 调 TrajectoryStore 落盘。

参考:
- docs/design.md §4.3
- docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scrivai.pes.hooks import hookimpl

if TYPE_CHECKING:
    from scrivai.models.pes import (
        CancelHookContext,
        FailureHookContext,
        OutputHookContext,
        PhaseHookContext,
        PromptTurnHookContext,
        RunHookContext,
    )
    from scrivai.trajectory.store import TrajectoryStore


class TrajectoryRecorderHook:
    """订阅全部 9 个 hook,sync 调 TrajectoryStore 落盘。"""

    def __init__(self, store: TrajectoryStore) -> None:
        self._store = store
        self._phase_ids: dict[str, int] = {}

    @hookimpl
    def before_run(self, context: RunHookContext) -> None:
        """写 runs 表新行。"""
        run = context.run
        self._store.start_run(
            run_id=run.run_id,
            pes_name=run.pes_name,
            model_name=run.model_name,
            provider=run.provider,
            sdk_version=run.sdk_version,
            skills_git_hash=run.skills_git_hash,
            agents_git_hash=run.agents_git_hash,
            skills_is_dirty=run.skills_is_dirty,
            task_prompt=run.task_prompt,
            runtime_context=None,
        )

    @hookimpl
    def before_phase(self, context: PhaseHookContext) -> None:
        """插入 phases 行,记录 phase_id。"""
        key = f"{context.run.run_id}:{context.phase}:{context.attempt_no}"
        phase_id = self._store.record_phase_start(
            run_id=context.run.run_id,
            phase_name=context.phase,
            phase_order=["plan", "execute", "summarize"].index(context.phase),
            attempt_no=context.attempt_no,
        )
        self._phase_ids[key] = phase_id

    @hookimpl
    def before_prompt(self, context: object) -> None:
        """占位;prompt 信息在 phase_end 一起写。"""

    @hookimpl
    def after_prompt_turn(self, context: PromptTurnHookContext) -> None:
        """逐 turn 写 turns 表 + tool_calls 表。"""
        key = f"{context.run.run_id}:{context.phase}:{context.attempt_no}"
        phase_id = self._phase_ids.get(key)
        if phase_id is None:
            return
        turn = context.turn
        turn_id = self._store.record_turn(
            phase_id=phase_id,
            turn_index=turn.turn_index,
            role=turn.role,
            content_type=turn.content_type,
            data=turn.data,
        )
        if turn.content_type == "tool_use":
            self._store.record_tool_call(
                turn_id=turn_id,
                tool_name=turn.data.get("name", ""),
                tool_input=turn.data.get("input"),
                tool_output=None,
                status="started",
                duration_ms=None,
            )
        elif turn.content_type == "tool_result":
            self._store.record_tool_call(
                turn_id=turn_id,
                tool_name=turn.data.get("name", ""),
                tool_input=None,
                tool_output=turn.data.get("content"),
                status="completed",
                duration_ms=None,
            )

    @hookimpl
    def after_phase(self, context: PhaseHookContext) -> None:
        """phase 成功时写 phase_end。"""
        self._record_phase_end(
            context.run.run_id, context.phase, context.attempt_no, context.phase_result
        )

    @hookimpl
    def on_phase_failed(self, context: FailureHookContext) -> None:
        """phase 失败时也写 phase_end。"""
        self._record_phase_end(
            context.run.run_id, context.phase, context.attempt_no, context.phase_result
        )

    @hookimpl
    def on_output_written(self, context: OutputHookContext) -> None:
        """占位。"""

    @hookimpl
    def on_run_cancelled(self, context: CancelHookContext) -> None:
        """占位;_persist_final_state 由 BasePES 直接调。"""

    @hookimpl
    def after_run(self, context: RunHookContext) -> None:
        """占位;_persist_final_state 由 BasePES 直接调。"""

    def _record_phase_end(self, run_id: str, phase: str, attempt_no: int, result: object) -> None:
        """共享的 record_phase_end 逻辑。"""
        key = f"{run_id}:{phase}:{attempt_no}"
        phase_id = self._phase_ids.get(key)
        if phase_id is None or result is None:
            return
        from scrivai.models.pes import PhaseResult

        if not isinstance(result, PhaseResult):
            return
        self._store.record_phase_end(
            phase_id=phase_id,
            prompt=result.prompt,
            response_text=result.response_text,
            produced_files=result.produced_files,
            usage=result.usage,
            error=result.error,
            error_type=result.error_type,
            is_retryable=result.is_retryable,
        )
