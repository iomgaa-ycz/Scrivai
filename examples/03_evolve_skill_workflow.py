#!/usr/bin/env python3
"""Example 03: M2 skill evolution workflow (end-to-end)

Demonstrates the complete M2 evolution loop:
  1. Seed 4 mock feedback rows into a demo trajectory DB
  2. Build a minimal source_project_root (only skills/ + scrivai/agents/*.yaml,
     avoiding copytree of Reference/ which can be large)
  3. Define a simple evaluator_fn (Jaccard similarity on predicted vs ground-truth items)
  4. Run run_evolution(max_iter=1, n_proposals=2, budget=20)
  5. Print baseline score, candidate scores, and the best candidate's diff
  6. Simulate expert decision: enter y to promote best to
     examples/data/demo-skill-project/skills/

Run:
    python examples/03_evolve_skill_workflow.py              # interactive (~5-10 min)
    python examples/03_evolve_skill_workflow.py <<< "n"     # non-interactive, skip promote

Environment variables:
    ANTHROPIC_API_KEY         (required)
    ANTHROPIC_BASE_URL        (optional, for compatible gateways)
    SCRIVAI_DEFAULT_MODEL     (optional, default claude-sonnet-4-20250514)

Key design notes:
  - skill_name="available-tools": reuses an existing Scrivai skill (the only extractor
    skill available under the real project root)
  - source_project_root points to a minimal copy under /tmp/..., avoiding pollution of
    the real skills/ directory
  - demo-skill-project is the promote target, further isolating demo artifacts
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

# examples/ is not a package, add current directory to sys.path for `from data...` imports
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
from scrivai.pes.llm_client import LLMClient  # noqa: E402
from scrivai.trajectory.store import TrajectoryStore  # noqa: E402

load_dotenv()

_EXAMPLES_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _EXAMPLES_ROOT.parent
_DEMO_ROOT = Path("/tmp/scrivai-examples/evolution-demo")
_DEMO_TRAJ_DB = _DEMO_ROOT / "trajectory.db"
_DEMO_EVO_DB = _DEMO_ROOT / "evolution.db"
_DEMO_SOURCE_PROJ = _DEMO_ROOT / "source-proj"  # minimal project_root, avoids copying Reference/


class _ExtractOut(BaseModel):
    """ExtractorPES output schema (items list)."""

    items: list[str] = Field(default_factory=list)


def _require_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("[ERROR] ANTHROPIC_API_KEY not set. See README for configuration.")


def _seed_feedback() -> None:
    """Call seed_demo_feedback.py via subprocess to ensure DB initialization is isolated."""
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
    """Build minimal source_project_root: only skills/ + scrivai/agents/*.yaml.

    CandidateEvaluator copies the source tree to a temp directory, so keeping it
    small is important (the real Scrivai repo with Reference/ is ~197 MB and
    copytree would be slow and unnecessary).
    """
    if _DEMO_SOURCE_PROJ.exists():
        shutil.rmtree(_DEMO_SOURCE_PROJ)
    _DEMO_SOURCE_PROJ.mkdir(parents=True)

    # Mirror the real skills/ directory (includes available-tools/SKILL.md as baseline)
    shutil.copytree(_REPO_ROOT / "skills", _DEMO_SOURCE_PROJ / "skills")

    # Mirror scrivai/agents/*.yaml (required by factory load_pes_config)
    agents_dir = _DEMO_SOURCE_PROJ / "scrivai" / "agents"
    agents_dir.mkdir(parents=True)
    for yaml_file in (_REPO_ROOT / "scrivai" / "agents").glob("*.yaml"):
        shutil.copy(yaml_file, agents_dir / yaml_file.name)

    return _DEMO_SOURCE_PROJ


def _overlap_score(question: str, predicted: str, ground_truth: str) -> float:
    """Simple evaluator: computes Jaccard similarity on the items sets.

    Args:
        question: Question text (unused in this example).
        predicted: JSON string of final PES output.
        ground_truth: JSON string of the reference answer.

    Returns:
        Jaccard similarity in [0.0, 1.0]. Returns 1.0 if both sides are empty,
        0.0 on parse error.
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
    """Return a (pes_name, workspace) -> ExtractorPES factory function.

    The factory must use ws.project_root (CandidateEvaluator points it at a temp
    project with the candidate skill injected). This is the core of the evolution
    mechanism: each candidate evaluation gets its own project root copy with only
    the target skill content replaced.
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

    # ── 2/5 Build minimal source_project_root + dependencies ────────
    print("[2/5] Preparing minimal source_project_root + running evolution...")
    source_proj = _build_minimal_source_proj()
    evo_store = SkillVersionStore(db_path=_DEMO_EVO_DB)
    ws_mgr = build_workspace_manager(
        workspaces_root=_DEMO_ROOT / "ws",
        archives_root=_DEMO_ROOT / "archives",
    )
    model = ModelConfig(
        model=os.environ.get("SCRIVAI_DEFAULT_MODEL", "claude-sonnet-4-20250514"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    llm = LLMClient(model)

    cfg = EvolutionRunConfig(
        pes_name="extractor",
        skill_name="available-tools",  # reuse existing Scrivai skill
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

    # ── 3/5 Report evolution results ────────────────────────────────
    print(f"\n[3/5] Evolution status: {record.status}")
    print(f"      evo_run_id      : {record.evo_run_id}")
    print(f"      baseline_score  : {record.baseline_score:.3f}")
    print(f"      LLM calls used  : {record.llm_calls_used}/{cfg.max_llm_calls}")
    print(f"      candidates      : {len(record.candidate_version_ids)}")
    print(f"      best_version_id : {record.best_version_id or '(no improvement)'}")
    print(f"      best_score      : {record.best_score}")
    if record.error:
        print(f"      error           : {record.error}")

    if not record.best_version_id:
        print("\n[4/5] No improvement this run, skipping promote.")
        print("[5/5] Done.")
        return

    # ── 4/5 Show best candidate diff ────────────────────────────────
    best = evo_store.get_version(record.best_version_id)
    print(f"\n[4/5] Best candidate diff (first 2000 chars):\n{'-' * 60}")
    print(best.content_diff[:2000] if best.content_diff else "(no diff)")
    print("-" * 60)

    # ── 5/5 Simulate expert decision ────────────────────────────────
    try:
        ans = input(
            "\nPromote this candidate to examples/data/demo-skill-project/skills/? [y/N] "
        ).strip().lower()
    except EOFError:
        ans = "n"

    if ans != "y":
        print("[5/5] Promote skipped.")
        return

    # Promote to demo target (avoids polluting real skills/)
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
