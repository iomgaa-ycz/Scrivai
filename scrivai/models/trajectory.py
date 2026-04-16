"""TrajectoryStore 持久化视图模型。

参考 docs/design.md §4.1 / §4.5。
- TrajectoryRecord:runs 表(可选联查 phases)的只读视图
- PhaseRecord:phases 表一行(同 run_id+phase_name 多 attempt 各一条)
- FeedbackRecord:feedback 表一行
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class PhaseRecord(BaseModel):
    """phases 表一行(对应 design §4.5 phases schema + design §4.1 PhaseRecord 表)。"""

    model_config = ConfigDict(extra="forbid")

    phase_id: int
    run_id: str
    phase_name: str = Field(..., description="plan / execute / summarize")
    attempt_no: int = Field(default=0, description="同 phase 多次 attempt 区分")
    phase_order: int = Field(..., description="0=plan, 1=execute, 2=summarize")
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
    """runs 表只读视图(可选联查 phases)。"""

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
    phase_records: list[PhaseRecord] = Field(default_factory=list, description="子表联查(可选)")


class FeedbackRecord(BaseModel):
    """feedback 表一行(对应 design §4.5 feedback schema)。"""

    model_config = ConfigDict(extra="forbid")

    feedback_id: int
    run_id: str
    input_summary: str = Field(..., description="业务层提供的本次 run 输入摘要")
    draft_output: dict[str, Any] = Field(..., description="Agent 原输出")
    final_output: dict[str, Any] = Field(..., description="专家定稿")
    corrections: Optional[list[dict[str, Any]]] = Field(default=None, description="可选结构化 diff")
    review_policy_version: Optional[str] = None
    source: str = Field(
        default="human_expert", description="human_expert / second_review / gold_set"
    )
    confidence: float = Field(default=1.0, description="0.0-1.0 反馈质量")
    submitted_at: datetime
    submitted_by: Optional[str] = None
