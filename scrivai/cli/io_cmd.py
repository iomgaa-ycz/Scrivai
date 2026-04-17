"""scrivai-cli io group — docx2md / doc2md / pdf2md / render。"""

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


def cmd_docx2md(args) -> dict[str, Any]:
    from scrivai.io import docx_to_markdown  # lazy import

    md = docx_to_markdown(args.input)
    return _write_or_echo(md, args.output)


def cmd_doc2md(args) -> dict[str, Any]:
    from scrivai.io import doc_to_markdown  # lazy import

    md = doc_to_markdown(args.input)
    return _write_or_echo(md, args.output)


def cmd_pdf2md(args) -> dict[str, Any]:
    from scrivai.io import pdf_to_markdown  # lazy import

    md = pdf_to_markdown(args.input, base_url=args.base_url, timeout=args.timeout)
    return _write_or_echo(md, args.output)


def cmd_render(args) -> dict[str, Any]:
    from scrivai.io import DocxRenderer  # lazy import

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

    d = sub.add_parser("docx2md", help="docx → markdown(pandoc)")
    d.add_argument("--input", required=True)
    d.add_argument("--output", default=None)
    d.set_defaults(func=cmd_docx2md)

    od = sub.add_parser("doc2md", help="doc → markdown(LibreOffice + pandoc)")
    od.add_argument("--input", required=True)
    od.add_argument("--output", default=None)
    od.set_defaults(func=cmd_doc2md)

    pdf = sub.add_parser("pdf2md", help="pdf → markdown(MonkeyOCR HTTP)")
    pdf.add_argument("--input", required=True)
    pdf.add_argument("--output", default=None)
    pdf.add_argument("--base-url", default="http://100.81.95.44:7861")
    pdf.add_argument("--timeout", type=int, default=120)
    pdf.set_defaults(func=cmd_pdf2md)

    r = sub.add_parser("render", help="docxtpl 模板渲染")
    r.add_argument("--template", required=True)
    r.add_argument("--context-json", required=True)
    r.add_argument("--output", required=True)
    r.set_defaults(func=cmd_render)
