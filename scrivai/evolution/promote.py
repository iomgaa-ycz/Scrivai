"""promote — 把评估通过的 SkillVersion 写回主仓 skills/ 目录。

参考 docs/superpowers/specs/2026-04-17-scrivai-m2-design.md §5.5
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
    """把 version.content_snapshot 原子写入 source_project_root/skills/<skill_name>/。

    参数:
        version_id: 待 promote 的版本 ID。
        source_project_root: 项目根目录路径。
        version_store: SkillVersionStore 实例,默认使用全局默认路径。
        backup: 是否备份当前内容到 skills/<skill_name>/.backup/evo-<ts>/。

    返回:
        backup=True 时返回备份目录;backup=False 时返回新 skill 目录。

    说明:
        - backup=True: 备份当前内容到 skills/<skill_name>/.backup/evo-<ts>/
        - 更新 SkillVersion.status = 'promoted' + promoted_at = now()
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
