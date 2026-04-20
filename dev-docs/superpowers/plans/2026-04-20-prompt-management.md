# Prompt Management + Issue #8 Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `json.dumps(context)` prompt construction with a Jinja2 template-based PromptManager (borrowed from Herald2), fix the extra_env/output_dir issues from GitHub issue #8, and eliminate the system_prompt duplication bug.

**Architecture:** Three-layer prompt system: YAML `prompt_spec.yaml` defines variable contracts per PES/phase, Jinja2 `.j2` templates control what the Agent sees, and `.md` fragments provide shared rules. BasePES delegates prompt rendering to PromptManager; `_call_sdk_query` passes `prompt_text` as `system_prompt` only (no duplication). WorkspaceHandle gains `extra_env` to close the env chain.

**Tech Stack:** Python 3.11, Jinja2 (new dep), Pydantic v2, pytest-asyncio

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `scrivai/pes/prompts/__init__.py` | Export `PromptManager` |
| `scrivai/pes/prompts/manager.py` | Template loading, context validation, prompt rendering |
| `scrivai/pes/prompts/prompt_spec.yaml` | Per-PES/phase variable contracts |
| `scrivai/pes/prompts/templates/auditor_plan.j2` | Auditor plan phase template |
| `scrivai/pes/prompts/templates/auditor_execute.j2` | Auditor execute phase template |
| `scrivai/pes/prompts/templates/auditor_summarize.j2` | Auditor summarize phase template |
| `scrivai/pes/prompts/templates/extractor_plan.j2` | Extractor plan phase template |
| `scrivai/pes/prompts/templates/extractor_execute.j2` | Extractor execute phase template |
| `scrivai/pes/prompts/templates/extractor_summarize.j2` | Extractor summarize phase template |
| `scrivai/pes/prompts/templates/generator_plan.j2` | Generator plan phase template |
| `scrivai/pes/prompts/templates/generator_execute.j2` | Generator execute phase template |
| `scrivai/pes/prompts/templates/generator_summarize.j2` | Generator summarize phase template |
| `scrivai/pes/prompts/fragments/workspace_rules.md` | Shared workspace/file-contract rules |
| `tests/contract/test_prompt_manager.py` | PromptManager unit tests |

### Modified Files
| File | Change |
|------|--------|
| `pyproject.toml` | Add `jinja2>=3.1` dependency |
| `scrivai/models/workspace.py:65-76` | `WorkspaceHandle`: add `extra_env` field |
| `scrivai/workspace/manager.py:101-109` | Pass `extra_env` when constructing WorkspaceHandle |
| `scrivai/models/pes.py:49-69` | `PhaseConfig`: remove `additional_system_prompt` |
| `scrivai/pes/base.py:196-224` | `build_phase_prompt`: delegate to PromptManager |
| `scrivai/pes/base.py:262-300` | `_call_sdk_query`: add `extra_env`, fix `system_prompt` |
| `scrivai/pes/base.py:340-400` | `_run_phase`: new context construction |
| `scrivai/pes/base.py:543-554` | Remove `_merge_context` (no longer needed) |
| `scrivai/pes/base.py:585-591` | `_workspace_payload`: remove `output_dir` |
| `scrivai/agents/auditor.yaml` | Remove `prompt_text` phase instructions, keep structural config |
| `scrivai/agents/extractor.yaml` | Same |
| `scrivai/agents/generator.yaml` | Same |
| `scrivai/__init__.py` | Export `PromptManager` |
| `tests/contract/test_base_pes.py` | Update `_make_workspace` for `extra_env`, update prompt tests |
| `tests/contract/test_workspace.py` | Add `extra_env` round-trip test |
| `tests/contract/conftest.py` | Update `sample_pes_config_yaml` (remove `additional_system_prompt`) |

---

### Task 1: Add jinja2 Dependency

**Files:**
- Modify: `pyproject.toml:26` (dependencies list)

- [ ] **Step 1: Add jinja2 to dependencies**

In `pyproject.toml`, add `"jinja2>=3.1"` to the `dependencies` list:

```toml
dependencies = [
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "qmd>=0.1.2",
    "pluggy>=1.4",
    "requests>=2.28",
    "docxtpl>=0.16",
    "claude-agent-sdk>=0.1.61",
    "jinja2>=3.1",
]
```

- [ ] **Step 2: Install and verify**

Run: `conda run -n scrivai pip install -e ".[dev]"`
Expected: jinja2 installs (likely already present as transitive dep of docxtpl)

- [ ] **Step 3: Verify import**

Run: `conda run -n scrivai python -c "import jinja2; print(jinja2.__version__)"`
Expected: prints version >= 3.1

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add jinja2 as explicit dependency for prompt template engine"
```

---

### Task 2: PromptManager Core

**Files:**
- Create: `scrivai/pes/prompts/__init__.py`
- Create: `scrivai/pes/prompts/manager.py`
- Test: `tests/contract/test_prompt_manager.py`

- [ ] **Step 1: Create package init**

```python
"""Prompt management: Jinja2 template rendering with contract validation."""

from scrivai.pes.prompts.manager import PromptManager

