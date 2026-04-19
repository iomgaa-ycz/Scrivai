#!/usr/bin/env python3
"""Example 02: GeneratorPES template generation with docxtpl

Demonstrates three things:
  1. Build a docxtpl template at runtime (avoids committing .docx binaries)
  2. GeneratorPES fills placeholders and produces output.json
  3. --render flag appends docx rendering

Run:
    python examples/02_generate_with_revision.py            # without docx render
    python examples/02_generate_with_revision.py --render   # render docx

Output:
    /tmp/scrivai-examples/ws/<run_id>/working/output.json
    /tmp/scrivai-examples/ws/<run_id>/output/final.docx  (with --render)

Environment variables:
    ANTHROPIC_API_KEY         (required)
    ANTHROPIC_BASE_URL        (optional, for compatible gateways)
    SCRIVAI_DEFAULT_MODEL     (optional, default claude-sonnet-4-20250514)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# examples/ is not a package (no __init__.py), add it to sys.path for relative module imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data.simple_template import build_template  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from scrivai import (  # noqa: E402
    GeneratorPES,
    ModelConfig,
    WorkspaceSpec,
    build_workspace_manager,
    load_pes_config,
)

load_dotenv()


class Section(BaseModel):
    placeholder: str
    content: str = ""
    source_refs: list[dict[str, Any]] = []


class GeneratorOutput(BaseModel):
    context: dict[str, str] = {}
    sections: list[Section] = []


def _require_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("[ERROR] ANTHROPIC_API_KEY not set. See README for configuration.")


async def main(render: bool) -> None:
    _require_env()
    repo_root = Path(__file__).resolve().parents[1]

    # 1. Build docxtpl template at runtime (avoids committing .docx binaries)
    template_path = Path("/tmp/scrivai-examples/simple_template.docx")
    build_template(template_path)

    # 2. Build workspace (isolated directory + skill snapshot)
    ws_mgr = build_workspace_manager(
        workspaces_root="/tmp/scrivai-examples/ws",
        archives_root="/tmp/scrivai-examples/archives",
    )
    workspace = ws_mgr.create(
        WorkspaceSpec(
            run_id=f"example-02-gen-{'render' if render else 'nodocx'}",
            project_root=repo_root,
            force=True,
        )
    )

    # 3. Load GeneratorPES config + model
    config = load_pes_config(repo_root / "scrivai" / "agents" / "generator.yaml")
    model = ModelConfig(
        model=os.environ.get("SCRIVAI_DEFAULT_MODEL", "claude-sonnet-4-20250514"),
    )

    # 4. Build PES and run
    pes = GeneratorPES(
        config=config,
        model=model,
        workspace=workspace,
        runtime_context={
            "template_path": template_path,
            "context_schema": GeneratorOutput,
            "auto_render": render,
        },
    )
    task_prompt = (
        "请基于以下工程输入填充 docxtpl 模板的 3 个占位符,产出工程概况章节。\n"
        "输入字段:\n"
        "  - project_name: 220kV 华阳变电站扩建工程\n"
        "  - project_location: 广东省广州市天河区\n"
        "  - project_scale: 新增主变 2 台,单台容量 180 MVA\n"
        "重要:写入所有 JSON 文件(plan.json / findings/*.json / output.json)时"
        '必须经 Bash 调 `python -c \'import json; json.dump(obj, open(p,"w"),'
        " ensure_ascii=False, indent=2)'`,不要手写 JSON 字符串(避免中文全角标点"
        "导致非法 JSON)。"
    )
    run = await pes.run(task_prompt)

    # 5. Print results
    print(f"\n=== GeneratorPES generation result (status={run.status}) ===\n")
    if run.status != "completed":
        print(f"[FAIL] {run.error}")
        sys.exit(1)
    output = GeneratorOutput.model_validate(run.final_output)
    for s in output.sections:
        print(f"  {{{{ {s.placeholder} }}}} → {s.content[:80]}")
    if render:
        final_docx = workspace.output_dir / "final.docx"
        print(f"\ndocx rendered: {final_docx} ({final_docx.stat().st_size} bytes)")
    print(f"\nWorkspace directory (working/output/logs available for inspection): {workspace.root_dir}")


def _cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="enable docxtpl auto_render")
    asyncio.run(main(ap.parse_args().render))


if __name__ == "__main__":
    _cli()
