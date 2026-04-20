"""PromptManager contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scrivai.pes.prompts.manager import PromptManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_spec(tmp_path: Path, templates: dict[str, Any]) -> Path:
    """Write a prompt_spec.yaml to *tmp_path* and return its path."""
    spec_path = tmp_path / "prompt_spec.yaml"
    spec_path.write_text(
        yaml.dump({"templates": templates}, default_flow_style=False),
        encoding="utf-8",
    )
    return spec_path


def _make_prompt_env(
    tmp_path: Path,
    *,
    template_content: str = "Hello {{ name }}",
    template_name: str = "extract_plan.j2",
    fragment_content: str = "# Rules\nBe precise.",
    fragment_name: str = "rules.md",
    spec_templates: dict[str, Any] | None = None,
) -> tuple[Path, Path, Path]:
    """Set up template_dir, fragments_dir, spec_path under *tmp_path*.

    Returns:
        (template_dir, fragments_dir, spec_path)
    """
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / template_name).write_text(template_content, encoding="utf-8")

    fragments_dir = tmp_path / "fragments"
    fragments_dir.mkdir()
    (fragments_dir / fragment_name).write_text(fragment_content, encoding="utf-8")

    if spec_templates is None:
        spec_templates = {
            "extract_plan": {
                "required_context": ["name"],
                "static_fragments": ["rules"],
                "artifacts": ["plan.md"],
            },
        }
    spec_path = _write_spec(tmp_path, spec_templates)
    return template_dir, fragments_dir, spec_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """build_prompt renders template with context + fragments."""

    def test_build_prompt_renders_template(self, tmp_path: Path) -> None:
        tpl_content = "{{ static_fragments_text }}\n---\nHello {{ name }}, phase={{ phase_name }}."
        template_dir, fragments_dir, spec_path = _make_prompt_env(
            tmp_path,
            template_content=tpl_content,
            spec_templates={
                "extract_plan": {
                    "required_context": ["name", "phase_name"],
                    "static_fragments": ["rules"],
                    "artifacts": [],
                },
            },
        )
        pm = PromptManager(template_dir, fragments_dir, spec_path)
        result = pm.build_prompt("extract", "plan", {"name": "Alice", "phase_name": "plan"})

        assert "Hello Alice" in result
        assert "phase=plan" in result
        assert "# Rules" in result
        assert "Be precise." in result


class TestValidateContext:
    """validate_context fast-fails on missing / None required fields."""

    def test_validate_context_raises_on_missing(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        with pytest.raises(ValueError, match="缺少必填字段"):
            pm.validate_context(
                "extract_plan",
                {"required_context": ["name"], "static_fragments": [], "artifacts": []},
                {},  # missing "name"
            )

    def test_validate_context_raises_on_none(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        with pytest.raises(ValueError, match="缺少必填字段"):
            pm.validate_context(
                "extract_plan",
                {"required_context": ["name"], "static_fragments": [], "artifacts": []},
                {"name": None},
            )


class TestUnknownTemplate:
    """get_template_spec raises for undefined template keys."""

    def test_unknown_template_raises(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        with pytest.raises(ValueError, match="未定义模板"):
            pm.get_template_spec("nonexistent", "phase")


class TestLoadFragment:
    """load_fragment reads .md files from fragments dir."""

    def test_load_fragment(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        content = pm.load_fragment("rules")
        assert "# Rules" in content
        assert "Be precise." in content

    def test_load_fragment_with_md_suffix(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        content = pm.load_fragment("rules.md")
        assert "# Rules" in content

    def test_load_fragment_missing_raises(self, tmp_path: Path) -> None:
        template_dir, fragments_dir, spec_path = _make_prompt_env(tmp_path)
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        with pytest.raises(FileNotFoundError, match="Prompt fragment 不存在"):
            pm.load_fragment("nonexistent")


class TestSpecValidation:
    """_load_prompt_spec rejects malformed YAML structures."""

    def test_spec_validation_rejects_bad_structure(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        fragments_dir = tmp_path / "fragments"
        fragments_dir.mkdir()

        # YAML with missing "templates" key
        spec_path = tmp_path / "bad_spec.yaml"
        spec_path.write_text(
            yaml.dump({"not_templates": {}}, default_flow_style=False),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="缺少合法 templates 映射"):
            PromptManager(template_dir, fragments_dir, spec_path)

    def test_spec_validation_rejects_extra_fields(self, tmp_path: Path) -> None:
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        fragments_dir = tmp_path / "fragments"
        fragments_dir.mkdir()

        spec_path = _write_spec(
            tmp_path,
            {
                "extract_plan": {
                    "required_context": [],
                    "static_fragments": [],
                    "artifacts": [],
                    "extra_bad_field": "oops",
                },
            },
        )

        with pytest.raises(ValueError, match="模板字段非法"):
            PromptManager(template_dir, fragments_dir, spec_path)


class TestOptionalContext:
    """Templates can reference optional fields not in required_context."""

    def test_optional_context_fields_not_required(self, tmp_path: Path) -> None:
        tpl_content = "Hello {{ name }}.{% if cli_tools %}\nTools: {{ cli_tools }}{% endif %}"
        template_dir, fragments_dir, spec_path = _make_prompt_env(
            tmp_path,
            template_content=tpl_content,
            spec_templates={
                "extract_plan": {
                    "required_context": ["name"],
                    "static_fragments": [],
                    "artifacts": [],
                },
            },
        )
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        # cli_tools not provided, not required -> should render without error
        result = pm.build_prompt("extract", "plan", {"name": "Bob"})
        assert "Hello Bob" in result
        assert "Tools:" not in result

    def test_optional_context_rendered_when_present(self, tmp_path: Path) -> None:
        tpl_content = "Hello {{ name }}.{% if cli_tools %}\nTools: {{ cli_tools }}{% endif %}"
        template_dir, fragments_dir, spec_path = _make_prompt_env(
            tmp_path,
            template_content=tpl_content,
            spec_templates={
                "extract_plan": {
                    "required_context": ["name"],
                    "static_fragments": [],
                    "artifacts": [],
                },
            },
        )
        pm = PromptManager(template_dir, fragments_dir, spec_path)

        result = pm.build_prompt("extract", "plan", {"name": "Bob", "cli_tools": "ruff,git"})
        assert "Hello Bob" in result
        assert "Tools: ruff,git" in result