__all__ = ["PromptManager"]
```

- [ ] **Step 2: Write failing tests for PromptManager**

```python
"""PromptManager contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scrivai.pes.prompts.manager import PromptManager


@pytest.fixture
def prompt_dir(tmp_path: Path) -> dict[str, Path]:
    """Set up a minimal prompt directory structure."""
    templates = tmp_path / "templates"
    fragments = tmp_path / "fragments"
    templates.mkdir()
    fragments.mkdir()

    # Fragment
    (fragments / "rules.md").write_text(
        "## Rules\n\nFollow the rules.", encoding="utf-8"
    )

    # Template
    (templates / "test_plan.j2").write_text(
        "{{ static_fragments_text }}\n\nPHASE = plan\n\nTask: {{ task_prompt }}\n\n"
        "Working dir: {{ workspace.working_dir }}",
        encoding="utf-8",
    )

    # Spec
    spec = tmp_path / "prompt_spec.yaml"
    spec.write_text(
        "templates:\n"
        "  test_plan:\n"
        "    required_context: [task_prompt, workspace]\n"
        "    static_fragments: [rules]\n"
        "    artifacts: []\n",
        encoding="utf-8",
    )

    return {
        "templates": templates,
        "fragments": fragments,
        "spec": spec,
    }


@pytest.fixture
def pm(prompt_dir: dict[str, Path]) -> PromptManager:
    return PromptManager(
        template_dir=prompt_dir["templates"],
        fragments_dir=prompt_dir["fragments"],
        spec_path=prompt_dir["spec"],
    )


def test_build_prompt_renders_template(pm: PromptManager) -> None:
    """build_prompt renders Jinja2 template with context variables."""
    result = pm.build_prompt(
        operation="test",
        phase="plan",
        context={
            "task_prompt": "audit this document",
            "workspace": {"working_dir": "/tmp/ws/working"},
        },
    )
    assert "## Rules" in result
    assert "PHASE = plan" in result
    assert "audit this document" in result
    assert "/tmp/ws/working" in result


def test_validate_context_raises_on_missing(pm: PromptManager) -> None:
    """validate_context raises ValueError for missing required fields."""
    with pytest.raises(ValueError, match="task_prompt"):
        pm.build_prompt(
            operation="test",
            phase="plan",
            context={"workspace": {"working_dir": "/tmp"}},
        )


def test_validate_context_raises_on_none(pm: PromptManager) -> None:
    """validate_context raises ValueError when required field is None."""
    with pytest.raises(ValueError, match="task_prompt"):
        pm.build_prompt(
            operation="test",
            phase="plan",
            context={"task_prompt": None, "workspace": {"working_dir": "/tmp"}},
        )


def test_unknown_template_raises(pm: PromptManager) -> None:
    """Requesting a non-existent template raises an error."""
    with pytest.raises(ValueError, match="未定义模板"):
        pm.build_prompt(
            operation="nonexistent",
            phase="plan",
            context={"task_prompt": "x", "workspace": {}},
        )


def test_load_fragment(pm: PromptManager) -> None:
    """load_fragment reads .md file content."""
    content = pm.load_fragment("rules")
    assert "## Rules" in content


def test_load_fragment_missing_raises(pm: PromptManager) -> None:
    """load_fragment raises FileNotFoundError for missing fragment."""
    with pytest.raises(FileNotFoundError):
        pm.load_fragment("nonexistent")


def test_spec_validation_rejects_bad_structure(tmp_path: Path) -> None:
    """_load_prompt_spec rejects YAML without proper structure."""
    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text("not_templates: {}", encoding="utf-8")
    templates = tmp_path / "t"
    fragments = tmp_path / "f"
    templates.mkdir()
    fragments.mkdir()

    with pytest.raises(ValueError, match="templates"):
        PromptManager(
            template_dir=templates,
            fragments_dir=fragments,
            spec_path=bad_spec,
        )


def test_optional_context_fields_not_required(prompt_dir: dict[str, Path]) -> None:
    """Template can reference optional fields via Jinja2 defaults without requiring them in spec."""
    (prompt_dir["templates"] / "opt_plan.j2").write_text(
        "{% if cli_tools %}tools: {{ cli_tools | join(', ') }}{% endif %}\n"
        "Task: {{ task_prompt }}",
        encoding="utf-8",
    )
    spec = prompt_dir["spec"]
    import yaml

    data = yaml.safe_load(spec.read_text())
    data["templates"]["opt_plan"] = {
        "required_context": ["task_prompt"],
        "static_fragments": [],
        "artifacts": [],
    }
    spec.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    pm = PromptManager(
        template_dir=prompt_dir["templates"],
        fragments_dir=prompt_dir["fragments"],
        spec_path=spec,
    )
    result = pm.build_prompt("opt", "plan", context={"task_prompt": "hello"})
    assert "Task: hello" in result
    assert "tools:" not in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n scrivai pytest tests/contract/test_prompt_manager.py -v`
Expected: ImportError — `scrivai.pes.prompts.manager` does not exist yet

- [ ] **Step 4: Implement PromptManager**

File: `scrivai/pes/prompts/manager.py`

```python
"""PromptManager — Jinja2 template-based prompt assembly with contract validation.

