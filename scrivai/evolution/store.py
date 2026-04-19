"""SkillVersionStore — CRUD operations for evolution.db.

See docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §4.2 / §5.7
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scrivai.evolution.schema import ALL_SCHEMAS
from scrivai.models.evolution import (
    EvolutionRunRecord,
    EvolutionScore,
    SkillVersion,
    SkillVersionStatus,
)

_SKIP_DIR_NAMES = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


class SkillVersionStore:
    """Encapsulates the skill_versions / evolution_runs / evolution_scores tables in evolution.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path("~/.scrivai/evolution.db").expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        for sql in ALL_SCHEMAS:
            self._conn.executescript(sql)
        self._conn.commit()

    # ── skill_versions ──────────────────────────────────────────────

    def save_version(self, version: SkillVersion) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO skill_versions
               (version_id, pes_name, skill_name, parent_version_id,
                content_snapshot_json, content_diff, change_summary, status,
                created_at, promoted_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version.version_id,
                version.pes_name,
                version.skill_name,
                version.parent_version_id,
                json.dumps(version.content_snapshot, ensure_ascii=False),
                version.content_diff,
                version.change_summary,
                version.status,
                _dt_to_str(version.created_at),
                _dt_to_str(version.promoted_at),
                version.created_by,
            ),
        )
        self._conn.commit()

    def get_version(self, version_id: str) -> SkillVersion:
        row = self._conn.execute(
            "SELECT * FROM skill_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"version not found: {version_id}")
        return self._row_to_version(row)

    def list_versions(
        self, pes_name: str, skill_name: str, status: Optional[SkillVersionStatus] = None
    ) -> list[SkillVersion]:
        q = "SELECT * FROM skill_versions WHERE pes_name=? AND skill_name=?"
        args: list[Any] = [pes_name, skill_name]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY created_at ASC"
        return [self._row_to_version(r) for r in self._conn.execute(q, args)]

    def update_version_status(self, version_id: str, status: SkillVersionStatus) -> None:
        self._conn.execute(
            "UPDATE skill_versions SET status=? WHERE version_id=?",
            (status, version_id),
        )
        self._conn.commit()

    def mark_promoted(self, version_id: str) -> None:
        self._conn.execute(
            "UPDATE skill_versions SET status='promoted', promoted_at=? WHERE version_id=?",
            (_dt_to_str(_utcnow()), version_id),
        )
        self._conn.commit()

    def get_baseline(
        self, pes_name: str, skill_name: str, source_project_root: Path
    ) -> SkillVersion:
        existing = self.list_versions(pes_name, skill_name, status="promoted")
        if existing:
            return existing[-1]
        roots = [v for v in self.list_versions(pes_name, skill_name) if v.parent_version_id is None]
        if roots:
            return roots[0]
        skill_dir = source_project_root / "skills" / skill_name
        if not skill_dir.exists():
            raise FileNotFoundError(f"skills/{skill_name} not found in {source_project_root}")
        snapshot: dict[str, str] = {}
        for p in sorted(skill_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            if any(part in _SKIP_DIR_NAMES for part in p.relative_to(skill_dir).parts):
                continue
            rel = p.relative_to(skill_dir)
            snapshot[str(rel)] = p.read_text(encoding="utf-8")
        h = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:8]
        vid = f"{pes_name}:{skill_name}:baseline:{h}"
        bl = SkillVersion(
            version_id=vid,
            pes_name=pes_name,
            skill_name=skill_name,
            parent_version_id=None,
            content_snapshot=snapshot,
            content_diff="",
            change_summary="baseline from skills/ on disk",
            status="draft",
            created_at=_utcnow(),
            created_by="human",
        )
        self.save_version(bl)
        return bl

    # ── evolution_runs ──────────────────────────────────────────────

    def create_run(self, record: EvolutionRunRecord) -> None:
        self._conn.execute(
            """INSERT INTO evolution_runs
               (evo_run_id, pes_name, skill_name, config_snapshot_json,
                started_at, completed_at, status, baseline_version_id,
                baseline_score, best_version_id, best_score, llm_calls_used,
                candidate_version_ids_json, iterations_history_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.evo_run_id,
                record.pes_name,
                record.skill_name,
                json.dumps(record.config_snapshot, ensure_ascii=False),
                _dt_to_str(record.started_at),
                _dt_to_str(record.completed_at),
                record.status,
                record.baseline_version_id,
                record.baseline_score,
                record.best_version_id,
                record.best_score,
                record.llm_calls_used,
                json.dumps(record.candidate_version_ids, ensure_ascii=False),
                json.dumps(record.iterations_history, ensure_ascii=False),
                record.error,
            ),
        )
        self._conn.commit()

    def finalize_run(self, record: EvolutionRunRecord) -> None:
        self._conn.execute(
            """UPDATE evolution_runs SET
                 completed_at=?, status=?, best_version_id=?, best_score=?,
                 llm_calls_used=?, candidate_version_ids_json=?,
                 iterations_history_json=?, error=?
               WHERE evo_run_id=?""",
            (
                _dt_to_str(record.completed_at),
                record.status,
                record.best_version_id,
                record.best_score,
                record.llm_calls_used,
                json.dumps(record.candidate_version_ids, ensure_ascii=False),
                json.dumps(record.iterations_history, ensure_ascii=False),
                record.error,
                record.evo_run_id,
            ),
        )
        self._conn.commit()

    def get_run(self, evo_run_id: str) -> EvolutionRunRecord:
        row = self._conn.execute(
            "SELECT * FROM evolution_runs WHERE evo_run_id=?", (evo_run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"evolution_run not found: {evo_run_id}")
        return self._row_to_run(row)

    # ── evolution_scores ────────────────────────────────────────────

    def record_score(self, score: EvolutionScore, evo_run_id: str) -> None:
        self._conn.execute(
            """INSERT INTO evolution_scores
               (version_id, evo_run_id, score, per_sample_scores_json,
                hold_out_size, llm_calls_consumed, evaluated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                score.version_id,
                evo_run_id,
                score.score,
                json.dumps(score.per_sample_scores),
                score.hold_out_size,
                score.llm_calls_consumed,
                _dt_to_str(score.evaluated_at),
            ),
        )
        self._conn.commit()

    def get_scores_for_version(self, version_id: str) -> list[EvolutionScore]:
        rows = self._conn.execute(
            "SELECT * FROM evolution_scores WHERE version_id=? ORDER BY evaluated_at DESC",
            (version_id,),
        ).fetchall()
        return [self._row_to_score(r) for r in rows]

    # ── row mappers ─────────────────────────────────────────────────

    def _row_to_version(self, row: tuple) -> SkillVersion:
        cols = [
            "version_id",
            "pes_name",
            "skill_name",
            "parent_version_id",
            "content_snapshot_json",
            "content_diff",
            "change_summary",
            "status",
            "created_at",
            "promoted_at",
            "created_by",
        ]
        d = dict(zip(cols, row))
        return SkillVersion(
            version_id=d["version_id"],
            pes_name=d["pes_name"],
            skill_name=d["skill_name"],
            parent_version_id=d["parent_version_id"],
            content_snapshot=json.loads(d["content_snapshot_json"]),
            content_diff=d["content_diff"],
            change_summary=d["change_summary"],
            status=d["status"],
            created_at=_str_to_dt(d["created_at"]),
            promoted_at=_str_to_dt(d["promoted_at"]),
            created_by=d["created_by"],
        )

    def _row_to_run(self, row: tuple) -> EvolutionRunRecord:
        cols = [
            "evo_run_id",
            "pes_name",
            "skill_name",
            "config_snapshot_json",
            "started_at",
            "completed_at",
            "status",
            "baseline_version_id",
            "baseline_score",
            "best_version_id",
            "best_score",
            "llm_calls_used",
            "candidate_version_ids_json",
            "iterations_history_json",
            "error",
        ]
        d = dict(zip(cols, row))
        return EvolutionRunRecord(
            evo_run_id=d["evo_run_id"],
            pes_name=d["pes_name"],
            skill_name=d["skill_name"],
            config_snapshot=json.loads(d["config_snapshot_json"]),
            started_at=_str_to_dt(d["started_at"]),
            completed_at=_str_to_dt(d["completed_at"]),
            status=d["status"],
            baseline_version_id=d["baseline_version_id"],
            baseline_score=d["baseline_score"],
            best_version_id=d["best_version_id"],
            best_score=d["best_score"],
            llm_calls_used=d["llm_calls_used"],
            candidate_version_ids=json.loads(d["candidate_version_ids_json"]),
            iterations_history=json.loads(d["iterations_history_json"]),
            error=d["error"],
        )

    def _row_to_score(self, row: tuple) -> EvolutionScore:
        cols = [
            "score_id",
            "version_id",
            "evo_run_id",
            "score",
            "per_sample_scores_json",
            "hold_out_size",
            "llm_calls_consumed",
            "evaluated_at",
        ]
        d = dict(zip(cols, row))
        return EvolutionScore(
            version_id=d["version_id"],
            score=d["score"],
            per_sample_scores=json.loads(d["per_sample_scores_json"]),
            hold_out_size=d["hold_out_size"],
            llm_calls_consumed=d["llm_calls_consumed"],
            evaluated_at=_str_to_dt(d["evaluated_at"]),
        )
