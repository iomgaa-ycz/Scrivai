# Scrivai

[English](README.md)

[![PyPI version](https://img.shields.io/pypi/v/scrivai.svg)](https://pypi.org/project/scrivai/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

可配置的文档生成与审核框架，基于 Claude Agent SDK 构建。

Scrivai 将 Claude Agent SDK 封装为三阶段执行引擎 **PES**（Plan→Execute→Summarize），每个阶段产出文件契约，框架自动校验。内置三个预置 Agent —— `ExtractorPES`、`AuditorPES` 和 `GeneratorPES` —— 并包含自我进化 Skill 系统，可根据轨迹反馈自动提出、评估并升级更优的 Agent 行为。

## 安装

```bash
pip install scrivai
```

## 快速开始

```python
import asyncio
from pathlib import Path
from pydantic import BaseModel
from scrivai import (
    ExtractorPES,
    ModelConfig,
    WorkspaceSpec,
    build_workspace_manager,
    load_pes_config,
)


class KeyItems(BaseModel):
    items: list[str]


async def main():
    ws_mgr = build_workspace_manager()
    ws = ws_mgr.create(WorkspaceSpec(run_id="demo", project_root=Path.cwd(), force=True))
    config = load_pes_config(Path("scrivai/agents/extractor.yaml"))

    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="claude-sonnet-4-20250514"),
        workspace=ws,
        runtime_context={"output_schema": KeyItems},
    )
    run = await pes.run("Extract all key items from data/source.md")
    print(run.final_output)


asyncio.run(main())
```

## 核心概念

Scrivai 中的每个 Agent 都遵循相同的三阶段契约：

```
┌──────┐      ┌─────────┐      ┌───────────┐
│ plan │ ───▶ │ execute │ ───▶ │ summarize │
└──────┘      └─────────┘      └───────────┘
    │               │                │
    ▼               ▼                ▼
plan.json    findings/*.json    output.json
```

每个阶段在 YAML 配置中声明 `required_outputs`，框架在阶段结束时检查这些文件契约，失败时自动重试至 `max_retries` 次。这使每个 PES 单元无需额外埋点即可测试和审计。

## 核心 API

| 符号 | 描述 |
|------|------|
| `BasePES` | 三阶段执行引擎基类 |
| `ExtractorPES` | 从文档抽取结构化数据 |
| `AuditorPES` | 对照检查点审核文档 |
| `GeneratorPES` | 从模板生成文档 |
| `ModelConfig` | LLM 供应商配置 |
| `load_pes_config()` | 从 YAML 加载 PES 配置 |
| `build_workspace_manager()` | 创建隔离工作区 |

## 示例

| 脚本 | 覆盖内容 | 预计耗时 |
|------|---------|---------|
| `examples/01_audit_single_doc.py` | `AuditorPES` 对照审核 | ~2–3 分钟 |
| `examples/02_generate_with_revision.py` | `GeneratorPES` 模板生成 | ~1–2 分钟 |
| `examples/03_evolve_skill_workflow.py` | Skill 进化端到端流程 | ~3–5 分钟 |

## 文档

完整 API 参考与指南：**https://iomgaa-ycz.github.io/Scrivai/**

## 配置

**必填**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**网关覆盖**（可选 —— 用于私有端点或其他模型）

```bash
export ANTHROPIC_BASE_URL=https://your-gateway.example.com
export SCRIVAI_DEFAULT_MODEL=your-model-name
```

这些环境变量在启动时自动读取。也可以直接向 `ModelConfig` 传入 `base_url`、`model` 和 `api_key` 在代码层覆盖。

## 贡献

开发环境搭建、代码规范与 PR 流程详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

Apache 2.0 —— 详见 [LICENSE](LICENSE)。