Adapted from Herald2's PromptManager V3. Three-layer architecture:
- prompt_spec.yaml: declares required_context per operation/phase
- templates/*.j2: Jinja2 templates control what the Agent sees
- fragments/*.md: shared static text injected into templates
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from loguru import logger


class PromptManager:
    """Jinja2 prompt assembler with contract validation.

    Args:
        template_dir: Directory containing ``{operation}_{phase}.j2`` files.
        fragments_dir: Directory containing shared ``.md`` fragment files.
        spec_path: Path to ``prompt_spec.yaml`` defining variable contracts.
    """

    def __init__(
        self,
        template_dir: Path,
        fragments_dir: Path,
        spec_path: Path,
    ) -> None:
        self.template_dir = Path(template_dir)
        self.fragments_dir = Path(fragments_dir)
        self.spec_path = Path(spec_path)
        self._prompt_spec = self._load_prompt_spec(self.spec_path)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def build_prompt(
        self,
        operation: str,
        phase: str,
        context: dict[str, Any],
    ) -> str:
        """Render a prompt from template + context + fragments.

        Args:
            operation: PES type name (e.g. ``"auditor"``).
            phase: Phase name (``"plan"`` / ``"execute"`` / ``"summarize"``).
            context: Variables available to the template.

        Returns:
            Fully rendered prompt string.

        Raises:
            ValueError: If required context fields are missing or spec is invalid.
            jinja2.TemplateNotFound: If the template file doesn't exist.
        """
        template_key = f"{operation}_{phase}"
        template_spec = self.get_template_spec(operation, phase)
        self.validate_context(template_key, template_spec, context)

        static_fragments_text = self._build_static_fragments_text(template_spec)

        template_name = f"{template_key}.j2"
        try:
            template = self.env.get_template(template_name)
        except TemplateNotFound:
            logger.error("模板文件不存在: %s", template_name)
            raise

        template_context = {
            **context,
            "static_fragments_text": static_fragments_text,
        }
        return template.render(**template_context)

    def get_template_spec(self, operation: str, phase: str) -> dict[str, Any]:
        """Read the prompt_spec entry for an operation/phase combination.

        Raises:
            ValueError: If the template key is not defined in prompt_spec.
        """
        template_key = f"{operation}_{phase}"
        templates = self._prompt_spec["templates"]
        template_spec = templates.get(template_key)
        if not isinstance(template_spec, dict):
            raise ValueError(f"prompt_spec 未定义模板: {template_key}")
        return template_spec

    def validate_context(
        self,
        template_key: str,
        template_spec: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """Validate that all required_context fields are present and non-None."""
        required_fields = self._get_string_list_field(template_spec, "required_context")
        missing = [
            f for f in required_fields
            if f not in context or context[f] is None
        ]
        if missing:
            raise ValueError(
                f"Prompt 上下文缺少必填字段: template={template_key}, missing={missing}"
            )

    def load_fragment(self, fragment_name: str) -> str:
        """Load a static .md fragment by name (with or without .md suffix).

        Raises:
            FileNotFoundError: If the fragment file does not exist.
        """
        normalized = fragment_name.removesuffix(".md")
        path = self.fragments_dir / f"{normalized}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt fragment 不存在: {path}")
        return path.read_text(encoding="utf-8").strip()

    def _build_static_fragments_text(self, template_spec: dict[str, Any]) -> str:
        """Concatenate static fragment files listed in the spec."""
        names = self._get_string_list_field(template_spec, "static_fragments")
        if not names:
            return ""
        return "\n\n".join(self.load_fragment(n) for n in names)

    def _load_prompt_spec(self, spec_path: Path) -> dict[str, Any]:
        """Load and validate prompt_spec.yaml structure."""
        if not spec_path.exists():
            raise FileNotFoundError(f"prompt_spec.yaml 不存在: {spec_path}")

        try:
            with open(spec_path, encoding="utf-8") as f:
                spec = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"prompt_spec.yaml YAML 解析失败: {spec_path}") from e

        if not isinstance(spec, dict):
            raise ValueError(f"prompt_spec.yaml 顶层必须是映射: {spec_path}")

        templates = spec.get("templates")
        if not isinstance(templates, dict):
            raise ValueError(f"prompt_spec.yaml 缺少合法 templates 映射: {spec_path}")

        for key, tspec in templates.items():
            if not isinstance(tspec, dict):
                raise ValueError(f"prompt_spec 模板配置必须是映射: {key}")
            expected_keys = {"required_context", "static_fragments", "artifacts"}
            if set(tspec.keys()) != expected_keys:
                raise ValueError(
                    f"prompt_spec 模板字段非法: {key} (expected {expected_keys}, got {set(tspec.keys())})"
                )
            for field_name in expected_keys:
                self._get_string_list_field(tspec, field_name)

        return spec

    @staticmethod
    def _get_string_list_field(template_spec: dict[str, Any], field_name: str) -> list[str]:
        """Read and validate a list-of-strings field from a template spec."""
        raw = template_spec.get(field_name, [])
        if not isinstance(raw, list):
            raise ValueError(f"prompt_spec 字段必须是列表: {field_name}")
        if not all(isinstance(item, str) and item.strip() for item in raw):
            raise ValueError(f"prompt_spec 字段必须是非空字符串列表: {field_name}")
        return raw
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n scrivai pytest tests/contract/test_prompt_manager.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add scrivai/pes/prompts/__init__.py scrivai/pes/prompts/manager.py tests/contract/test_prompt_manager.py
git commit -m "feat(pes): add PromptManager with Jinja2 template rendering and contract validation"
```

---

### Task 3: Prompt Spec, Fragments, and Templates

**Files:**
- Create: `scrivai/pes/prompts/prompt_spec.yaml`
- Create: `scrivai/pes/prompts/fragments/workspace_rules.md`
- Create: `scrivai/pes/prompts/templates/auditor_plan.j2`
- Create: `scrivai/pes/prompts/templates/auditor_execute.j2`
- Create: `scrivai/pes/prompts/templates/auditor_summarize.j2`
- Create: `scrivai/pes/prompts/templates/extractor_plan.j2`
- Create: `scrivai/pes/prompts/templates/extractor_execute.j2`
- Create: `scrivai/pes/prompts/templates/extractor_summarize.j2`
- Create: `scrivai/pes/prompts/templates/generator_plan.j2`
- Create: `scrivai/pes/prompts/templates/generator_execute.j2`
- Create: `scrivai/pes/prompts/templates/generator_summarize.j2`

- [ ] **Step 1: Create prompt_spec.yaml**

```yaml
# Scrivai Prompt Spec — variable contracts per PES/phase
# Each entry defines: required_context (validated before render),
# static_fragments (injected as static_fragments_text), artifacts (future use).

templates:

  # ── Auditor ──
  auditor_plan:
    required_context: [task_prompt, workspace]
    static_fragments: [workspace_rules]
    artifacts: []

  auditor_execute:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []

  auditor_summarize:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []

  # ── Extractor ──
  extractor_plan:
    required_context: [task_prompt, workspace]
    static_fragments: [workspace_rules]
    artifacts: []

  extractor_execute:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []

  extractor_summarize:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []

  # ── Generator ──
  generator_plan:
    required_context: [task_prompt, workspace]
    static_fragments: [workspace_rules]
    artifacts: []

  generator_execute:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []

  generator_summarize:
    required_context: [task_prompt, workspace, previous_phase_output]
    static_fragments: [workspace_rules]
    artifacts: []
```

- [ ] **Step 2: Create workspace_rules.md fragment**

```markdown
## Workspace Rules

All file operations are relative to your current working directory (cwd).

- `data/` — read-only input data pre-placed by the framework
- `findings/` — intermediate artifacts you create under cwd
- `output.json` — final output file you create under cwd

Do NOT write files outside cwd. Do NOT use absolute paths.
```

- [ ] **Step 3: Create auditor templates**

`auditor_plan.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = plan

Read `data/checkpoints.json` and the source document(s) referenced in the task prompt.
Produce TWO files in your working directory:

1. `plan.md` — human-readable audit plan (which documents to inspect per checkpoint).

2. `plan.json` — strict JSON with this shape:
   {
     "audits": [
       {"cp_id": "<from checkpoints.json>", "strategy": "how you'll audit"},
       ...
     ]
   }
   Every cp_id from `data/checkpoints.json` must appear in plan.json.audits.

Respond "plan done" once both files are valid.

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}
```

`auditor_execute.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = execute

For each cp_id in `data/checkpoints.json`, produce exactly one finding file:
`findings/<cp_id>.json` with this shape:
  {
    "checkpoint_id": "<cp-id>",
    "verdict": "合格" | "不合格" | "不适用" | "需要澄清",
    "evidence": [{"chunk_id": "...", "quote": "..."}],
    "reasoning": "why this verdict"
  }

`verdict` must match one of the four values (unless caller overrode
`verdict_levels`). `evidence` should be non-empty unless `evidence_required`
is explicitly disabled by the caller.

Respond "execute done" once every cp_id has a findings file.

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## PLAN OUTPUT (from plan phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

`auditor_summarize.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = summarize

Merge `findings/*.json` into `output.json` with shape:
  {
    "findings": [...all findings from findings/ ...],
    "summary": {"total": <int>, "合格": <int>, "不合格": <int>, ...}
  }

The output structure is validated by the framework against the caller's
output_schema (pydantic). Respond "summarize done".

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## FINDINGS (from execute phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

- [ ] **Step 4: Create extractor templates**

`extractor_plan.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = plan

Read the task prompt and any referenced source documents under `data/`.
Produce TWO files in your working directory:

1. `plan.md` — human-readable extraction plan (sections, rationale).

2. `plan.json` — strict JSON with this shape:
   {
     "items_to_extract": [
       {"id": "<unique-slug>", "description": "what to extract"},
       ...
     ]
   }

   The `id` field names the finding file in the execute phase
   (findings/<id>.json), so use stable slugs (snake_case, no spaces).

When both files exist and plan.json is valid JSON, respond "plan done".

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}
```

`extractor_execute.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = execute

For each entry in `plan.json.items_to_extract`, produce exactly one
finding file: `findings/<id>.json`.

Each finding is free-form JSON (structured as needed by the downstream
summarize phase). Treat source references carefully; include char offsets
or chunk IDs when possible.

When every plan item has a matching findings/<id>.json, respond "execute done".

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## PLAN OUTPUT (from plan phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

`extractor_summarize.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = summarize

Read all files under `findings/` and merge them into ONE file:
`output.json`.

The output structure MUST match the pydantic schema provided by the
caller at runtime (validated by the framework after this phase).
If the schema is unknown, default to:
  {"items": [...merged findings...]}

Respond "summarize done" when output.json is written.

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## FINDINGS (from execute phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

- [ ] **Step 5: Create generator templates**

`generator_plan.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = plan

The template placeholders are:
{% if placeholders %}
{% for ph in placeholders %}
- `{{ ph }}`
{% endfor %}
{% else %}
(no placeholders detected)
{% endif %}

Produce TWO files in your working directory:

1. `plan.md` — human-readable material-gathering plan per placeholder.

2. `plan.json` — strict JSON with this shape:
   {
     "fills": [
       {"placeholder": "<name>", "source": "where you'll draw content from"},
       ...
     ]
   }
   Every placeholder listed above must appear in plan.json.fills.

Respond "plan done" once both files are valid.

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}
```

`generator_execute.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = execute

For each placeholder, produce exactly one file:
`findings/<placeholder>.json` with this shape:
  {
    "placeholder": "<name>",
    "content": "<filled content, possibly multiline markdown>",
    "source_refs": [{"chunk_id": "...", "quote": "..."}]
  }

Respond "execute done" once every placeholder has a findings file.

{% if cli_tools %}
## ALLOWED EXTERNAL CLI TOOLS

You have access to the following external CLI commands via Bash:
{% for cmd in cli_tools %}
- `{{ cmd }}`
{% endfor %}

Do NOT run Bash commands outside this whitelist.
{% endif %}

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## PLAN OUTPUT (from plan phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

`generator_summarize.j2`:
```jinja2
{{ static_fragments_text }}

PHASE = summarize

Merge findings into `output.json` with shape:
  {
    "context": {"<placeholder>": "<content>", ...},
    "sections": [
      {"placeholder": "<name>", "content": "...", "source_refs": [...]},
      ...
    ]
  }

The `context` dict is what docxtpl uses to render the template if the
caller enabled `auto_render=True`. Respond "summarize done".

## TASK

{{ task_prompt }}

{% if previous_phase_output %}
## FINDINGS (from execute phase)

{{ previous_phase_output | tojson(indent=2) }}
{% endif %}
```

- [ ] **Step 6: Smoke-test that PromptManager can load real spec and render a template**

Add to `tests/contract/test_prompt_manager.py`:

```python
def test_real_prompt_spec_loads() -> None:
    """Verify the actual prompt_spec.yaml shipped with scrivai loads correctly."""
    base = Path(__file__).resolve().parent.parent.parent / "scrivai" / "pes" / "prompts"
    pm = PromptManager(
        template_dir=base / "templates",
        fragments_dir=base / "fragments",
        spec_path=base / "prompt_spec.yaml",
    )
    result = pm.build_prompt(
        "auditor",
        "plan",
        context={
            "task_prompt": "Audit data/doc.md against checkpoints",
            "workspace": {"working_dir": "/tmp/ws/working", "data_dir": "/tmp/ws/data"},
        },
    )
    assert "PHASE = plan" in result
    assert "Workspace Rules" in result
    assert "Audit data/doc.md" in result
    assert "output_dir" not in result
```

- [ ] **Step 7: Run tests**

Run: `conda run -n scrivai pytest tests/contract/test_prompt_manager.py -v`
Expected: All tests PASS (including the real spec smoke test)

- [ ] **Step 8: Commit**

```bash
git add scrivai/pes/prompts/prompt_spec.yaml scrivai/pes/prompts/fragments/ scrivai/pes/prompts/templates/
git add tests/contract/test_prompt_manager.py
git commit -m "feat(pes): add prompt_spec, fragments, and 9 Jinja2 templates for all built-in PES"
```

---

### Task 4: WorkspaceHandle extra_env (Issue #8 Fix — Part 1)

**Files:**
- Modify: `scrivai/models/workspace.py:65-76`
- Modify: `scrivai/workspace/manager.py:101-109`
- Test: `tests/contract/test_workspace.py`

- [ ] **Step 1: Write failing test for extra_env round-trip**

Append to `tests/contract/test_workspace.py`:

```python
def test_extra_env_roundtrip(ws_mgr, fake_project_root: Path, tmp_path: Path) -> None:
    """extra_env on WorkspaceSpec should be accessible on the returned WorkspaceHandle."""
    from scrivai import WorkspaceSpec

    env = {"QMD_COLLECTION": "tender_001", "QMD_DB_PATH": "/data/qmd.db"}
    spec = WorkspaceSpec(
        run_id="env-test",
        project_root=fake_project_root,
        extra_env=env,
    )
    handle = ws_mgr.create(spec)
    assert handle.extra_env == env


def test_extra_env_defaults_empty(ws_mgr, fake_project_root: Path, tmp_path: Path) -> None:
    """WorkspaceHandle.extra_env defaults to empty dict when not specified."""
    from scrivai import WorkspaceSpec

    spec = WorkspaceSpec(run_id="noenv-test", project_root=fake_project_root)
    handle = ws_mgr.create(spec)
    assert handle.extra_env == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n scrivai pytest tests/contract/test_workspace.py::test_extra_env_roundtrip -v`
Expected: FAIL — `WorkspaceHandle` has no field `extra_env`

- [ ] **Step 3: Add extra_env to WorkspaceHandle**

In `scrivai/models/workspace.py`, add the field to `WorkspaceHandle`:

```python
class WorkspaceHandle(BaseModel):
    """Reference to an existing workspace; used by both the business layer and PES."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    root_dir: Path = Field(..., description="Workspace root directory (contains working / data / output / logs).")
    working_dir: Path = Field(..., description="Agent cwd (contains .claude/skills and .claude/agents).")
    data_dir: Path
    output_dir: Path
    logs_dir: Path
    snapshot: WorkspaceSnapshot
    extra_env: dict[str, str] = Field(
        default_factory=dict,
        description="Additional environment variables to pass to the Agent SDK subprocess.",
    )
```

- [ ] **Step 4: Pass extra_env in LocalWorkspaceManager.create()**

In `scrivai/workspace/manager.py`, add `extra_env=spec.extra_env` to the `WorkspaceHandle(...)` constructor call (around line 101-109):

```python
            return WorkspaceHandle(
                run_id=spec.run_id,
                root_dir=root,
                working_dir=working,
                data_dir=data,
                output_dir=output,
                logs_dir=logs,
                snapshot=snapshot,
                extra_env=spec.extra_env,
            )
```

- [ ] **Step 5: Run tests**

Run: `conda run -n scrivai pytest tests/contract/test_workspace.py -v`
Expected: All tests PASS including the two new ones

- [ ] **Step 6: Update all test helpers that construct WorkspaceHandle**

Many test files construct `WorkspaceHandle(...)` directly. Add `extra_env={}` is **not needed** since it has a default. Verify existing tests still pass:

Run: `conda run -n scrivai pytest tests/contract/test_base_pes.py tests/contract/test_base_pes_sdk.py tests/contract/test_auditor_pes.py tests/contract/test_extractor_pes.py tests/contract/test_generator_pes.py -v`
Expected: All PASS (default `extra_env={}` is backward-compatible)

- [ ] **Step 7: Commit**

```bash
git add scrivai/models/workspace.py scrivai/workspace/manager.py tests/contract/test_workspace.py
git commit -m "feat(workspace): add extra_env field to WorkspaceHandle, close issue #8 断点A"
```

---

### Task 5: BasePES Refactor — PromptManager Integration

**Files:**
- Modify: `scrivai/pes/base.py:80-102` (constructor)
- Modify: `scrivai/pes/base.py:196-224` (build_phase_prompt)
- Modify: `scrivai/pes/base.py:340-400` (_run_phase context construction)
- Modify: `scrivai/pes/base.py:543-554` (remove _merge_context)
- Modify: `scrivai/pes/base.py:585-591` (_workspace_payload: remove output_dir)
- Modify: `scrivai/models/pes.py:49-69` (PhaseConfig: remove additional_system_prompt)
- Test: `tests/contract/test_base_pes.py`

- [ ] **Step 1: Write failing test — build_phase_prompt uses PromptManager**

Add to `tests/contract/test_base_pes.py`:

```python
@pytest.mark.asyncio
async def test_build_phase_prompt_uses_template(tmp_path: Path) -> None:
    """build_phase_prompt should render via PromptManager, not json.dumps."""
    workspace = _make_workspace(tmp_path)
    config = _make_config()
    pes = MockPES(config=config, workspace=workspace)
    run = _make_run()

    prompt = await pes.build_phase_prompt(
        phase="plan",
        phase_cfg=config.phases["plan"],
        context={
            "task_prompt": "audit this doc",
            "workspace": {"working_dir": str(workspace.working_dir), "data_dir": str(workspace.data_dir)},
        },
        task_prompt="audit this doc",
    )
    # Should NOT contain raw json.dumps output
    assert '"attempt_no"' not in prompt or "PHASE" in prompt
```

- [ ] **Step 2: Remove additional_system_prompt from PhaseConfig**

In `scrivai/models/pes.py`, remove the field:

```python
class PhaseConfig(BaseModel):
    """Configuration for a single phase (plan, execute, or summarize)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Phase name: one of plan / execute / summarize.",
    )
    allowed_tools: list[str] = Field(..., description="SDK allowed_tools list.")
    max_turns: int = Field(default=10, description="Maximum Agent interaction turns within a single query.")
    max_retries: int = Field(default=1, description="Phase-level retry count (L2 retry).")
    permission_mode: str = Field(default="default", description="SDK permission_mode.")
    required_outputs: list[Union[str, dict[str, Any]]] = Field(
        default_factory=list,
        description=(
            "Required output rules: a string path (file must exist) or a directory rule "
            "{'path':'findings/','min_files':1,'pattern':'*.json'}."
        ),
    )
```

- [ ] **Step 3: Update YAML configs to remove additional_system_prompt**

Update `scrivai/agents/auditor.yaml`:
```yaml
name: auditor
display_name: Auditor — 对照审核
prompt_text: |
  You are a compliance audit agent. Your task is to audit a document against
  a given checklist of checkpoints and assign a verdict per checkpoint with
  supporting evidence.

  You operate in three sequential phases: plan, execute, summarize.
  Each phase has explicit file-contract outputs under your working directory.

  The caller provides `data/checkpoints.json` with shape:
    [{"id": "<cp-id>", "description": "...", ...}, ...]

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

Update `scrivai/agents/extractor.yaml`:
```yaml
name: extractor
display_name: Extractor — 结构化条目抽取
prompt_text: |
  You are a document extraction agent. Your task is to extract structured items
  (audit checkpoints, key clauses, FAQ entries, etc.) from source documents
  into machine-parseable JSON.

  You operate in three sequential phases: plan, execute, summarize.
  Each phase has explicit file-contract outputs under your working directory.
  You MUST honor the file contract; downstream phases depend on these files.

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
    max_turns: 20
    max_retries: 1
    required_outputs:
      - {path: "findings", min_files: 1, pattern: "*.json"}

  summarize:
    allowed_tools: ["Bash", "Read", "Write"]
    max_turns: 10
    max_retries: 1
    required_outputs: [output.json]
```

Update `scrivai/agents/generator.yaml`:
```yaml
name: generator
display_name: Generator — 模板化文档生成
prompt_text: |
  You are a document generation agent. Your task is to fill in placeholders of
  a docxtpl template with material drawn from source documents or knowledge
  libraries.

  You operate in three sequential phases: plan, execute, summarize.
  Each phase has explicit file-contract outputs under your working directory.

  The caller provides:
  - A docxtpl template path via `runtime_context["template_path"]` (framework
    parses the template and injects `context.placeholders = [...]` into the
    plan-phase prompt automatically — you'll see the list).
  - An optional `auto_render` flag that triggers docx rendering in summarize.

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

- [ ] **Step 4: Refactor BasePES constructor — add PromptManager**

In `scrivai/pes/base.py`, update `__init__`:

```python
    def __init__(
        self,
        *,
        config: PESConfig,
        model: ModelConfig,
        workspace: WorkspaceHandle,
        hooks: HookManager | None = None,
        trajectory_store: TrajectoryStore | None = None,
        runtime_context: dict[str, Any] | None = None,
        llm_client: "LLMClient | None" = None,
        prompt_manager: "PromptManager | None" = None,
    ) -> None:
        self.config = config
        self.model = model
        self.workspace = workspace
        self.hooks: HookManager | _NullHookManager = hooks or _NullHookManager()
        self.trajectory_store = trajectory_store
        self.runtime_context = runtime_context or {}
        if llm_client is None:
            from scrivai.pes.llm_client import LLMClient as _LLMClient

            llm_client = _LLMClient(model)
        self._llm = llm_client

        if prompt_manager is None:
            prompt_manager = self._create_default_prompt_manager()
        self._prompt_manager = prompt_manager

    def _create_default_prompt_manager(self) -> "PromptManager":
        """Create a PromptManager pointing to the built-in templates."""
        from scrivai.pes.prompts import PromptManager

        base = Path(__file__).resolve().parent / "prompts"
        return PromptManager(
            template_dir=base / "templates",
            fragments_dir=base / "fragments",
            spec_path=base / "prompt_spec.yaml",
        )
```

Add `from pathlib import Path` to the imports at the top if not already present (it's not currently imported in base.py — check the existing imports).

- [ ] **Step 5: Refactor _workspace_payload — remove output_dir**

```python
    def _workspace_payload(self) -> dict[str, str]:
        """Return workspace paths visible to the Agent (excludes output_dir)."""
        return {
            "working_dir": str(self.workspace.working_dir),
            "data_dir": str(self.workspace.data_dir),
        }
```

- [ ] **Step 6: Refactor build_phase_prompt — delegate to PromptManager**

```python
    async def build_phase_prompt(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        context: dict[str, Any],
        task_prompt: str,
    ) -> str:
        """Render the prompt via PromptManager templates.

        Override this method in subclasses for fully custom prompt assembly.
        For most cases, override ``build_execution_context`` instead to inject
        additional template variables.
        """
        context["task_prompt"] = task_prompt
        return self._prompt_manager.build_prompt(
            operation=self.config.name,
            phase=phase,
            context=context,
        )
```

- [ ] **Step 7: Refactor _run_phase — new context construction**

Replace lines 360-373 (steps 2-3) in `_run_phase`:

```python
        # 2. build_execution_context
        execution_context = await self.build_execution_context(phase, run)

        # 3. Build context (template selects which fields to render)
        context: dict[str, Any] = {
            "phase": phase,
            "attempt_no": attempt_no,
            "workspace": self._workspace_payload(),
            "previous_phase_output": self._read_previous_phase_output(phase),
            "cli_tools": self._resolve_cli_tools(),
            "run": run.to_prompt_payload(),
        }
        context.update(self.runtime_context)
        context.update(execution_context)
```

- [ ] **Step 8: Remove _merge_context**

Delete the `_merge_context` method entirely (lines ~543-554). It's no longer called.

- [ ] **Step 9: Update conftest.py — remove additional_system_prompt from sample YAML**

In `tests/contract/conftest.py`, update `sample_pes_config_yaml`:

```python
@pytest.fixture
def sample_pes_config_yaml(tmp_path: Path) -> Path:
    """Generate a valid extractor PESConfig YAML, return Path."""
    yaml_text = """\
name: extractor
display_name: 通用条目抽取
prompt_text: |
  You are a structured information extractor.
default_skills:
  - available-tools
phases:
  plan:
    allowed_tools: [Bash, Read, Write]
    max_turns: 6
    max_retries: 1
    permission_mode: default
    required_outputs: [plan.md, plan.json]
  execute:
    allowed_tools: [Bash, Read, Write]
    max_turns: 30
    max_retries: 1
    permission_mode: default
    required_outputs:
      - {path: "findings/", min_files: 1, pattern: "*.json"}
  summarize:
    allowed_tools: [Bash, Read, Write]
    max_turns: 4
    max_retries: 1
    permission_mode: default
    required_outputs: [output.json]
"""
    p = tmp_path / "extractor.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    return p
```

- [ ] **Step 10: Run all contract tests to check for breakage**

Run: `conda run -n scrivai pytest tests/contract/ -v --tb=short 2>&1 | tail -40`
Expected: Fix any failures caused by the `additional_system_prompt` removal and the new context construction. Common failure patterns:
- Tests referencing `phase_cfg.additional_system_prompt` → remove those references
- Tests constructing `PhaseConfig(additional_system_prompt=...)` → remove the kwarg
- Tests asserting prompt content → update to match template output

- [ ] **Step 11: Fix broken tests iteratively**

For each failing test, update the `PhaseConfig(...)` construction calls to remove `additional_system_prompt`. For tests that assert prompt content, update assertions to match the new template-based output.

- [ ] **Step 12: Run full test suite**

Run: `conda run -n scrivai pytest tests/contract/ -v`
Expected: All PASS (except the 3 pre-existing failures noted earlier)

- [ ] **Step 13: Commit**

```bash
git add scrivai/pes/base.py scrivai/models/pes.py scrivai/agents/*.yaml tests/contract/conftest.py tests/contract/test_base_pes.py
git commit -m "refactor(pes): replace json.dumps prompt with PromptManager template rendering

- build_phase_prompt delegates to PromptManager.build_prompt()
- _workspace_payload removes output_dir (fixes issue #8 path ambiguity)
- Remove additional_system_prompt from PhaseConfig (content moved to .j2 templates)
- Remove _merge_context (replaced by direct dict construction)
- BasePES accepts optional prompt_manager parameter for DI"
```

---

### Task 6: _call_sdk_query — extra_env + system_prompt Fix (Issue #8 — Part 2)

**Files:**
- Modify: `scrivai/pes/base.py:262-300`

- [ ] **Step 1: Write failing test — extra_env passed to LLM**

Add to `tests/contract/test_base_pes.py`:

```python
@pytest.mark.asyncio
async def test_extra_env_passed_to_sdk(tmp_path: Path) -> None:
    """_call_sdk_query should pass workspace.extra_env to execute_task."""
    workspace = _make_workspace(tmp_path)
    workspace = WorkspaceHandle(
        **{**workspace.model_dump(), "extra_env": {"MY_VAR": "my_value"}},
    )
    config = _make_config()
    captured_kwargs: dict[str, Any] = {}

    class CapturePES(BasePES):
        async def _call_sdk_query(self, phase_cfg, prompt, run, attempt_no, on_turn):
            # Verify extra_env would be passed (we can't test real SDK here)
            assert self.workspace.extra_env == {"MY_VAR": "my_value"}
            return "", {}, []

    pes = CapturePES(config=config, model=ModelConfig(model="mock"), workspace=workspace)
    run = await pes.run("test task")
    assert run.status == "completed"
```

- [ ] **Step 2: Run to verify test setup works**

Run: `conda run -n scrivai pytest tests/contract/test_base_pes.py::test_extra_env_passed_to_sdk -v`
Expected: PASS (this validates the plumbing; real SDK test is in test_base_pes_sdk.py)

- [ ] **Step 3: Fix _call_sdk_query — add extra_env, fix system_prompt duplication**

```python
    async def _call_sdk_query(
        self,
        phase_cfg: PhaseConfig,
        prompt: str,
        run: PESRun,
        attempt_no: int,
        on_turn: Callable[[PhaseTurn], None],
    ) -> tuple[str, dict[str, Any], list[PhaseTurn]]:
        """Call LLMClient, translating exceptions to _SDKError(error_type=...)."""
        from claude_agent_sdk import ClaudeSDKError, CLIConnectionError, ProcessError

        from scrivai.exceptions import _SDKError
        from scrivai.pes.llm_client import _MaxTurnsError, _SDKExecutionError

        try:
            resp = await self._llm.execute_task(
                prompt=prompt,
                system_prompt=self.config.prompt_text,
                allowed_tools=phase_cfg.allowed_tools,
                max_turns=phase_cfg.max_turns,
                permission_mode=phase_cfg.permission_mode,
                cwd=self.workspace.working_dir,
                extra_env=self.workspace.extra_env or None,
                on_turn=on_turn,
            )
            return resp.result, resp.usage, resp.turns
        except _MaxTurnsError as e:
            raise _SDKError("max_turns_exceeded", str(e)) from e
        except _SDKExecutionError as e:
            raise _SDKError("sdk_other", str(e)) from e
        except (CLIConnectionError, ProcessError, ClaudeSDKError, RuntimeError) as e:
            raise _SDKError("sdk_other", str(e)) from e
```

Key changes:
1. `system_prompt=self.config.prompt_text` — no more `+ additional_system_prompt` (fixes duplication)
2. `extra_env=self.workspace.extra_env or None` — closes issue #8 断点B

- [ ] **Step 4: Run tests**

Run: `conda run -n scrivai pytest tests/contract/test_base_pes.py tests/contract/test_base_pes_sdk.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scrivai/pes/base.py tests/contract/test_base_pes.py
git commit -m "fix(pes): pass extra_env to SDK and deduplicate system_prompt

- _call_sdk_query now passes workspace.extra_env to execute_task (closes issue #8 断点B)
- system_prompt uses only config.prompt_text (no more duplication with template)"
```

---

### Task 7: Public API + Cleanup

**Files:**
- Modify: `scrivai/__init__.py`
- Delete or ignore: `templates/prompts/` (legacy, NOT in scrivai/ package)

- [ ] **Step 1: Add PromptManager to public API**

In `scrivai/__init__.py`, add the import and `__all__` entry:

```python
# After "from scrivai.pes.config import load_pes_config"
from scrivai.pes.prompts import PromptManager
```

Add `"PromptManager"` to `__all__` under the `# PES core` section:

```python
    # PES core
    "BasePES",
    "PromptManager",
```

- [ ] **Step 2: Remove relaxed_json_loads from __all__ (fixes pre-existing test failure)**

In `scrivai/__init__.py`, remove `"relaxed_json_loads"` from `__all__` (it was flagged by `test_import_surface`). Keep the import for internal use but remove from the public API list.

- [ ] **Step 3: Run the public API contract test**

Run: `conda run -n scrivai pytest tests/contract/test_public_api.py -v`
Expected: `test_import_surface` should PASS now (relaxed_json_loads removed from __all__)

- [ ] **Step 4: Run full test suite**

Run: `conda run -n scrivai pytest tests/contract/ -q --tb=short`
Expected: Only the 2 pre-existing failures remain (test_nonblocking_dispatch, test_no_result_message_raises). The `test_import_surface` failure should be fixed.

- [ ] **Step 5: Commit**

```bash
git add scrivai/__init__.py
git commit -m "feat: export PromptManager in public API, fix __all__ surface (remove relaxed_json_loads)"
```

---

### Task 8: Update Existing PES Tests for Template-Based Prompts

**Files:**
- Modify: `tests/contract/test_bash_whitelist.py`
- Modify: `tests/contract/test_auditor_pes.py`
- Modify: `tests/contract/test_extractor_pes.py`
- Modify: `tests/contract/test_generator_pes.py`
- Modify: `tests/contract/test_mock_pes.py`
- Modify: any other test files that construct `PhaseConfig(additional_system_prompt=...)`

- [ ] **Step 1: Find all test references to additional_system_prompt**

Run: `conda run -n scrivai grep -rn "additional_system_prompt" tests/`

For each occurrence, remove the kwarg from `PhaseConfig(...)` or update the test logic.

- [ ] **Step 2: Update test_bash_whitelist.py**

The `test_build_phase_prompt_injects_whitelist` tests call `build_phase_prompt` directly. Update the context dict and assertions to match the new template-based output. The CLI tools whitelist is now rendered by Jinja2 `{% if cli_tools %}` blocks in templates.

Since `build_phase_prompt` now delegates to PromptManager, these tests should pass a context dict with `task_prompt` and `workspace` keys. Use a PromptManager with test-specific templates or test via the real templates.

- [ ] **Step 3: Run each test file and fix failures**

Run each file individually and fix:
```bash
conda run -n scrivai pytest tests/contract/test_bash_whitelist.py -v
conda run -n scrivai pytest tests/contract/test_auditor_pes.py -v
conda run -n scrivai pytest tests/contract/test_extractor_pes.py -v
conda run -n scrivai pytest tests/contract/test_generator_pes.py -v
conda run -n scrivai pytest tests/contract/test_mock_pes.py -v
```

- [ ] **Step 4: Run full suite**

Run: `conda run -n scrivai pytest tests/contract/ -q --tb=short`
Expected: ≤ 2 pre-existing failures, 0 new failures

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update all PES tests for template-based prompt system"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run ruff**

Run: `conda run -n scrivai ruff check scrivai/ tests/ --fix && conda run -n scrivai ruff format scrivai/ tests/`

- [ ] **Step 2: Run full test suite**

Run: `conda run -n scrivai pytest tests/contract/ -v --tb=short`

- [ ] **Step 3: Verify issue #8 fixes specifically**

Checklist:
- `WorkspaceHandle` has `extra_env` field → `grep "extra_env" scrivai/models/workspace.py`
- `_call_sdk_query` passes `extra_env` → `grep "extra_env" scrivai/pes/base.py`
- `_workspace_payload` has no `output_dir` → `grep "output_dir" scrivai/pes/base.py` (should only appear in the field definition, not in payload)
- No prompt duplication → `system_prompt=self.config.prompt_text` (no `+ additional_system_prompt`)

- [ ] **Step 4: Verify no legacy prompt system remains**

- `json.dumps(context` should NOT appear in `build_phase_prompt` → `grep "json.dumps" scrivai/pes/base.py`
- `additional_system_prompt` should NOT appear in PhaseConfig → `grep "additional_system_prompt" scrivai/models/pes.py`
- Templates render correctly → run `test_real_prompt_spec_loads`

- [ ] **Step 5: Commit any lint fixes**

```bash
git add -A
git commit -m "style: ruff lint and format fixes"
```
