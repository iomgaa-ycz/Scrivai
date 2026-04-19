"""PhaseLogHook — dumps each phase attempt's prompt/response/turns to logs_dir.

Reference: docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.4.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scrivai.pes.hooks import hookimpl

if TYPE_CHECKING:
    from scrivai.models.pes import FailureHookContext, PhaseHookContext, PhaseResult
    from scrivai.models.workspace import WorkspaceHandle


class PhaseLogHook:
    """Dumps each phase attempt's prompt/response/turns to logs_dir."""

    def __init__(self, workspace: WorkspaceHandle) -> None:
        self._logs_dir = workspace.logs_dir

    @hookimpl
    def after_phase(self, context: PhaseHookContext) -> None:
        """Dump on successful phase completion."""
        self._dump(context.phase, context.attempt_no, context.phase_result)

    @hookimpl
    def on_phase_failed(self, context: FailureHookContext) -> None:
        """Dump even when the phase fails."""
        self._dump(context.phase, context.attempt_no, context.phase_result)

    def _dump(self, phase: str, attempt_no: int, result: PhaseResult | None) -> None:
        if result is None:
            return
        log_path = self._logs_dir / f"phase-{phase}-attempt-{attempt_no}.log.json"
        log_path.write_text(
            json.dumps(
                {
                    "phase": phase,
                    "attempt_no": attempt_no,
                    "prompt": result.prompt,
                    "response_text": result.response_text,
                    "turns": [t.model_dump(mode="json") for t in result.turns],
                    "usage": result.usage,
                    "error": result.error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
