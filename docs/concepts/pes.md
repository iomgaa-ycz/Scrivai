# PES Engine

A **PES** (Plan–Execute–Summarize) is the core abstraction in Scrivai. Every interaction with an LLM is wrapped in a PES, which enforces a deterministic three-phase lifecycle.

## The Three Phases

| Phase | Purpose | Output |
|---|---|---|
| **Plan** | The LLM reads the system prompt and runtime context, then generates a step-by-step plan. | `PhaseResult` with plan text |
| **Execute** | The LLM follows the plan, optionally using tools in a multi-turn conversation. | `PhaseResult` with all turns |
| **Summarize** | The LLM distils the execution trace into a clean, structured final output. | `PhaseResult` with structured output |

The three phases map to `PESRun.phases[0]`, `phases[1]`, and `phases[2]`.

## File Contracts

Each built-in PES specifies which keys it reads from `runtime_context` and what it writes to `output`. These contracts are enforced at runtime.

### ExtractorPES

Reads structured fields out of a document.

| `runtime_context` key | Type | Description |
|---|---|---|
| `document_text` | `str` | The raw text to extract from |
| `extraction_schema` | `dict` | Field names mapped to their expected types |

Output: a `dict` matching `extraction_schema`.

### AuditorPES

Reviews a document against a set of rules and produces findings.

| `runtime_context` key | Type | Description |
|---|---|---|
| `document_text` | `str` | The document to audit |
| `rules` | `list[str]` | Audit criteria as plain-text rules |

Output: a `dict` with keys `findings` (list) and `verdict` (str).

### GeneratorPES

Generates a document from a template and input variables.

| `runtime_context` key | Type | Description |
|---|---|---|
| `template` | `str` | A Markdown template with `{{variable}}` placeholders |
| `inputs` | `dict` | Values to substitute into the template |

Output: the rendered document as a `str`.

## Custom PES via Subclassing

To create your own PES, subclass `BasePES` and implement `_build_plan_prompt` and `_parse_output`:

```python
from scrivai.pes.base import BasePES
from scrivai import PESConfig, ModelConfig, PhaseConfig

class TranslatorPES(BasePES):
    """Translate a document from one language to another."""

    def _build_plan_prompt(self, runtime_context: dict) -> str:
        src = runtime_context["source_language"]
        tgt = runtime_context["target_language"]
        return f"Translate the following text from {src} to {tgt}."

    def _parse_output(self, raw: str) -> str:
        return raw.strip()


config = PESConfig(
    name="translator",
    model=ModelConfig(model="claude-sonnet-4-20250514"),
    phases=[
        PhaseConfig(name="plan"),
        PhaseConfig(name="execute"),
        PhaseConfig(name="summarize"),
    ],
)

pes = TranslatorPES(config=config)
result = pes.run(
    runtime_context={
        "document_text": "Hello, world!",
        "source_language": "English",
        "target_language": "Spanish",
    }
)
print(result.output)  # 'Hola, mundo!'
```

## See Also

- [API Reference: PES](../api/pes.md)
- [Models: PESConfig, PhaseConfig, PESRun](../api/models.md)
