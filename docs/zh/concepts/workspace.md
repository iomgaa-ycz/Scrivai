<!-- This is a Chinese translation of docs/concepts/workspace.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 工作区

**工作区**是为每次 PES 运行创建的隔离沙箱目录。它提供干净的文件 I/O 工作空间，防止跨运行干扰，并支持快照与归档。

## 目录结构

每个工作区位于可配置的根目录下（默认 `~/.scrivai/workspaces/`），以运行 ID 命名：

```
~/.scrivai/workspaces/
└── <run_id>/
    ├── input/          # Files copied in before the run
    ├── work/           # Working directory for the PES
    ├── output/         # Files written by the PES
    └── snapshots/      # Point-in-time snapshots (if requested)
```

## 创建工作区

使用 `build_workspace_manager` 获取 `WorkspaceManager`，再为特定运行创建 `WorkspaceHandle`：

```python
from scrivai import build_workspace_manager, WorkspaceSpec

# Build a manager pointing at a custom root
manager = build_workspace_manager(root="~/.scrivai/workspaces")

# Define the workspace spec for a run
spec = WorkspaceSpec(run_id="audit-run-001")

# Create the workspace
handle = manager.create(spec)
print(handle.work_dir)  # Path to the work/ subdirectory
```

`WorkspaceHandle` 为每个子目录提供类型化的 `Path` 属性（`input_dir`、`work_dir`、`output_dir`）。

## 快照

在运行过程中的任意时刻调用 `handle.snapshot()` 以捕获工作目录的当前状态：

```python
snapshot: WorkspaceSnapshot = handle.snapshot(label="after-phase-1")
print(snapshot.path)   # Path to the frozen snapshot directory
print(snapshot.label)  # 'after-phase-1'
```

## 归档

运行完成后，归档工作区以将其移至长期存储：

```python
manager.archive(handle)
```

已归档的工作区将被移至 `~/.scrivai/workspaces/_archive/<run_id>/`。

## 环境变量（`extra_env`）

`WorkspaceSpec.extra_env` 允许你向 Agent SDK 子进程传递环境变量。这是业务层工具（例如 qmd 搜索引擎、数据库连接器）对 Agent 可用的方式。

```python
spec = WorkspaceSpec(
    run_id="audit-with-qmd",
    project_root=project_root,
    extra_env={
        "QMD_COLLECTION": "tender_001",
        "QMD_DB_PATH": "/data/qmd.db",
    },
)
ws = ws_mgr.create(spec)
# ws.extra_env == {"QMD_COLLECTION": "tender_001", "QMD_DB_PATH": "/data/qmd.db"}
```

`extra_env` 字典在完整链路中流转：

```
WorkspaceSpec.extra_env → meta.json → WorkspaceHandle.extra_env
    → BasePES._call_sdk_query → LLMClient.execute_task(extra_env=...)
    → Agent subprocess environment
```

Agent 随后可以在 Bash 工具调用中使用这些变量，或以编程方式读取它们。

## 另请参阅

- [API 参考：Workspace](../../api/workspace.md)
