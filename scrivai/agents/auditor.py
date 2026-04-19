"""AuditorPES — Audit a document against a checklist of checkpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, ValidationError

from scrivai.pes.base import BasePES
from scrivai.utils import relaxed_json_loads

if TYPE_CHECKING:
    from scrivai.models.pes import PESRun, PhaseConfig, PhaseResult


DEFAULT_VERDICT_LEVELS: list[str] = ["合格", "不合格", "不适用", "需要澄清"]  # Chinese domain values kept intentionally


class AuditorPES(BasePES):
    """Audit a document against a checklist of checkpoints.

    Before calling ``run()``, place a JSON file at
    ``workspace.data_dir / "checkpoints.json"`` containing a list of
    checkpoint objects: ``[{"id": "CP001", "description": "..."}, ...]``.

    Args:
        config: PES configuration (use ``load_pes_config("auditor.yaml")``).
        model: LLM provider configuration.
        workspace: Isolated workspace for this run.
        runtime_context: Must include:
            - ``output_schema`` (``type[BaseModel]``): Pydantic model for audit output.

    Phase contracts:
        - **plan** → ``working/plan.json`` (reads ``data/checkpoints.json``)
        - **execute** → ``working/findings/<cp_id>.json`` per checkpoint
        - **summarize** → ``working/output.json`` with findings + summary

    Example:
        >>> from scrivai import AuditorPES, ModelConfig, load_pes_config
        >>> pes = AuditorPES(
        ...     config=load_pes_config(Path("auditor.yaml")),
        ...     model=ModelConfig(model="claude-sonnet-4-20250514"),
        ...     workspace=ws,
        ...     runtime_context={"output_schema": AuditOutput},
        ... )
        >>> run = await pes.run("Audit data/document.md against checkpoints")
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Summarize phase: schema validation + verdict/evidence rules."""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "AuditorPES requires runtime_context['output_schema'] (a pydantic BaseModel subclass)."
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] must be a BaseModel subclass, "
                f"got {type(schema).__name__}."
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(f"AuditorPES summarize phase: output.json was not produced: {output_path}")

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

        verdict_levels: list[str] = list(
            self.runtime_context.get("verdict_levels") or DEFAULT_VERDICT_LEVELS
        )
        evidence_required: bool = bool(self.runtime_context.get("evidence_required", True))

        findings = data.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("output.json.findings must be a list")

        for idx, finding in enumerate(findings):
            if not isinstance(finding, dict):
                raise ValueError(f"findings[{idx}] must be an object")
            verdict = finding.get("verdict")
            # LLM may output verdict as a dict: {"verdict": "<level>", "evidence_quotes": [...]}
            verdict_str = verdict.get("verdict") if isinstance(verdict, dict) else verdict
            if verdict_str not in verdict_levels:
                raise ValueError(
                    f"findings[{idx}].verdict={verdict_str!r} is not in verdict_levels={verdict_levels}"
                )
            if evidence_required:
                evidence = finding.get("evidence") or []
                has_evidence = isinstance(evidence, list) and len(evidence) > 0
                evidence_quotes = (
                    verdict.get("evidence_quotes") if isinstance(verdict, dict) else []
                ) or []
                has_quotes = isinstance(evidence_quotes, list) and len(evidence_quotes) > 0
                evidence_refs = finding.get("evidence_refs") or []
                has_refs = isinstance(evidence_refs, list) and len(evidence_refs) > 0
                if not has_evidence and not has_quotes and not has_refs:
                    raise ValueError(
                        f"findings[{idx}] is missing evidence (evidence_required=True)"
                    )

        # Repair bad JSON in findings/ written by the LLM (e.g. Chinese quotation marks)
        findings_dir = self.workspace.working_dir / "findings"
        if findings_dir.exists():
            for fp in findings_dir.glob("*.json"):
                raw = fp.read_text(encoding="utf-8")
                try:
                    json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    try:
                        fixed = relaxed_json_loads(raw, strict=self.config.strict_json)
                        fp.write_text(
                            json.dumps(fixed, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        logger.warning("findings JSON repair failed: {}", fp.name)

        run.final_output = validated.model_dump()
        run.final_output_path = output_path

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: "PhaseConfig",
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Execute phase: verify that checkpoint IDs in data/checkpoints.json are covered by findings."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        cp_path = self.workspace.data_dir / "checkpoints.json"
        if not cp_path.exists():
            raise ValueError(f"AuditorPES requires data/checkpoints.json to be pre-placed by the business layer (not found: {cp_path})")

        try:
            checkpoints = relaxed_json_loads(
                cp_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"data/checkpoints.json is not valid JSON: {e}") from e

        if not isinstance(checkpoints, list):
            raise ValueError("data/checkpoints.json must be a list of objects [{id, description}, ...]")

        expected_ids = {cp["id"] for cp in checkpoints if isinstance(cp, dict) and "id" in cp}

        findings_dir = self.workspace.working_dir / "findings"
        actual_ids = (
            {p.stem for p in findings_dir.glob("*.json")} if findings_dir.exists() else set()
        )

        missing = expected_ids - actual_ids
        if missing:
            raise ValueError(f"Uncovered checkpoint ids: {sorted(missing)}")
