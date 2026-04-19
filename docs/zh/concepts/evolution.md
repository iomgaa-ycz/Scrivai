<!-- This is a Chinese translation of docs/concepts/evolution.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# Skill 进化

Scrivai 的 skill 进化系统从轨迹存储中识别失败案例，使用 LLM 提出改进后的 skill 版本，在留存集上评估候选版本，并可选择性地将最佳候选晋升回 `skills/` 目录。

## 工作原理

```
TrajectoryStore
      │
      ▼  (collect failure samples)
EvolutionTrigger
      │
      ▼  (split train / holdout)
   Proposer
      │   (LLM generates N candidate skill versions)
      ▼
CandidateEvaluator
      │   (run each candidate on holdout set, score)
      ▼
SkillVersionStore
      │   (store all versions + scores in evolution.db)
      ▼  (if best score > threshold, expert calls promote())
   promote()
      │
      ▼
  skills/  (atomic write-back)
```

## 关键设计决策

| 决策 | 原因 |
|---|---|
| **禁止自动晋升** | 由人类（领域专家）决定候选版本何时可投入生产。 |
| **显式触发** | 业务逻辑调用 `run_evolution()`，无后台守护进程或调度器。 |
| **独立数据库** | 进化状态存储于 `evolution.db`，与 `trajectory.db` 分离，避免 schema 耦合。 |
| **预算守卫** | `LLMCallBudget` 限制单次进化运行的 LLM 调用总数（默认：500）。 |

## 使用方法

```python
from scrivai import (
    run_evolution,
    promote,
    EvolutionRunConfig,
    TrajectoryStore,
    LLMCallBudget,
    ModelConfig,
)

store = TrajectoryStore(db_path="~/.scrivai/trajectory.db")
model = ModelConfig(model="claude-sonnet-4-20250514")

config = EvolutionRunConfig(
    pes_name="my-auditor",
    skill_name="audit_rules",
    n_candidates=3,
    holdout_ratio=0.2,
    min_improvement=0.05,
    model=model,
    budget=LLMCallBudget(max_calls=200),
)

# Run the evolution loop
evo_record = run_evolution(config=config, trajectory_store=store)

print(evo_record.status)       # 'completed' or 'no_improvement'
print(evo_record.best_score)   # float

# If satisfied, promote the best candidate
if evo_record.best_version_id:
    promote(
        version_id=evo_record.best_version_id,
        source_project_root=".",
    )
```

## 另请参阅

- [API 参考：Evolution](../../api/evolution.md)
- [概念：轨迹存储](trajectory.md) — 进化机制从轨迹存储读取失败样本
