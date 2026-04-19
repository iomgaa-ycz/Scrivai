<!-- This is a Chinese translation of docs/getting-started/quickstart.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 快速开始

本指南带你从零开始运行你的第一个 Scrivai PES。

## 前提条件

- 已安装 Scrivai（`pip install scrivai`）
- 在环境变量（或 `.env` 文件）中设置了 `ANTHROPIC_API_KEY`

## 最简 ExtractorPES 示例

以下脚本从一段短文档字符串中提取结构化字段。

```python
import os
from scrivai import ExtractorPES, ModelConfig, PESConfig, PhaseConfig

# 1. Define the model to use
model = ModelConfig(model="claude-sonnet-4-20250514")

# 2. Build a PES configuration with one extraction phase
config = PESConfig(
    name="quickstart-extractor",
    model=model,
    phases=[
        PhaseConfig(
            name="extract",
            system_prompt=(
                "You are a precise document extractor. "
                "Return a JSON object matching the requested schema."
            ),
        ),
    ],
)

# 3. Instantiate the PES
pes = ExtractorPES(config=config)

# 4. Provide runtime context and run
result = pes.run(
    runtime_context={
        "document_text": (
            "Service Agreement dated 2024-03-01 between Acme Corp (provider) "
            "and Globex Ltd (client). Total value: $45,000."
        ),
        "extraction_schema": {
            "date": "str",
            "provider": "str",
            "client": "str",
            "value_usd": "int",
        },
    }
)

print(result.status)   # completed
print(result.output)   # {'date': '2024-03-01', 'provider': 'Acme Corp', ...}
```

## 三阶段生命周期

每次 PES 运行都严格经历三个阶段：

```
┌─────────────────────────────────────────────────────────┐
│                      PES Run                            │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  PLAN    │───▶│   EXECUTE    │───▶│   SUMMARIZE   │  │
│  │          │    │              │    │               │  │
│  │ Generate │    │ Multi-turn   │    │ Distil final  │  │
│  │ a step-  │    │ tool-use     │    │ output from   │  │
│  │ by-step  │    │ conversation │    │ raw turns     │  │
│  │ plan     │    │ following    │    │               │  │
│  │          │    │ the plan     │    │               │  │
│  └──────────┘    └──────────────┘    └───────────────┘  │
│                                                         │
│  result.phases[0]  result.phases[1]  result.phases[2]   │
└─────────────────────────────────────────────────────────┘
```

- **计划（Plan）**：LLM 读取系统提示词和运行时上下文，生成结构化计划。
- **执行（Execute）**：LLM 按计划执行，可能发起多轮工具调用。
- **摘要（Summarize）**：LLM 将执行轨迹提炼为简洁、结构化的最终输出。

每个阶段以 `PhaseResult` 形式记录，包含所有轮次（`PhaseTurn`）和该阶段的最终文本。

## 下一步

- [概念：PES 引擎](../concepts/pes.md) — 了解文件契约与自定义 PES 类
- [概念：工作区](../concepts/workspace.md) — 理解运行隔离机制
- [概念：轨迹存储](../concepts/trajectory.md) — 记录与回放运行
- [API 参考：PES](../api/pes.md) — 完整类文档
