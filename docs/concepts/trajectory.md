# Trajectory

The **TrajectoryStore** persists every PES run — all phases, turns, LLM inputs/outputs, and feedback — to a SQLite database. This supports debugging, replay, and training-data collection.

## What Gets Recorded

| Record type | Contents |
|---|---|
| `TrajectoryRecord` | Run-level metadata: run ID, PES name, status, start/end time, final output |
| `PhaseRecord` | Per-phase data: phase name, plan text, all turns, phase result |
| `FeedbackRecord` | Human or automated feedback attached to a run: label, score, notes |

## Usage

```python
from scrivai import TrajectoryStore, ExtractorPES, ModelConfig, PESConfig, PhaseConfig
from scrivai import TrajectoryRecorderHook

# Open (or create) the trajectory database
store = TrajectoryStore(db_path="~/.scrivai/trajectory.db")

# Attach the recorder hook to a PES
model = ModelConfig(model="claude-sonnet-4-20250514")
config = PESConfig(
    name="my-extractor",
    model=model,
    phases=[PhaseConfig(name="extract")],
)
pes = ExtractorPES(config=config)
pes.pm.register(TrajectoryRecorderHook(store=store))

# Run normally — all phases are recorded automatically
result = pes.run(runtime_context={"document_text": "...", "extraction_schema": {}})

# Query recorded runs
records = store.list_runs(pes_name="my-extractor")
for record in records:
    print(record.run_id, record.status)
```

## Database Location

By default the database is created at `~/.scrivai/trajectory.db`. Override by passing a `db_path` to `TrajectoryStore`:

```python
store = TrajectoryStore(db_path="/data/scrivai/my-project.db")
```

## See Also

- [API Reference: (TrajectoryStore is in the workspace API page)](../api/workspace.md)
- [Concepts: Evolution](evolution.md) — evolution uses the trajectory store to collect failure samples
