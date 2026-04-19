"""promote — write an evaluated SkillVersion back to the project's skills/ directory.

Reference: docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.5
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scrivai.evolution.store import SkillVersionStore


def promote(
    version_id: str,
    source_project_root: Path,
    version_store: Optional[SkillVersionStore] = None,
    backup: bool = True,
) -> Path:
    """Atomically write a skill version's content back to the project.

    Args:
        version_id: ID of the version to promote.
        source_project_root: Project root path.
        version_store: SkillVersionStore instance (defaults to global path).
        backup: If True, back up current content before overwriting.

    Returns:
        Path to the backup directory (if backup=True) or the new skill
        directory (if backup=False).
    """
    store = version_store or SkillVersionStore()
    version = store.get_version(version_id)
    skill_dir = source_project_root / "skills" / version.skill_name

    backup_dir: Optional[Path] = None
    if backup and skill_dir.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = skill_dir / ".backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_dir = backup_root / f"evo-{ts}"
        backup_dir.mkdir()
        for p in skill_dir.iterdir():
            if p.name == ".backup":
                continue
            dst = backup_dir / p.name
            if p.is_dir():
                shutil.copytree(p, dst)
            else:
                shutil.copy2(p, dst)

    if skill_dir.exists():
        for p in skill_dir.iterdir():
            if p.name == ".backup":
                continue
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    else:
        skill_dir.mkdir(parents=True)

    for rel, content in version.content_snapshot.items():
        dst = skill_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

    store.mark_promoted(version_id)
    return backup_dir if backup_dir else skill_dir
