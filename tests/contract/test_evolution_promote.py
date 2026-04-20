"""promote SDK 合约测试。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scrivai.models.evolution import SkillVersion


@pytest.fixture
def source_project(tmp_path):
    p = tmp_path / "proj"
    (p / "skills" / "available-tools").mkdir(parents=True)
    (p / "skills" / "available-tools" / "SKILL.md").write_text("# baseline", encoding="utf-8")
    return p


def _mk_version(snap: dict[str, str]) -> SkillVersion:
    return SkillVersion(
        version_id="v1",
        pes_name="extractor",
        skill_name="available-tools",
        parent_version_id=None,
        content_snapshot=snap,
        content_diff="",
        change_summary="x",
        status="evaluated",
        created_at=datetime.now(timezone.utc),
        created_by="test",
    )


def test_promote_writes_snapshot_and_backs_up(source_project, tmp_path):
    from scrivai.evolution.promote import promote
    from scrivai.evolution.store import SkillVersionStore

    vstore = SkillVersionStore(db_path=tmp_path / "evo.db")
    v = _mk_version({"SKILL.md": "# PROMOTED NEW"})
    vstore.save_version(v)

    backup_dir = promote(
        version_id="v1",
        source_project_root=source_project,
        version_store=vstore,
    )
    assert (source_project / "skills" / "available-tools" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "# PROMOTED NEW"
    assert backup_dir.parent.name == ".backup"
    assert (backup_dir / "SKILL.md").read_text(encoding="utf-8") == "# baseline"
    after = vstore.get_version("v1")
    assert after.status == "promoted"
    assert after.promoted_at is not None


def test_promote_no_backup(source_project, tmp_path):
    from scrivai.evolution.promote import promote
    from scrivai.evolution.store import SkillVersionStore

    vstore = SkillVersionStore(db_path=tmp_path / "evo.db")
    v = _mk_version({"SKILL.md": "# NEW"})
    vstore.save_version(v)

    result_path = promote(
        "v1",
        source_project_root=source_project,
        version_store=vstore,
        backup=False,
    )
    assert result_path == source_project / "skills" / "available-tools"
    assert not (source_project / "skills" / "available-tools" / ".backup").exists()
