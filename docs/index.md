# Scrivai

**Scrivai** is a configurable document generation and audit framework for Python, built on top of the Claude Agent SDK. It wraps the SDK into a structured three-phase execution engine — plan, execute, summarize — called a **PES** (Plan–Execute–Summarize).

## Key Features

- **Three-phase engine**: Every LLM interaction follows a deterministic plan → execute → summarize lifecycle, making behaviour reproducible and debuggable.
- **Built-in PES implementations**: Drop-in `ExtractorPES`, `AuditorPES`, and `GeneratorPES` cover the most common document-processing workflows.
- **Workspace management**: Each run gets an isolated sandbox directory with snapshotting and archival support.
- **Trajectory recording**: All phases, turns, and feedback are persisted to SQLite for replay, debugging, and training data collection.
- **Skill evolution**: An end-to-end evolution loop identifies failing cases, proposes skill improvements, and evaluates candidates before promotion.
- **Knowledge integration**: First-class support for rule, case, and template libraries backed by the `qmd` semantic retrieval engine.
- **IO utilities**: Convert `.docx`, `.doc`, and `.pdf` files to Markdown and render Markdown back to `.docx`.

## Quick Start

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

## Next Steps

- [Installation](getting-started/installation.md) — set up your environment
- [Quick Start](getting-started/quickstart.md) — a fuller walkthrough
- [Concepts: PES Engine](concepts/pes.md) — understand the three-phase model
- [API Reference](api/pes.md) — complete class and function documentation
