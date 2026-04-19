<!-- This is a Chinese translation of docs/index.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# Scrivai

**Scrivai** 是一个可配置的 Python 文档生成与审核框架，构建于 Claude Agent SDK 之上。它将 SDK 封装进一个结构化的三阶段执行引擎——计划、执行、摘要——称为 **PES**（Plan–Execute–Summarize）。

## 核心功能

- **三阶段引擎**：每次 LLM 交互都遵循确定性的计划 → 执行 → 摘要生命周期，使行为可复现、可调试。
- **预置 PES 实现**：开箱即用的 `ExtractorPES`、`AuditorPES` 和 `GeneratorPES`，覆盖最常见的文档处理工作流。
- **工作区管理**：每次运行获得一个隔离的沙箱目录，支持快照与归档。
- **轨迹记录**：所有阶段、轮次和反馈均持久化到 SQLite，支持回放、调试和训练数据采集。
- **Skill 进化**：端到端进化循环，识别失败案例、提出 skill 改进方案，并在晋升前评估候选版本。
- **知识集成**：对规则、案例和模板库提供一等支持，底层采用 `qmd` 语义检索引擎。
- **IO 工具**：将 `.docx`、`.doc` 和 `.pdf` 文件转换为 Markdown，并将 Markdown 渲染回 `.docx`。

## 快速开始

```python
import scrivai
from scrivai import ExtractorPES, ModelConfig, PESConfig, PhaseConfig

# Configure the model
model = ModelConfig(model="claude-sonnet-4-20250514")

# Load a PES config (or build one in code)
config = PESConfig(
    name="my-extractor",
    model=model,
    phases=[
        PhaseConfig(name="extract", system_prompt="You are a document extractor."),
    ],
)

# Run the extractor
pes = ExtractorPES(config=config)
result = pes.run(
    runtime_context={
        "document_text": "The contract is dated 2024-01-15 and signed by Alice.",
        "extraction_schema": {"date": "str", "signer": "str"},
    }
)

print(result.output)
# {'date': '2024-01-15', 'signer': 'Alice'}
```

## 下一步

- [安装](getting-started/installation.md) — 配置你的环境
- [快速开始](getting-started/quickstart.md) — 更完整的入门指引
- [概念：PES 引擎](concepts/pes.md) — 理解三阶段模型
- [API 参考](../api/pes.md) — 完整的类与函数文档
