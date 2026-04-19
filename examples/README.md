# Scrivai Examples

Three end-to-end runnable demos covering PES (M1.5) and Evolution (M2).

## Prerequisites

```bash
pip install scrivai
export ANTHROPIC_API_KEY=sk-ant-...
```

## Examples

| # | Script | Coverage | Time | LLM Calls |
|---|--------|----------|------|-----------|
| 01 | `01_audit_single_doc.py` | AuditorPES checkpoint audit | ~2-3 min | ~3 |
| 02 | `02_generate_with_revision.py` | GeneratorPES template generation | ~1-2 min | ~3 |
| 03 | `03_evolve_skill_workflow.py` | M2 skill evolution workflow | ~3-5 min | 3-10 |

## Running

```bash
python examples/01_audit_single_doc.py
python examples/02_generate_with_revision.py
python examples/02_generate_with_revision.py --render    # render docx
python examples/03_evolve_skill_workflow.py
```

## Output

All outputs go to `/tmp/scrivai-examples/`. Reset: `rm -rf /tmp/scrivai-examples/`

## Using a compatible gateway

```bash
export ANTHROPIC_BASE_URL=https://your-gateway.example.com
export ANTHROPIC_API_KEY=sk-gateway-xxx
export SCRIVAI_DEFAULT_MODEL=your-model-name
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ANTHROPIC_API_KEY not set` | Missing env var | Set `ANTHROPIC_API_KEY` |
| `pes.run` status = `failed` | Gateway unreachable or model unsupported | Check `ANTHROPIC_BASE_URL` and `SCRIVAI_DEFAULT_MODEL` |
