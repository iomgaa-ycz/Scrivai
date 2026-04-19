"""run_evolution — full evolution cycle orchestrator (M2).

Reference: docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.4 / §6.3
"""

from __future__ import annotations

import difflib
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from scrivai.evolution.budget import BudgetExceededError, LLMCallBudget
from scrivai.evolution.evaluator import CandidateEvaluator
from scrivai.evolution.proposer import Proposer, ProposerError
from scrivai.evolution.store import SkillVersionStore
from scrivai.evolution.trigger import EvolutionTrigger
from scrivai.models.evolution import (
    EvolutionProposal,
    EvolutionRunConfig,
    EvolutionRunRecord,
    SkillVersion,
)
from scrivai.models.workspace import WorkspaceHandle


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def _version_id(pes: str, skill: str, parent: Optional[str], snapshot: dict[str, str]) -> str:
    """Generate a deterministic version ID for a candidate.

    Args:
        pes: PES name.
        skill: Skill name.
        parent: Parent version ID (``None`` for baseline).
        snapshot: Content snapshot dict.

    Returns:
        Version ID string in the format ``{pes}:{skill}:{parent_tag}:{ts}:{hash8}``.
    """
    h = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:8]
    ts = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    parent_tag = parent[-8:] if parent else "baseline"
    return f"{pes}:{skill}:{parent_tag}:{ts}:{h}"


def _unified_diff(parent_snapshot: dict[str, str], new_snapshot: dict[str, str]) -> str:
    """Generate a unified diff string between two content snapshots.

    Args:
        parent_snapshot: Parent version content snapshot.
        new_snapshot: New version content snapshot.

    Returns:
        Unified diff string.
    """
    lines: list[str] = []
    all_keys = set(parent_snapshot) | set(new_snapshot)
    for k in sorted(all_keys):
        a = parent_snapshot.get(k, "").splitlines(keepends=True)
        b = new_snapshot.get(k, "").splitlines(keepends=True)
        lines.extend(difflib.unified_diff(a, b, fromfile=f"a/{k}", tofile=f"b/{k}"))
    return "".join(lines)


@dataclass
class Frontier:
    """Greedy top-K frontier maintaining the current best candidate set.

    Args:
        size: Maximum number of candidates to retain.
        members: Ordered list of (version_id, score) tuples (descending).
    """

    size: int
    members: list[tuple[str, float]] = field(default_factory=list)

    def consider(self, version_id: str, score: float) -> bool:
        """Attempt to add a candidate to the frontier.

        Args:
            version_id: Candidate version ID.
            score: Candidate score.

        Returns:
            True if the candidate was admitted to the frontier.
        """
        if len(self.members) < self.size:
            self.members.append((version_id, score))
            self.members.sort(key=lambda x: -x[1])
            return True
        lowest = self.members[-1][1]
        if score > lowest:
            self.members[-1] = (version_id, score)
            self.members.sort(key=lambda x: -x[1])
            return True
        return False

    def top(self) -> Optional[tuple[str, float]]:
        """Return the best candidate in the frontier.

        Returns:
            ``(version_id, score)`` tuple, or ``None`` if the frontier is empty.
        """
        return self.members[0] if self.members else None


