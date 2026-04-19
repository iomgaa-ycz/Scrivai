<!-- This is a Chinese translation of docs/concepts/trajectory.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 轨迹存储

**TrajectoryStore** 将每次 PES 运行的所有阶段、轮次、LLM 输入/输出和反馈持久化到 SQLite 数据库，支持调试、回放和训练数据采集。

## 记录内容

| 记录类型 | 内容 |
|---|---|
| `TrajectoryRecord` | 运行级元数据：运行 ID、PES 名称、状态、开始/结束时间、最终输出 |
| `PhaseRecord` | 每阶段数据：阶段名称、计划文本、所有轮次、阶段结果 |
| `FeedbackRecord` | 附加到运行的人工或自动反馈：标签、分数、备注 |

## 使用方法

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

## 数据库位置

默认情况下，数据库创建于 `~/.scrivai/trajectory.db`。可通过向 `TrajectoryStore` 传入 `db_path` 覆盖：

```python
store = TrajectoryStore(db_path="/data/scrivai/my-project.db")
```

## 另请参阅

- [API 参考：（TrajectoryStore 位于 workspace API 页面）](../api/workspace.md)
- [概念：Skill 进化](evolution.md) — 进化机制使用轨迹存储采集失败样本
