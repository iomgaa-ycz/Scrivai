"""EvolutionTrigger 合约测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from scrivai.models.trajectory import (
    FeedbackRecord,
    PhaseRecord,
    TrajectoryRecord,
)


def _mk_feedback(fid: int, run_id: str, draft, final, conf=0.9) -> FeedbackRecord:
    return FeedbackRecord(
        feedback_id=fid,
        run_id=run_id,
        input_summary=f"input-{fid}",
        draft_output=draft,
        final_output=final,
        corrections=None,
        confidence=conf,
        submitted_at=datetime.now(timezone.utc),
    )


def _mk_trajectory(run_id: str) -> TrajectoryRecord:
    return TrajectoryRecord(
        run_id=run_id,
        pes_name="extractor",
        model_name="glm-5.1",
        provider="glm",
        sdk_version="0.1.3",
        task_prompt=f"task for {run_id}",
        status="completed",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        final_output={},
        phase_records=[
            PhaseRecord(
                phase_id=1,
                run_id=run_id,
                phase_name="plan",
                attempt_no=1,
                phase_order=0,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
                prompt="plan prompt",
                response_text="plan response",
            ),
            PhaseRecord(
                phase_id=2,
                run_id=run_id,
                phase_name="execute",
                attempt_no=1,
                phase_order=1,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
                prompt="exec prompt",
                response_text="exec response",
            ),
        ],
    )


def _evaluator(question, predicted, ground_truth) -> float:
    """简单 IoU scorer(测试用)。"""
    pset = set(predicted.split())
    gset = set(ground_truth.split())
    if not gset:
        return 1.0
    inter = len(pset & gset)
    union = len(pset | gset)
    return inter / union if union else 0.0


def test_has_enough_data():
    from scrivai.evolution.trigger import EvolutionTrigger

    store = MagicMock()
    store.get_feedback_pairs.return_value = [
        _mk_feedback(i, f"r-{i}", {"x": "a"}, {"x": "b"}) for i in range(12)
    ]
    t = EvolutionTrigger(store, "extractor", "available-tools", _evaluator)
    assert t.has_enough_data(min_samples=10)
    assert not t.has_enough_data(min_samples=20)


def test_collect_failures_split_deterministic():
    from scrivai.evolution.trigger import EvolutionTrigger

    feedbacks = []
    for i in range(10):
        if i % 2 == 0:
            feedbacks.append(_mk_feedback(i, f"r-{i}", {"x": "a"}, {"x": "a"}))
        else:
            feedbacks.append(_mk_feedback(i, f"r-{i}", {"x": "a"}, {"x": "b c d"}))

    store = MagicMock()
    store.get_feedback_pairs.return_value = feedbacks
    store.get_run.side_effect = lambda run_id: _mk_trajectory(run_id)

    t = EvolutionTrigger(store, "extractor", "available-tools", _evaluator)
    train1, hold1 = t.collect_failures(hold_out_ratio=0.3, random_seed=42)
    train2, hold2 = t.collect_failures(hold_out_ratio=0.3, random_seed=42)

    assert [s.feedback_id for s in train1] == [s.feedback_id for s in train2]
    assert [s.feedback_id for s in hold1] == [s.feedback_id for s in hold2]


def test_collect_failures_failure_threshold():
    from scrivai.evolution.trigger import EvolutionTrigger

    fb_hit = _mk_feedback(0, "r-0", {"x": "a"}, {"x": "a"})
    fb_miss = _mk_feedback(1, "r-1", {"x": "a"}, {"x": "b c d"})
    store = MagicMock()
    store.get_feedback_pairs.return_value = [fb_hit, fb_miss] * 10
    store.get_run.side_effect = lambda rid: _mk_trajectory(rid)

    t = EvolutionTrigger(store, "extractor", "available-tools", _evaluator, failure_threshold=0.5)
    train, _ = t.collect_failures(hold_out_ratio=0.3, random_seed=42)
    assert all(s.baseline_score < 0.5 for s in train)


def test_trajectory_summary_truncation():
    from scrivai.evolution.trigger import EvolutionTrigger

    long_resp = "x" * 5000
    tr = _mk_trajectory("r-0")
    tr.phase_records[0].response_text = long_resp

    store = MagicMock()
    store.get_feedback_pairs.return_value = [_mk_feedback(0, "r-0", {"a": "1"}, {"a": "2"})]
    store.get_run.return_value = tr

    t = EvolutionTrigger(store, "extractor", "available-tools", _evaluator)
    train, hold = t.collect_failures(hold_out_ratio=0.0, random_seed=1)
    samples = train + hold
    assert len(samples) == 1
    assert len(samples[0].trajectory_summary["plan"]) < 1000
