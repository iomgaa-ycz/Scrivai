"""run_evolution 合约测试(mock evaluator & proposer)。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from scrivai.models.evolution import (
    EvolutionProposal,
    EvolutionRunConfig,
    EvolutionScore,
    FailureSample,
)


@pytest.fixture
def source_project(tmp_path):
    p = tmp_path / "proj"
    (p / "skills" / "available-tools").mkdir(parents=True)
    (p / "skills" / "available-tools" / "SKILL.md").write_text("# baseline", encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_run_evolution_baseline_plus_one_iter(source_project, tmp_path):
    """跑 1 轮,单个 proposal,验证 baseline 入库 + 候选入库 + best 填充。"""
    from scrivai.evolution.runner import run_evolution
    from scrivai.evolution.store import SkillVersionStore

    tstore = MagicMock()
    tstore.get_feedback_pairs.return_value = []
    tstore.get_run.side_effect = KeyError

    async def fake_evaluate(version, hold_out):
        return EvolutionScore(
            version_id=version.version_id,
            score=0.9 if version.parent_version_id else 0.5,
            per_sample_scores=[0.9],
            hold_out_size=1,
            llm_calls_consumed=3,
            evaluated_at=datetime.now(timezone.utc),
        )

    def evaluator_fn(q, p, g) -> float:
        return 0.0

    import scrivai.evolution.runner as runner_mod

    orig_evaluator_cls = runner_mod.CandidateEvaluator
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = fake_evaluate

    def mock_evaluator_cls(*args, **kwargs):
        return mock_evaluator

    runner_mod.CandidateEvaluator = mock_evaluator_cls

    orig_proposer_cls = runner_mod.Proposer
    mock_proposer = MagicMock()
    mock_proposer.propose = AsyncMock(
        return_value=[
            EvolutionProposal(
                new_content_snapshot={"SKILL.md": "# improved"},
                change_summary="x",
                reasoning="y",
            ),
        ]
    )

    def mock_proposer_cls(*args, **kwargs):
        return mock_proposer

    runner_mod.Proposer = mock_proposer_cls

    orig_trigger_cls = runner_mod.EvolutionTrigger
    mock_trigger = MagicMock()
    sample = FailureSample(
        feedback_id=1,
        run_id="r-1",
        task_prompt="t",
        question="q",
        draft_output_str="{}",
        ground_truth_str="{}",
        baseline_score=0.3,
        confidence=0.9,
    )
    mock_trigger.has_enough_data.return_value = True
    mock_trigger.collect_failures.return_value = ([sample], [sample])

    def mock_trigger_cls(*args, **kwargs):
        return mock_trigger

    runner_mod.EvolutionTrigger = mock_trigger_cls

    try:
        vstore = SkillVersionStore(db_path=tmp_path / "evo.db")
        config = EvolutionRunConfig(
            pes_name="extractor",
            skill_name="available-tools",
            max_iterations=1,
            n_proposals_per_iter=1,
            max_llm_calls=50,
        )
        record = await run_evolution(
            config=config,
            trajectory_store=tstore,
            workspace_mgr=MagicMock(),
            pes_factory=lambda n, w: MagicMock(),
            evaluator_fn=evaluator_fn,
            source_project_root=source_project,
            llm_client=MagicMock(),
            version_store=vstore,
        )
        assert record.status == "completed"
        assert record.baseline_score == 0.5
        assert record.best_score == 0.9
        assert record.best_version_id is not None
        assert len(record.candidate_version_ids) == 1
        vers = vstore.list_versions("extractor", "available-tools")
        assert len(vers) >= 2
    finally:
        runner_mod.CandidateEvaluator = orig_evaluator_cls
        runner_mod.Proposer = orig_proposer_cls
        runner_mod.EvolutionTrigger = orig_trigger_cls


@pytest.mark.asyncio
async def test_run_evolution_budget_exceeded(source_project, tmp_path):
    """budget 满了提前退出 + status budget_exceeded。"""
    import scrivai.evolution.runner as runner_mod
    from scrivai.evolution.budget import BudgetExceededError
    from scrivai.evolution.runner import run_evolution
    from scrivai.evolution.store import SkillVersionStore

    orig_ev_cls = runner_mod.CandidateEvaluator
    orig_prop_cls = runner_mod.Proposer
    orig_trig_cls = runner_mod.EvolutionTrigger

    async def angry_evaluate(v, h):
        raise BudgetExceededError("no budget")

    mock_ev = MagicMock()
    mock_ev.evaluate = angry_evaluate
    runner_mod.CandidateEvaluator = lambda *a, **kw: mock_ev

    mock_prop = MagicMock()
    mock_prop.propose = AsyncMock(return_value=[])
    runner_mod.Proposer = lambda *a, **kw: mock_prop

    mock_trig = MagicMock()
    mock_trig.has_enough_data.return_value = True
    mock_trig.collect_failures.return_value = (
        [],
        [
            FailureSample(
                feedback_id=1,
                run_id="r-1",
                task_prompt="t",
                question="q",
                draft_output_str="{}",
                ground_truth_str="{}",
                baseline_score=0.3,
                confidence=0.9,
            )
        ],
    )
    runner_mod.EvolutionTrigger = lambda *a, **kw: mock_trig

    try:
        vstore = SkillVersionStore(db_path=tmp_path / "evo.db")
        config = EvolutionRunConfig(
            pes_name="extractor",
            skill_name="available-tools",
            max_iterations=2,
            max_llm_calls=1,
        )
        record = await run_evolution(
            config=config,
            trajectory_store=MagicMock(),
            workspace_mgr=MagicMock(),
            pes_factory=lambda n, w: MagicMock(),
            evaluator_fn=lambda q, p, g: 0.0,
            source_project_root=source_project,
            llm_client=MagicMock(),
            version_store=vstore,
        )
        assert record.status == "budget_exceeded"
    finally:
        runner_mod.CandidateEvaluator = orig_ev_cls
        runner_mod.Proposer = orig_prop_cls
        runner_mod.EvolutionTrigger = orig_trig_cls
