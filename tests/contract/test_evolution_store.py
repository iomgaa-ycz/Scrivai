"""SkillVersionStore(evolution.db)合约测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scrivai.models.evolution import (
    EvolutionRunRecord,
    EvolutionScore,
    SkillVersion,
)


@pytest.fixture
def store(tmp_path):
    from scrivai.evolution.store import SkillVersionStore

    return SkillVersionStore(db_path=tmp_path / "evo.db")


def _mk_version(vid: str, parent: str | None = None) -> SkillVersion:
    return SkillVersion(
        version_id=vid,
        pes_name="extractor",
        skill_name="available-tools",
        parent_version_id=parent,
        content_snapshot={"SKILL.md": f"# {vid}"},
        content_diff="",
        change_summary=f"version {vid}",
        status="draft",
        created_at=datetime.now(timezone.utc),
        created_by="human",
    )


def test_init_creates_schema(store, tmp_path):
    # DB 文件存在且 3 表已建
    assert (tmp_path / "evo.db").exists()
    rows = list(
        store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    )
    names = {r[0] for r in rows}
    assert {"skill_versions", "evolution_runs", "evolution_scores"} <= names


def test_save_and_get_version(store):
    v = _mk_version("v1")
    store.save_version(v)
    got = store.get_version("v1")
    assert got == v


def test_list_versions_by_pes_skill(store):
    store.save_version(_mk_version("v1"))
    store.save_version(_mk_version("v2", parent="v1"))
    vs = store.list_versions("extractor", "available-tools")
    assert {v.version_id for v in vs} == {"v1", "v2"}


def test_list_versions_filter_status(store):
    store.save_version(_mk_version("v1"))
    store.save_version(_mk_version("v2"))
    store.update_version_status("v1", "evaluated")
    draft_only = store.list_versions("extractor", "available-tools", status="draft")
    assert [v.version_id for v in draft_only] == ["v2"]


def test_mark_promoted(store):
    store.save_version(_mk_version("v1"))
    store.mark_promoted("v1")
    v = store.get_version("v1")
    assert v.status == "promoted"
    assert v.promoted_at is not None


def test_create_and_get_run(store):
    store.save_version(_mk_version("v0"))
    rec = EvolutionRunRecord(
        evo_run_id="run1",
        pes_name="extractor",
        skill_name="available-tools",
        config_snapshot={"max_iterations": 2},
        started_at=datetime.now(timezone.utc),
        baseline_version_id="v0",
        baseline_score=0.5,
    )
    store.create_run(rec)
    got = store.get_run("run1")
    assert got.pes_name == "extractor"
    assert got.baseline_score == 0.5


def test_finalize_run_updates_fields(store):
    store.save_version(_mk_version("v0"))
    store.save_version(_mk_version("v1", parent="v0"))
    rec = EvolutionRunRecord(
        evo_run_id="run1",
        pes_name="extractor",
        skill_name="available-tools",
        config_snapshot={},
        started_at=datetime.now(timezone.utc),
        baseline_version_id="v0",
        baseline_score=0.4,
    )
    store.create_run(rec)
    rec.status = "completed"
    rec.best_version_id = "v1"
    rec.best_score = 0.7
    rec.completed_at = datetime.now(timezone.utc)
    rec.llm_calls_used = 42
    rec.candidate_version_ids = ["v1"]
    store.finalize_run(rec)
    got = store.get_run("run1")
    assert got.status == "completed"
    assert got.best_version_id == "v1"
    assert got.llm_calls_used == 42


def test_record_and_get_scores(store):
    store.save_version(_mk_version("v0"))
    store.save_version(_mk_version("v1", parent="v0"))
    rec = EvolutionRunRecord(
        evo_run_id="run1",
        pes_name="extractor",
        skill_name="available-tools",
        config_snapshot={},
        started_at=datetime.now(timezone.utc),
        baseline_version_id="v0",
        baseline_score=0.4,
    )
    store.create_run(rec)
    s = EvolutionScore(
        version_id="v1",
        score=0.8,
        per_sample_scores=[0.7, 0.9],
        hold_out_size=2,
        llm_calls_consumed=6,
        evaluated_at=datetime.now(timezone.utc),
    )
    store.record_score(s, evo_run_id="run1")
    got = store.get_scores_for_version("v1")
    assert len(got) == 1
    assert got[0].score == 0.8


def test_get_baseline_creates_from_source_when_absent(store, tmp_path):
    """baseline 不存在时从 source_project_root/skills/<name>/ 读取并入库。"""
    proj = tmp_path / "proj"
    skill_dir = proj / "skills" / "available-tools"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# baseline content", encoding="utf-8")

    bl = store.get_baseline("extractor", "available-tools", source_project_root=proj)
    assert bl.parent_version_id is None
    assert bl.content_snapshot["SKILL.md"] == "# baseline content"
    assert bl.created_by == "human"
    # 第二次调返回同一条(不重复入库)
    bl2 = store.get_baseline("extractor", "available-tools", source_project_root=proj)
    assert bl.version_id == bl2.version_id
