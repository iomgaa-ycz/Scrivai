"""Evolution(EvoSkill 进化)相关 pydantic + Protocol。

参考 docs/design.md §4.6。
- EvolutionConfig / EvolutionRun / FeedbackExample:M0 定义,
  M2 由 EvolutionTrigger / run_evolution 消费
- Evaluator Protocol:业务层实现的评分函数协议
- SkillsRootResolver Protocol:EvoSkill 的 skills 根目录适配层(M2 实现两个内置)

职责边界:SkillsRootResolver 只准备路径,**不**负责切换 cwd(由 run_evolution 自行处理)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class FeedbackExample(BaseModel):
    """从 FeedbackRecord 构建进化评测集的中间结构。"""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., description="JSON 字符串:{'task_prompt': ..., 'input_summary': ...}")
    ground_truth: str = Field(..., description="final_output 的规范化 JSON 字符串")
    category: str = Field(..., description="分类标签,默认 pes_name,业务可自定义")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="透传 review_policy_version/source/confidence/run_id",
    )


class EvolutionConfig(BaseModel):
    """run_evolution 的输入配置。"""

    model_config = ConfigDict(extra="forbid")

    task_name: str
    model: str
    mode: Literal["greedy", "pareto"] = "greedy"
    eval_dataset_csv: Path
    max_iterations: int = 5
    no_improvement_limit: int = 2
    concurrency: int = 4
    train_ratio: float = 0.7
    val_ratio: float = 0.3
    tolerance: float = 0.01
    selection_strategy: Literal["top_k", "pareto_frontier"] = "top_k"
    cache_enabled: bool = True
    cache_dir: Optional[Path] = None
    project_root: Path = Field(..., description="给 SkillsRootResolver 用")


class EvolutionRun(BaseModel):
    """run_evolution 的输出。"""

    model_config = ConfigDict(extra="forbid")

    best_score_base: float
    best_score_evolved: float
    promoted_branch: Optional[str] = Field(
        default=None, description="最高分超过 base 时填,例 'evo/2026-04-15-123-idx2'"
    )
    candidate_branches: list[str] = Field(default_factory=list)
    iterations_history: list[dict[str, Any]] = Field(default_factory=list)


@runtime_checkable
class Evaluator(Protocol):
    """业务层提供的评分函数。

    返回 0.0 - 1.0,1.0 表示 predicted 与 ground_truth 完全一致。
    """

    def __call__(
        self,
        question: str,
        predicted: str,
        ground_truth: str,
    ) -> float: ...


@runtime_checkable
class SkillsRootResolver(Protocol):
    """解析 EvoSkill 需要看到的 skills 根目录。

    职责范围(单一职责):
    - __enter__: 准备并返回路径 P,使得 P/.claude/skills/ 存在且指向正确内容
    - __exit__: 清理 __enter__ 创建的临时资源(symlink / 临时目录等)

    不负责:
    - 切换进程的工作目录(由 run_evolution 自行处理)
    - 启动 EvoSkill 进程或传参
    """

    def __enter__(self) -> Path:
        """返回路径 P,P/.claude/skills/ 可被 EvoSkill 读到。"""
        ...

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """清理 __enter__ 创建的临时 symlink / 目录。"""
        ...