async def run_evolution(
    config: EvolutionRunConfig,
    trajectory_store: Any,
    workspace_mgr: Any,
    pes_factory: Callable[[str, WorkspaceHandle], Any],
    evaluator_fn: Callable[[str, str, str], float],
    source_project_root: Path,
    llm_client: Any,
    version_store: Optional[SkillVersionStore] = None,
) -> EvolutionRunRecord:
    """Run a complete skill evolution cycle.

    Workflow: load/create baseline -> iterate (Proposer generates candidates ->
    CandidateEvaluator scores them) -> finalize with best version.

    Args:
        config: Evolution run configuration.
        trajectory_store: TrajectoryStore instance for feedback data.
        workspace_mgr: WorkspaceManager for creating evaluation workspaces.
        pes_factory: Factory ``(pes_name, workspace) -> PES`` for evaluation.
        evaluator_fn: Scoring function ``(question, predicted, truth) -> float``.
        source_project_root: Project root containing ``skills/`` directory.
        llm_client: LLM client for the Proposer.
        version_store: Optional SkillVersionStore (defaults to global path).

    Returns:
        EvolutionRunRecord with status, scores, and best version ID.
    """
    vstore = version_store or SkillVersionStore()
    budget = LLMCallBudget(limit=config.max_llm_calls)
    trigger = EvolutionTrigger(
        trajectory_store,
        config.pes_name,
        config.skill_name,
        evaluator_fn,
        min_confidence=config.min_confidence,
        failure_threshold=config.failure_threshold,
    )
    proposer = Proposer(llm_client, model=config.proposer_model)
    evaluator = CandidateEvaluator(
        workspace_mgr=workspace_mgr,
        pes_factory=pes_factory,
        evaluator_fn=evaluator_fn,
        source_project_root=source_project_root,
        budget=budget,
    )

    baseline = vstore.get_baseline(config.pes_name, config.skill_name, source_project_root)
    train_failures, hold_out = trigger.collect_failures(
        hold_out_ratio=config.hold_out_ratio,
        random_seed=config.random_seed,
    )

    evo_run_id = f"evo-{_utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    record = EvolutionRunRecord(
        evo_run_id=evo_run_id,
        pes_name=config.pes_name,
        skill_name=config.skill_name,
        config_snapshot=config.model_dump(),
        started_at=_utcnow(),
        baseline_version_id=baseline.version_id,
        baseline_score=0.0,
    )
    vstore.create_run(record)

    # Phase 1: evaluate baseline
    try:
        bl_score = await evaluator.evaluate(baseline, hold_out)
        record.baseline_score = bl_score.score
        record.llm_calls_used = budget.used
        vstore.record_score(bl_score, evo_run_id=evo_run_id)
        vstore.update_version_status(baseline.version_id, "evaluated")
    except BudgetExceededError:
        record.status = "budget_exceeded"
        record.completed_at = _utcnow()
        vstore.finalize_run(record)
        return record
    except Exception as e:
        record.status = "failed"
        record.error = f"baseline evaluate failed: {e}"
        record.completed_at = _utcnow()
        vstore.finalize_run(record)
        return record

    # Phase 2: iterative evolution
    frontier = Frontier(size=config.frontier_size)
    frontier.consider(baseline.version_id, bl_score.score)
    record.best_version_id = baseline.version_id
    record.best_score = bl_score.score
    rejected_history: list[EvolutionProposal] = []
    no_improvement = 0

    for it in range(config.max_iterations):
        if budget.is_exhausted:
            record.status = "budget_exceeded"
            break
        top = frontier.top()
        if top is None:
            break
        parent_id, parent_score = top
        parent_version = vstore.get_version(parent_id)
        iter_entry: dict[str, Any] = {
            "iteration": it + 1,
            "parent_id": parent_id,
            "parent_score": parent_score,
            "candidates": [],
        }
        try:
            proposals = await proposer.propose(
                current_skill_snapshot=parent_version.content_snapshot,
                failures=train_failures,
                rejected_proposals=rejected_history,
                n=config.n_proposals_per_iter,
                budget=budget,
            )
        except BudgetExceededError:
            record.status = "budget_exceeded"
            break
        except ProposerError as e:
            iter_entry["proposer_error"] = str(e)
            record.iterations_history.append(iter_entry)
            no_improvement += 1
            if no_improvement >= config.no_improvement_limit:
                break
            continue

        any_improved = False
        for p in proposals:
            vid = _version_id(
                config.pes_name,
                config.skill_name,
                parent_id,
                p.new_content_snapshot,
            )
            cand = SkillVersion(
                version_id=vid,
                pes_name=config.pes_name,
                skill_name=config.skill_name,
                parent_version_id=parent_id,
                content_snapshot=p.new_content_snapshot,
                content_diff=_unified_diff(parent_version.content_snapshot, p.new_content_snapshot),
                change_summary=p.change_summary,
                status="draft",
                created_at=_utcnow(),
                created_by=config.proposer_model,
            )
            vstore.save_version(cand)
            record.candidate_version_ids.append(vid)

            try:
                score = await evaluator.evaluate(cand, hold_out)
            except BudgetExceededError:
                record.status = "budget_exceeded"
                record.llm_calls_used = budget.used
                iter_entry["candidates"].append(
                    {
                        "version_id": vid,
                        "error": "budget_exceeded",
                    }
                )
                record.iterations_history.append(iter_entry)
                record.completed_at = _utcnow()
                vstore.finalize_run(record)
                return record
            vstore.record_score(score, evo_run_id=evo_run_id)
            vstore.update_version_status(vid, "evaluated")
            iter_entry["candidates"].append(
                {
                    "version_id": vid,
                    "score": score.score,
                }
            )
            frontier.consider(vid, score.score)
            if score.score > parent_score:
                any_improved = True
                if score.score > (record.best_score or 0):
                    record.best_version_id = vid
                    record.best_score = score.score
            else:
                rejected_history.append(p)

        record.iterations_history.append(iter_entry)
        record.llm_calls_used = budget.used
        if any_improved:
            no_improvement = 0
        else:
            no_improvement += 1
        if no_improvement >= config.no_improvement_limit:
            break

    # Phase 3: finalise
    if record.status == "running":
        record.status = "completed"
    record.completed_at = _utcnow()
    # best == baseline means no improvement this run; clear it
    if record.best_version_id == baseline.version_id:
        record.best_version_id = None
        record.best_score = None
    vstore.finalize_run(record)
    return record
