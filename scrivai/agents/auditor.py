"""AuditorPES — audits documents against data/checkpoints.json (M1.5a T1.5).

runtime_context business fields:
- output_schema: type[BaseModel]            (required)
- verdict_levels: list[str]                 (optional, default DEFAULT_VERDICT_LEVELS)
- evidence_required: bool                   (optional, default True)

References:
- docs/design.md §4.4.2
- docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md §4.1 / §5.2
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel, ValidationError

from scrivai.pes.base import BasePES
from scrivai.utils import relaxed_json_loads

if TYPE_CHECKING:
    from scrivai.models.pes import PESRun, PhaseConfig, PhaseResult


DEFAULT_VERDICT_LEVELS: list[str] = ["合格", "不合格", "不适用", "需要澄清"]


class AuditorPES(BasePES):
    """Audits document compliance against data/checkpoints.json.

    Phase contract:
    - plan     → working/plan.md + working/plan.json (Agent reads data/checkpoints.json)
    - execute  → working/findings/<cp_id>.json (one file per checkpoint)
    - summarize→ working/output.json (aggregated findings + summary)

    The business layer must write checkpoints as ``[{id, description, ...}]``
    to ``workspace.data_dir/checkpoints.json`` before calling ``pes.run()``.
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """Post-process for the summarize phase: schema validation and verdict/evidence rules."""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "AuditorPES requires runtime_context['output_schema'] (a pydantic BaseModel subclass)"
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] must be a BaseModel subclass, got "
                f"{type(schema).__name__}"
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(f"AuditorPES summarize phase: output.json not generated: {output_path}")

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
                    f"findings[{idx}].verdict={verdict_str!r} not in verdict_levels={verdict_levels}"
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
                        f"findings[{idx}] missing evidence (evidence_required=True)"
                    )

        # Repair bad JSON written by the LLM in the findings directory (e.g. Chinese quotes)
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
        """Validate execute phase outputs: align data/checkpoints.json cp_ids with findings/."""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        cp_path = self.workspace.data_dir / "checkpoints.json"
        if not cp_path.exists():
            raise ValueError(f"AuditorPES requires data/checkpoints.json (not found: {cp_path})")

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
            raise ValueError(f"uncovered checkpoint ids: {sorted(missing)}")
