"""scrivai-cli library group — search / get / list。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scrivai.knowledge import build_libraries, build_qmd_client_from_config


def _resolve_qmd_db(args: argparse.Namespace) -> Path:
    db = getattr(args, "db_path", None) or os.environ.get("QMD_DB_PATH")
    if not db:
        raise ValueError("missing env var: QMD_DB_PATH (或传 --db-path)")
    return Path(db).expanduser()


def _pick_library(libs: tuple, kind: str):
    rules, cases, templates = libs
    return {"rules": rules, "cases": cases, "templates": templates}[kind]


def _entry_to_json(entry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "markdown": entry.markdown,
        "metadata": entry.metadata,
    }


def _search_result_to_json(r) -> dict[str, Any]:
    """SearchResult 透传所有公开属性(qmd 提供 model_dump 或 dict)。"""
    if hasattr(r, "model_dump"):
        return r.model_dump(mode="json")
    if hasattr(r, "__dict__"):
        return {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
    return {"value": str(r)}


def cmd_search(args: argparse.Namespace) -> dict[str, Any]:
    client = build_qmd_client_from_config(_resolve_qmd_db(args))
    libs = build_libraries(client)
    lib = _pick_library(libs, args.type)

    filters = json.loads(args.filters) if args.filters else None
    hits = lib.search(query=args.query, top_k=args.top_k, filters=filters)
    return {"hits": [_search_result_to_json(h) for h in hits]}


def cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    client = build_qmd_client_from_config(_resolve_qmd_db(args))
    libs = build_libraries(client)
    lib = _pick_library(libs, args.type)

    entry = lib.get(args.entry_id)
    if entry is None:
        raise ValueError(f"entry not found: {args.entry_id}")
    return _entry_to_json(entry)


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    client = build_qmd_client_from_config(_resolve_qmd_db(args))
    libs = build_libraries(client)
    lib = _pick_library(libs, args.type)

    return {"entry_ids": lib.list()}


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--type",
        required=True,
        choices=["rules", "cases", "templates"],
        help="library 类型",
    )
    common.add_argument("--db-path", help="qmd db path(覆盖 env QMD_DB_PATH)")

    s = sub.add_parser("search", parents=[common], help="hybrid search")
    s.add_argument("--query", required=True)
    s.add_argument("--top-k", type=int, default=5)
    s.add_argument("--filters", default=None, help="JSON 字符串")
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("get", parents=[common], help="按 entry_id 取一条")
    g.add_argument("--entry-id", required=True)
    g.set_defaults(func=cmd_get)

    ls = sub.add_parser("list", parents=[common], help="列 collection 内全部 entry_id")
    ls.set_defaults(func=cmd_list)
