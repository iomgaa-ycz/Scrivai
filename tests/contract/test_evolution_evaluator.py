"""CandidateEvaluator 合约测试。

注意:此测试不跑真 PES,只 mock pes_factory,验证:
- 临时 project_root 结构正确(target skill 被换,其余文件完整)
- budget 消耗准确(3 per sample)
- 失败的 single sample 不影响其他 samples
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from scrivai.models.evolution import FailureSample, SkillVersion


@pytest.fixture
def source_project(tmp_path):
    root = tmp_path / "proj"
    (root / "skills" / "available-tools").mkdir(parents=True)
    (root / "skills" / "available-tools" / "SKILL.md").write_text("# baseline", encoding="utf-8")
    (root / "skills" / "other").mkdir(parents=True)
    (root / "skills" / "other" / "SKILL.md").write_text("# other untouched", encoding="utf-8")
    return root


def _mk_sample(i: int) -> FailureSample:
    return FailureSample(
        feedback_id=i,
        run_id=f"r-{i}",
        task_prompt=f"task-{i}",
        question=f"q-{i}",
        draft_output_str='{"x":1}',
        ground_truth_str='{"x":2}',
        baseline_score=0.1,
        confidence=0.9,
    )


def _mk_version(content: str = "# candidate") -> SkillVersion:
    return SkillVersion(
        version_id="cand-1",
        pes_name="extractor",
        skill_name="available-tools",
        parent_version_id="baseline",
        content_snapshot={"SKILL.md": content},
        content_diff="",
        change_summary="test",
        status="draft",
        created_at=datetime.now(timezone.utc),
        created_by="test",
    )


def _fake_workspace_create(tmp_path):
    """Helper to build a workspace_mgr.create fake using real WorkspaceHandle."""
    from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot

    def fake_create(spec):
        ws_root = tmp_path / "ws" / spec.run_id
        (ws_root / "working").mkdir(parents=True, exist_ok=True)
        (ws_root / "data").mkdir(parents=True, exist_ok=True)
        (ws_root / "output").mkdir(parents=True, exist_ok=True)
        (ws_root / "logs").mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            spec.project_root / "skills",
            ws_root / "working" / ".claude" / "skills",
            dirs_exist_ok=True,
        )
        snap = WorkspaceSnapshot(
            run_id=spec.run_id,
            project_root=spec.project_root.resolve(),
            skills_git_hash=None,
            agents_git_hash=None,
            snapshot_at=datetime.now(timezone.utc),
        )
        return WorkspaceHandle(
            run_id=spec.run_id,
            root_dir=ws_root,
            working_dir=ws_root / "working",
            data_dir=ws_root / "data",
            output_dir=ws_root / "output",
            logs_dir=ws_root / "logs",
            snapshot=snap,
        )

    return fake_create


@pytest.mark.asyncio
async def test_evaluate_prepares_temp_project_root(source_project, tmp_path):
    from scrivai.evolution.budget import LLMCallBudget
    from scrivai.evolution.evaluator import CandidateEvaluator

    seen_contents: list[str] = []

    async def fake_run(task_prompt):
        wd = fake_pes._workspace.working_dir
        skill_file = wd / ".claude" / "skills" / "available-tools" / "SKILL.md"
        seen_contents.append(skill_file.read_text(encoding="utf-8"))
        fake_result = MagicMock()
        fake_result.final_output = {"answer": "pretend"}
        return fake_result

    fake_pes = MagicMock()
    fake_pes.run = AsyncMock(side_effect=fake_run)

    def fake_factory(pes_name, workspace):
        fake_pes._workspace = workspace
        return fake_pes

    wm = MagicMock()
    wm.create = _fake_workspace_create(tmp_path)
    wm.archive = MagicMock(return_value=tmp_path / "archive.tar.gz")

    def evaluator_fn(q, pred, gt) -> float:
        return 0.75

    b = LLMCallBudget(limit=100)
    ev = CandidateEvaluator(
        workspace_mgr=wm,
        pes_factory=fake_factory,
        evaluator_fn=evaluator_fn,
        source_project_root=source_project,
        budget=b,
    )
    score = await ev.evaluate(_mk_version("# CANDIDATE NEW"), [_mk_sample(0)])
    assert all("CANDIDATE NEW" in c for c in seen_contents)
    assert score.score == 0.75
    assert score.hold_out_size == 1
    assert b.used == 3


@pytest.mark.asyncio
async def test_evaluate_isolated_sample_failure(source_project, tmp_path):
    from scrivai.evolution.budget import LLMCallBudget
    from scrivai.evolution.evaluator import CandidateEvaluator

    call_count = {"n": 0}

    async def flaky_run(task_prompt):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("second sample blows up")
        r = MagicMock()
        r.final_output = {"ok": True}
        return r

    fake_pes = MagicMock()
    fake_pes.run = AsyncMock(side_effect=flaky_run)

    def factory(pn, ws):
        return fake_pes

    wm = MagicMock()
    wm.create = _fake_workspace_create(tmp_path)
    wm.archive = MagicMock()

    ev = CandidateEvaluator(
        workspace_mgr=wm,
        pes_factory=factory,
        evaluator_fn=lambda q, p, g: 0.9,
        source_project_root=source_project,
        budget=LLMCallBudget(limit=100),
    )
    score = await ev.evaluate(_mk_version(), [_mk_sample(0), _mk_sample(1), _mk_sample(2)])
    assert score.per_sample_scores == [0.9, 0.0, 0.9]
    assert abs(score.score - (0.9 + 0 + 0.9) / 3) < 1e-9


@pytest.mark.asyncio
async def test_evaluate_propagates_budget_exceeded(source_project, tmp_path):
    """BudgetExceededError 必须向上传播而非被 per-sample except 吞掉。"""
    from scrivai.evolution.budget import BudgetExceededError, LLMCallBudget
    from scrivai.evolution.evaluator import CandidateEvaluator

    fake_pes = MagicMock()
    fake_pes.run = AsyncMock(return_value=MagicMock(final_output={"x": 1}))

    wm = MagicMock()
    wm.create = _fake_workspace_create(tmp_path)
    wm.archive = MagicMock()

    # 给预算只够 1 个样本(3 calls),第二个样本时应抛 BudgetExceededError
    b = LLMCallBudget(limit=3)
    ev = CandidateEvaluator(
        workspace_mgr=wm,
        pes_factory=lambda pn, ws: fake_pes,
        evaluator_fn=lambda q, p, g: 0.5,
        source_project_root=source_project,
        budget=b,
    )
    with pytest.raises(BudgetExceededError):
        await ev.evaluate(_mk_version(), [_mk_sample(0), _mk_sample(1)])
