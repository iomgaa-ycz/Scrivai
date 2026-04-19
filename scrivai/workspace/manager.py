"""LocalWorkspaceManager — POSIX implementation of the WorkspaceManager Protocol.

References:
- docs/design.md §4.9 / §5.2
- docs/TD.md T0.4
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.1
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    raise ImportError(
        "scrivai.workspace requires POSIX (fcntl is unavailable); "
        "for Windows support, implement an alternative WorkspaceManager Protocol."
    )

import fcntl
import json
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from scrivai.exceptions import WorkspaceError
from scrivai.models.workspace import (
    WorkspaceHandle,
    WorkspaceManager,
    WorkspaceSnapshot,
    WorkspaceSpec,
)


class LocalWorkspaceManager:
    """Local-filesystem implementation of the WorkspaceManager Protocol.

    Constructed via the build_workspace_manager factory; not exposed directly.
    """

    def __init__(self, workspaces_root: Path, archives_root: Path) -> None:
        self.workspaces_root = workspaces_root.expanduser().resolve()
        self.archives_root = archives_root.expanduser().resolve()
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.archives_root.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────

    def create(self, spec: WorkspaceSpec) -> WorkspaceHandle:
        if not spec.project_root.exists():
            raise WorkspaceError(f"project_root not found: {spec.project_root}")

        lock_fd = self._acquire_lock(spec.run_id)
        try:
            root = self.workspaces_root / spec.run_id
            if root.exists():
                if not spec.force:
                    raise WorkspaceError(f"workspace already exists: {root}")
                shutil.rmtree(root)

            working = root / "working"
            data = root / "data"
            output = root / "output"
            logs = root / "logs"
            for d in (working, data, output, logs):
                d.mkdir(parents=True, exist_ok=True)

            claude_dir = working / ".claude"
            claude_dir.mkdir()
            for sub in ("skills", "agents"):
                src = spec.project_root / sub
                if src.exists():
                    shutil.copytree(src, claude_dir / sub, symlinks=False)

            for name, src in spec.data_inputs.items():
                dst = data / name
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=False)
                else:
                    shutil.copy2(src, dst)

            snapshot = WorkspaceSnapshot(
                run_id=spec.run_id,
                project_root=spec.project_root.resolve(),
                skills_git_hash=self._git_hash(spec.project_root),
                agents_git_hash=self._git_hash(spec.project_root),
                snapshot_at=datetime.now(timezone.utc),
            )
            (root / "meta.json").write_text(
                json.dumps(
                    {
                        "run_id": spec.run_id,
                        "project_root": str(spec.project_root.resolve()),
                        "data_inputs": {k: str(v) for k, v in spec.data_inputs.items()},
                        "extra_env": spec.extra_env,
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            return WorkspaceHandle(
                run_id=spec.run_id,
                root_dir=root,
                working_dir=working,
                data_dir=data,
                output_dir=output,
                logs_dir=logs,
                snapshot=snapshot,
            )
        finally:
            self._release_lock(lock_fd, spec.run_id)

    def archive(self, handle: WorkspaceHandle, success: bool) -> Path:
        if not handle.root_dir.exists():
            raise WorkspaceError(f"workspace not found: {handle.root_dir}")

        if success:
            archive_path = self.archives_root / f"{handle.run_id}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tf:
                tf.add(handle.root_dir, arcname=handle.run_id)
            shutil.rmtree(handle.root_dir)
            return archive_path
        else:
            failed_marker = handle.root_dir / ".failed"
            failed_marker.touch()
            return failed_marker

    def cleanup_old(self, days: int = 30) -> None:
        """Remove old archives and failed workspace directories older than the given threshold."""
        threshold = time.time() - days * 86400

        # clean up archives
        for arch in self.archives_root.glob("*.tar.gz"):
            if arch.stat().st_mtime < threshold:
                arch.unlink()

        # clean up .failed workspace directories
        for ws in self.workspaces_root.iterdir():
            if not ws.is_dir():
                continue
            failed_marker = ws / ".failed"
            if failed_marker.exists() and failed_marker.stat().st_mtime < threshold:
                shutil.rmtree(ws)

    # ── Internal helpers ─────────────────────────────────────

    def _git_hash(self, path: Path) -> str | None:
        """Return the HEAD short hash of the git repo at path; None if not a git repo or on failure."""
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None

    def _git_is_dirty(self, path: Path) -> bool:
        """Return True if the git repo at path has uncommitted changes; False if not a git repo or on failure."""
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False
            return bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False

    def _acquire_lock(self, run_id: str) -> IO[str]:
        """Acquire an exclusive lock for run_id. Raises WorkspaceError on conflict; returns a file object (close() is safer than raw fd)."""
        lock_path = self.workspaces_root / f".{run_id}.lock"
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            lock_fd.close()
            raise WorkspaceError(f"workspace {run_id} is locked") from e
        return lock_fd

    def _release_lock(self, lock_fd: IO[str], run_id: str) -> None:
        """Release the lock file for run_id."""
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            lock_fd.close()
            (self.workspaces_root / f".{run_id}.lock").unlink(missing_ok=True)


def build_workspace_manager(
    workspaces_root: Path | str = "~/.scrivai/workspaces",
    archives_root: Path | str = "~/.scrivai/archives",
) -> WorkspaceManager:
    """Build the default LocalWorkspaceManager (return type is the Protocol, leaving room for alternative implementations)."""
    return LocalWorkspaceManager(Path(workspaces_root), Path(archives_root))
