"""TrajectoryStore read-only view models.

See docs/design.md §4.1 and §4.5.
- TrajectoryRecord: read-only view of the runs table (optionally joined with phases)
- PhaseRecord: one row of the phases table (one row per run_id + phase_name + attempt)
- FeedbackRecord: one row of the feedback table
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PhaseRecord(BaseModel):
    """One row of the phases table (see design §4.5 phases schema and §4.1 PhaseRecord)."""

    model_config = ConfigDict(extra="forbid")

    phase_id: int
    run_id: str
    phase_name: str = Field(..., description="Phase name: plan, execute, or summarize.")
    attempt_no: int = Field(default=0, description="Distinguishes multiple attempts of the same phase.")
    phase_order: int = Field(..., description="Phase order index: 0=plan, 1=execute, 2=summarize.")
    prompt: Optional[str] = None
    response_text: Optional[str] = None
    produced_files: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    error_type: Optional[str] = None
    is_retryable: Optional[bool] = None
    started_at: datetime
    ended_at: Optional[datetime] = None


class TrajectoryRecord(BaseModel):
    """Read-only view of the runs table (optionally joined with phases)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    pes_name: str
    model_name: str
    provider: str
    sdk_version: str
    skills_git_hash: Optional[str] = None
    agents_git_hash: Optional[str] = None
    skills_is_dirty: bool = False
    status: Literal["running", "completed", "failed", "cancelled"]
    task_prompt: str
    runtime_context: Optional[dict[str, Any]] = None
    workspace_archive_path: Optional[str] = None
    final_output: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    phase_records: list[PhaseRecord] = Field(default_factory=list, description="Phase records from a sub-table join (optional).")


class FeedbackRecord(BaseModel):
    """One row of the feedback table (see design §4.5 feedback schema)."""

    model_config = ConfigDict(extra="forbid")

    feedback_id: int
    run_id: str
    input_summary: str = Field(..., description="Input summary for this run, provided by the business layer.")
    draft_output: dict[str, Any] = Field(..., description="Original output produced by the Agent.")
    final_output: dict[str, Any] = Field(..., description="Expert-approved final output.")
    corrections: Optional[list[dict[str, Any]]] = Field(default=None, description="Optional structured diff between draft and final output.")
    review_policy_version: Optional[str] = None
    source: str = Field(
        default="human_expert", description="Feedback source: human_expert, second_review, or gold_set."
    )
    confidence: float = Field(default=1.0, description="Feedback quality score in [0.0, 1.0].")
    submitted_at: datetime
    submitted_by: Optional[str] = None
