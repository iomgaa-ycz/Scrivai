# Workspace

A **workspace** is an isolated sandbox directory created for each PES run. It provides a clean working area for file I/O, prevents cross-run interference, and supports snapshotting and archival.

## Directory Structure

Each workspace lives under a configurable root (default `~/.scrivai/workspaces/`) and is named after the run ID:

```
~/.scrivai/workspaces/
└── <run_id>/
    ├── input/          # Files copied in before the run
    ├── work/           # Working directory for the PES
    ├── output/         # Files written by the PES
    └── snapshots/      # Point-in-time snapshots (if requested)
```

## Creating a Workspace

Use `build_workspace_manager` to obtain a `WorkspaceManager`, then create a `WorkspaceHandle` for a specific run:

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

The `WorkspaceHandle` gives you typed `Path` attributes for each subdirectory (`input_dir`, `work_dir`, `output_dir`).

## Snapshotting

Call `handle.snapshot()` at any point during a run to capture the current state of the work directory:

```python
snapshot: WorkspaceSnapshot = handle.snapshot(label="after-phase-1")
print(snapshot.path)   # Path to the frozen snapshot directory
print(snapshot.label)  # 'after-phase-1'
```

## Archiving

When a run completes, archive the workspace to move it to long-term storage:

```python
manager.archive(handle)
```

Archived workspaces are moved to `~/.scrivai/workspaces/_archive/<run_id>/`.

## See Also

- [API Reference: Workspace](../api/workspace.md)
