"""CandidateEvaluator — 用候选 SKILL.md 重跑真实 PES,打分。

参考 docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.3 / §6.1
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
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _prepare_temp_project_root(
    source: Path,
    skill_name: str,
    candidate_snapshot: dict[str, str],
    prefix: str = "scrivai-eval-",
) -> Path:
    """复制 source 到临时目录,在 skills/<skill_name>/ 内放候选内容。

    参数:
        source: 源项目根目录。
        skill_name: 目标 skill 目录名。
        candidate_snapshot: 候选文件映射 {相对路径: 内容}。
        prefix: tempfile.mkdtemp 前缀,默认含 version_id 以便追踪孤立临时目录。

    返回:
        临时 project_root 路径(调用方负责清理)。
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
    """对候选 SkillVersion 在 hold-out 样本上 replay 真实 PES 并打分。

    工作流:
    1. 将源 project_root copytree 到临时目录,替换目标 skill 内容。
    2. 对每个 hold-out 样本:创建 workspace → 实例化 PES → run → 打分。
    3. 每个样本消耗 3 个 LLM budget 单位。
    4. 单样本失败时 score=0.0,不影响其他样本。
    5. finally 块清理临时目录。
    """

    def __init__(
        self,
        workspace_mgr: Any,
        pes_factory: Callable[[str, WorkspaceHandle], Any],
        evaluator_fn: Callable[[str, str, str], float],
        source_project_root: Path,
        budget: LLMCallBudget,
    ) -> None:
        """初始化 CandidateEvaluator。

        参数:
            workspace_mgr: WorkspaceManager 实例。
            pes_factory: (pes_name, workspace) -> PES 实例工厂函数。
            evaluator_fn: (question, predicted, ground_truth) -> float 评分函数。
            source_project_root: 源项目根目录路径。
            budget: LLM 调用预算守卫。
        """
        self.workspace_mgr = workspace_mgr
        self.pes_factory = pes_factory
        self.evaluator_fn = evaluator_fn
        self.source_project_root = source_project_root
        self.budget = budget

    async def evaluate(
        self, version: SkillVersion, hold_out: list[FailureSample]
    ) -> EvolutionScore:
        """在 hold-out 样本上评估候选 SkillVersion。

        参数:
            version: 待评估的候选版本。
            hold_out: hold-out 样本列表。

        返回:
            EvolutionScore:含总分、每样本分、预算消耗等信息。
        """
        # 将 version_id 中的冒号替换为连字符,避免路径非法;提前提取供 prefix 和 run_id 共用
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
                    # 预算耗尽 — 让 runner 捕获并提前终止,不吞掉
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
