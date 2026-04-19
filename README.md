# Scrivai

[中文](README.zh-CN.md)

[![PyPI version](https://img.shields.io/pypi/v/scrivai.svg)](https://pypi.org/project/scrivai/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

Configurable document generation & audit framework built on Claude Agent SDK.

Scrivai wraps the Claude Agent SDK in a three-phase execution engine called **PES** (Plan→Execute→Summarize), where each phase produces file-contract outputs that the framework validates automatically. It ships three built-in agents — `ExtractorPES`, `AuditorPES`, and `GeneratorPES` — and includes a self-improving skill system that proposes, evaluates, and promotes better agent behaviors from trajectory feedback.

## Install

```bash
pip install scrivai
```

## Quick Start

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

## Core Concepts

Every agent in Scrivai follows the same three-phase contract:

```
┌──────┐      ┌─────────┐      ┌───────────┐
│ plan │ ───▶ │ execute │ ───▶ │ summarize │
└──────┘      └─────────┘      └───────────┘
    │               │                │
    ▼               ▼                ▼
plan.json    findings/*.json    output.json
```

Each phase declares `required_outputs` in a YAML config. The framework checks those file contracts at phase exit and automatically retries up to `max_retries` times on failure. This makes every PES unit testable and auditable without extra instrumentation.

## Key APIs

| Symbol | Description |
|--------|-------------|
| `BasePES` | Three-phase execution engine base class |
| `ExtractorPES` | Extract structured data from documents |
| `AuditorPES` | Audit documents against checkpoints |
| `GeneratorPES` | Generate documents from templates |
| `ModelConfig` | LLM provider configuration |
| `load_pes_config()` | Load PES config from YAML |
| `build_workspace_manager()` | Create isolated workspaces |

## Examples

| Script | Covers | Estimated time |
|--------|--------|----------------|
| `examples/01_audit_single_doc.py` | `AuditorPES` checkpoint audit | ~2–3 min |
| `examples/02_generate_with_revision.py` | `GeneratorPES` template generation | ~1–2 min |
| `examples/03_evolve_skill_workflow.py` | Skill evolution end-to-end | ~3–5 min |

## Documentation

Full API reference and guides: **https://iomgaa-ycz.github.io/Scrivai/**

## Configuration

**Required**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Gateway override** (optional — for private endpoints or alternative models)

```bash
export ANTHROPIC_BASE_URL=https://your-gateway.example.com
export SCRIVAI_DEFAULT_MODEL=your-model-name
```

These environment variables are read automatically at startup. You can also pass `base_url`, `model`, and `api_key` directly to `ModelConfig` to override them at the code level.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and the pull-request workflow.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
