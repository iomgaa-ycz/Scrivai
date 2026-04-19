# Examples

The `examples/` directory contains three end-to-end scripts that demonstrate the main Scrivai workflows.

## Example Scripts

| Script | Description | LLM Calls | Typical Time |
|---|---|---|---|
| `examples/01_audit_single_doc.py` | Audit a single document against a rule set using `AuditorPES`. Produces a findings list and a verdict. | ~6 | ~30 s |
| `examples/02_generate_with_revision.py` | Generate a document from a template using `GeneratorPES`, then self-audit and revise up to 2 times. | ~12 | ~60 s |
| `examples/03_evolve_skill_workflow.py` | Collect failure samples from a trajectory store, run one evolution loop with `run_evolution()`, and inspect the result. | ~30 | ~3 min |

## Prerequisites

```bash
pip install scrivai
export ANTHROPIC_API_KEY=your-key-here
```

## Running the Examples

```bash
# Audit example
python examples/01_audit_single_doc.py

# Generation with self-revision
python examples/02_generate_with_revision.py

# Skill evolution workflow
python examples/03_evolve_skill_workflow.py
```

Each script writes its output to `tests/outputs/examples/<script_name>_<timestamp>.md`.

## Using a Private Gateway

If you route through a gateway (e.g. GLM or MiniMax), set the following variables before running any example:

```bash
export ANTHROPIC_BASE_URL=https://my-gateway.example.com
export ANTHROPIC_API_KEY=my-gateway-key
export SCRIVAI_DEFAULT_MODEL=glm-5.1
```

No code changes are required — the Claude Agent SDK picks up `ANTHROPIC_BASE_URL` automatically.
