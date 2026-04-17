"""M1 I1 集成节点:ExtractorPES → AuditorPES → GeneratorPES 真实 E2E。

参考:
- docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md §8.3
- tests/contract/test_{extractor,auditor,generator}_pes.py::test_*_smoke_with_real_glm

门禁:ANTHROPIC_AUTH_TOKEN 缺失跳过(需 GLM-5.1 网关 token)。
产物:tests/outputs/integration/m1_e2e_<timestamp>.md 运行报告。
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from scrivai import (
    AuditorPES,
    ExtractorPES,
    GeneratorPES,
    HookManager,
    ModelConfig,
    TrajectoryRecorderHook,
    TrajectoryStore,
    WorkspaceSpec,
    build_workspace_manager,
    load_pes_config,
)

# ─── fixtures 路径 ──────────────────────────────────────────

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "m1_e2e"
GUIDE_PATH = FIXTURES_DIR / "substation_guide.md"
CHECKPOINTS_PATH = FIXTURES_DIR / "checkpoints_golden.json"
TEMPLATE_PATH = FIXTURES_DIR / "workpaper_template.docx"

OUTPUTS_DIR = Path(__file__).resolve().parents[1] / "outputs" / "integration"


# ─── pydantic schemas(各 PES 的 output_schema)───────────────


class _ExtractItem(BaseModel):
    id: str
    content: str


class _ExtractorOutput(BaseModel):
    items: list[_ExtractItem]


class _AuditEvidence(BaseModel):
    chunk_id: str
    quote: str


class _AuditFinding(BaseModel):
    checkpoint_id: str
    verdict: str
    evidence: list[_AuditEvidence] = []
    reasoning: str = ""


class _AuditorOutput(BaseModel):
    findings: list[_AuditFinding]
    summary: dict = {}


class _GeneratorContext(BaseModel):
    project_name: str
    report_date: str
    audit_summary: str


class _GeneratorOutput(BaseModel):
    """Generator 的 output.json 顶层 shape:`{context: {...}, sections: [...]}`。

    注意:GeneratorPES.postprocess_phase_result 用 context_schema 校验 **整个
    output.json**(不是只校验 .context 子字段),与 tests/contract/
    test_generator_pes.py::_GenOutput 的惯例一致。
    """

    context: _GeneratorContext
    sections: list[dict] = []


VERDICT_LEVELS = {"合格", "不合格", "不适用", "需要澄清"}


# ─── 主 E2E 测试 ────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_AUTH_TOKEN"),
    reason="real SDK E2E; requires ANTHROPIC_AUTH_TOKEN in .env",
)
async def test_m1_end_to_end_extractor_auditor_generator(tmp_path: Path) -> None:
    """三 PES 串联 + trajectory / archive 验证,产出 markdown 报告。"""

    # ── 公共基础设施(全部 tmp_path 隔离,不污染 ~/.scrivai/)
    workspaces_root = tmp_path / "workspaces"
    archives_root = tmp_path / "archives"
    trajectory_db = tmp_path / "trajectories.sqlite"

    ws_manager = build_workspace_manager(
        workspaces_root=workspaces_root,
        archives_root=archives_root,
    )
    store = TrajectoryStore(trajectory_db)

    project_root = Path(__file__).resolve().parents[2]

    model = ModelConfig(
        model=os.getenv("SCRIVAI_DEFAULT_MODEL") or "glm-5.1",
        provider=os.getenv("SCRIVAI_DEFAULT_PROVIDER") or "glm",
    )

    def _hook_manager() -> HookManager:
        hm = HookManager()
        hm.register(TrajectoryRecorderHook(store))
        return hm

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_ids = {
        "extractor": f"e2e_{ts}_extractor",
        "auditor": f"e2e_{ts}_auditor",
        "generator": f"e2e_{ts}_generator",
    }
    report_lines: list[str] = [
        f"# M1 E2E 集成报告 — {ts}",
        "",
        f"- guide: `{GUIDE_PATH}`",
        f"- checkpoints: `{CHECKPOINTS_PATH}`",
        f"- template: `{TEMPLATE_PATH}`",
        f"- workspaces: `{workspaces_root}`",
        f"- archives: `{archives_root}`",
        f"- trajectory db: `{trajectory_db}`",
        "",
    ]

    # ── Run 1: ExtractorPES ─────────────────────────────────
    ex_ws = ws_manager.create(WorkspaceSpec(run_id=run_ids["extractor"], project_root=project_root))
    shutil.copy(GUIDE_PATH, ex_ws.data_dir / "guide.md")

    ex_pes = ExtractorPES(
        config=load_pes_config(project_root / "scrivai" / "agents" / "extractor.yaml"),
        model=model,
        workspace=ex_ws,
        hooks=_hook_manager(),
        trajectory_store=store,
        runtime_context={"output_schema": _ExtractorOutput},
    )
    ex_run = await ex_pes.run(
        "Read data/guide.md. Each numbered section (1..10) defines one "
        "technical oversight checkpoint. Extract exactly 10 items, using "
        "the parenthesized english slug (e.g. 'insulation_resistance') as "
        "`id` and the section's body text as `content`. "
        "IMPORTANT: when writing JSON files (plan.json / findings/*.json / "
        "output.json), ALWAYS generate them via `python -c 'import json, sys; "
        'json.dump(obj, open(path, "w"), ensure_ascii=False, indent=2)\'` '
        "through Bash — never hand-write JSON. This prevents quote/comma escape "
        "errors when content contains Chinese punctuation."
    )
    assert ex_run.status == "completed", f"extractor failed: {ex_run.error_type} {ex_run.error}"
    assert ex_run.final_output is not None
    ex_items = ex_run.final_output["items"]
    assert len(ex_items) == 10, f"expected 10 items, got {len(ex_items)}"
    ex_archive = ws_manager.archive(ex_ws, success=True)
    assert ex_archive.suffix == ".gz" and ex_archive.exists()
    report_lines += [
        "## Extractor",
        f"- items extracted: **{len(ex_items)}**",
        f"- archive: `{ex_archive.name}` ({ex_archive.stat().st_size} bytes)",
        "",
    ]

    # ── Run 2: AuditorPES ───────────────────────────────────
    au_ws = ws_manager.create(WorkspaceSpec(run_id=run_ids["auditor"], project_root=project_root))
    shutil.copy(GUIDE_PATH, au_ws.data_dir / "guide.md")
    shutil.copy(CHECKPOINTS_PATH, au_ws.data_dir / "checkpoints.json")

    au_pes = AuditorPES(
        config=load_pes_config(project_root / "scrivai" / "agents" / "auditor.yaml"),
        model=model,
        workspace=au_ws,
        hooks=_hook_manager(),
        trajectory_store=store,
        runtime_context={"output_schema": _AuditorOutput},
    )
    au_run = await au_pes.run(
        "Audit data/guide.md against data/checkpoints.json. For each checkpoint, "
        "choose verdict from {合格,不合格,不适用,需要澄清} and cite at least one "
        "evidence quote from guide.md(chunk_id can be the section heading). "
        "IMPORTANT: when writing JSON files (plan.json / findings/*.json / "
        "output.json), ALWAYS generate them via `python -c 'import json, sys; "
        'json.dump(obj, open(path, "w"), ensure_ascii=False, indent=2)\'` '
        "through Bash — never hand-write JSON. Chinese punctuation inside "
        "evidence quotes otherwise breaks downstream parsing."
    )
    assert au_run.status == "completed", f"auditor failed: {au_run.error_type} {au_run.error}"
    au_findings = au_run.final_output["findings"]
    assert len(au_findings) == 10, f"expected 10 findings, got {len(au_findings)}"
    bad = [f for f in au_findings if f["verdict"] not in VERDICT_LEVELS]
    assert not bad, f"findings with invalid verdict: {bad}"
    au_archive = ws_manager.archive(au_ws, success=True)
    report_lines += [
        "## Auditor",
        f"- findings: **{len(au_findings)}**",
        "- verdicts: "
        + ", ".join(
            f"{v}={sum(1 for f in au_findings if f['verdict'] == v)}"
            for v in sorted(VERDICT_LEVELS)
        ),
        f"- archive: `{au_archive.name}` ({au_archive.stat().st_size} bytes)",
        "",
    ]

    # ── Run 3: GeneratorPES(auto_render=True)────────────────
    gen_ws = ws_manager.create(
        WorkspaceSpec(run_id=run_ids["generator"], project_root=project_root)
    )
    shutil.copy(GUIDE_PATH, gen_ws.data_dir / "guide.md")
    # 把 auditor 的 output 作为生成素材写入 data/
    (gen_ws.data_dir / "audit_findings.json").write_text(
        json.dumps(au_run.final_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    gen_pes = GeneratorPES(
        config=load_pes_config(project_root / "scrivai" / "agents" / "generator.yaml"),
        model=model,
        workspace=gen_ws,
        hooks=_hook_manager(),
        trajectory_store=store,
        runtime_context={
            "template_path": TEMPLATE_PATH,
            "context_schema": _GeneratorOutput,
            "auto_render": True,
        },
    )
    gen_run = await gen_pes.run(
        "Fill the template placeholders. Read data/guide.md to infer 'project_name' "
        "(use '220kV 变电站技术监督示范项目' if not explicit). Read "
        "data/audit_findings.json and compose 'audit_summary' (~150 字概述 10 项审核结论). "
        "Set 'report_date' to today's date in YYYY-MM-DD format. "
        "IMPORTANT: when writing JSON files (plan.json / findings/*.json / "
        "output.json), ALWAYS generate them via `python -c 'import json, sys; "
        'json.dump(obj, open(path, "w"), ensure_ascii=False, indent=2)\'` '
        "through Bash — never hand-write JSON. The 'audit_summary' field must "
        "stay a single string (no embedded newlines that could break JSON)."
    )
    assert gen_run.status == "completed", f"generator failed: {gen_run.error_type} {gen_run.error}"
    final_docx = gen_ws.output_dir / "final.docx"
    assert final_docx.exists(), f"final.docx missing: {final_docx}"
    with zipfile.ZipFile(final_docx) as zf:
        assert "word/document.xml" in zf.namelist()
    # 归档前捕获 size(archive 会 rmtree 工作目录)
    final_docx_size = final_docx.stat().st_size
    gen_archive = ws_manager.archive(gen_ws, success=True)
    report_lines += [
        "## Generator",
        f"- final.docx: `{final_docx.name}` ({final_docx_size} bytes) — zip 合法",
        f"- archive: `{gen_archive.name}` ({gen_archive.stat().st_size} bytes)",
        "",
    ]

    # ── trajectory + archive 验证 ───────────────────────────
    for rid in run_ids.values():
        rec = store.get_run(rid)
        assert rec is not None, f"trajectory missing for run_id={rid}"

    archives = sorted(archives_root.glob("*.tar.gz"))
    assert len(archives) == 3, f"expected 3 archives, got {archives}"
    for arch in archives:
        with tarfile.open(arch, "r:gz") as tf:
            names = tf.getnames()
            assert any(n.endswith("/meta.json") for n in names), f"{arch.name}: meta.json 缺失"

    report_lines += [
        "## Trajectory & Archives",
        f"- trajectory runs: **{len(run_ids)}**(全部找到)",
        f"- archives: **{len(archives)}** / 预期 3",
        "",
        "## 结论",
        "- ✅ 三 PES 连跑成功,output 全部校验通过",
        "- ✅ trajectory DB 三 run 齐全",
        "- ✅ archives tar.gz 三份可解压",
        "",
    ]

    # ── 写 markdown 报告 ────────────────────────────────────
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUTS_DIR / f"m1_e2e_{ts}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n报告已写入:{report_path}")
