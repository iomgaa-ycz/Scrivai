"""ExtractorPES contract tests (M1.5a T1.4).

Covers:
- postprocess_phase_result happy + error paths (schema validation)
- validate_phase_outputs execute coverage (plan items vs findings)
- runtime_context missing-field handling
- real GLM smoke (skipif no ANTHROPIC_AUTH_TOKEN)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel

from scrivai.agents.extractor import ExtractorPES
from scrivai.exceptions import PhaseError
from scrivai.models.pes import (
    ModelConfig,
    PESConfig,
    PESRun,
    PhaseResult,
)
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.config import load_pes_config

# ──────────────── Fixtures ────────────────


class _Item(BaseModel):
    id: str
    content: str


class _Output(BaseModel):
    items: list[_Item]


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceHandle:
    project = tmp_path / "project"
    project.mkdir()
    ws = tmp_path / "ws"
    for sub in ("working", "data", "output", "logs"):
        (ws / sub).mkdir(parents=True)
    return WorkspaceHandle(
        run_id="r1",
        root_dir=ws,
        working_dir=ws / "working",
        data_dir=ws / "data",
        output_dir=ws / "output",
        logs_dir=ws / "logs",
        snapshot=WorkspaceSnapshot(
            run_id="r1",
            project_root=project,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def config() -> PESConfig:
    return load_pes_config(Path("scrivai/agents/extractor.yaml"))


def _phase_result(phase: str = "summarize") -> PhaseResult:
    return PhaseResult(
        phase=phase,
        attempt_no=0,
        started_at=datetime.now(timezone.utc),
    )


def _run(pes: ExtractorPES) -> PESRun:
    return PESRun(
        run_id="r1",
        pes_name="extractor",
        task_prompt="test",
        model_name="mock",
        started_at=datetime.now(timezone.utc),
    )


# ──────────────── postprocess_phase_result ────────────────


async def test_postprocess_happy_path(workspace, config):
    """output.json 合法 + schema 通过 → run.final_output 被写入。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _Output},
    )
    (workspace.working_dir / "output.json").write_text(
        json.dumps({"items": [{"id": "a", "content": "x"}]}),
        encoding="utf-8",
    )
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output == {"items": [{"id": "a", "content": "x"}]}
    assert run.final_output_path == workspace.working_dir / "output.json"


async def test_postprocess_noop_for_non_summarize_phase(workspace, config):
    """plan / execute 阶段 postprocess 不动 run.final_output。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _Output},
    )
    run = _run(pes)
    await pes.postprocess_phase_result("plan", _phase_result("plan"), run)
    await pes.postprocess_phase_result("execute", _phase_result("execute"), run)
    assert run.final_output is None


async def test_postprocess_missing_output_schema(workspace, config):
    """runtime_context 缺 output_schema → ValueError。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={},
    )
    (workspace.working_dir / "output.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="output_schema"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_output_schema_not_basemodel(workspace, config):
    """output_schema 不是 BaseModel 子类 → ValueError。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": dict},
    )
    (workspace.working_dir / "output.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="BaseModel"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_output_json_missing(workspace, config):
    """output.json 不存在 → FileNotFoundError。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _Output},
    )
    with pytest.raises(FileNotFoundError, match="output.json"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_invalid_json(workspace, config):
    """output.json 非合法 JSON → ValueError。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _Output},
    )
    (workspace.working_dir / "output.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_schema_validation_fails(workspace, config):
    """schema.model_validate 失败 → ValueError。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _Output},
    )
    (workspace.working_dir / "output.json").write_text(
        json.dumps({"items": [{"id": "a"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="schema"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


# ──────────────── validate_phase_outputs (execute) ────────────────


async def test_validate_execute_coverage_ok(workspace, config):
    """plan items = findings/*.json → 校验通过。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
    )
    (workspace.working_dir / "plan.json").write_text(
        json.dumps(
            {
                "items_to_extract": [
                    {"id": "a", "description": "x"},
                    {"id": "b", "description": "y"},
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = workspace.working_dir / "findings"
    findings.mkdir()
    (findings / "a.json").write_text("{}", encoding="utf-8")
    (findings / "b.json").write_text("{}", encoding="utf-8")

    await pes.validate_phase_outputs(
        "execute",
        config.phases["execute"],
        _phase_result("execute"),
        _run(pes),
    )


async def test_validate_execute_coverage_missing(workspace, config):
    """findings 漏一个 → ValueError(BasePES 会归并为 output_validation_error)。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
    )
    (workspace.working_dir / "plan.json").write_text(
        json.dumps(
            {
                "items_to_extract": [
                    {"id": "a", "description": "x"},
                    {"id": "b", "description": "y"},
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = workspace.working_dir / "findings"
    findings.mkdir()
    (findings / "a.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="b"):
        await pes.validate_phase_outputs(
            "execute",
            config.phases["execute"],
            _phase_result("execute"),
            _run(pes),
        )


async def test_validate_plan_falls_back_to_super(workspace, config):
    """plan 阶段:基类 required_outputs 校验(plan.md / plan.json 任缺 → PhaseError)。"""
    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
    )
    with pytest.raises(PhaseError, match="plan.md"):
        await pes.validate_phase_outputs(
            "plan",
            config.phases["plan"],
            _phase_result("plan"),
            _run(pes),
        )


# ──────────────── Real GLM smoke (skipif) ────────────────


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_AUTH_TOKEN"),
    reason="real SDK smoke; requires ANTHROPIC_AUTH_TOKEN in .env",
)
async def test_extractor_smoke_with_real_glm(workspace, config):
    """ExtractorPES 真跑 GLM-5.1:极简 fixture + 三阶段端到端。"""
    guide = workspace.data_dir / "guide.md"
    guide.write_text(
        "# Section A\nItem 1: foo\n\n# Section B\nItem 2: bar\n",
        encoding="utf-8",
    )

    class SmokeItem(BaseModel):
        id: str
        content: str

    class SmokeOutput(BaseModel):
        items: list[SmokeItem]

    model = ModelConfig(
        model=os.getenv("SCRIVAI_DEFAULT_MODEL") or "glm-5.1",
        provider=os.getenv("SCRIVAI_DEFAULT_PROVIDER") or "glm",
    )
    pes = ExtractorPES(
        config=config,
        model=model,
        workspace=workspace,
        runtime_context={"output_schema": SmokeOutput},
    )

    run = await pes.run(
        "Read data/guide.md and extract each 'Item N: X' line as one item. "
        "Use the line's 'Item N' part (lowercased, underscore) as id, "
        "and the 'X' part as content. Expect exactly 2 items."
    )

    assert run.status == "completed", f"run failed: {run.error_type} {run.error}"
    assert run.final_output is not None
    assert "items" in run.final_output
    assert len(run.final_output["items"]) == 2, f"expected 2 items, got {run.final_output}"
