"""TrajectoryRecorderHook — subscribes to all 9 hook points and synchronously persists data via TrajectoryStore.

References:
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
    """Subscribes to all 9 hooks and synchronously persists data to TrajectoryStore."""

    def __init__(self, store: TrajectoryStore) -> None:
        self._store = store
        self._phase_ids: dict[str, int] = {}

    @hookimpl
    def before_run(self, context: RunHookContext) -> None:
        """Insert a new row into the runs table."""
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
        """Insert a phases row and record the resulting phase_id."""
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
        """No-op; prompt information is written together with phase_end."""

    @hookimpl
    def after_prompt_turn(self, context: PromptTurnHookContext) -> None:
        """Write each turn to the turns table and tool_calls table."""
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
        """Write phase_end when the phase succeeds."""
        self._record_phase_end(
            context.run.run_id, context.phase, context.attempt_no, context.phase_result
        )

    @hookimpl
    def on_phase_failed(self, context: FailureHookContext) -> None:
        """Write phase_end even when the phase fails."""
        self._record_phase_end(
            context.run.run_id, context.phase, context.attempt_no, context.phase_result
        )

    @hookimpl
    def on_output_written(self, context: OutputHookContext) -> None:
        """No-op."""

    @hookimpl
    def on_run_cancelled(self, context: CancelHookContext) -> None:
        """No-op; _persist_final_state is called directly by BasePES."""

    @hookimpl
    def after_run(self, context: RunHookContext) -> None:
        """No-op; _persist_final_state is called directly by BasePES."""

    def _record_phase_end(self, run_id: str, phase: str, attempt_no: int, result: object) -> None:
        """Shared logic for recording phase end data."""
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
