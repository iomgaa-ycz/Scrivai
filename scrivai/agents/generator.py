"""GeneratorPES — generates final documents from a docxtpl template (M1.5a T1.6).

runtime_context business fields:
- template_path: Path                        (required)
- context_schema: type[BaseModel]            (required)
- auto_render: bool                          (optional, default False)

References:
- docs/design.md §4.4.3
- docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md §4.1 / §5.2
"""

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
    """Generates final documents from a docxtpl template.

    Phase contract:
    - plan     → working/plan.md + working/plan.json ({"fills": [{"placeholder", "source"}]})
    - execute  → working/findings/<placeholder>.json
    - summarize→ working/output.json (contains context dict + sections);
                 if auto_render=True, also writes output/final.docx
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
            raise ValueError("GeneratorPES requires runtime_context['template_path'] (docxtpl template path)")
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
        """Summarize phase: validate context_schema; render docx when auto_render=True."""
        if phase != "summarize":
            return

        context_schema = self.runtime_context.get("context_schema")
        if context_schema is None:
            raise ValueError(
                "GeneratorPES requires runtime_context['context_schema'] (a pydantic BaseModel subclass)"
            )
        if not (isinstance(context_schema, type) and issubclass(context_schema, BaseModel)):
            raise ValueError(
                "runtime_context['context_schema'] must be a BaseModel subclass, got "
                f"{type(context_schema).__name__}"
            )

        template_path = self.runtime_context.get("template_path")
        if template_path is None:
            raise ValueError(
                "GeneratorPES requires runtime_context['template_path'] "
                "(postprocess depends on it even when auto_render=False)"
            )
        template_path = Path(template_path)

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(f"GeneratorPES output.json not generated: {output_path}")

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
                    "auto_render=True requires output.json to contain a 'context' dict (docxtpl render context)"
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
        """plan: verify plan.json covers all placeholders; execute: verify findings/ coverage."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase not in ("plan", "execute"):
            return

        template_path = self.runtime_context.get("template_path")
        if template_path is None:
            raise ValueError("runtime_context['template_path'] is missing (required for validation)")
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
                raise ValueError(f"plan.json missing placeholders: {sorted(missing)}")
        elif phase == "execute":
            findings_dir = self.workspace.working_dir / "findings"
            actual = (
                {p.stem for p in findings_dir.glob("*.json")} if findings_dir.exists() else set()
            )
            missing = placeholders - actual
            if missing:
                raise ValueError(f"findings missing placeholders: {sorted(missing)}")
