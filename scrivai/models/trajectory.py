"""TrajectoryStore read-only view models.

See docs/design.md §4.1 and §4.5.
- TrajectoryRecord: read-only view of the runs table (optionally joined with phases)
- PhaseRecord: one row of the phases table (one row per run_id + phase_name + attempt)
- FeedbackRecord: one row of the feedback table
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PhaseRecord(BaseModel):
    """One row of the phases table (see design §4.5 phases schema and §4.1 PhaseRecord)."""

    model_config = ConfigDict(extra="forbid")

    phase_id: int
    run_id: str
    phase_name: str = Field(..., description="Phase name: plan, execute, or summarize.")
    attempt_no: int = Field(
        default=0, description="Distinguishes multiple attempts of the same phase."
    )
    phase_order: int = Field(..., description="Phase order index: 0=plan, 1=execute, 2=summarize.")
    prompt: str | None = None
    response_text: str | None = None
    produced_files: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None
    is_retryable: bool | None = None
    started_at: datetime
    ended_at: datetime | None = None


class TrajectoryRecord(BaseModel):
    """Read-only view of the runs table (optionally joined with phases)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    pes_name: str
    model_name: str
    provider: str
    sdk_version: str
    skills_git_hash: str | None = None
    agents_git_hash: str | None = None
    skills_is_dirty: bool = False
    status: Literal["running", "completed", "failed", "cancelled"]
    task_prompt: str
    runtime_context: dict[str, Any] | None = None
    workspace_archive_path: str | None = None
    final_output: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    phase_records: list[PhaseRecord] = Field(
        default_factory=list, description="Phase records from a sub-table join (optional)."
    )


class FeedbackRecord(BaseModel):
    """One row of the feedback table (see design §4.5 feedback schema)."""

    model_config = ConfigDict(extra="forbid")

    feedback_id: int
    run_id: str
    input_summary: str = Field(
        ..., description="Input summary for this run, provided by the business layer."
    )
    draft_output: dict[str, Any] = Field(..., description="Original output produced by the Agent.")
    final_output: dict[str, Any] = Field(..., description="Expert-approved final output.")
    corrections: list[dict[str, Any]] | None = Field(
        default=None, description="Optional structured diff between draft and final output."
    )
    review_policy_version: str | None = None
    source: str = Field(
        default="human_expert",
        description="Feedback source: human_expert, second_review, or gold_set.",
    )
    confidence: float = Field(default=1.0, description="Feedback quality score in [0.0, 1.0].")
    submitted_at: datetime
    submitted_by: str | None = None
