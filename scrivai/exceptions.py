"""Scrivai exception hierarchy — declared in M0; behaviour added in later milestones."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrivai.models.pes import PhaseResult


class ScrivaiError(Exception):
    """Base class for all Scrivai exceptions."""


class PESConfigError(ScrivaiError):
    """PESConfig YAML load or schema validation failure (M0 T0.3)."""


class WorkspaceError(ScrivaiError):
    """WorkspaceManager error (run_id conflict, fcntl failure, etc.) (M0.25 T0.4)."""


class TrajectoryWriteError(ScrivaiError):
    """TrajectoryStore write failure (SQLite busy beyond retry budget) (M0.25 T0.7)."""


class PhaseError(ScrivaiError):
    """Unified exit point for BasePES phase-level failures; carries result / error_type / is_retryable (M0.5 T0.6)."""

    def __init__(
        self,
        phase: str,
        message: str,
        *,
        result: PhaseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.result = result


class RateLimitError(ScrivaiError):
    """Claude SDK rate limit; used for L1 transport-level retries (M0.5 T0.6)."""


class _SDKError(ScrivaiError):
    """Internal exception translated at the LLMClient boundary; lives only between
    BasePES._call_sdk_query and _run_phase.

    BasePES._run_phase step 5 catches this, builds a PhaseResult from ``error_type``,
    then re-raises as PhaseError. Business code never sees _SDKError.

    Attributes:
        error_type: ``"max_turns_exceeded"`` or ``"sdk_other"`` — determines
            ``PhaseResult.is_retryable``.
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


class ScrivaiJSONRepairError(ScrivaiError, json.JSONDecodeError):
    """All JSON fault-tolerant repair stages failed.

    Multiple inheritance: can be caught by both ``except ScrivaiError`` and
    ``except json.JSONDecodeError``.

    Attributes:
        original_text: The original input text.
        repaired_text: The text after the last repair attempt.
        stages_applied: Names of repair stages that were tried.
    """

    def __init__(
        self,
        msg: str,
        doc: str,
        pos: int,
        *,
        original_text: str,
        repaired_text: str,
        stages_applied: list[str],
    ) -> None:
        json.JSONDecodeError.__init__(self, msg, doc, pos)
        self.original_text = original_text
        self.repaired_text = repaired_text
        self.stages_applied = stages_applied
