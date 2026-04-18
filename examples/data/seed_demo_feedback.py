"""M3a Example 03 专用 feedback seeder(4 条,extractor)。

与 tests/fixtures/m2_evolution/seed_feedback.py 不同:
- 更少样本(4 vs 30)
- 统一的 {"items": [...]} 输出 shape,配合 _overlap_score evaluator
- 专注 extractor(不 seed auditor/generator)
- 路径通过 --db 参数传入,不假设全局 DB

用法:
    python examples/data/seed_demo_feedback.py --db /tmp/scrivai-examples/evolution-demo/trajectory.db
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from scrivai.trajectory.store import TrajectoryStore


# 所有样本都用 {"items": [...]} 形状,与 _overlap_score 评分器严格匹配
_FIXTURES = [
    {
        "q": "从《220kV 巡视规程》第 3 章抽取主要检查项",
        "draft": {"items": ["油位"]},
        "final": {
            "items": [
                "主变压器油位",
                "SF6 气体压力",
                "接地电阻",
                "继电保护定值",
                "遥信状态",
            ]
        },
    },
    {
        "q": "抽取《10kV 安全规程》作业前必做项",
        "draft": {"items": ["挂牌"]},
        "final": {
            "items": [
                "验电",
                "装设接地线",
                "挂警示牌",
                "装设遮栏",
                "检查工器具合格证",
            ]
        },
    },
    {
        "q": "抽取《检修计划》模板必填字段",
        "draft": {"items": ["日期"]},
        "final": {
            "items": [
                "日期",
                "工作票编号",
                "负责人",
                "停电范围",
                "预计时长",
                "验收方式",
            ]
        },
    },
    {
        "q": "抽取《事故预案》关键动作清单",
        "draft": {"items": ["切电源"]},
        "final": {
            "items": [
                "断电",
                "报调度",
                "疏散人员",
                "启用备用电源",
                "记录时间线",
            ]
        },
    },
]


def seed(db_path: Path) -> int:
    """清 demo-extractor-* 旧行并 seed 4 条新 feedback(幂等)。

    参数:
        db_path: trajectory.db 文件路径,不存在会自动创建。

    返回:
        实际插入的 feedback 条数(正常为 4)。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = TrajectoryStore(db_path=db_path)

    # 清旧行(幂等)。feedback 有 FK → runs,先删 feedback 再删 runs。
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM feedback WHERE run_id LIKE 'demo-extractor-%'")
        conn.execute("DELETE FROM runs WHERE run_id LIKE 'demo-extractor-%'")
        conn.commit()

    count = 0
    for i, f in enumerate(_FIXTURES):
        run_id = f"demo-extractor-{i}"
        store.start_run(
            run_id=run_id,
            pes_name="extractor",
            model_name="glm-5.1",
            provider="glm",
            sdk_version="0.2.0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt=f["q"],
            runtime_context={"demo": True, "seed_index": i},
        )
        store.finalize_run(
            run_id=run_id,
            status="completed",
            final_output=f["draft"],
            workspace_archive_path=None,
            error=None,
            error_type=None,
        )
        store.record_feedback(
            run_id=run_id,
            input_summary=f["q"],
            draft_output=f["draft"],
            final_output=f["final"],
            corrections=None,
            review_policy_version="demo-v1",
            source="demo",
            confidence=0.9,
            submitted_by="example-03",
        )
        count += 1

    print(f"[OK] seeded {count} demo feedback rows → {db_path}")
    return count


def _main() -> None:
    ap = argparse.ArgumentParser(description="M3a Example 03 demo feedback seeder")
    ap.add_argument("--db", required=True, help="trajectory.db 路径")
    args = ap.parse_args()
    seed(Path(args.db))


if __name__ == "__main__":
    _main()
