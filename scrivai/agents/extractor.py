"""ExtractorPES — extracts structured entries from documents (M1.5a T1.4).

runtime_context business fields:
- output_schema: type[BaseModel]  (required, used by summarize validation)

References:
- docs/design.md §4.4.1
- docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md §4.1 / §5.2
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from scrivai.pes.base import BasePES
from scrivai.utils import relaxed_json_loads

if TYPE_CHECKING:
    from scrivai.models.pes import PESRun, PhaseConfig, PhaseResult


class ExtractorPES(BasePES):
    """Extracts structured entries from documents.

    Constructor signature = BasePES.__init__ (no new parameters); business parameters
    go in runtime_context:
    - output_schema: type[BaseModel]  (required)

    Phase contract:
    - plan     → working/plan.md + working/plan.json
                 plan.json: {"items_to_extract": [{"id": str, "description": str}, ...]}
    - execute  → working/findings/<id>.json (one per plan item)
    - summarize→ working/output.json (matches output_schema)
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Read output.json in the summarize phase and validate against output_schema. No-op for other phases."""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "ExtractorPES requires runtime_context['output_schema'] (a pydantic BaseModel subclass)"
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] must be a BaseModel subclass, got "
                f"{type(schema).__name__}"
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(
                f"ExtractorPES summarize phase: output.json not generated: {output_path}"
            )

        try:
            data = relaxed_json_loads(
                output_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"output.json is not valid JSON: {e}") from e

        try:
            validated = schema.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"output.json does not match output_schema: {e}") from e

        run.final_output = validated.model_dump()
        run.final_output_path = output_path

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: "PhaseConfig",
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Validate execute outputs: extends required_outputs check with plan-to-findings coverage."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        plan_path = self.workspace.working_dir / "plan.json"
        if not plan_path.exists():
            raise ValueError(f"execute coverage check requires plan.json (not found: {plan_path})")

        try:
            plan = relaxed_json_loads(
                plan_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"plan.json is not valid JSON: {e}") from e

        expected_ids = {
            item["id"]
            for item in plan.get("items_to_extract", [])
            if isinstance(item, dict) and "id" in item
        }

        findings_dir = self.workspace.working_dir / "findings"
        actual_ids = (
            {p.stem for p in findings_dir.glob("*.json")} if findings_dir.exists() else set()
        )

        missing = expected_ids - actual_ids
        if missing:
            raise ValueError(f"uncovered plan item ids: {sorted(missing)}")
