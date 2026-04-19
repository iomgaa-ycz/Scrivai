"""TrajectoryStore SQLite schema (see design.md §4.5).

All DDL statements use ``CREATE TABLE IF NOT EXISTS``; the schema is created
automatically on first open and no migrations are introduced in M0-M2.
"""

from __future__ import annotations

# PRAGMAs: applied on every connection (executed inside init_schema)
PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=3000",  # 3 s — consistent with "framework retries once after 0.5 s, total budget ≤ 6.5 s"
)

DDL_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id                 TEXT PRIMARY KEY,
    pes_name               TEXT NOT NULL,
    model_name             TEXT NOT NULL,
    provider               TEXT NOT NULL,
    sdk_version            TEXT NOT NULL,
    skills_git_hash        TEXT,
    agents_git_hash        TEXT,
    skills_is_dirty        INTEGER NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL,
    task_prompt            TEXT NOT NULL,
    runtime_context        TEXT,
    workspace_archive_path TEXT,
    final_output           TEXT,
    error                  TEXT,
    error_type             TEXT,
    started_at             TEXT NOT NULL,
    ended_at               TEXT
)
"""

DDL_PHASES = """
CREATE TABLE IF NOT EXISTS phases (
    phase_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    phase_name      TEXT NOT NULL,
    phase_order     INTEGER NOT NULL,
    attempt_no      INTEGER NOT NULL DEFAULT 0,
    prompt          TEXT,
    response_text   TEXT,
    produced_files  TEXT,
    usage           TEXT,
    error           TEXT,
    error_type      TEXT,
    is_retryable    INTEGER,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    UNIQUE(run_id, phase_name, attempt_no)
)
"""

DDL_TURNS = """
CREATE TABLE IF NOT EXISTS turns (
    turn_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id      INTEGER NOT NULL REFERENCES phases(phase_id),
    turn_index    INTEGER NOT NULL,
    role          TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    data          TEXT NOT NULL,
    timestamp     TEXT NOT NULL
)
"""

DDL_TOOL_CALLS = """
CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id       INTEGER NOT NULL REFERENCES turns(turn_id),
    tool_name     TEXT NOT NULL,
    tool_input    TEXT,
    tool_output   TEXT,
    status        TEXT,
    duration_ms   INTEGER,
    timestamp     TEXT NOT NULL
)
"""

DDL_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                 TEXT NOT NULL REFERENCES runs(run_id),
    input_summary          TEXT NOT NULL,
    draft_output           TEXT NOT NULL,
    final_output           TEXT NOT NULL,
    corrections            TEXT,
    review_policy_version  TEXT,
    source                 TEXT NOT NULL DEFAULT 'human_expert',
    confidence             REAL NOT NULL DEFAULT 1.0,
    submitted_at           TEXT NOT NULL,
    submitted_by           TEXT
)
"""

INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_runs_pes_name ON runs(pes_name)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_phases_run_id ON phases(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_turns_phase_id ON turns(phase_id)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_run_id ON feedback(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_source ON feedback(source)",
)

ALL_TABLES: tuple[str, ...] = ("runs", "phases", "turns", "tool_calls", "feedback")

ALL_DDL: tuple[str, ...] = (DDL_RUNS, DDL_PHASES, DDL_TURNS, DDL_TOOL_CALLS, DDL_FEEDBACK)
