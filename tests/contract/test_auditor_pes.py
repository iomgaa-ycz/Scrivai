"""AuditorPES contract tests (M1.5a T1.5)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel

from scrivai.agents.auditor import AuditorPES
from scrivai.models.pes import (
    ModelConfig,
    PESConfig,
    PESRun,
    PhaseResult,
)
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.config import load_pes_config

# ──────────────── Fixtures ────────────────


class _Evidence(BaseModel):
    chunk_id: str
    quote: str


class _Finding(BaseModel):
    checkpoint_id: str
    verdict: str
    evidence: list[_Evidence]
    reasoning: str


class _AuditorOutput(BaseModel):
    findings: list[_Finding]
    summary: dict[str, int]


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
    return load_pes_config(Path("scrivai/agents/auditor.yaml"))


def _phase_result(phase: str = "summarize") -> PhaseResult:
    return PhaseResult(phase=phase, attempt_no=0, started_at=datetime.now(timezone.utc))


def _run(pes: AuditorPES) -> PESRun:
    return PESRun(
        run_id="r1",
        pes_name="auditor",
        task_prompt="test",
        model_name="mock",
        started_at=datetime.now(timezone.utc),
    )


def _write_checkpoints(ws: WorkspaceHandle, cp_ids: list[str]) -> None:
    payload = [{"id": c, "description": f"desc {c}"} for c in cp_ids]
    (ws.data_dir / "checkpoints.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid_output(cp_ids: list[str]) -> dict:
    return {
        "findings": [
            {
                "checkpoint_id": c,
                "verdict": "合格",
                "evidence": [{"chunk_id": "k", "quote": "q"}],
                "reasoning": "r",
            }
            for c in cp_ids
        ],
        "summary": {"total": len(cp_ids), "合格": len(cp_ids)},
    }


# ──────────────── postprocess_phase_result ────────────────


async def test_postprocess_happy_path(workspace, config):
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    (workspace.working_dir / "output.json").write_text(
        json.dumps(_valid_output(["a"])), encoding="utf-8"
    )
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None
    assert run.final_output["findings"][0]["verdict"] == "合格"


async def test_postprocess_missing_output_schema(workspace, config):
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={},
    )
    (workspace.working_dir / "output.json").write_text(
        json.dumps(_valid_output(["a"])), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="output_schema"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_rejects_verdict_outside_levels(workspace, config):
    """verdict 超出默认 verdict_levels → ValueError。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    bad = _valid_output(["a"])
    bad["findings"][0]["verdict"] = "totally_invalid"
    (workspace.working_dir / "output.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="verdict"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_custom_verdict_levels_accepted(workspace, config):
    """业务覆盖 verdict_levels → 新列表里的值通过。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={
            "output_schema": _AuditorOutput,
            "verdict_levels": ["pass", "fail"],
        },
    )
    out = _valid_output(["a"])
    out["findings"][0]["verdict"] = "pass"
    (workspace.working_dir / "output.json").write_text(json.dumps(out), encoding="utf-8")
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None


async def test_postprocess_evidence_required_default(workspace, config):
    """默认 evidence_required=True → evidence 空列表 → ValueError。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    bad = _valid_output(["a"])
    bad["findings"][0]["evidence"] = []
    (workspace.working_dir / "output.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_postprocess_evidence_required_disabled(workspace, config):
    """evidence_required=False → 空 evidence 可通过。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput, "evidence_required": False},
    )
    out = _valid_output(["a"])
    out["findings"][0]["evidence"] = []
    (workspace.working_dir / "output.json").write_text(json.dumps(out), encoding="utf-8")
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None


# ──────────────── validate_phase_outputs (execute) ────────────────


async def test_validate_execute_coverage_ok(workspace, config):
    pes = AuditorPES(config=config, model=ModelConfig(model="mock"), workspace=workspace)
    _write_checkpoints(workspace, ["a", "b"])
    findings = workspace.working_dir / "findings"
    findings.mkdir()
    (findings / "a.json").write_text("{}", encoding="utf-8")
    (findings / "b.json").write_text("{}", encoding="utf-8")
    await pes.validate_phase_outputs(
        "execute", config.phases["execute"], _phase_result("execute"), _run(pes)
    )


async def test_validate_execute_coverage_missing(workspace, config):
    pes = AuditorPES(config=config, model=ModelConfig(model="mock"), workspace=workspace)
    _write_checkpoints(workspace, ["a", "b"])
    findings = workspace.working_dir / "findings"
    findings.mkdir()
    (findings / "a.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="b"):
        await pes.validate_phase_outputs(
            "execute", config.phases["execute"], _phase_result("execute"), _run(pes)
        )


async def test_validate_execute_requires_checkpoints_file(workspace, config):
    """execute 阶段 data/checkpoints.json 缺失 → ValueError。"""
    pes = AuditorPES(config=config, model=ModelConfig(model="mock"), workspace=workspace)
    findings = workspace.working_dir / "findings"
    findings.mkdir()
    (findings / "a.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoints.json"):
        await pes.validate_phase_outputs(
            "execute", config.phases["execute"], _phase_result("execute"), _run(pes)
        )


# ──────────────── Real GLM smoke ────────────────


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_AUTH_TOKEN"),
    reason="real SDK smoke; requires ANTHROPIC_AUTH_TOKEN in .env",
)
async def test_auditor_smoke_with_real_glm(workspace, config):
    """AuditorPES 真跑 GLM-5.1:2 checkpoint + 短文档 → 2 findings。"""
    (workspace.data_dir / "guide.md").write_text(
        "# Safety\nAll cables are insulated.\n# Documentation\nNo manual found.\n",
        encoding="utf-8",
    )
    _write_checkpoints(workspace, ["cable_insulation", "manual_existence"])

    model = ModelConfig(
        model=os.getenv("SCRIVAI_DEFAULT_MODEL") or "glm-5.1",
        provider=os.getenv("SCRIVAI_DEFAULT_PROVIDER") or "glm",
    )
    pes = AuditorPES(
        config=config,
        model=model,
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    run = await pes.run(
        "Audit data/guide.md against data/checkpoints.json. "
        "Assign verdict '合格' when evidence exists, '不合格' otherwise. "
        "Provide evidence quote from guide.md (chunk_id can be section name)."
    )
    assert run.status == "completed", f"run failed: {run.error_type} {run.error}"
    assert run.final_output is not None
    assert len(run.final_output["findings"]) == 2
