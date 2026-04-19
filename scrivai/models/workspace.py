"""Workspace sandbox data models: WorkspaceSpec, WorkspaceHandle, and WorkspaceManager Protocol."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSpec(BaseModel):
    """Specification for creating an isolated workspace.

    Args:
        run_id: Globally unique identifier. The workspace directory is
            named after this ID.
        project_root: Path to the business project root (must contain
            ``skills/`` and ``agents/`` directories).
        data_inputs: Mapping of logical names to source file paths.
            Files are copied into ``workspace/data/`` at creation time.
        extra_env: Additional environment variables passed to the Agent SDK.
        force: If True, overwrite existing workspace with the same
            ``run_id``. If False (default), raise ``WorkspaceError``.

    Example:
        >>> from pathlib import Path
        >>> from scrivai import WorkspaceSpec
        >>> spec = WorkspaceSpec(
        ...     run_id="audit-001",
        ...     project_root=Path("/path/to/project"),
        ...     force=True,
        ... )
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Globally unique; the workspace directory is named after this ID.")
    project_root: Path = Field(..., description="Business project root (must contain skills/ and agents/).")
    data_inputs: dict[str, Path] = Field(
        default_factory=dict,
        description="Input file mapping logical_name → source path; copied to workspace/data/ at creation time.",
    )
    extra_env: dict[str, str] = Field(
        default_factory=dict, description="Additional environment variables passed to the Agent SDK."
    )
    force: bool = Field(
        default=False, description="On run_id conflict: True overwrites, False raises WorkspaceError."
    )


class WorkspaceSnapshot(BaseModel):
    """Workspace snapshot metadata (written to meta.json)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_root: Path
    skills_git_hash: Optional[str] = Field(default=None, description="Git hash of skills at snapshot time.")
    agents_git_hash: Optional[str] = None
    snapshot_at: datetime
    extra: dict[str, Any] = Field(default_factory=dict)


class WorkspaceHandle(BaseModel):
    """Reference to an existing workspace; used by both the business layer and PES."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    root_dir: Path = Field(..., description="Workspace root directory (contains working / data / output / logs).")
    working_dir: Path = Field(..., description="Agent cwd (contains .claude/skills and .claude/agents).")
    data_dir: Path
    output_dir: Path
    logs_dir: Path
    snapshot: WorkspaceSnapshot


@runtime_checkable
class WorkspaceManager(Protocol):
    """WorkspaceManager Protocol (M0.25 implementation)."""

    def create(self, spec: WorkspaceSpec) -> WorkspaceHandle:
        """Create a new workspace from spec; behaviour on run_id conflict is determined by spec.force."""
        ...

    def archive(self, handle: WorkspaceHandle, success: bool) -> Path:
        """Archive a workspace. success=True creates a tar.gz and removes the directory; False writes a .failed marker."""
        ...

    def cleanup_old(self, days: int = 30) -> None:
        """Delete archives and .failed workspaces whose mtime exceeds the given number of days."""
        ...
