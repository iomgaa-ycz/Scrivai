#!/usr/bin/env python3
"""Example 03: M2 自研 Skill 进化 workflow(端到端)

演示完整 M2 进化循环:
  1. seed 4 条 mock feedback 到 demo trajectory DB
  2. 构造最小 source_project_root(仅含 skills/ + scrivai/agents/*.yaml,避免 copytree Reference/)
  3. 定义简单 evaluator_fn(预测 items 集合与标准 items 集合的 Jaccard)
  4. 跑 run_evolution(max_iter=1, n_proposals=2, budget=20)
  5. 打印 baseline 得分 + 候选得分 + best 的 diff
  6. 模拟专家决策:输入 y → promote best 到 examples/data/demo-skill-project/skills/

运行(需已配 .env 并激活 scrivai 环境):

    # 交互式(~5-10min,消耗 GLM 配额)
    conda run -n scrivai python examples/03_evolve_skill_workflow.py

    # 非交互(喂 "n" 跳过 promote 步骤)
    conda run -n scrivai python examples/03_evolve_skill_workflow.py <<< "n"

依赖环境变量(可经 .env):
    ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN
    SCRIVAI_DEFAULT_MODEL    (可选,默认 glm-5.1)
    SCRIVAI_DEFAULT_PROVIDER (可选,默认 glm)

关键设计:
  - skill_name="available-tools": 复用 Scrivai 现有 skill(真实项目根下唯一有的 extractor 可用 skill)
  - source_project_root 指向 /tmp/... 下复刻的最小 proj,避免污染真实 skills/ 目录
  - demo-skill-project 作为 promote 目标,进一步隔离 demo 产物
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# examples/ 非 package,把当前目录加入 sys.path 以便后续 `from data...` 导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from scrivai import (  # noqa: E402
    EvolutionRunConfig,
    ExtractorPES,
    ModelConfig,
    SkillVersionStore,
    build_workspace_manager,
    load_pes_config,
    promote,
    run_evolution,
)
from scrivai.models.workspace import WorkspaceSpec  # noqa: E402
from scrivai.pes.llm_client import LLMClient  # noqa: E402
from scrivai.trajectory.store import TrajectoryStore  # noqa: E402

load_dotenv()

_EXAMPLES_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _EXAMPLES_ROOT.parent
_DEMO_ROOT = Path("/tmp/scrivai-examples/evolution-demo")
_DEMO_TRAJ_DB = _DEMO_ROOT / "trajectory.db"
_DEMO_EVO_DB = _DEMO_ROOT / "evolution.db"
_DEMO_SOURCE_PROJ = _DEMO_ROOT / "source-proj"  # 最小 project_root,避免 copy Reference/


class _ExtractOut(BaseModel):
    """ExtractorPES 输出 schema(items 列表)。"""

    items: list[str] = Field(default_factory=list)


def _require_env() -> None:
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        sys.exit("[ERROR] 未设置 ANTHROPIC_AUTH_TOKEN,请配置 .env(见 README)")


def _seed_feedback() -> None:
    """调 seed_demo_feedback.py(subprocess 保证 DB 初始化隔离)。"""
    subprocess.run(
        [
            sys.executable,
            str(_EXAMPLES_ROOT / "data" / "seed_demo_feedback.py"),
            "--db",
            str(_DEMO_TRAJ_DB),
        ],
        check=True,
    )


def _build_minimal_source_proj() -> Path:
    """构造最小 source_project_root:仅含 skills/ + scrivai/agents/*.yaml。

    CandidateEvaluator 会把 source copytree 到临时目录,所以要尽量小
    (真实 Scrivai repo 带 Reference/ 有 197MB,copytree 太慢且无用)。
    """
    if _DEMO_SOURCE_PROJ.exists():
        shutil.rmtree(_DEMO_SOURCE_PROJ)
    _DEMO_SOURCE_PROJ.mkdir(parents=True)

    # 复刻真实 skills/ 目录(含 available-tools/SKILL.md 作为 baseline)
    shutil.copytree(_REPO_ROOT / "skills", _DEMO_SOURCE_PROJ / "skills")

    # 复刻 scrivai/agents/*.yaml(factory load_pes_config 需要)
    agents_dir = _DEMO_SOURCE_PROJ / "scrivai" / "agents"
    agents_dir.mkdir(parents=True)
    for yaml_file in (_REPO_ROOT / "scrivai" / "agents").glob("*.yaml"):
        shutil.copy(yaml_file, agents_dir / yaml_file.name)

    return _DEMO_SOURCE_PROJ


def _overlap_score(question: str, predicted: str, ground_truth: str) -> float:
    """简单 evaluator:对 items 集合算 Jaccard。

    参数:
        question: 问题文本(本例未使用)。
        predicted: PES 最终输出的 JSON 字符串。
        ground_truth: 标准答案 JSON 字符串。

    返回:
        Jaccard 相似度 [0.0, 1.0]。两边均空返回 1.0,解析失败返回 0.0。
    """
    try:
        pred_obj = json.loads(predicted)
        gt_obj = json.loads(ground_truth)
    except Exception:
        return 0.0
    pitems = set(map(str, pred_obj.get("items", []) if isinstance(pred_obj, dict) else []))
    gitems = set(map(str, gt_obj.get("items", []) if isinstance(gt_obj, dict) else []))
    if not pitems and not gitems:
        return 1.0
    inter = len(pitems & gitems)
    union = len(pitems | gitems)
    return inter / union if union > 0 else 0.0


def _make_pes_factory(
    model: ModelConfig, llm_client: LLMClient, traj_store: TrajectoryStore
) -> Any:
    """返回 (pes_name, workspace) -> ExtractorPES 的工厂函数。

    工厂必须用 ws.project_root(CandidateEvaluator 会把它指向注入候选 skill 的 temp proj),
    这是进化机制核心:每次候选评估都复刻项目根,只替换目标 skill 内容。
    """

    def _factory(pes_name: str, ws: Any) -> ExtractorPES:
        config = load_pes_config(
            ws.project_root / "scrivai" / "agents" / f"{pes_name}.yaml"
        )
        return ExtractorPES(
            config=config,
            model=model,
            workspace=ws,
            trajectory_store=traj_store,
            llm_client=llm_client,
            runtime_context={"output_schema": _ExtractOut},
        )

    return _factory


async def main() -> None:
    _require_env()
    _DEMO_ROOT.mkdir(parents=True, exist_ok=True)

    # ── 1/5 seed feedback ───────────────────────────────────────────
    print("[1/5] Seeding 4 demo feedback rows...")
    _seed_feedback()
    traj_store = TrajectoryStore(db_path=_DEMO_TRAJ_DB)

    # ── 2/5 构造最小 source_project_root + 依赖 ─────────────────────
    print("[2/5] Preparing minimal source_project_root + running evolution...")
    source_proj = _build_minimal_source_proj()
    evo_store = SkillVersionStore(db_path=_DEMO_EVO_DB)
    ws_mgr = build_workspace_manager(
        workspaces_root=_DEMO_ROOT / "ws",
        archives_root=_DEMO_ROOT / "archives",
    )
    model = ModelConfig(
        model=os.environ.get("SCRIVAI_DEFAULT_MODEL", "glm-5.1"),
        provider=os.environ.get("SCRIVAI_DEFAULT_PROVIDER", "glm"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    )
    llm = LLMClient(model)

    cfg = EvolutionRunConfig(
        pes_name="extractor",
        skill_name="available-tools",  # 复用 Scrivai 现有 skill
        max_iterations=1,
        n_proposals_per_iter=2,
        frontier_size=2,
        max_llm_calls=20,
        hold_out_ratio=0.5,
        random_seed=42,
        min_confidence=0.5,
        failure_threshold=0.6,
        proposer_model=model.model,
        no_improvement_limit=1,
    )

    record = await run_evolution(
        config=cfg,
        trajectory_store=traj_store,
        workspace_mgr=ws_mgr,
        pes_factory=_make_pes_factory(model, llm, traj_store),
        evaluator_fn=_overlap_score,
        source_project_root=source_proj,
        llm_client=llm,
        version_store=evo_store,
    )

    # ── 3/5 报告进化结果 ────────────────────────────────────────────
    print(f"\n[3/5] Evolution status: {record.status}")
    print(f"      evo_run_id      : {record.evo_run_id}")
    print(f"      baseline_score  : {record.baseline_score:.3f}")
    print(f"      LLM calls used  : {record.llm_calls_used}/{cfg.max_llm_calls}")
    print(f"      candidates      : {len(record.candidate_version_ids)}")
    print(f"      best_version_id : {record.best_version_id or '(无增益)'}")
    print(f"      best_score      : {record.best_score}")
    if record.error:
        print(f"      error           : {record.error}")

    if not record.best_version_id:
        print("\n[4/5] 本次无增益,跳过 promote。")
        print("[5/5] Done.")
        return

    # ── 4/5 展示 best 的 diff ──────────────────────────────────────
    best = evo_store.get_version(record.best_version_id)
    print(f"\n[4/5] Best candidate diff (截前 2000 字符):\n{'-' * 60}")
    print(best.content_diff[:2000] if best.content_diff else "(无 diff)")
    print("-" * 60)

    # ── 5/5 模拟专家决策 ───────────────────────────────────────────
    try:
        ans = input("\n是否 promote 这个候选到 examples/data/demo-skill-project/skills/? [y/N] ").strip().lower()
    except EOFError:
        ans = "n"

    if ans != "y":
        print("[5/5] 已跳过 promote。")
        return

    # promote 到 demo 场地(避免污染真实 skills/)
    demo_target = _EXAMPLES_ROOT / "data" / "demo-skill-project"
    (demo_target / "skills" / best.skill_name).mkdir(parents=True, exist_ok=True)
    backup = promote(
        version_id=best.version_id,
        source_project_root=demo_target,
        version_store=evo_store,
        backup=True,
    )
    print(f"[5/5] Promoted → {demo_target / 'skills' / best.skill_name}")
    print(f"      Backup   → {backup}")


if __name__ == "__main__":
    asyncio.run(main())
