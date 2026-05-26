# Quick Start

This guide walks you through running your first Scrivai PES.

## Prerequisites

- Python >= 3.11
- Scrivai installed (`pip install scrivai`)
- Claude Agent SDK CLI available (`claude` command)
- API key configured (via `.env` file or environment variable)

```bash
pip install scrivai
# Create .env with your API credentials
echo 'ANTHROPIC_BASE_URL=https://your-gateway.example.com' >> .env
echo 'ANTHROPIC_AUTH_TOKEN=your-key-here' >> .env
```

## Minimal AuditorPES Example

The following script audits a document against a set of checkpoints.

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

## The Three-Phase Lifecycle

Every PES run goes through exactly three phases:

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

- **Plan**: The Agent reads inputs and generates `plan.json` + `plan.md`.
- **Execute**: The Agent follows the plan, producing `findings/<id>.json` per item.
- **Summarize**: The Agent merges findings into `output.json` (validated by the framework).

Each phase is recorded as a `PhaseResult` containing all turns and the final text.

## Document Conversion (OCR)

Scrivai includes a `to_markdown()` function that converts PDF, DOC, and DOCX files to Markdown using pluggable OCR backends.

### MinerU (Local Pipeline, Default)

```python
from scrivai import to_markdown

# MinerU runs locally — no API key needed
md = to_markdown("report.pdf")
print(md)

# With page range
md = to_markdown("long_report.pdf", start_page=10, end_page=20)
```

MinerU uses intelligent auto-routing: text-based pages are extracted directly, scanned pages go through OCR. Includes professional table recognition, layout analysis, and formula detection.

> **First run:** MinerU downloads models automatically (~2-3 GB). Subsequent runs use cached models.

### GLM-OCR (Cloud)

```python
# Set your API key via env or parameter
# export SCRIVAI_GLM_API_KEY=your-key-here

md = to_markdown("report.pdf", ocr_backend="glm")

# With page range
md = to_markdown("long_report.pdf", ocr_backend="glm", start_page=10, end_page=20)
```

Large PDFs are automatically split into overlapping chunks and processed **in parallel** (max 3 concurrent requests).

```python
# Customize chunking (defaults shown)
md = to_markdown(
    "large_report.pdf",
    ocr_backend="glm",
    chunk_pages=30,       # pages per chunk
    overlap_pages=2,      # overlap to preserve cross-page tables
    max_workers=3,        # parallel threads (hard cap 3)
)
```

### MonkeyOCR (Self-Hosted)

```python
md = to_markdown(
    "report.pdf",
    ocr_backend="monkey",
    ocr_base_url="http://localhost:7861",
)
```

### Supported Formats

| Input | Pipeline |
|---|---|
| `.pdf` | Direct OCR |
| `.docx` | LibreOffice → PDF → OCR |
| `.doc` | LibreOffice → PDF → OCR |

When the OCR backend is unreachable and `fallback=True` (default), `.doc`/`.docx` files fall back to pandoc conversion.

### CLI

```bash
scrivai-cli io convert --input report.pdf --output report.md
scrivai-cli io convert --input report.pdf --ocr-backend monkey --ocr-base-url http://localhost:7861

# Parallel chunking options
scrivai-cli io convert --input large.pdf --chunk-pages 30 --overlap-pages 2 --max-workers 12
```

## Next Steps

- [Concepts: PES Engine](../concepts/pes.md) — file contracts, prompt templates, custom PES
- [Concepts: Workspace](../concepts/workspace.md) — run isolation and `extra_env`
- [Concepts: Trajectory](../concepts/trajectory.md) — record and replay runs
- [API Reference: PES](../api/pes.md) — full class documentation
