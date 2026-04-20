"""scrivai-cli workspace group — create / archive / cleanup。"""

from __future__ import annotations

import argparse
import json as _json
import os
from pathlib import Path
from typing import Any


def _resolve_workspace_roots(args) -> tuple[Path, Path]:
    ws = getattr(args, "workspaces_root", None) or os.environ.get("SCRIVAI_WORKSPACE_ROOT")
    if not ws:
        raise ValueError("missing env var: SCRIVAI_WORKSPACE_ROOT (or pass --workspaces-root)")
    arc = getattr(args, "archives_root", None) or os.environ.get("SCRIVAI_ARCHIVES_ROOT")
    if not arc:
        raise ValueError("missing env var: SCRIVAI_ARCHIVES_ROOT (or pass --archives-root)")
    return Path(ws).expanduser(), Path(arc).expanduser()


def _parse_kv_list(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items or []:
        if "=" not in it:
            raise ValueError(f"invalid format (expected KEY=VAL): {it}")
        k, v = it.split("=", 1)
        out[k] = v
    return out


def cmd_create(args) -> dict[str, Any]:
    from scrivai import build_workspace_manager
    from scrivai.models.workspace import WorkspaceSpec

    ws, arc = _resolve_workspace_roots(args)
    mgr = build_workspace_manager(workspaces_root=ws, archives_root=arc)

    data_inputs = {k: Path(v).expanduser() for k, v in _parse_kv_list(args.data).items()}
    extra_env = _parse_kv_list(
        args.env
    )  # defaults to empty dict; WorkspaceSpec does not accept None

    spec = WorkspaceSpec(
        run_id=args.run_id,
        project_root=Path(args.project_root).expanduser(),
        data_inputs=data_inputs,
        extra_env=extra_env,
        force=args.force,
    )
    handle = mgr.create(spec)
    return handle.model_dump(mode="json")


def cmd_archive(args) -> dict[str, Any]:
    from scrivai import build_workspace_manager
    from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot

    ws, arc = _resolve_workspace_roots(args)
    mgr = build_workspace_manager(workspaces_root=ws, archives_root=arc)

    # Reconstruct WorkspaceHandle from meta.json (full snapshot written by create)
    root = ws / args.run_id
    meta_path = root / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"meta.json not found: {meta_path}")

    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    snapshot = WorkspaceSnapshot.model_validate(meta["snapshot"])

    handle = WorkspaceHandle(
        run_id=args.run_id,
        root_dir=root,
        working_dir=root / "working",
        data_dir=root / "data",
        output_dir=root / "output",
        logs_dir=root / "logs",
        snapshot=snapshot,
    )
    result = mgr.archive(handle, success=args.success)
    return {"path": str(result)}


def cmd_cleanup(args) -> dict[str, Any]:
    from scrivai import build_workspace_manager

    ws, arc = _resolve_workspace_roots(args)
    mgr = build_workspace_manager(workspaces_root=ws, archives_root=arc)
    mgr.cleanup_old(days=args.days)
    return {"days": args.days, "cleaned": True}


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspaces-root")
    common.add_argument("--archives-root")

    c = sub.add_parser("create", parents=[common])
    c.add_argument("--run-id", required=True)
    c.add_argument("--project-root", required=True)
    c.add_argument("--data", action="append", default=[], help="name=path, may be repeated")
    c.add_argument("--env", action="append", default=[], help="KEY=VAL, may be repeated")
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=cmd_create)

    a = sub.add_parser("archive", parents=[common])
    a.add_argument("--run-id", required=True)
    grp = a.add_mutually_exclusive_group(required=True)
    grp.add_argument("--success", action="store_true")
    grp.add_argument("--failed", dest="success", action="store_false")
    a.set_defaults(func=cmd_archive)

    cl = sub.add_parser("cleanup", parents=[common])
    cl.add_argument("--days", type=int, default=30)
    cl.set_defaults(func=cmd_cleanup)
