"""ExtractorPES — 从文档抽取结构化条目(M1.5a T1.4)。

runtime_context 业务字段:
- output_schema: type[BaseModel]  (必需,summarize 校验用)

参考:
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
    """从文档抽取结构化条目。

    构造签名 = BasePES.__init__(零新参数);业务参数走 runtime_context:
    - output_schema: type[BaseModel]  (必需)

    阶段契约:
    - plan     → working/plan.md + working/plan.json
                 plan.json: {"items_to_extract": [{"id": str, "description": str}, ...]}
    - execute  → working/findings/<id>.json(每 plan item 一个)
    - summarize→ working/output.json(matches output_schema)
    """

    async def postprocess_phase_result(
        self,
        phase: str,
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """summarize 阶段读 output.json 并用 output_schema 校验。其他阶段 no-op。"""
        if phase != "summarize":
            return

        schema = self.runtime_context.get("output_schema")
        if schema is None:
            raise ValueError(
                "ExtractorPES 需要 runtime_context['output_schema'](pydantic BaseModel 子类)"
            )
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                "runtime_context['output_schema'] 必须是 BaseModel 子类,"
                f"得到 {type(schema).__name__}"
            )

        output_path = self.workspace.working_dir / "output.json"
        if not output_path.exists():
            raise FileNotFoundError(
                f"ExtractorPES summarize 阶段 output.json 未生成: {output_path}"
            )

        try:
            data = relaxed_json_loads(
                output_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"output.json 不是合法 JSON: {e}") from e

        try:
            validated = schema.model_validate(data)
        except ValidationError as e:
            raise ValueError(f"output.json 不符 output_schema 定义: {e}") from e

        run.final_output = validated.model_dump()
        run.final_output_path = output_path

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: "PhaseConfig",
        result: "PhaseResult",
        run: "PESRun",
    ) -> None:
        """execute 阶段在 required_outputs 基础上追加 plan→findings 覆盖率校验。"""
        await super().validate_phase_outputs(phase, phase_cfg, result, run)

        if phase != "execute":
            return

        plan_path = self.workspace.working_dir / "plan.json"
        if not plan_path.exists():
            raise ValueError(f"execute 覆盖率校验需要 plan.json,但未找到: {plan_path}")

        try:
            plan = relaxed_json_loads(
                plan_path.read_text(encoding="utf-8"), strict=self.config.strict_json
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"plan.json 不是合法 JSON: {e}") from e

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
            raise ValueError(f"未覆盖的 plan item id: {sorted(missing)}")
