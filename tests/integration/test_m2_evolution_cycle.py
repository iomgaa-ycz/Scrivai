"""M2 E2E:真 GLM-5.1 跑一次短进化循环。

gated by ANTHROPIC_AUTH_TOKEN(CI 跳;本地必须能跑)。
LLM 调用上限 100。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_AUTH_TOKEN"),
    reason="requires ANTHROPIC_AUTH_TOKEN for GLM gateway",
)
@pytest.mark.asyncio
async def test_m2_evolution_cycle_extractor(tmp_path):
    """跑一次 Extractor available-tools 进化循环,2 轮 × 1 candidate。"""
    from scrivai import (
        EvolutionRunConfig,
        SkillVersionStore,
        build_workspace_manager,
        run_evolution,
    )
    from scrivai.agents import ExtractorPES
    from scrivai.models.pes import ModelConfig, PESConfig
    from scrivai.pes.llm_client import LLMClient
    from scrivai.trajectory.store import TrajectoryStore
    from tests.fixtures.m2_evolution.seed_feedback import seed

    # 1. seed mock feedback
    traj_db = tmp_path / "trajectory.db"
    seed(traj_db)
    tstore = TrajectoryStore(db_path=traj_db)

    # 2. source_project_root: 复制 Scrivai skills/
    source = tmp_path / "proj"
    src_skills = Path(__file__).resolve().parents[2] / "skills"
    shutil.copytree(src_skills, source / "skills")

    # 3. workspace manager
    wm = build_workspace_manager(
        workspaces_root=tmp_path / "workspaces",
        archives_root=tmp_path / "archives",
    )

    # 4. model + llm_client
    import yaml as _yaml

    cfg_path = Path(__file__).resolve().parents[2] / "scrivai" / "agents" / "extractor.yaml"
    pes_cfg_raw = _yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # PhaseConfig 需要 name 字段，YAML 中 phases 用 key 作为阶段名；注入进去
    for phase_name, phase_dict in pes_cfg_raw.get("phases", {}).items():
        phase_dict["name"] = phase_name
    pes_config = PESConfig(**pes_cfg_raw)
    model_cfg = ModelConfig(
        model=os.getenv("SCRIVAI_DEFAULT_MODEL", "glm-5.1"),
        provider=os.getenv("SCRIVAI_DEFAULT_PROVIDER", "glm"),
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
        api_key=os.getenv("ANTHROPIC_AUTH_TOKEN"),
    )
    llm_client = LLMClient(model_cfg)

    # 5. pes_factory
    def pes_factory(pes_name: str, workspace):
        from pydantic import BaseModel, Field

        class _MinimalOut(BaseModel):
            items: list[str] = Field(default_factory=list)

        return ExtractorPES(
            config=pes_config,
            model=model_cfg,
            workspace=workspace,
            trajectory_store=tstore,
            llm_client=llm_client,
            runtime_context={"output_schema": _MinimalOut},
        )

    # 6. evaluator_fn: 对 items 列表做简单 IoU
    def evaluator_fn(question: str, predicted: str, ground_truth: str) -> float:
        try:
            pred_obj = json.loads(predicted)
            gt_obj = json.loads(ground_truth)
        except Exception:
            return 0.0
        pitems = set(map(str, pred_obj.get("items", [])))
        gitems = set(map(str, gt_obj.get("items", [])))
        if not gitems:
            return 1.0 if not pitems else 0.0
        inter = len(pitems & gitems)
        union = len(pitems | gitems)
        return inter / union if union else 0.0

    # 7. run
    vstore = SkillVersionStore(db_path=tmp_path / "evolution.db")
    config = EvolutionRunConfig(
        pes_name="extractor",
        skill_name="available-tools",
        max_iterations=2,
        n_proposals_per_iter=1,
        frontier_size=2,
        no_improvement_limit=2,
        max_llm_calls=100,
        hold_out_ratio=0.3,
    )
    record = await run_evolution(
        config=config,
        trajectory_store=tstore,
        workspace_mgr=wm,
        pes_factory=pes_factory,
        evaluator_fn=evaluator_fn,
        source_project_root=source,
        llm_client=llm_client,
        version_store=vstore,
    )

    # 8. assertions
    assert record.status in ("completed", "budget_exceeded", "failed"), record.status
    versions = vstore.list_versions("extractor", "available-tools")
    assert len(versions) >= 1, f"expected at least baseline, got {len(versions)}"

    # 9. Markdown 报告
    out_dir = Path(__file__).resolve().parents[1] / "outputs" / "integration"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    report = out_dir / f"m2_evolution_{ts}.md"
    lines = [
        f"# M2 Evolution Cycle — {ts}",
        f"- evo_run_id: `{record.evo_run_id}`",
        f"- status: **{record.status}**",
        f"- baseline_score: {record.baseline_score:.3f}",
        f"- best_score: {record.best_score}",
        f"- best_version_id: `{record.best_version_id}`",
        f"- llm_calls_used: {record.llm_calls_used}",
        f"- candidates: {len(record.candidate_version_ids)}",
        f"- error: {record.error}" if record.error else "",
        "",
        "## Iterations",
    ]
    for it in record.iterations_history:
        lines.append(f"### Iter {it.get('iteration')}")
        lines.append(f"- parent: `{it.get('parent_id')}`  parent_score={it.get('parent_score')}")
        if it.get("proposer_error"):
            lines.append(f"- proposer_error: {it['proposer_error']}")
        for c in it.get("candidates", []):
            lines.append(f"  - {c.get('version_id')}: {c.get('score', c.get('error'))}")
    report.write_text(
        "\n".join(line for line in lines if line is not None),
        encoding="utf-8",
    )
    print(f"report written to {report}")
