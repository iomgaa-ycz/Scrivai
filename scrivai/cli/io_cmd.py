"""scrivai-cli io group — convert / render。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _write_or_echo(text: str, output: str | None) -> dict[str, Any]:
    if output:
        Path(output).expanduser().write_text(text, encoding="utf-8")
        return {"output": output, "bytes": len(text.encode("utf-8"))}
    return {"markdown": text}


def cmd_convert(args: argparse.Namespace) -> dict[str, Any]:
    from scrivai.io import to_markdown

    md = to_markdown(
        args.input,
        ocr_base_url=args.ocr_base_url,
        timeout=args.timeout,
        fallback=not args.no_fallback,
        upload_rate=args.upload_rate,
    )
    return _write_or_echo(md, args.output)


def cmd_render(args: argparse.Namespace) -> dict[str, Any]:
    from scrivai.io import DocxRenderer

    ctx_path = Path(args.context_json).expanduser()
    if not ctx_path.is_file():
        raise FileNotFoundError(f"context json not found: {ctx_path}")
    context = json.loads(ctx_path.read_text(encoding="utf-8"))

    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    renderer = DocxRenderer(args.template)
    result = renderer.render(context=context, output_path=out)
    return {"output": str(result)}


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", required=True)

    c = sub.add_parser("convert", help="doc/docx/pdf → markdown (MonkeyOCR pipeline)")
    c.add_argument("--input", required=True)
    c.add_argument("--output", default=None)
    c.add_argument("--ocr-base-url", default=None, help="MonkeyOCR service URL override")
    c.add_argument("--timeout", type=int, default=300)
    c.add_argument("--no-fallback", action="store_true", help="disable pandoc fallback")
    c.add_argument(
        "--upload-rate",
        type=int,
        default=None,
        help="max upload speed in bytes/s (0=unlimited, default 500KB/s from env)",
    )
    c.set_defaults(func=cmd_convert)

    r = sub.add_parser("render", help="docxtpl template rendering")
    r.add_argument("--template", required=True)
    r.add_argument("--context-json", required=True)
    r.add_argument("--output", required=True)
    r.set_defaults(func=cmd_render)
