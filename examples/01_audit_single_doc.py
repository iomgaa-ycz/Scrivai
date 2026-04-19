#!/usr/bin/env python3
"""Example 01: AuditorPES checkpoint audit on a single document

Demonstrates: running AuditorPES to audit a maintenance report against
checkpoints defined in checkpoints.json.

Run:
    python examples/01_audit_single_doc.py

Expected output:
    === AuditorPES audit result (status=completed) ===
      CP001 pass: ...
      CP002 pass: ...
      CP003 pass: ...
    Summary: {'total': 3, 'pass': 3, ...}

Environment variables:
    ANTHROPIC_API_KEY         (required)
    ANTHROPIC_BASE_URL        (optional, for compatible gateways)
    SCRIVAI_DEFAULT_MODEL     (optional, default claude-sonnet-4-20250514)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

from scrivai import (
    AuditorPES,
    ModelConfig,
    WorkspaceSpec,
    build_workspace_manager,
    load_pes_config,
)

load_dotenv()


class Finding(BaseModel):
    checkpoint_id: str
    verdict: str
    evidence: list[dict[str, Any]] = []
    reasoning: str = ""


class AuditOutput(BaseModel):
    findings: list[Finding]
    summary: dict[str, int] = {}


def _require_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("[ERROR] ANTHROPIC_API_KEY not set. See README for configuration.")


async def main() -> None:
    _require_env()
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "examples" / "data"

    # 1. Build workspace (isolated directory + skill snapshot)
    ws_mgr = build_workspace_manager(
        workspaces_root="/tmp/scrivai-examples/ws",
        archives_root="/tmp/scrivai-examples/archives",
    )
    workspace = ws_mgr.create(
        WorkspaceSpec(
            run_id="example-01-audit",
            project_root=repo_root,
            force=True,
        )
    )

    # 2. Stage business data into workspace.data_dir (AuditorPES contract requirement)
    shutil.copy(data_dir / "checkpoints.json", workspace.data_dir / "checkpoints.json")
    shutil.copy(data_dir / "maintenance_report.md", workspace.data_dir / "document.md")

    # 3. Load AuditorPES config + model
    config = load_pes_config(repo_root / "scrivai" / "agents" / "auditor.yaml")
    model = ModelConfig(
        model=os.environ.get("SCRIVAI_DEFAULT_MODEL", "claude-sonnet-4-20250514"),
    )

    # 4. Build PES and run
    pes = AuditorPES(
        config=config,
        model=model,
        workspace=workspace,
        runtime_context={
            "output_schema": AuditOutput,
            "evidence_required": False,
        },
    )
    task_prompt = (
        "请对 data/document.md 按 data/checkpoints.json 中的 3 条要点做对照审核。"
        "为每条 checkpoint 产出一个 working/findings/<cp_id>.json,"
        "verdict 从 {合格,不合格,不适用,需要澄清} 中选一。"
        "重要:写入所有 JSON 文件(plan.json / findings/*.json / output.json)时"
        '必须经 Bash 调 `python -c \'import json; json.dump(obj, open(p,"w"),'
        " ensure_ascii=False, indent=2)'`,不要手写 JSON 字符串(避免中文标点导致"
        "非法 JSON)。"
    )
    run = await pes.run(task_prompt)

    # 5. Print results
    print(f"\n=== AuditorPES audit result (status={run.status}) ===\n")
    if run.status != "completed":
        print(f"[FAIL] {run.error}")
        sys.exit(1)
    output = AuditOutput.model_validate(run.final_output)
    for f in output.findings:
        print(f"  {f.checkpoint_id} {f.verdict}: {f.reasoning[:80]}")
    print(f"\nSummary: {output.summary}")
    print(f"\nWorkspace directory (working/output/logs available for inspection): {workspace.root_dir}")


if __name__ == "__main__":
    asyncio.run(main())
