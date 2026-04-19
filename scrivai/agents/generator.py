"""GeneratorPES — Generate a document by filling a docxtpl template."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docxtpl import DocxTemplate  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from scrivai.pes.base import BasePES
from scrivai.utils import relaxed_json_loads

if TYPE_CHECKING:
    from scrivai.models.pes import PESRun, PhaseConfig, PhaseResult


def _parse_placeholders(template_path: Path) -> list[str]:
    """Extract the list of undeclared template variables using docxtpl's built-in capability."""
    tpl = DocxTemplate(str(template_path))
    return sorted(tpl.get_undeclared_template_variables())


class GeneratorPES(BasePES):
    """Generate a document by filling a docxtpl template.

    The LLM plans which template placeholders to fill, executes data
    gathering for each placeholder, and summarizes results into a context
    dict. Optionally renders the final ``.docx`` file.

    Args:
        config: PES configuration (use ``load_pes_config("generator.yaml")``).
        model: LLM provider configuration.
        workspace: Isolated workspace for this run.
        runtime_context: Must include:
            - ``template_path`` (``Path``): Path to docxtpl template.
            - ``context_schema`` (``type[BaseModel]``): Schema for template context.
            - ``auto_render`` (``bool``, optional): If True, render final.docx.

    Phase contracts:
        - **plan** → ``working/plan.json`` with placeholder fill plan
        - **execute** → ``working/findings/<placeholder>.json`` per fill
        - **summarize** → ``working/output.json`` with context dict;
          ``output/final.docx`` if ``auto_render=True``

    Example:
        >>> from scrivai import GeneratorPES, ModelConfig, load_pes_config
        >>> pes = GeneratorPES(
        ...     config=load_pes_config(Path("generator.yaml")),
        ...     model=ModelConfig(model="claude-sonnet-4-20250514"),
        ...     workspace=ws,
        ...     runtime_context={"template_path": Path("t.docx"), ...},
        ... )
        >>> run = await pes.run("Fill the project report template")
    """

    async def build_execution_context(
        self,
        phase: str,
        run: "PESRun",
    ) -> dict[str, Any]:
        """Plan phase: parse template_path placeholders and inject context['placeholders']."""
        if phase != "plan":
            return {}

        template_path = self.runtime_context.get("template_path")
        if template_path is None:
            raise ValueError("GeneratorPES requires runtime_context['template_path'] (docxtpl template path).")
        template_path = Path(template_path)
        if not template_path.exists():
            raise FileNotFoundError(f"template_path does not exist: {template_path}")

        return {"placeholders": _parse_placeholders(template_path)}

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Summarize phase: validate context_schema; render docx if auto_render=True."""
        if phase != "summarize":
            return

        context_schema = self.runtime_context.get("context_schema")
        if context_schema is None:
            raise ValueError(
                "GeneratorPES requires runtime_context['context_schema'] (a pydantic BaseModel subclass)."
            )
        if not (isinstance(context_schema, type) and issubclass(context_schema, BaseModel)):
            raise ValueError(
                "runtime_context['context_schema'] must be a BaseModel subclass, "
                f"got {type(context_schema).__name__}."
            )

        template_path = self.runtime_context.get("template_path")
        if template_path is None:
            raise ValueError(
                "GeneratorPES requires runtime_context['template_path'] "
                "(even if auto_render=False, postprocess still needs it)."
            )
        template_path = Path(template_path)

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(f"GeneratorPES output.json was not produced: {output_path}")

        try:
            data = relaxed_json_loads(
                output_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"output.json is not valid JSON: {e}") from e

        try:
            validated = context_schema.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"output.json does not match context_schema: {e}") from e

        run.final_output = validated.model_dump()
        run.final_output_path = output_path

        auto_render = bool(self.runtime_context.get("auto_render", False))
        if auto_render:
            if "context" not in data or not isinstance(data["context"], dict):
                raise ValueError(
                    "auto_render=True requires output.json to contain a 'context' dict (docxtpl render context)."
                )
            final_docx = self.workspace.output_dir / "final.docx"
            try:
                tpl = DocxTemplate(str(template_path))
                tpl.render(data["context"])
                tpl.save(str(final_docx))
            except Exception as e:
                raise ValueError(f"docxtpl render failed: {e}") from e

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: "PhaseConfig",
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Plan phase: verify plan.json covers all placeholders; execute phase: verify findings/ coverage."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase not in ("plan", "execute"):
            return

        template_path = self.runtime_context.get("template_path")
        if template_path is None:
            raise ValueError("runtime_context['template_path'] is missing (required by validate).")
        placeholders = set(_parse_placeholders(Path(template_path)))

        if phase == "plan":
            plan_path = self.workspace.working_dir / "plan.json"
            try:
                plan = relaxed_json_loads(
                    plan_path.read_text(encoding="utf-8"), strict=self.config.strict_json
                )
            except json.JSONDecodeError as e:
                raise ValueError(f"plan.json is not valid JSON: {e}") from e
            declared = {
                f["placeholder"]
                for f in plan.get("fills", [])
                if isinstance(f, dict) and "placeholder" in f
            }
            missing = placeholders - declared
            if missing:
                raise ValueError(f"plan.json does not cover placeholders: {sorted(missing)}")
        elif phase == "execute":
            findings_dir = self.workspace.working_dir / "findings"
            actual = (
                {p.stem for p in findings_dir.glob("*.json")} if findings_dir.exists() else set()
            )
            missing = placeholders - actual
            if missing:
                raise ValueError(f"findings do not cover placeholders: {sorted(missing)}")
