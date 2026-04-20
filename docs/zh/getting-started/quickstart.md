<!-- This is a Chinese translation of docs/getting-started/quickstart.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 快速开始

本指南带你从零开始运行你的第一个 Scrivai PES。

## 前提条件

- Python >= 3.11
- 已安装 Scrivai（`pip install scrivai`）
- Claude Agent SDK CLI 可用（`claude` 命令）
- 已配置 API 密钥（通过 `.env` 文件或环境变量）

```bash
pip install scrivai
# Create .env with your API credentials
echo 'ANTHROPIC_BASE_URL=https://your-gateway.example.com' >> .env
echo 'ANTHROPIC_AUTH_TOKEN=your-key-here' >> .env
```

## 最简 AuditorPES 示例

以下脚本按照一组检查点审核文档。

```python
import asyncio
from pathlib import Path
from pydantic import BaseModel
from scrivai import (
    AuditorPES, ModelConfig, WorkspaceSpec,
    build_workspace_manager, load_pes_config,
)

# 1. Define output schema
class AuditOutput(BaseModel):
    findings: list[dict]
    summary: dict

# 2. Set up workspace
ws_mgr = build_workspace_manager()
spec = WorkspaceSpec(
    run_id="quickstart-audit",
    project_root=Path("."),  # must contain skills/ and agents/ dirs
    data_inputs={"document.md": Path("my_document.md")},
    force=True,
)
ws = ws_mgr.create(spec)

# 3. Place checkpoints in workspace
import json
checkpoints = [
    {"id": "CP001", "description": "Document must have a title"},
    {"id": "CP002", "description": "All figures must have captions"},
]
(ws.data_dir / "checkpoints.json").write_text(
    json.dumps(checkpoints, ensure_ascii=False)
)

# 4. Load config, create PES, and run
config = load_pes_config(Path("scrivai/agents/auditor.yaml"))
model = ModelConfig(model="claude-sonnet-4-20250514")
pes = AuditorPES(
    config=config,
    model=model,
    workspace=ws,
    runtime_context={"output_schema": AuditOutput},
)

async def main():
    run = await pes.run("Audit data/document.md against all checkpoints")
    print(f"Status: {run.status}")           # "completed"
    print(f"Findings: {run.final_output}")   # {"findings": [...], "summary": {...}}

asyncio.run(main())
```

## 三阶段生命周期

每次 PES 运行都严格经历三个阶段：

```
┌──────────────────────────────────────────────────────────┐
│                       PES Run                            │
│                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐   │
│  │   PLAN   │───▶│   EXECUTE    │───▶│  SUMMARIZE    │   │
│  │          │    │              │    │               │   │
│  │ Read     │    │ Per-item     │    │ Merge all     │   │
│  │ inputs,  │    │ processing   │    │ findings into │   │
│  │ produce  │    │ with tool    │    │ output.json   │   │
│  │ plan.json│    │ use          │    │               │   │
│  └──────────┘    └──────────────┘    └───────────────┘   │
│                                                          │
│  phase_results     phase_results      phase_results      │
│  ["plan"]          ["execute"]        ["summarize"]      │
└──────────────────────────────────────────────────────────┘
```

- **计划（Plan）**：Agent 读取输入并生成 `plan.json` + `plan.md`。
- **执行（Execute）**：Agent 按计划执行，为每个条目生成 `findings/<id>.json`。
- **摘要（Summarize）**：Agent 将发现结果合并为 `output.json`（由框架验证）。

每个阶段以 `PhaseResult` 形式记录，包含所有轮次和该阶段的最终文本。

## 下一步

- [概念：PES 引擎](../concepts/pes.md) — 文件契约、提示词模板、自定义 PES
- [概念：工作区](../concepts/workspace.md) — 运行隔离与 `extra_env`
- [概念：轨迹存储](../concepts/trajectory.md) — 记录与回放运行
- [API 参考：PES](../api/pes.md) — 完整类文档
