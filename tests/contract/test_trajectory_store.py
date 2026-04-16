"""M0.25 T0.7 contract tests for TrajectoryStore.

References:
- docs/design.md §4.5
- docs/TD.md T0.7
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.3
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scrivai import TrajectoryStore
from scrivai.trajectory.schema import ALL_TABLES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_schema_init_creates_five_tables() -> None:
    """首次 TrajectoryStore(":memory:") 后,sqlite_master 必须含 5 张表。"""
    store = TrajectoryStore(db_path=":memory:")
    conn = store._memory_conn
    assert conn is not None
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    for t in ALL_TABLES:
        assert t in names, f"missing table: {t}"


def test_default_path_uses_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """env SCRIVAI_TRAJECTORY_DB 设定后,TrajectoryStore() 不传参时使用该路径。"""
    db_path = tmp_path / "custom.db"
    monkeypatch.setenv("SCRIVAI_TRAJECTORY_DB", str(db_path))

    store = TrajectoryStore()
    assert store.db_path == db_path
    assert db_path.is_file()


def test_run_lifecycle_runs_table_only() -> None:
    """start_run → finalize_run → get_run → list_runs 路径完整(暂不涉及 phases)。"""
    store = TrajectoryStore(":memory:")

    asyncio.run(
        store.start_run(
            run_id="r1",
            pes_name="extractor",
            model_name="glm-5.1",
            provider="glm",
            sdk_version="0.1.0",
            skills_git_hash="abc",
            agents_git_hash="abc",
            skills_is_dirty=False,
            task_prompt="hello",
            runtime_context={"k": "v"},
        )
    )

    asyncio.run(
        store.finalize_run(
            run_id="r1",
            status="completed",
            final_output={"answer": 42},
            workspace_archive_path="/tmp/r1.tar.gz",
            error=None,
            error_type=None,
        )
    )

    rec = asyncio.run(store.get_run("r1"))
    assert rec is not None
    assert rec.run_id == "r1"
    assert rec.status == "completed"
    assert rec.final_output == {"answer": 42}
    assert rec.workspace_archive_path == "/tmp/r1.tar.gz"
    assert rec.runtime_context == {"k": "v"}
    assert rec.ended_at is not None

    runs = asyncio.run(store.list_runs(pes_name="extractor"))
    assert len(runs) == 1
    assert runs[0].run_id == "r1"


def test_phases_unique_constraint() -> None:
    """同 (run_id, phase_name, attempt_no) 重复 record_phase_start → IntegrityError。"""
    store = TrajectoryStore(":memory:")
    asyncio.run(
        store.start_run(
            run_id="r-uniq",
            pes_name="x",
            model_name="m",
            provider="p",
            sdk_version="0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )

    pid = asyncio.run(store.record_phase_start("r-uniq", "plan", phase_order=0, attempt_no=0))
    assert pid > 0

    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(store.record_phase_start("r-uniq", "plan", phase_order=0, attempt_no=0))

    # 不同 attempt_no 不冲突
    pid2 = asyncio.run(store.record_phase_start("r-uniq", "plan", phase_order=0, attempt_no=1))
    assert pid2 != pid


def test_full_run_lifecycle_with_attempt_no() -> None:
    """start_run → 3 phase × 2 attempt → 多 turn + tool_call → finalize_run;表行数对齐。"""
    store = TrajectoryStore(":memory:")
    asyncio.run(
        store.start_run(
            run_id="r-life",
            pes_name="extractor",
            model_name="glm-5.1",
            provider="glm",
            sdk_version="0.1.0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )

    for phase_order, phase_name in enumerate(("plan", "execute", "summarize")):
        for attempt_no in (0, 1):
            pid = asyncio.run(
                store.record_phase_start(
                    "r-life", phase_name, phase_order=phase_order, attempt_no=attempt_no
                )
            )
            tid = asyncio.run(
                store.record_turn(
                    phase_id=pid,
                    turn_index=0,
                    role="assistant",
                    content_type="text",
                    data={"text": f"{phase_name}-{attempt_no}"},
                )
            )
            asyncio.run(
                store.record_tool_call(
                    turn_id=tid,
                    tool_name="Bash",
                    tool_input={"command": "ls"},
                    tool_output="file1\n",
                    status="success",
                    duration_ms=10,
                )
            )
            asyncio.run(
                store.record_phase_end(
                    phase_id=pid,
                    prompt="p",
                    response_text="r",
                    produced_files=["x.json"],
                    usage={"input_tokens": 1},
                    error=None,
                    error_type=None,
                    is_retryable=None,
                )
            )

    asyncio.run(
        store.finalize_run(
            run_id="r-life",
            status="completed",
            final_output={"ok": True},
            workspace_archive_path=None,
            error=None,
            error_type=None,
        )
    )

    rec = asyncio.run(store.get_run("r-life"))
    assert rec is not None
    assert rec.status == "completed"
    assert len(rec.phase_records) == 6  # 3 phases × 2 attempts

    conn = store._memory_conn
    assert conn is not None
    assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 6


def test_feedback_pair_query_filters_confidence() -> None:
    """confidence={0.5, 0.7, 1.0} → get_feedback_pairs(min_confidence=0.7) 返回 2 条。"""
    store = TrajectoryStore(":memory:")
    asyncio.run(
        store.start_run(
            run_id="r-fb",
            pes_name="extractor",
            model_name="m",
            provider="p",
            sdk_version="0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )

    for conf in (0.5, 0.7, 1.0):
        asyncio.run(
            store.record_feedback(
                run_id="r-fb",
                input_summary=f"summary-{conf}",
                draft_output={"v": conf},
                final_output={"v": conf + 0.1},
                corrections=None,
                review_policy_version="v1",
                source="human_expert",
                confidence=conf,
                submitted_by="alice",
            )
        )

    all_pairs = asyncio.run(store.get_feedback_pairs(pes_name="extractor"))
    assert len(all_pairs) == 3

    high_pairs = asyncio.run(store.get_feedback_pairs(pes_name="extractor", min_confidence=0.7))
    assert len(high_pairs) == 2
    assert {p.confidence for p in high_pairs} == {0.7, 1.0}


def test_concurrent_write_safety_two_threads() -> None:
    """2 协程并发 record_turn 共 100 次 → 100 行落表,无丢失。

    :memory: 模式下 SQLite C 层对单 conn 自带串行;to_thread 多 worker 按队列排队。
    """
    store = TrajectoryStore(":memory:")
    asyncio.run(
        store.start_run(
            run_id="r-conc",
            pes_name="x",
            model_name="m",
            provider="p",
            sdk_version="0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )
    pid = asyncio.run(store.record_phase_start("r-conc", "plan", phase_order=0, attempt_no=0))

    async def _writer(start: int, count: int) -> None:
        for i in range(count):
            await store.record_turn(
                phase_id=pid,
                turn_index=start + i,
                role="assistant",
                content_type="text",
                data={"i": start + i},
            )

    async def _runner() -> None:
        await asyncio.gather(_writer(0, 50), _writer(50, 50))

    asyncio.run(_runner())

    conn = store._memory_conn
    assert conn is not None
    n = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    assert n == 100


class _FlakyConnWrapper:
    """包装 sqlite3.Connection;execute 调用按 hook 决定是否抛 SQLITE_BUSY。"""

    def __init__(self, real: sqlite3.Connection, hook: object) -> None:
        self._real = real
        self._hook = hook  # callable(sql) -> None | raises

    def execute(self, sql: str, parameters: object = ()) -> sqlite3.Cursor:  # noqa: D401
        # 调 hook;hook 决定抛错或放行
        self._hook(sql)  # type: ignore[operator]
        return self._real.execute(sql, parameters)

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()

    @property
    def row_factory(self) -> object:
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, value: object) -> None:
        self._real.row_factory = value  # type: ignore[assignment]

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def test_busy_retry_on_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_connection 返回的 conn,第 1 次 INSERT INTO runs 抛 busy,第 2 次成功 → 整体成功。"""
    store = TrajectoryStore(":memory:")
    real_conn = store._memory_conn
    assert real_conn is not None

    call_count = {"n": 0}

    def hook(sql: str) -> None:
        if "INSERT INTO runs" in sql and call_count["n"] == 0:
            call_count["n"] += 1
            raise sqlite3.OperationalError("database is locked")

    wrapper = _FlakyConnWrapper(real_conn, hook)
    monkeypatch.setattr(store, "_get_connection", lambda: wrapper)

    asyncio.run(
        store.start_run(
            run_id="r-busy",
            pes_name="x",
            model_name="m",
            provider="p",
            sdk_version="0",
            skills_git_hash=None,
            agents_git_hash=None,
            skills_is_dirty=False,
            task_prompt="t",
            runtime_context=None,
        )
    )

    rec = asyncio.run(store.get_run("r-busy"))
    assert rec is not None
    assert call_count["n"] == 1  # 重试用过 1 次


def test_busy_exhausts_raises_trajectory_write_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_connection 返回的 conn,INSERT INTO runs 持续抛 busy → 抛 TrajectoryWriteError。"""
    from scrivai.exceptions import TrajectoryWriteError

    store = TrajectoryStore(":memory:")
    real_conn = store._memory_conn
    assert real_conn is not None

    def hook(sql: str) -> None:
        if "INSERT INTO runs" in sql:
            raise sqlite3.OperationalError("database is locked")

    wrapper = _FlakyConnWrapper(real_conn, hook)
    monkeypatch.setattr(store, "_get_connection", lambda: wrapper)

    with pytest.raises(TrajectoryWriteError, match="busy/locked"):
        asyncio.run(
            store.start_run(
                run_id="r-bx",
                pes_name="x",
                model_name="m",
                provider="p",
                sdk_version="0",
                skills_git_hash=None,
                agents_git_hash=None,
                skills_is_dirty=False,
                task_prompt="t",
                runtime_context=None,
            )
        )
