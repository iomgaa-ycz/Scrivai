"""Workspace sandbox pydantic models and WorkspaceManager Protocol.

See docs/design.md §4.1 and §4.9.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSpec(BaseModel):
    """Input specification for creating a workspace."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Globally unique; the workspace directory shares this name.")
    project_root: Path = Field(..., description="Business project root containing skills/ and agents/.")
    data_inputs: dict[str, Path] = Field(
        default_factory=dict,
        description="Mapping of logical_name -> source path; files are copied to workspace/data/ at creation.",
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
    """WorkspaceManager Protocol (implemented in M0.25)."""

    def create(self, spec: WorkspaceSpec) -> WorkspaceHandle:
        """Create a new workspace from spec; conflict behaviour is governed by spec.force."""
        ...

    def archive(self, handle: WorkspaceHandle, success: bool) -> Path:
        """Archive the workspace. success=True creates a tar.gz and removes the directory; False writes a .failed marker."""
        ...

    def cleanup_old(self, days: int = 30) -> None:
        """Remove archives and .failed workspaces whose mtime is older than days."""
        ...
