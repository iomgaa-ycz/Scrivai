"""scrivai.models.evolution 新版 pydantic 模型合约测试(M2)。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_failure_sample_roundtrip():
    from scrivai.models.evolution import FailureSample

    sample = FailureSample(
        feedback_id=1,
        run_id="mock-extractor-0",
        task_prompt="抽取变电站维护要点",
        question='{"input_summary":"..."}',
        draft_output_str='{"items":[]}',
        ground_truth_str='{"items":["变压器油温"]}',
        baseline_score=0.42,
        confidence=0.9,
        trajectory_summary={"plan": "p", "execute": "e", "summarize": "s"},
        data_inputs={"tender.md": Path("/tmp/x")},
    )
    dumped = sample.model_dump_json()
    loaded = FailureSample.model_validate_json(dumped)
    assert loaded == sample


def test_skill_version_required_fields():
    from scrivai.models.evolution import SkillVersion

    v = SkillVersion(
        version_id="extractor:available-tools:2026-04-17T00:00:00+00:00:abc",
        pes_name="extractor",
        skill_name="available-tools",
        parent_version_id=None,
        content_snapshot={"SKILL.md": "# test"},
        content_diff="",
        change_summary="baseline",
        status="draft",
        created_at=datetime.now(timezone.utc),
        created_by="human",
    )
    assert v.promoted_at is None
    assert v.status == "draft"


def test_skill_version_status_enum():
    from scrivai.models.evolution import SkillVersion

    with pytest.raises(ValidationError):
        SkillVersion(
            version_id="x",
            pes_name="e",
            skill_name="s",
            parent_version_id=None,
            content_snapshot={},
            content_diff="",
            change_summary="",
            status="invalid",  # type: ignore[arg-type]
            created_at=datetime.now(timezone.utc),
            created_by="human",
        )


def test_evolution_proposal_fields():
    from scrivai.models.evolution import EvolutionProposal

    p = EvolutionProposal(
        new_content_snapshot={"SKILL.md": "x"},
        change_summary="试",
        reasoning="因为",
    )
    assert "SKILL.md" in p.new_content_snapshot


def test_evolution_score_shape():
    from scrivai.models.evolution import EvolutionScore

    s = EvolutionScore(
        version_id="v1",
        score=0.7,
        per_sample_scores=[0.6, 0.8],
        hold_out_size=2,
        llm_calls_consumed=6,
        evaluated_at=datetime.now(timezone.utc),
    )
    assert s.score == 0.7


def test_evolution_run_record_defaults():
    from scrivai.models.evolution import EvolutionRunRecord

    r = EvolutionRunRecord(
        evo_run_id="run1",
        pes_name="extractor",
        skill_name="available-tools",
        config_snapshot={"max_iterations": 5},
        started_at=datetime.now(timezone.utc),
        baseline_version_id="v0",
        baseline_score=0.5,
    )
    assert r.status == "running"
    assert r.candidate_version_ids == []
    assert r.llm_calls_used == 0


def test_evolution_run_config_validation():
    from scrivai.models.evolution import EvolutionRunConfig

    c = EvolutionRunConfig(pes_name="extractor", skill_name="available-tools")
    assert c.max_iterations == 5
    assert c.max_llm_calls == 500
    with pytest.raises(ValidationError):
        EvolutionRunConfig(pes_name="e", skill_name="s", hold_out_ratio=0.05)  # < 0.1
    with pytest.raises(ValidationError):
        EvolutionRunConfig(
            pes_name="e",
            skill_name="s",
            hold_out_ratio=0.7,
        )  # > 0.5


def test_old_symbols_removed():
    """M0 残留的 EvoSkill 兼容符号不应再导出。"""
    import scrivai.models.evolution as mod

    for sym in (
        "FeedbackExample",
        "EvolutionConfig",
        "EvolutionRun",
        "SkillsRootResolver",
        "Evaluator",
    ):
        assert not hasattr(mod, sym), f"{sym} 应已删除"
