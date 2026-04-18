"""EvolutionTrigger — 从 trajectory 拉反馈并分 train/hold_out。

参考 docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.1
"""

from __future__ import annotations

import json
import random
from typing import Callable

from scrivai.models.evolution import FailureSample
from scrivai.models.trajectory import TrajectoryRecord
from scrivai.trajectory.store import TrajectoryStore

_PHASE_TRUNCATE = 800  # 每阶段响应文本截断长度


def _truncate(s: str, n: int = _PHASE_TRUNCATE) -> str:
    """截断字符串,超长时保留首尾各 n//2 字符,中间插入省略标记。"""
    if len(s) <= n:
        return s
    half = n // 2
    return s[:half] + " … " + s[-half:]


def _summarize_trajectory(tr: TrajectoryRecord | None) -> dict[str, str]:
    """将轨迹各阶段响应文本截断后聚合为 {phase_name: summary} 字典。"""
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
    """将任意值序列化为确定性 JSON 字符串。"""
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class EvolutionTrigger:
    """从 trajectory.feedback 中拉反馈,按 evaluator 打分,分 train/hold_out。

    参数:
        trajectory_store: TrajectoryStore 实例,提供 get_feedback_pairs/get_run。
        pes_name: 目标 PES 名称,用于筛选反馈记录。
        skill_name: 技能名称(当前为标识字段,供上层使用)。
        evaluator_fn: 评分函数 (question, predicted, ground_truth) -> float [0,1]。
        min_confidence: 反馈质量最低阈值,低于此值的记录被过滤。
        failure_threshold: baseline_score 低于此值视为失败样本进入 train。
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
        """判断是否积累了足够的反馈样本。

        参数:
            min_samples: 最少样本数阈值。

        返回:
            True 表示样本数达到阈值,可触发 evolution。
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
        """拉取反馈、打分并拆分 train/hold_out。

        流程:
        1. 从 TrajectoryStore 拉取满足 min_confidence 的反馈对。
        2. 尝试加载对应轨迹,提取截断版阶段摘要(get_run 失败则静默处理)。
        3. 调用 evaluator_fn 计算 baseline_score。
        4. 用固定随机种子 shuffle 后按 hold_out_ratio 切分。
        5. train 集只保留 baseline_score < failure_threshold 的失败样本。

        参数:
            hold_out_ratio: hold_out 占总样本比例 [0.0, 1.0)。
            random_seed: 随机种子,保证同参数调用结果一致。

        返回:
            (train_failures, hold_out_samples) 两个 FailureSample 列表。
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
