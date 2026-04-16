"""Workspace 沙箱相关 pydantic + WorkspaceManager Protocol。

参考 docs/design.md §4.1 / §4.9。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSpec(BaseModel):
    """创建 workspace 的输入规范。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="全局唯一;workspace 目录与本 id 同名")
    project_root: Path = Field(..., description="业务项目根(含 skills/ 与 agents/)")
    data_inputs: dict[str, Path] = Field(
        default_factory=dict,
        description="输入文件 logical_name → 源路径 映射;create 时复制到 workspace/data/",
    )
    extra_env: dict[str, str] = Field(
        default_factory=dict, description="附加环境变量,传给 Agent SDK"
    )
    force: bool = Field(
        default=False, description="run_id 冲突时:True 覆盖,False 抛 WorkspaceError"
    )


class WorkspaceSnapshot(BaseModel):
    """workspace 快照元信息(写入 meta.json)。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_root: Path
    skills_git_hash: Optional[str] = Field(default=None, description="快照时 skills 的 git hash")
    agents_git_hash: Optional[str] = None
    snapshot_at: datetime
    extra: dict[str, Any] = Field(default_factory=dict)


class WorkspaceHandle(BaseModel):
    """对一个已创建 workspace 的引用,业务层与 PES 都通过此对象操作。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    root_dir: Path = Field(..., description="workspace 根目录(含 working / data / output / logs)")
    working_dir: Path = Field(..., description="Agent 的 cwd(含 .claude/skills+agents)")
    data_dir: Path
    output_dir: Path
    logs_dir: Path
    snapshot: WorkspaceSnapshot


@runtime_checkable
class WorkspaceManager(Protocol):
    """WorkspaceManager Protocol(M0.25 实现)。"""

    def create(self, spec: WorkspaceSpec) -> WorkspaceHandle:
        """按 spec 创建新 workspace;run_id 冲突时按 spec.force 决定行为。"""
        ...

    def archive(self, handle: WorkspaceHandle, success: bool) -> Path:
        """归档 workspace。success=True 打 tar.gz 删原目录;False 写 .failed 标记。"""
        ...

    def cleanup_old(self, days: int = 30) -> None:
        """清理 archives 与 .failed workspace,按 mtime 超过 days 的全删。"""
        ...
