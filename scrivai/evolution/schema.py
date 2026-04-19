"""evolution.db SQL schema (3 tables).

See docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §4.2
"""

from __future__ import annotations

SCHEMA_SKILL_VERSIONS = """
CREATE TABLE IF NOT EXISTS skill_versions (
    version_id              TEXT PRIMARY KEY,
    pes_name                TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    parent_version_id       TEXT,
    content_snapshot_json   TEXT NOT NULL,
    content_diff            TEXT NOT NULL,
    change_summary          TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK(status IN
                            ('draft','evaluated','promoted','rejected')),
    created_at              TEXT NOT NULL,
    promoted_at             TEXT,
    created_by              TEXT NOT NULL,
    FOREIGN KEY(parent_version_id) REFERENCES skill_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_versions_pes_skill
    ON skill_versions(pes_name, skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_versions_parent
    ON skill_versions(parent_version_id);
"""

SCHEMA_EVOLUTION_RUNS = """
CREATE TABLE IF NOT EXISTS evolution_runs (
    evo_run_id              TEXT PRIMARY KEY,
    pes_name                TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    config_snapshot_json    TEXT NOT NULL,
    started_at              TEXT NOT NULL,
    completed_at            TEXT,
    status                  TEXT NOT NULL CHECK(status IN
                            ('running','completed','failed','budget_exceeded')),
    baseline_version_id     TEXT NOT NULL,
    baseline_score          REAL NOT NULL,
    best_version_id         TEXT,
    best_score              REAL,
    llm_calls_used          INTEGER NOT NULL DEFAULT 0,
    candidate_version_ids_json TEXT NOT NULL,
    iterations_history_json TEXT NOT NULL,
    error                   TEXT,
    FOREIGN KEY(baseline_version_id) REFERENCES skill_versions(version_id),
    FOREIGN KEY(best_version_id) REFERENCES skill_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_pes_skill
    ON evolution_runs(pes_name, skill_name);
"""

SCHEMA_EVOLUTION_SCORES = """
CREATE TABLE IF NOT EXISTS evolution_scores (
    score_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id              TEXT NOT NULL,
    evo_run_id              TEXT NOT NULL,
    score                   REAL NOT NULL,
    per_sample_scores_json  TEXT NOT NULL,
    hold_out_size           INTEGER NOT NULL,
    llm_calls_consumed      INTEGER NOT NULL,
    evaluated_at            TEXT NOT NULL,
    FOREIGN KEY(version_id) REFERENCES skill_versions(version_id),
    FOREIGN KEY(evo_run_id) REFERENCES evolution_runs(evo_run_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_scores_version
    ON evolution_scores(version_id);
"""

ALL_SCHEMAS = [SCHEMA_SKILL_VERSIONS, SCHEMA_EVOLUTION_RUNS, SCHEMA_EVOLUTION_SCORES]
