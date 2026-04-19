"""CandidateEvaluator — re-runs the real PES with a candidate SKILL.md and scores it.

See docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.3 / §6.1
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scrivai.evolution.budget import BudgetExceededError, LLMCallBudget
from scrivai.models.evolution import EvolutionScore, FailureSample, SkillVersion
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSpec


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def _prepare_temp_project_root(
    source: Path,
    skill_name: str,
    candidate_snapshot: dict[str, str],
    prefix: str = "scrivai-eval-",
) -> Path:
    """Copy source to a temp directory and place candidate content under skills/<skill_name>/.

    Args:
        source: Source project root directory.
        skill_name: Target skill directory name.
        candidate_snapshot: Candidate file mapping {relative_path: content}.
        prefix: tempfile.mkdtemp prefix; include the version_id to help trace orphaned temp dirs.

    Returns:
        Temporary project_root path (caller is responsible for cleanup).
    """
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    shutil.copytree(source, tmp, dirs_exist_ok=True)
    target = tmp / "skills" / skill_name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for rel, content in candidate_snapshot.items():
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
    return tmp


class CandidateEvaluator:
    """Replays the real PES with a candidate SkillVersion on hold-out samples and scores it.

    Workflow:
    1. Copytree the source project_root to a temp directory, replacing the target skill content.
    2. For each hold-out sample: create workspace -> instantiate PES -> run -> score.
    3. Each sample consumes 3 LLM budget units.
    4. A single-sample failure yields score=0.0 without affecting other samples.
    5. The finally block cleans up the temp directory.
    """

    def __init__(
        self,
        workspace_mgr: Any,
        pes_factory: Callable[[str, WorkspaceHandle], Any],
        evaluator_fn: Callable[[str, str, str], float],
        source_project_root: Path,
        budget: LLMCallBudget,
    ) -> None:
        """Initialise CandidateEvaluator.

        Args:
            workspace_mgr: WorkspaceManager instance.
            pes_factory: Factory ``(pes_name, workspace) -> PES`` instance.
            evaluator_fn: Scoring function ``(question, predicted, ground_truth) -> float``.
            source_project_root: Source project root directory path.
            budget: LLM call budget guard.
        """
        self.workspace_mgr = workspace_mgr
        self.pes_factory = pes_factory
        self.evaluator_fn = evaluator_fn
        self.source_project_root = source_project_root
        self.budget = budget

    async def evaluate(
        self, version: SkillVersion, hold_out: list[FailureSample]
    ) -> EvolutionScore:
        """Evaluate a candidate SkillVersion on hold-out samples.

        Args:
            version: Candidate version to evaluate.
            hold_out: List of hold-out samples.

        Returns:
            EvolutionScore with total score, per-sample scores, and budget consumed.
        """
        # Replace colons in version_id with hyphens to avoid invalid paths; shared by prefix and run_id
        safe_vid = version.version_id.replace(":", "-")
        temp_root = _prepare_temp_project_root(
            self.source_project_root,
            version.skill_name,
            version.content_snapshot,
            prefix=f"scrivai-eval-{safe_vid}-",
        )
        per_scores: list[float] = []
        calls = 0
        try:
            for idx, sample in enumerate(hold_out):
                run_id = f"eval-{safe_vid}-{idx}"
                score = 0.0
                try:
                    spec = WorkspaceSpec(
                        run_id=run_id,
                        project_root=temp_root,
                        data_inputs=sample.data_inputs,
                        force=True,
                    )
                    ws = self.workspace_mgr.create(spec)
                    pes = self.pes_factory(version.pes_name, ws)
                    self.budget.consume(3)
                    calls += 3
                    result = await pes.run(sample.task_prompt)
                    predicted = json.dumps(
                        result.final_output,
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    score = self.evaluator_fn(sample.question, predicted, sample.ground_truth_str)
                    try:
                        self.workspace_mgr.archive(ws, success=True)
                    except Exception:
                        pass
                except BudgetExceededError:
                    # Budget exhausted — let the runner catch and terminate early; do not swallow
                    raise
                except Exception:
                    score = 0.0
                per_scores.append(score)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
        total = sum(per_scores) / len(per_scores) if per_scores else 0.0
        return EvolutionScore(
            version_id=version.version_id,
            score=total,
            per_sample_scores=per_scores,
            hold_out_size=len(hold_out),
            llm_calls_consumed=calls,
            evaluated_at=_utcnow(),
        )
