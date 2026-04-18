"""Evolution 数据模型(M2 自研,替代 M0 EvoSkill 兼容层)。

参考:
- docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §4.1
- docs/design.md §4.6(M2 合入时同步重写)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SkillVersionStatus = Literal["draft", "evaluated", "promoted", "rejected"]
EvolutionRunStatus = Literal["running", "completed", "failed", "budget_exceeded"]

EvaluatorFn = Callable[[str, str, str], float]
"""业务层提供的评分函数签名:(question, predicted, ground_truth) -> float。"""


class FailureSample(BaseModel):
    """单条失败样本(来自 trajectory.feedback)。"""

    model_config = ConfigDict(extra="forbid")

    feedback_id: int
    run_id: str
    task_prompt: str
    question: str
    draft_output_str: str
    ground_truth_str: str
    baseline_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    trajectory_summary: dict[str, str] = Field(default_factory=dict)
    data_inputs: dict[str, Path] = Field(default_factory=dict)


class SkillVersion(BaseModel):
    """版本 DAG 节点。"""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    pes_name: str
    skill_name: str
    parent_version_id: Optional[str]
    content_snapshot: dict[str, str]
    content_diff: str
    change_summary: str
    status: SkillVersionStatus = "draft"
    created_at: datetime
    promoted_at: Optional[datetime] = None
    created_by: str


class EvolutionProposal(BaseModel):
    """Proposer 单次产出的候选(未入库,未打分)。"""

    model_config = ConfigDict(extra="forbid")

    new_content_snapshot: dict[str, str]
    change_summary: str
    reasoning: str


class EvolutionScore(BaseModel):
    """候选在 hold-out 上的评分。"""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    score: float = Field(ge=0.0, le=1.0)
    per_sample_scores: list[float]
    hold_out_size: int
    llm_calls_consumed: int
    evaluated_at: datetime


class EvolutionRunRecord(BaseModel):
    """一次 run_evolution 调用的完整记录。"""

    model_config = ConfigDict(extra="forbid")

    evo_run_id: str
    pes_name: str
    skill_name: str
    config_snapshot: dict[str, Any]
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: EvolutionRunStatus = "running"
    baseline_version_id: str
    baseline_score: float
    best_version_id: Optional[str] = None
    best_score: Optional[float] = None
    candidate_version_ids: list[str] = Field(default_factory=list)
    llm_calls_used: int = 0
    iterations_history: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class EvolutionRunConfig(BaseModel):
    """run_evolution 输入配置。"""

    model_config = ConfigDict(extra="forbid")

    pes_name: str
    skill_name: str
    max_iterations: int = 5
    n_proposals_per_iter: int = 3
    frontier_size: int = 3
    no_improvement_limit: int = 2
    max_llm_calls: int = 500
    hold_out_ratio: float = Field(default=0.3, ge=0.1, le=0.5)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    failure_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    proposer_model: str = "glm-5.1"
    random_seed: int = 42
