"""scrivai-cli trajectory group — record-feedback / list / get-run / build-eval-dataset。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _resolve_db(args) -> Path:
    db = getattr(args, "db_path", None) or os.environ.get("SCRIVAI_TRAJECTORY_DB")
    if not db:
        raise ValueError("missing env var: SCRIVAI_TRAJECTORY_DB (or pass --db-path)")
    return Path(db).expanduser()


def _read_json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def cmd_record_feedback(args) -> dict[str, Any]:
    from scrivai import TrajectoryStore

    store = TrajectoryStore(_resolve_db(args))
    store.record_feedback(
        run_id=args.run_id,
        input_summary=args.input_summary or "",
        draft_output=_read_json(args.draft),
        final_output=_read_json(args.final),
        corrections=_read_json(args.corrections) if args.corrections else None,
        review_policy_version=args.review_policy_version,
        source=args.source,
        confidence=args.confidence,
        submitted_by=args.submitted_by,
    )
    return {"recorded": True, "run_id": args.run_id}


def cmd_list(args) -> dict[str, Any]:
    from scrivai import TrajectoryStore

    store = TrajectoryStore(_resolve_db(args))
    runs = store.list_runs(pes_name=args.pes_name, limit=args.limit)
    return {"runs": [r.model_dump(mode="json") for r in runs]}


def cmd_get_run(args) -> dict[str, Any]:
    from scrivai import TrajectoryStore

    store = TrajectoryStore(_resolve_db(args))
    rec = store.get_run(args.run_id)
    if rec is None:
        raise ValueError(f"run not found: {args.run_id}")
    return rec.model_dump(mode="json")


def cmd_build_eval_dataset(args) -> dict[str, Any]:
    raise NotImplementedError("build-eval-dataset is implemented in M2 (T2.2)")


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db-path")

    f = sub.add_parser("record-feedback", parents=[common])
    f.add_argument("--run-id", required=True)
    f.add_argument("--draft", required=True, help="path to draft_output JSON file")
    f.add_argument("--final", required=True, help="path to final_output JSON file")
    f.add_argument("--corrections", default=None)
    f.add_argument("--input-summary", default=None)
    f.add_argument("--review-policy-version", default=None)
    f.add_argument("--source", default="human_expert")
    f.add_argument("--confidence", type=float, default=1.0)
    f.add_argument("--submitted-by", default=None)
    f.set_defaults(func=cmd_record_feedback)

    ls = sub.add_parser("list", parents=[common])
    ls.add_argument("--pes-name", default=None)
    ls.add_argument("--limit", type=int, default=50)
    ls.set_defaults(func=cmd_list)

    g = sub.add_parser("get-run", parents=[common])
    g.add_argument("--run-id", required=True)
    g.set_defaults(func=cmd_get_run)

    b = sub.add_parser("build-eval-dataset", parents=[common])
    b.add_argument("--pes-name", required=True)
    b.add_argument("--output", required=True)
    b.set_defaults(func=cmd_build_eval_dataset)
