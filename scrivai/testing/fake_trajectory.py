"""FakeTrajectoryStore — 测试用的 :memory: SQLite TrajectoryStore。

行为与 prod TrajectoryStore 完全一致(继承同一份 schema 与 record_* 实现),
只是 db 是进程内独立的 :memory: SQLite。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.4。
"""

from __future__ import annotations

from scrivai.trajectory.store import TrajectoryStore


class FakeTrajectoryStore(TrajectoryStore):
    """跑真 schema 的 :memory: SQLite。

    用法:
        store = FakeTrajectoryStore()
        store.start_run(...)
    """

    def __init__(self) -> None:
        super().__init__(db_path=":memory:")
