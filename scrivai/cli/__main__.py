"""scrivai-cli main entry — argparse router for 4 command groups."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from scrivai.cli import io_cmd, library, trajectory_cmd, workspace_cmd


def _emit_ok(payload: Any) -> int:
    """Write a successful JSON payload to stdout."""
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _emit_err(message: str) -> int:
    """Write an error JSON message to stderr; returns exit code 1."""
    json.dump({"error": message}, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scrivai-cli", description="Scrivai CLI")
    sub = p.add_subparsers(dest="group", required=True)

    library.register(sub.add_parser("library", help="Knowledge library CRUD + search"))
    io_cmd.register(sub.add_parser("io", help="Document format conversion + docx rendering"))
    workspace_cmd.register(sub.add_parser("workspace", help="WorkspaceManager lifecycle"))
    trajectory_cmd.register(
        sub.add_parser("trajectory", help="TrajectoryStore feedback + evolution trigger")
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except SystemExit:
        raise
    except FileNotFoundError as e:
        return _emit_err(f"file not found: {e}")
    except KeyError as e:
        return _emit_err(f"missing key: {e}")
    except ValueError as e:
        return _emit_err(str(e))
    except NotImplementedError as e:
        return _emit_err(f"not implemented: {e}")
    except Exception as e:  # noqa: BLE001
        return _emit_err(f"{type(e).__name__}: {e}")
    return _emit_ok(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
