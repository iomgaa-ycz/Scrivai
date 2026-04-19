"""MockPES — test double that replays pre-recorded PhaseOutcome objects.

Reference: docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from scrivai.exceptions import PhaseError
from scrivai.models.pes import (
    ModelConfig,
    PESConfig,
    PESRun,
    PhaseConfig,
    PhaseErrorType,
    PhaseResult,
    PhaseTurn,
)
from scrivai.models.workspace import WorkspaceHandle
from scrivai.pes.base import BasePES
from scrivai.pes.hooks import HookManager
from scrivai.trajectory.store import TrajectoryStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PhaseOutcome:
    """Pre-recorded result for a single phase attempt."""

    response_text: str = ""
    turns: list[PhaseTurn] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: PhaseErrorType | None = None
    is_retryable: bool = False
    produced_files: list[str] = field(default_factory=list)


class MockPES(BasePES):
    """Replays pre-recorded PhaseOutcome objects without depending on claude_agent_sdk."""

    def __init__(
        self,
        *,
        config: PESConfig,
        workspace: WorkspaceHandle,
        hooks: HookManager | None = None,
        trajectory_store: TrajectoryStore | None = None,
        runtime_context: dict[str, Any] | None = None,
        phase_outcomes: dict[str, list[PhaseOutcome]] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            model=ModelConfig(model="mock-model"),
            workspace=workspace,
            hooks=hooks,
            trajectory_store=trajectory_store,
            runtime_context=runtime_context,
        )
        self._outcomes = phase_outcomes or {}

    async def _call_sdk_query(
        self,
        phase_cfg: PhaseConfig,
        prompt: str,
        run: PESRun,
        attempt_no: int,
        on_turn: Callable[[PhaseTurn], None],
    ) -> tuple[str, dict[str, Any], list[PhaseTurn]]:
        """Replay a PhaseOutcome; raise PhaseError if the outcome contains an error."""
        outcomes = self._outcomes.get(phase_cfg.name, [])
        if attempt_no >= len(outcomes):
            return "", {}, []

        outcome = outcomes[attempt_no]

        for turn in outcome.turns:
            on_turn(turn)

        if outcome.error:
            result = PhaseResult(
                phase=phase_cfg.name,
                attempt_no=attempt_no,
                prompt=prompt,
                response_text=outcome.response_text,
                turns=outcome.turns,
                usage=outcome.usage,
                produced_files=outcome.produced_files,
                started_at=_utcnow(),
                ended_at=_utcnow(),
                error=outcome.error,
                error_type=outcome.error_type,
                is_retryable=outcome.is_retryable,
            )
            raise PhaseError(phase_cfg.name, outcome.error, result=result)

        for f in outcome.produced_files:
            path = self.workspace.working_dir / f
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("{}", encoding="utf-8")

        return outcome.response_text, outcome.usage, outcome.turns
