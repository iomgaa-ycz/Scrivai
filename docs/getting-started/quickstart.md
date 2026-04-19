# Quick Start

This guide walks you through running your first Scrivai PES from scratch.

## Prerequisites

- Scrivai installed (`pip install scrivai`)
- `ANTHROPIC_API_KEY` set in your environment (or `.env` file)

## Minimal ExtractorPES Example

The following script extracts structured fields from a short document string.

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

## The Three-Phase Lifecycle

Every PES run goes through exactly three phases:

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

- **Plan**: The LLM reads the system prompt and runtime context, then produces a structured plan.
- **Execute**: The LLM carries out the plan, potentially making multiple tool-use turns.
- **Summarize**: The LLM condenses the execution trace into a clean, structured output.

Each phase is recorded as a `PhaseResult` containing all turns (`PhaseTurn`) and the phase's final text.

## Next Steps

- [Concepts: PES Engine](../concepts/pes.md) — learn about file contracts and custom PES classes
- [Concepts: Workspace](../concepts/workspace.md) — understand run isolation
- [Concepts: Trajectory](../concepts/trajectory.md) — record and replay runs
- [API Reference: PES](../api/pes.md) — full class documentation
