"""TrajectoryStore - SQLite 单文件 trajectory 存储(同步接口)。

参考:
- docs/design.md §4.5(schema、PRAGMAs、并发模型、时间预算)
- docs/TD.md T0.7
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.3

接口设计要点:
- 全同步:record_* / get_* / list_* 都是普通 def。
- 文件模式:每次操作新 conn(WAL 保证并发);:memory: 模式:单 conn 持久。
- 框架级 1 次 busy 重试(0.5s 间隔);超 → TrajectoryWriteError。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from loguru import logger

from scrivai.exceptions import TrajectoryWriteError
from scrivai.models.trajectory import FeedbackRecord, PhaseRecord, TrajectoryRecord
from scrivai.trajectory.schema import ALL_DDL, INDEXES, PRAGMAS

DEFAULT_DB_FALLBACK = "~/.scrivai/trajectories.sqlite"

T = TypeVar("T")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: object | None) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _json_loads(value: str | None) -> object | None:
    return json.loads(value) if value is not None else None


class TrajectoryStore:
    """SQLite 单文件 trajectory 存储。所有 record_* / get_* / list_* 都是同步。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        """初始化:解析 db_path,打开/建库,执行一次 schema 初始化。

        Args:
            db_path: SQLite 路径。可选三态:
                - ":memory:":内存库,单 conn 持久化(测试用)。
                - None:读 env SCRIVAI_TRAJECTORY_DB,缺省走 ~/.scrivai/trajectories.sqlite。
                - Path | str:显式路径。
        """
        self.db_path: Path | str
        self._memory_conn: sqlite3.Connection | None = None
        # 跨线程串行锁:仅保护 :memory: 共享 conn(防 to_thread 多 worker 在
        # execute→commit 边界相互踩踏);文件模式每次 record 新建 conn,
        # 由 SQLite WAL 处理并发,无需 Python 层加锁。
        self._write_lock = threading.Lock()

        if db_path == ":memory:":
            self.db_path = ":memory:"
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            if db_path is None:
                # 实时读 env(允许测试 monkeypatch.setenv 后构造新实例即生效)
                db_path = os.environ.get("SCRIVAI_TRAJECTORY_DB", DEFAULT_DB_FALLBACK)
            self.db_path = Path(db_path).expanduser()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_schema()

    # ── 内部:连接与 schema ────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """:memory: 返回单例 conn;文件模式新 conn(每次 record 跑完即关)。"""
        if self._memory_conn is not None:
            return self._memory_conn
        assert isinstance(self.db_path, Path)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=True)
        for pragma in PRAGMAS:
            conn.execute(pragma)
        return conn

    def _init_schema(self) -> None:
        """同步;__init__ 调一次。CREATE TABLE IF NOT EXISTS + 索引 + PRAGMAs。"""
        conn = self._get_connection()
        try:
            for pragma in PRAGMAS:
                conn.execute(pragma)
            for ddl in ALL_DDL:
                conn.execute(ddl)
            for idx in INDEXES:
                conn.execute(idx)
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    def _execute_with_retry(self, work: Callable[[sqlite3.Connection], T]) -> T:
        """跑 work(conn) 一次;遇 SQLITE_BUSY 重试 1 次(间隔 0.5s);仍失败抛 TrajectoryWriteError。

        work 是接受 conn 的 callable,可以执行任意操作(execute / fetchall / lastrowid);
        :memory: 模式共享单 conn,文件模式每次新 conn。
        """
        # 仅 :memory: 模式锁保护;文件模式靠 WAL,跳锁以保 BasePES 多 run 并发吞吐
        lock_ctx: AbstractContextManager[Any] = (
            self._write_lock if self._memory_conn is not None else nullcontext()
        )
        with lock_ctx:
            for attempt in (1, 2):
                conn = self._get_connection()
                try:
                    result = work(conn)
                    conn.commit()
                    return result
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if attempt == 1 and ("busy" in msg or "locked" in msg):
                        logger.warning("TrajectoryStore busy retry [attempt={}]: {}", attempt, e)
                        # 关掉非 :memory: 的临时 conn 后重试
                        if self._memory_conn is None:
                            conn.close()
                        time.sleep(0.5)
                        continue
                    raise TrajectoryWriteError(f"SQLite busy/locked after retries: {e}") from e
                finally:
                    if self._memory_conn is None:
                        conn.close()
            raise TrajectoryWriteError("unreachable")

    # ── runs 表 API ───────────────────────────────────────

    def start_run(
        self,
        run_id: str,
        pes_name: str,
        model_name: str,
        provider: str,
        sdk_version: str,
        skills_git_hash: str | None,
        agents_git_hash: str | None,
        skills_is_dirty: bool,
        task_prompt: str,
        runtime_context: dict[str, Any] | None,
    ) -> None:
        """写入 runs 表新行,status='running',started_at=now。"""
        sql = """
            INSERT INTO runs (run_id, pes_name, model_name, provider, sdk_version,
                              skills_git_hash, agents_git_hash, skills_is_dirty,
                              status, task_prompt, runtime_context, started_at)
            VALUES (?,?,?,?,?,?,?,?,'running',?,?,?)
        """
        params = (
            run_id,
            pes_name,
            model_name,
            provider,
            sdk_version,
            skills_git_hash,
            agents_git_hash,
            int(skills_is_dirty),
            task_prompt,
            _json_dumps(runtime_context),
            _utcnow_iso(),
        )

        def _work(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self._execute_with_retry(_work)

    def finalize_run(
        self,
        run_id: str,
        status: str,
        final_output: dict[str, Any] | None,
        workspace_archive_path: str | None,
        error: str | None,
        error_type: str | None,
    ) -> None:
        """更新 runs 表:status / ended_at / final_output / archive / error。"""
        sql = """
            UPDATE runs
            SET status=?, final_output=?, workspace_archive_path=?,
                error=?, error_type=?, ended_at=?
            WHERE run_id=?
        """
        params = (
            status,
            _json_dumps(final_output),
            workspace_archive_path,
            error,
            error_type,
            _utcnow_iso(),
            run_id,
        )

        def _work(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self._execute_with_retry(_work)

    def get_run(self, run_id: str) -> TrajectoryRecord | None:
        """读 runs 行 + 联查 phases(按 phase_order, attempt_no 升序)。"""

        def _work(
            conn: sqlite3.Connection,
        ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
            prev_factory = conn.row_factory
            conn.row_factory = sqlite3.Row
            try:
                run_row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if run_row is None:
                    return None, []
                phase_rows = conn.execute(
                    "SELECT * FROM phases WHERE run_id=? ORDER BY phase_order, attempt_no",
                    (run_id,),
                ).fetchall()
                return dict(run_row), [dict(r) for r in phase_rows]
            finally:
                conn.row_factory = prev_factory

        run_row, phase_rows = self._execute_with_retry(_work)
        if run_row is None:
            return None
        rec = self._row_to_trajectory_record(run_row)
        rec = rec.model_copy(
            update={"phase_records": [self._row_to_phase_record(r) for r in phase_rows]}
        )
        return rec

    def list_runs(
        self,
        pes_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TrajectoryRecord]:
        """按 pes_name / status 过滤,返回最新 limit 条(按 started_at 降序)。"""
        clauses: list[str] = []
        params: list[Any] = []
        if pes_name is not None:
            clauses.append("pes_name=?")
            params.append(pes_name)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM runs {where} ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            prev_factory = conn.row_factory
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, tuple(params)).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.row_factory = prev_factory

        rows = self._execute_with_retry(_work)
        return [self._row_to_trajectory_record(r) for r in rows]

    # ── phases 表 API ─────────────────────────────────────

    def record_phase_start(
        self,
        run_id: str,
        phase_name: str,
        phase_order: int,
        attempt_no: int,
    ) -> int:
        """插入 phases 行(started_at=now),返回新 phase_id;UNIQUE 冲突直接抛 IntegrityError。"""
        sql = """
            INSERT INTO phases (run_id, phase_name, phase_order, attempt_no, started_at)
            VALUES (?,?,?,?,?)
        """
        params = (run_id, phase_name, phase_order, attempt_no, _utcnow_iso())

        def _work(conn: sqlite3.Connection) -> int:
            cur = conn.execute(sql, params)
            assert cur.lastrowid is not None, "INSERT 必须设置 lastrowid"
            return cur.lastrowid

        return self._execute_with_retry(_work)

    def record_phase_end(
        self,
        phase_id: int,
        prompt: str | None,
        response_text: str | None,
        produced_files: list[str] | None,
        usage: dict[str, Any] | None,
        error: str | None,
        error_type: str | None,
        is_retryable: bool | None,
    ) -> None:
        """更新 phases 行:prompt / response_text / produced_files / usage / error / ended_at。"""
        sql = """
            UPDATE phases
            SET prompt=?, response_text=?, produced_files=?, usage=?,
                error=?, error_type=?, is_retryable=?, ended_at=?
            WHERE phase_id=?
        """
        params = (
            prompt,
            response_text,
            _json_dumps(produced_files),
            _json_dumps(usage),
            error,
            error_type,
            None if is_retryable is None else int(is_retryable),
            _utcnow_iso(),
            phase_id,
        )

        def _work(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self._execute_with_retry(_work)

    # ── turns / tool_calls 表 API ────────────────────────

    def record_turn(
        self,
        phase_id: int,
        turn_index: int,
        role: str,
        content_type: str,
        data: dict[str, Any],
    ) -> int:
        """插入 turns 行,返回新 turn_id。"""
        sql = """
            INSERT INTO turns (phase_id, turn_index, role, content_type, data, timestamp)
            VALUES (?,?,?,?,?,?)
        """
        params = (phase_id, turn_index, role, content_type, _json_dumps(data), _utcnow_iso())

        def _work(conn: sqlite3.Connection) -> int:
            cur = conn.execute(sql, params)
            assert cur.lastrowid is not None, "INSERT 必须设置 lastrowid"
            return cur.lastrowid

        return self._execute_with_retry(_work)

    def record_tool_call(
        self,
        turn_id: int,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        tool_output: str | None,
        status: str | None,
        duration_ms: int | None,
    ) -> None:
        """插入 tool_calls 行。"""
        sql = """
            INSERT INTO tool_calls (turn_id, tool_name, tool_input, tool_output,
                                    status, duration_ms, timestamp)
            VALUES (?,?,?,?,?,?,?)
        """
        params = (
            turn_id,
            tool_name,
            _json_dumps(tool_input),
            tool_output,
            status,
            duration_ms,
            _utcnow_iso(),
        )

        def _work(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self._execute_with_retry(_work)

    # ── feedback 表 API ──────────────────────────────────

    def record_feedback(
        self,
        run_id: str,
        input_summary: str,
        draft_output: dict[str, Any],
        final_output: dict[str, Any],
        corrections: list[dict[str, Any]] | None,
        review_policy_version: str | None,
        source: str = "human_expert",
        confidence: float = 1.0,
        submitted_by: str | None = None,
    ) -> None:
        """插入 feedback 行。draft / final 都必填(NOT NULL)。"""
        sql = """
            INSERT INTO feedback (run_id, input_summary, draft_output, final_output,
                                  corrections, review_policy_version, source, confidence,
                                  submitted_at, submitted_by)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """
        params = (
            run_id,
            input_summary,
            _json_dumps(draft_output),
            _json_dumps(final_output),
            _json_dumps(corrections),
            review_policy_version,
            source,
            confidence,
            _utcnow_iso(),
            submitted_by,
        )

        def _work(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self._execute_with_retry(_work)

    def get_feedback_pairs(
        self,
        pes_name: str | None = None,
        min_confidence: float | None = None,
        limit: int | None = None,
    ) -> list[FeedbackRecord]:
        """按 pes_name(联查 runs)+ min_confidence 过滤,按 submitted_at 升序。"""
        clauses: list[str] = []
        params: list[Any] = []
        join = ""
        if pes_name is not None:
            join = "JOIN runs ON runs.run_id = feedback.run_id"
            clauses.append("runs.pes_name=?")
            params.append(pes_name)
        if min_confidence is not None:
            clauses.append("feedback.confidence >= ?")
            params.append(min_confidence)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
        sql = (
            f"SELECT feedback.* FROM feedback {join} {where} "
            f"ORDER BY feedback.submitted_at ASC {limit_sql}"
        )

        def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            prev_factory = conn.row_factory
            conn.row_factory = sqlite3.Row
            try:
                return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
            finally:
                conn.row_factory = prev_factory

        rows = self._execute_with_retry(_work)
        return [self._row_to_feedback_record(r) for r in rows]

    def _row_to_feedback_record(self, row: dict[str, Any]) -> FeedbackRecord:
        """SQLite row → FeedbackRecord pydantic。"""
        return FeedbackRecord(
            feedback_id=row["feedback_id"],
            run_id=row["run_id"],
            input_summary=row["input_summary"],
            draft_output=_json_loads(row["draft_output"]),
            final_output=_json_loads(row["final_output"]),
            corrections=_json_loads(row.get("corrections")),
            review_policy_version=row.get("review_policy_version"),
            source=row["source"],
            confidence=row["confidence"],
            submitted_at=row["submitted_at"],
            submitted_by=row.get("submitted_by"),
        )

    # ── pydantic 转换 ────────────────────────────────────

    def _row_to_trajectory_record(self, row: dict[str, Any]) -> TrajectoryRecord:
        """SQLite row → TrajectoryRecord pydantic。"""
        return TrajectoryRecord(
            run_id=row["run_id"],
            pes_name=row["pes_name"],
            model_name=row["model_name"],
            provider=row["provider"],
            sdk_version=row["sdk_version"],
            skills_git_hash=row.get("skills_git_hash"),
            agents_git_hash=row.get("agents_git_hash"),
            skills_is_dirty=bool(row["skills_is_dirty"]),
            status=row["status"],
            task_prompt=row["task_prompt"],
            runtime_context=_json_loads(row.get("runtime_context")),
            workspace_archive_path=row.get("workspace_archive_path"),
            final_output=_json_loads(row.get("final_output")),
            error=row.get("error"),
            error_type=row.get("error_type"),
            started_at=row["started_at"],
            ended_at=row.get("ended_at"),
            phase_records=[],
        )

    def _row_to_phase_record(self, row: dict[str, Any]) -> PhaseRecord:
        """SQLite row → PhaseRecord pydantic。"""
        produced = _json_loads(row.get("produced_files")) or []
        usage = _json_loads(row.get("usage")) or {}
        is_ret = row.get("is_retryable")
        return PhaseRecord(
            phase_id=row["phase_id"],
            run_id=row["run_id"],
            phase_name=row["phase_name"],
            attempt_no=row["attempt_no"],
            phase_order=row["phase_order"],
            prompt=row.get("prompt"),
            response_text=row.get("response_text"),
            produced_files=produced,
            usage=usage,
            error=row.get("error"),
            error_type=row.get("error_type"),
            is_retryable=None if is_ret is None else bool(is_ret),
            started_at=row["started_at"],
            ended_at=row.get("ended_at"),
        )
