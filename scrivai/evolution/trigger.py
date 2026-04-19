"""EvolutionTrigger — pulls feedback from trajectory and splits into train/hold_out.

See docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.1
"""

from __future__ import annotations

import json
import random
from typing import Callable

from scrivai.models.evolution import FailureSample
from scrivai.models.trajectory import TrajectoryRecord
from scrivai.trajectory.store import TrajectoryStore

_PHASE_TRUNCATE = 800  # max characters per phase response text


def _truncate(s: str, n: int = _PHASE_TRUNCATE) -> str:
    """Truncate a string; when over-length, keep the first and last n//2 characters with an ellipsis."""
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + " … " + s[-half:]


def _summarize_trajectory(tr: TrajectoryRecord | None) -> dict[str, str]:
    """Aggregate truncated phase response texts from a trajectory into a {phase_name: summary} dict."""
    if tr is None or not tr.phase_records:
        return {}
    out: dict[str, str] = {}
    for p in tr.phase_records:
        parts = [f"response: {_truncate(p.response_text or '')}"]
        if p.error:
            parts.append(f"error: {p.error}")
        out[p.phase_name] = " | ".join(parts)
    return out


def _json_dumps(v: object) -> str:
    """Serialize an arbitrary value to a deterministic JSON string."""
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class EvolutionTrigger:
    """Pulls feedback from trajectory.feedback, scores with the evaluator, and splits into train/hold_out.

    Args:
        trajectory_store: TrajectoryStore instance providing get_feedback_pairs/get_run.
        pes_name: Target PES name used to filter feedback records.
        skill_name: Skill name (currently an identifier field used by the caller).
        evaluator_fn: Scoring function ``(question, predicted, ground_truth) -> float`` in [0, 1].
        min_confidence: Minimum feedback quality threshold; records below this are filtered out.
        failure_threshold: baseline_score below this value is treated as a failure sample for train.
    """

    def __init__(
        self,
        trajectory_store: TrajectoryStore,
        pes_name: str,
        skill_name: str,
        evaluator_fn: Callable[[str, str, str], float],
        min_confidence: float = 0.7,
        failure_threshold: float = 0.5,
    ) -> None:
        self.store = trajectory_store
        self.pes_name = pes_name
        self.skill_name = skill_name
        self.evaluator_fn = evaluator_fn
        self.min_confidence = min_confidence
        self.failure_threshold = failure_threshold

    def has_enough_data(self, min_samples: int = 10) -> bool:
        """Check whether enough feedback samples have been accumulated.

        Args:
            min_samples: Minimum sample count threshold.

        Returns:
            True if the sample count meets the threshold and evolution can be triggered.
        """
        pairs = self.store.get_feedback_pairs(
            pes_name=self.pes_name, min_confidence=self.min_confidence
        )
        return len(pairs) >= min_samples

    def collect_failures(
        self,
        hold_out_ratio: float = 0.3,
        random_seed: int = 42,
    ) -> tuple[list[FailureSample], list[FailureSample]]:
        """Fetch feedback, score samples, and split into train/hold_out.

        Steps:
        1. Pull feedback pairs from TrajectoryStore that meet min_confidence.
        2. Try to load the corresponding trajectory and extract truncated phase summaries
           (silently skip if get_run fails).
        3. Call evaluator_fn to compute baseline_score.
        4. Shuffle with a fixed random seed, then split by hold_out_ratio.
        5. Keep only samples with baseline_score < failure_threshold in the train set.

        Args:
            hold_out_ratio: Fraction of total samples for hold_out in [0.0, 1.0).
            random_seed: Random seed to guarantee reproducible results for the same parameters.

        Returns:
            Tuple ``(train_failures, hold_out_samples)`` of two FailureSample lists.
        """
        pairs = self.store.get_feedback_pairs(
            pes_name=self.pes_name, min_confidence=self.min_confidence
        )
        samples: list[FailureSample] = []
        for fb in pairs:
            tr: TrajectoryRecord | None = None
            try:
                tr = self.store.get_run(fb.run_id)
            except Exception:
                pass
            task_prompt = tr.task_prompt if tr else ""
            question = fb.input_summary
            draft_str = _json_dumps(fb.draft_output)
            gt_str = _json_dumps(fb.final_output)
            score = self.evaluator_fn(question, draft_str, gt_str)
            samples.append(
                FailureSample(
                    feedback_id=fb.feedback_id,
                    run_id=fb.run_id,
                    task_prompt=task_prompt,
                    question=question,
                    draft_output_str=draft_str,
                    ground_truth_str=gt_str,
                    baseline_score=score,
                    confidence=fb.confidence,
                    trajectory_summary=_summarize_trajectory(tr),
                )
            )

        rng = random.Random(random_seed)
        shuffled = samples[:]
        rng.shuffle(shuffled)
        n_hold = int(round(len(shuffled) * hold_out_ratio))
        hold_out = shuffled[:n_hold]
        train_pool = shuffled[n_hold:]
        train_failures = [s for s in train_pool if s.baseline_score < self.failure_threshold]
        return train_failures, hold_out
