"""PromptManager — Jinja2-based prompt assembly with contract validation.

Loads a YAML prompt spec that declares, per template key (``{operation}_{phase}``):
- ``required_context``: fields that must be present and non-None in the render context.
- ``static_fragments``: ordered list of ``.md`` fragment names to concatenate.
- ``artifacts``: downstream artifact names (informational, not enforced here).

The manager validates the context, loads static fragments, and renders the
corresponding Jinja2 template file (``{operation}_{phase}.j2``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from loguru import logger


class PromptManager:
    """Assemble prompts from Jinja2 templates, YAML spec, and markdown fragments."""

    def __init__(
        self,
        template_dir: Path,
        fragments_dir: Path,
        spec_path: Path,
    ) -> None:
        """Initialize PromptManager.

        Args:
            template_dir: Directory containing Jinja2 ``.j2`` template files.
            fragments_dir: Directory containing static ``.md`` prompt fragments.
            spec_path: Path to the YAML prompt spec file.

        Raises:
            FileNotFoundError: If spec_path does not exist.
            ValueError: If the YAML structure is invalid.
        """
        self.template_dir = Path(template_dir)
        self.fragments_dir = Path(fragments_dir)
        self.spec_path = Path(spec_path)
        self._prompt_spec = self._load_prompt_spec(self.spec_path)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.debug(
            "PromptManager 初始化完成 (template_dir={}, fragments_dir={})",
            self.template_dir,
            self.fragments_dir,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        operation: str,
        phase: str,
        context: dict[str, Any],
    ) -> str:
        """Build a complete prompt by validating context, loading fragments,
        and rendering the template.

        Args:
            operation: Operation type (e.g. ``"extractor"``).
            phase: Phase name (e.g. ``"plan"``).
            context: Render context dict; must satisfy ``required_context`` from spec.

        Returns:
            Rendered prompt string.

        Raises:
            ValueError: If required context fields are missing/None or template key is unknown.
            jinja2.TemplateNotFound: If the ``.j2`` file does not exist.
        """
        template_key = f"{operation}_{phase}"
        template_spec = self.get_template_spec(operation, phase)
        self.validate_context(template_key, template_spec, context)

        static_fragments_text = self._build_static_fragments_text(template_spec)

        template_name = f"{template_key}.j2"
        try:
            template = self.env.get_template(template_name)
        except TemplateNotFound:
            logger.error("模板文件不存在: {}", template_name)
            raise

        template_context = {
            **context,
            "static_fragments_text": static_fragments_text,
        }
        prompt = template.render(**template_context)
        logger.debug("Prompt 构建完成 (template={})", template_key)
        return prompt

    def get_template_spec(self, operation: str, phase: str) -> dict[str, Any]:
        """Read the spec entry for a given operation/phase combination.

        Args:
            operation: Operation type.
            phase: Phase name.

        Returns:
            Spec dict with ``required_context``, ``static_fragments``, ``artifacts`` keys.

        Raises:
            ValueError: If the template key is not defined in the spec.
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
        """Validate that all required context fields are present and non-None.

        Args:
            template_key: Template key for error messages.
            template_spec: Spec dict containing ``required_context``.
            context: Render context to validate.

        Raises:
            ValueError: If any required field is missing or None.
        """
        required_fields = self._get_string_list_field(template_spec, "required_context")
        missing_fields = [
            field for field in required_fields if field not in context or context[field] is None
        ]
        if missing_fields:
            missing_text = ", ".join(missing_fields)
            raise ValueError(
                f"Prompt 上下文缺少必填字段: template={template_key}, missing=[{missing_text}]"
            )

    def load_fragment(self, fragment_name: str) -> str:
        """Load a static ``.md`` prompt fragment by name.

        Args:
            fragment_name: Fragment name, with or without ``.md`` suffix.

        Returns:
            Stripped text content of the fragment file.

        Raises:
            FileNotFoundError: If the fragment file does not exist.
        """
        normalized_name = fragment_name[:-3] if fragment_name.endswith(".md") else fragment_name
        fragment_path = self.fragments_dir / f"{normalized_name}.md"
        if not fragment_path.exists():
            raise FileNotFoundError(f"Prompt fragment 不存在: {fragment_path}")
        return fragment_path.read_text(encoding="utf-8").strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_static_fragments_text(self, template_spec: dict[str, Any]) -> str:
        """Concatenate fragment files listed in the spec's ``static_fragments``."""
        fragment_names = self._get_string_list_field(template_spec, "static_fragments")
        if not fragment_names:
            return ""
        fragments = [self.load_fragment(name) for name in fragment_names]
        return "\n\n".join(fragments)

    def _load_prompt_spec(self, spec_path: Path) -> dict[str, Any]:
        """Load and validate the YAML prompt spec.

        Expected structure::

            templates:
              operation_phase:
                required_context: [field1, field2]
                static_fragments: [frag1, frag2]
                artifacts: [artifact1]

        Raises:
            FileNotFoundError: If spec file does not exist.
            ValueError: If YAML is invalid or structure is malformed.
        """
        path = Path(spec_path)
        if not path.exists():
            raise FileNotFoundError(f"prompt_spec.yaml 不存在: {path}")

        try:
            with open(path, encoding="utf-8") as fh:
                spec = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(f"prompt_spec.yaml YAML 解析失败: {path}") from exc

        if not isinstance(spec, dict):
            raise ValueError(f"prompt_spec.yaml 顶层必须是映射: {path}")

        templates = spec.get("templates")
        if not isinstance(templates, dict):
            raise ValueError(f"prompt_spec.yaml 缺少合法 templates 映射: {path}")

        for template_key, template_spec in templates.items():
            if not isinstance(template_spec, dict):
                raise ValueError(f"prompt_spec 模板配置必须是映射: {template_key}")
            if set(template_spec.keys()) != {
                "required_context",
                "static_fragments",
                "artifacts",
            }:
                raise ValueError(f"prompt_spec 模板字段非法: {template_key}")
            for field_name in ("required_context", "static_fragments", "artifacts"):
                self._get_string_list_field(template_spec, field_name)

        return spec

    @staticmethod
    def _get_string_list_field(
        template_spec: dict[str, Any],
        field_name: str,
    ) -> list[str]:
        """Read and validate a string-list field from a template spec entry.

        Args:
            template_spec: Single template spec dict.
            field_name: Key to read (e.g. ``"required_context"``).

        Returns:
            List of strings (may be empty).

        Raises:
            ValueError: If the field is not a list of non-empty strings.
        """
        raw_value = template_spec.get(field_name, [])
        if not isinstance(raw_value, list):
            raise ValueError(f"prompt_spec 字段必须是列表: {field_name}")
        if not all(isinstance(item, str) and item.strip() for item in raw_value):
            raise ValueError(f"prompt_spec 字段必须是非空字符串列表: {field_name}")
        return raw_value
