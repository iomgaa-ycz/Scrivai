"""AuditorPES — 对照 data/checkpoints.json 审核(M1.5a T1.5)。

runtime_context 业务字段:
- output_schema: type[BaseModel]            (必需)
- verdict_levels: list[str]                 (可选,默认 DEFAULT_VERDICT_LEVELS)
- evidence_required: bool                   (可选,默认 True)

参考:
- docs/design.md §4.4.2
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


DEFAULT_VERDICT_LEVELS: list[str] = ["合格", "不合格", "不适用", "需要澄清"]


class AuditorPES(BasePES):
    """对照 data/checkpoints.json 审核文档合规性。

    阶段契约:
    - plan     → working/plan.md + working/plan.json(Agent 读 data/checkpoints.json)
    - execute  → working/findings/<cp_id>.json(每 checkpoint 一个)
    - summarize→ working/output.json(汇总 findings + summary)

    业务层需在调 pes.run() 前把 checkpoints 以 `[{id, description, ...}]`
    写入 `workspace.data_dir/checkpoints.json`。
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """summarize 阶段:schema 校验 + verdict/evidence 规则。"""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "AuditorPES 需要 runtime_context['output_schema'](pydantic BaseModel 子类)"
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] 必须是 BaseModel 子类,"
                f"得到 {type(schema).__name__}"
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(f"AuditorPES summarize 阶段 output.json 未生成: {output_path}")

        try:
            data = relaxed_json_loads(
                output_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"output.json 不是合法 JSON: {e}") from e

        try:
            validated = schema.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"output.json 不符 output_schema: {e}") from e

        verdict_levels: list[str] = list(
            self.runtime_context.get("verdict_levels") or DEFAULT_VERDICT_LEVELS
        )
        evidence_required: bool = bool(self.runtime_context.get("evidence_required", True))

        findings = data.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("output.json.findings 必须是列表")

        for idx, finding in enumerate(findings):
            if not isinstance(finding, dict):
                raise ValueError(f"findings[{idx}] 必须是对象")
            verdict = finding.get("verdict")
            if verdict not in verdict_levels:
                raise ValueError(
                    f"findings[{idx}].verdict={verdict!r} 不在 verdict_levels={verdict_levels}"
                )
            if evidence_required:
                evidence = finding.get("evidence") or []
                if not isinstance(evidence, list) or len(evidence) == 0:
                    raise ValueError(f"findings[{idx}] 缺少 evidence(evidence_required=True)")

        run.final_output = validated.model_dump()
        run.final_output_path = output_path

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: "PhaseConfig",
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """execute 阶段:data/checkpoints.json 的 cp_id 与 findings 对齐。"""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        cp_path = self.workspace.data_dir / "checkpoints.json"
        if not cp_path.exists():
            raise ValueError(f"AuditorPES 需要业务层预置 data/checkpoints.json(未找到: {cp_path})")

        try:
            checkpoints = relaxed_json_loads(
                cp_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"data/checkpoints.json 不是合法 JSON: {e}") from e

        if not isinstance(checkpoints, list):
            raise ValueError("data/checkpoints.json 必须是对象列表 [{id, description}, ...]")

        expected_ids = {cp["id"] for cp in checkpoints if isinstance(cp, dict) and "id" in cp}

        findings_dir = self.workspace.working_dir / "findings"
        actual_ids = (
            {p.stem for p in findings_dir.glob("*.json")} if findings_dir.exists() else set()
        )

        missing = expected_ids - actual_ids
        if missing:
            raise ValueError(f"未覆盖的 checkpoint id: {sorted(missing)}")
