"""ExtractorPES — Extract structured data from documents using LLM."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from scrivai.pes.base import BasePES
from scrivai.utils import relaxed_json_loads

if TYPE_CHECKING:
    from scrivai.models.pes import PESRun, PhaseConfig, PhaseResult


class ExtractorPES(BasePES):
    """Extract structured data from documents using LLM.

    Inherits from ``BasePES`` with no additional constructor parameters.
    Business parameters are passed via ``runtime_context``.

    Args:
        config: PES configuration (use ``load_pes_config("extractor.yaml")``).
        model: LLM provider configuration.
        workspace: Isolated workspace for this run.
        runtime_context: Must include:
            - ``output_schema`` (``type[BaseModel]``): Pydantic model for output validation.

    Phase contracts:
        - **plan** → ``working/plan.json`` with extraction items
        - **execute** → ``working/findings/<id>.json`` per planned item
        - **summarize** → ``working/output.json`` conforming to ``output_schema``

    Example:
        >>> from pydantic import BaseModel
        >>> from scrivai import ExtractorPES, ModelConfig, load_pes_config
        >>> class Items(BaseModel):
        ...     items: list[str]
        >>> pes = ExtractorPES(
        ...     config=load_pes_config(Path("extractor.yaml")),
        ...     model=ModelConfig(model="claude-sonnet-4-20250514"),
        ...     workspace=ws,
        ...     runtime_context={"output_schema": Items},
        ... )
        >>> run = await pes.run("Extract items from data/source.md")
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Summarize phase: read output.json and validate against output_schema. No-op for other phases."""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "ExtractorPES requires runtime_context['output_schema'] (a pydantic BaseModel subclass)."
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] must be a BaseModel subclass, "
                f"got {type(schema).__name__}."
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(
                f"ExtractorPES summarize phase: output.json was not produced: {output_path}"
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
        """Execute phase: extend required_outputs validation with plan→findings coverage check."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        plan_path = self.workspace.working_dir / "plan.json"
        if not plan_path.exists():
            raise ValueError(
                f"execute coverage check requires plan.json, but it was not found: {plan_path}"
            )

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
            raise ValueError(f"Uncovered plan item ids: {sorted(missing)}")
