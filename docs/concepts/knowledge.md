# Knowledge

Scrivai provides three first-class library types for injecting domain knowledge into PES runs. All three are backed by the `qmd` semantic retrieval engine.

## Library Types

| Type | Class | Purpose |
|---|---|---|
| **Rules** | `RuleLibrary` | Audit criteria, constraints, and compliance requirements |
| **Cases** | `CaseLibrary` | Reference examples (few-shot demonstrations, precedents) |
| **Templates** | `TemplateLibrary` | Document templates with `{{variable}}` placeholders |

## Setup via `build_libraries`

The recommended way to initialise all three libraries at once is `build_libraries`, which reads collection paths from a config dict:

```python
from scrivai import build_libraries, build_qmd_client_from_config

# Build the qmd client from project config
qmd_client = build_qmd_client_from_config(
    config={"embedding_model": "text-embedding-3-small"}
)

# Build all three libraries
rule_lib, case_lib, template_lib = build_libraries(
    qmd_client=qmd_client,
    rules_path="knowledge/rules/",
    cases_path="knowledge/cases/",
    templates_path="knowledge/templates/",
)
```

## Search Interface

Each library exposes a `.search(query, top_k)` method that returns semantically ranked results:

```python
# Find the most relevant audit rules for a query
results = rule_lib.search("financial disclosure requirements", top_k=5)
for result in results:
    print(result.chunk_text)
    print(result.score)

# Find reference cases
cases = case_lib.search("contract termination clause", top_k=3)

# Find a matching template
templates = template_lib.search("engineering inspection report", top_k=1)
```

## Injecting Knowledge into a PES

Pass search results into `runtime_context` so the PES can use them in its system prompt:

```python
rules = rule_lib.search("safety compliance", top_k=5)
result = pes.run(
    runtime_context={
        "document_text": document,
        "applicable_rules": [r.chunk_text for r in rules],
    }
)
```

## See Also

- [API Reference: Knowledge](../api/knowledge.md)
