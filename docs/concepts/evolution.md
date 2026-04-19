# Evolution

Scrivai's skill evolution system identifies failing cases in a trajectory store, proposes improved skill versions using an LLM, evaluates candidates on a held-out set, and optionally promotes the best candidate back to the `skills/` directory.

## Workflow

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

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **No auto-promote** | Humans (domain experts) decide when a candidate is ready for production. |
| **Explicit trigger** | Business logic calls `run_evolution()` — no background daemon or scheduler. |
| **Separate database** | Evolution state lives in `evolution.db`, separate from `trajectory.db`, to avoid schema coupling. |
| **Budget guard** | `LLMCallBudget` caps the total number of LLM calls in one evolution run (default: 500). |

## Usage

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

## See Also

- [API Reference: Evolution](../api/evolution.md)
- [Concepts: Trajectory](trajectory.md) — evolution reads failure samples from the trajectory store
