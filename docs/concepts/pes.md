# PES Engine

A **PES** (Plan–Execute–Summarize) is the core abstraction in Scrivai. Every LLM interaction is wrapped in a three-phase pipeline with file-contract enforcement.

## The Three Phases

| Phase | Purpose | File Contract |
|---|---|---|
| **Plan** | Read inputs, produce a step-by-step plan | `working/plan.md` + `working/plan.json` |
| **Execute** | Follow the plan, produce per-item findings | `working/findings/<id>.json` |
| **Summarize** | Merge findings into a single structured output | `working/output.json` |

Phase results are stored in `PESRun.phase_results["plan"]`, `phase_results["execute"]`, and `phase_results["summarize"]`.

## Configuration

PES behavior is defined in a YAML config loaded via `load_pes_config()`:

```yaml
name: auditor
display_name: Auditor — Compliance Audit
prompt_text: |
  You are a compliance audit agent. ...
default_skills:
  - available-tools
phases:
  plan:
    allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    max_turns: 10
    max_retries: 1
    required_outputs: [plan.md, plan.json]
  execute:
    allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    max_turns: 25
    max_retries: 1
    required_outputs:
      - {path: "findings", min_files: 1, pattern: "*.json"}
  summarize:
    allowed_tools: ["Bash", "Read", "Write"]
    max_turns: 10
    max_retries: 1
    required_outputs: [output.json]
```

Key fields:

- `prompt_text` — base system prompt sent to the Agent SDK
- `phases` — a dict of three `PhaseConfig` entries (plan/execute/summarize)
- `external_cli_tools` — Bash commands the Agent is allowed to execute (prompt-level constraint)

## Prompt Management

Since v0.1.7, phase-specific instructions are managed by **Jinja2 templates** via `PromptManager`. Each built-in PES has 3 templates (`{name}_{phase}.j2`) that control exactly what the Agent sees:

```
scrivai/pes/prompts/
├── prompt_spec.yaml          # Variable contracts per template
├── templates/                # Jinja2 templates
│   ├── auditor_plan.j2
│   ├── auditor_execute.j2
│   └── ...
└── fragments/                # Shared rules injected into all templates
    └── workspace_rules.md
```

Templates reference only the variables they need (e.g. `{{ workspace.working_dir }}`). Internal paths like `output_dir` are never exposed to the Agent.

## Built-in PES Implementations

### ExtractorPES

Extract structured data from documents.

| `runtime_context` key | Type | Required | Description |
|---|---|---|---|
| `output_schema` | `type[BaseModel]` | Yes | Pydantic model for output validation |

File contract: plan → `plan.json` with `items_to_extract` list; execute → `findings/<id>.json` per item; summarize → `output.json` validated against `output_schema`.

### AuditorPES

Audit a document against a checklist of checkpoints.

| `runtime_context` key | Type | Required | Description |
|---|---|---|---|
| `output_schema` | `type[BaseModel]` | Yes | Pydantic model for audit output |
| `verdict_levels` | `list[str]` | No | Default: `["合格", "不合格", "不适用", "需要澄清"]` |
| `evidence_required` | `bool` | No | Default: `True` |

Prerequisite: place `data/checkpoints.json` in workspace before running.

### GeneratorPES

Fill a docxtpl template with LLM-gathered content.

| `runtime_context` key | Type | Required | Description |
|---|---|---|---|
| `template_path` | `Path` | Yes | Path to docxtpl `.docx` template |
| `context_schema` | `type[BaseModel]` | Yes | Pydantic model for template context |
| `auto_render` | `bool` | No | If True, render `output/final.docx` |

## Custom PES via Subclassing

To create a custom PES, subclass `BasePES` and override the extension points:

```python
from pathlib import Path
from pydantic import BaseModel
from scrivai import (
    BasePES, ModelConfig, WorkspaceSpec,
    build_workspace_manager, load_pes_config,
)

class MyOutput(BaseModel):
    summary: str

class MyPES(BasePES):
    """Custom PES with additional execution context."""

    async def build_execution_context(self, phase, run):
        if phase == "plan":
            return {"custom_field": "injected into template context"}
        return {}

# 1. Create workspace
ws_mgr = build_workspace_manager()
spec = WorkspaceSpec(
    run_id="my-run-001",
    project_root=Path("/path/to/project"),
    data_inputs={"source.md": Path("/path/to/source.md")},
    extra_env={"MY_DB_PATH": "/data/my.db"},  # passed to Agent subprocess
)
ws = ws_mgr.create(spec)

# 2. Load config and run
config = load_pes_config(Path("my_pes.yaml"))
model = ModelConfig(model="claude-sonnet-4-20250514")
pes = MyPES(config=config, model=model, workspace=ws,
            runtime_context={"output_schema": MyOutput})
run = await pes.run("Process source.md and produce a summary")

print(run.status)        # "completed"
print(run.final_output)  # {"summary": "..."}
```

Extension points (override as needed):

| Method | Purpose | Default |
|---|---|---|
| `build_execution_context()` | Inject extra variables into the template context | Returns `{}` |
| `build_phase_prompt()` | Full control over prompt assembly | Delegates to `PromptManager` |
| `postprocess_phase_result()` | Validate/transform LLM output after each phase | No-op |
| `validate_phase_outputs()` | Check file-contract outputs exist | Validates `required_outputs` |

## See Also

- [API Reference: PES](../api/pes.md)
- [Models: PESConfig, PhaseConfig, PESRun](../api/models.md)
- [Concepts: Workspace](workspace.md)
