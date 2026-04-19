"""AuditorPES verdict dict 兼容 + evidence 多字段容错测试。

来源: PR#6 (Bepr4) V3 适配需求。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel

from scrivai.agents.auditor import AuditorPES
from scrivai.models.pes import ModelConfig, PESRun, PhaseResult
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.pes.config import load_pes_config


class _Evidence(BaseModel):
    chunk_id: str
    quote: str


class _Finding(BaseModel):
    checkpoint_id: str
    verdict: str | dict
    evidence: list[_Evidence] = []
    evidence_refs: list[str] = []
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
def config():
    return load_pes_config(Path("scrivai/agents/auditor.yaml"))


def _phase_result():
    return PhaseResult(phase="summarize", attempt_no=0, started_at=datetime.now(timezone.utc))


def _run(pes):
    return PESRun(
        run_id="r1",
        pes_name="auditor",
        task_prompt="test",
        model_name="mock",
        started_at=datetime.now(timezone.utc),
    )


async def test_verdict_as_dict_accepted(workspace, config):
    """verdict 为 dict 形式 {"verdict": "合格", ...} 时正常通过。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    output = {
        "findings": [
            {
                "checkpoint_id": "a",
                "verdict": {"verdict": "合格", "evidence_quotes": ["quote1"]},
                "evidence": [],
                "reasoning": "r",
            }
        ],
        "summary": {"total": 1, "合格": 1},
    }
    (workspace.working_dir / "output.json").write_text(
        json.dumps(output), encoding="utf-8"
    )
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None


async def test_verdict_dict_invalid_level_rejected(workspace, config):
    """verdict dict 内的 verdict 值不在 verdict_levels -> ValueError。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    output = {
        "findings": [
            {
                "checkpoint_id": "a",
                "verdict": {"verdict": "bogus"},
                "evidence": [{"chunk_id": "k", "quote": "q"}],
                "reasoning": "r",
            }
        ],
        "summary": {"total": 1},
    }
    (workspace.working_dir / "output.json").write_text(
        json.dumps(output), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="verdict"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))


async def test_evidence_via_evidence_refs(workspace, config):
    """evidence 为空但 evidence_refs 非空 -> 通过 evidence_required 检查。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    output = {
        "findings": [
            {
                "checkpoint_id": "a",
                "verdict": "合格",
                "evidence": [],
                "evidence_refs": ["ref1"],
                "reasoning": "r",
            }
        ],
        "summary": {"total": 1, "合格": 1},
    }
    (workspace.working_dir / "output.json").write_text(
        json.dumps(output), encoding="utf-8"
    )
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None


async def test_evidence_via_verdict_dict_quotes(workspace, config):
    """evidence 为空但 verdict dict 含 evidence_quotes -> 通过检查。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    output = {
        "findings": [
            {
                "checkpoint_id": "a",
                "verdict": {"verdict": "合格", "evidence_quotes": ["q1"]},
                "evidence": [],
                "reasoning": "r",
            }
        ],
        "summary": {"total": 1, "合格": 1},
    }
    (workspace.working_dir / "output.json").write_text(
        json.dumps(output), encoding="utf-8"
    )
    run = _run(pes)
    await pes.postprocess_phase_result("summarize", _phase_result(), run)
    assert run.final_output is not None


async def test_all_evidence_sources_empty_rejected(workspace, config):
    """evidence / evidence_refs / evidence_quotes 全空 -> ValueError。"""
    pes = AuditorPES(
        config=config,
        model=ModelConfig(model="mock"),
        workspace=workspace,
        runtime_context={"output_schema": _AuditorOutput},
    )
    output = {
        "findings": [
            {
                "checkpoint_id": "a",
                "verdict": "合格",
                "evidence": [],
                "reasoning": "r",
            }
        ],
        "summary": {"total": 1, "合格": 1},
    }
    (workspace.working_dir / "output.json").write_text(
        json.dumps(output), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="evidence"):
        await pes.postprocess_phase_result("summarize", _phase_result(), _run(pes))
