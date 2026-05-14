# 统一 OCR 转换管线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `scrivai/io/convert.py` 中三条独立转换路径合并为统一入口 `to_markdown()`，所有格式经 MonkeyOCR 管线输出 Markdown，解决 Issue #9 的 .doc 乱码问题。

**Architecture:** 删除 `docx_to_markdown` / `doc_to_markdown` / `pdf_to_markdown`，替换为 `to_markdown(path)` 单一入口。内部按后缀路由：`.doc/.docx` 先经 LibreOffice headless 转 PDF，再与 `.pdf` 一同送 MonkeyOCR HTTP 服务。MonkeyOCR 网络不可达时，`.doc/.docx` 可降级到 pandoc 路径。

**Tech Stack:** Python 3.11, LibreOffice headless, pandoc (fallback), MonkeyOCR HTTP, requests, pytest

**Design doc:** `dev-docs/superpowers/plans/2026-05-14-unified-ocr-pipeline.md`

---

## File Map

| 文件 | 操作 | 职责 |
|------|------|------|
| `scrivai/io/convert.py` | 重写 | 统一 `to_markdown()` 入口 + 3 个私有辅助 |
| `scrivai/io/__init__.py` | 修改 | 只导出 `to_markdown` + `DocxRenderer` |
| `scrivai/__init__.py` | 修改 | 同步更新导入和 `__all__` |
| `scrivai/cli/io_cmd.py` | 重写 | 删除旧子命令，新增 `convert` |
| `tests/contract/test_io_smoke.py` | 重写 | 用 `real_data/` 真实文件测试 |

---

### Task 1: 重写 `scrivai/io/convert.py`

**Files:**
- Rewrite: `scrivai/io/convert.py`

- [ ] **Step 1: 重写 convert.py 为统一 OCR 管线**

用以下内容完全替换 `scrivai/io/convert.py`：

```python
"""Unified document → Markdown conversion via MonkeyOCR.

External dependencies:
- libreoffice/soffice binary (doc/docx → PDF)
- pandoc binary (fallback: docx → markdown)
- MonkeyOCR HTTP service Docker container

All failures raise IOError with an explicit message.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_DEFAULT_OCR_URL = os.environ.get("SCRIVAI_OCR_BASE_URL", "http://100.81.95.44:7861")

_SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx"}


def _to_pdf(path: Path, *, target_dir: Path) -> Path:
    """Convert a .doc/.docx file to PDF via LibreOffice headless.

    Args:
        path: Source document.
        target_dir: Directory to write the output PDF.
    Returns:
        Path to the generated PDF.
    Raises:
        IOError: LibreOffice unavailable or conversion failed.
    """
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice is None:
        raise IOError("libreoffice/soffice binary not found")

    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(target_dir),
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise IOError(f"LibreOffice PDF conversion failed ({path}): {proc.stderr.strip()}")

    converted = target_dir / f"{path.stem}.pdf"
    if not converted.is_file():
        raise IOError(f"LibreOffice did not produce expected file: {converted}")
    return converted


def _ocr_to_markdown(pdf_path: Path, *, base_url: str, timeout: int) -> str:
    """Send a PDF to MonkeyOCR HTTP service and return Markdown.

    Args:
        pdf_path: Path to the PDF file.
        base_url: MonkeyOCR service URL.
        timeout: Per-request HTTP timeout in seconds.
    Returns:
        Markdown text.
    Raises:
        IOError: Service unreachable / non-200 / no .md in ZIP.
        requests.exceptions.RequestException: Network-level failures (connection refused, timeout).
    """
    base = base_url.rstrip("/")

    session = requests.Session()
    session.trust_env = False

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        resp = session.post(f"{base}/parse", files=files, timeout=timeout)

    if resp.status_code != 200:
        raise IOError(f"MonkeyOCR /parse returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise IOError(f"MonkeyOCR processing failed: {data.get('message')}")
    download_url = data.get("download_url")
    if not download_url:
        raise IOError(f"MonkeyOCR response missing download_url: {data}")

    full_url = f"{base}{download_url}" if download_url.startswith("/") else download_url

    zip_resp = session.get(full_url, timeout=timeout)

    if zip_resp.status_code != 200:
        raise IOError(f"MonkeyOCR ZIP download returned {zip_resp.status_code}")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            md_files = [n for n in zf.namelist() if n.endswith(".md")]
            if not md_files:
                raise IOError("No .md file found in MonkeyOCR ZIP")
            return zf.read(md_files[0]).decode("utf-8")
    except zipfile.BadZipFile as e:
        raise IOError(f"MonkeyOCR did not return a valid ZIP: {e}") from e


def _pandoc_to_markdown(docx_path: Path) -> str:
    """Convert a .docx to Markdown using pandoc (fallback path).

    Args:
        docx_path: Path to the .docx file.
    Returns:
        Markdown text.
    Raises:
        IOError: pandoc unavailable or conversion failed.
    """
    if shutil.which("pandoc") is None:
        raise IOError("pandoc binary not found (run `apt install pandoc` or conda install)")

    proc = subprocess.run(
        ["pandoc", str(docx_path), "-t", "markdown"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise IOError(f"pandoc conversion failed ({docx_path}): {proc.stderr.strip()}")
    return proc.stdout


def to_markdown(
    path: str | Path,
    *,
    ocr_base_url: str | None = None,
    timeout: int = 300,
    fallback: bool = True,
) -> str:
    """Convert a document to Markdown.

    Routing:
      .pdf         → MonkeyOCR
      .doc / .docx → LibreOffice headless → PDF → MonkeyOCR

    When fallback=True and MonkeyOCR is unreachable:
      .docx → pandoc direct conversion
      .doc  → LibreOffice → docx → pandoc
      .pdf  → no fallback (raises)

    Config priority: ocr_base_url param > SCRIVAI_OCR_BASE_URL env > hardcoded default.

    Args:
        path: Path to the source document (.pdf / .doc / .docx).
        ocr_base_url: MonkeyOCR service URL override.
        timeout: Per-request HTTP timeout in seconds.
        fallback: Enable pandoc fallback for .doc/.docx when OCR is unreachable.
    Returns:
        Markdown text.
    Raises:
        IOError: Unsupported format / conversion failure / service unreachable without fallback.
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"File not found: {src}")

    suffix = src.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise IOError(f"Unsupported format: {suffix} (supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))})")

    base_url = ocr_base_url or _DEFAULT_OCR_URL

    # --- PDF: direct OCR ---
    if suffix == ".pdf":
        return _ocr_to_markdown(src, base_url=base_url, timeout=timeout)

    # --- DOC / DOCX: LibreOffice → PDF → OCR (with optional fallback) ---
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        pdf_path = _to_pdf(src, target_dir=tmp_dir)

        try:
            return _ocr_to_markdown(pdf_path, base_url=base_url, timeout=timeout)
        except (requests.exceptions.RequestException, IOError) as ocr_err:
            is_network_error = isinstance(ocr_err, requests.exceptions.RequestException) or (
                isinstance(ocr_err, IOError)
                and any(kw in str(ocr_err) for kw in ("network", "unreachable", "timed out", "Connection"))
            )

            if not (fallback and is_network_error):
                raise

            logger.warning("MonkeyOCR 不可达，降级到 pandoc 路径: %s", ocr_err)

            if suffix == ".docx":
                return _pandoc_to_markdown(src)

            # .doc → LibreOffice → docx → pandoc
            docx_path = tmp_dir / f"{src.stem}.docx"
            soffice = shutil.which("libreoffice") or shutil.which("soffice")
            if soffice is None:
                raise IOError("libreoffice/soffice binary not found") from ocr_err

            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "docx", "--outdir", str(tmp_dir), str(src)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise IOError(
                    f"LibreOffice docx fallback conversion failed ({src}): {proc.stderr.strip()}"
                ) from ocr_err
            if not docx_path.is_file():
                raise IOError(f"LibreOffice did not produce expected file: {docx_path}") from ocr_err
            return _pandoc_to_markdown(docx_path)
```

- [ ] **Step 2: 验证 convert.py 语法无误**

Run: `cd /home/iomgaa/Projects/Scrivai && python -c "import ast; ast.parse(open('scrivai/io/convert.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add scrivai/io/convert.py
git commit -m "refactor(io): rewrite convert.py with unified to_markdown() entry point

Replace docx_to_markdown/doc_to_markdown/pdf_to_markdown with single
to_markdown() that routes all formats through MonkeyOCR pipeline.
Closes #9 (partial)."
```

---

### Task 2: 更新 `scrivai/io/__init__.py`

**Files:**
- Modify: `scrivai/io/__init__.py`

- [ ] **Step 1: 替换 `__init__.py` 内容**

用以下内容完全替换 `scrivai/io/__init__.py`：

```python
"""Scrivai IO utilities — document format conversion and docxtpl rendering."""

from scrivai.io.convert import to_markdown
from scrivai.io.render import DocxRenderer

__all__ = ["to_markdown", "DocxRenderer"]
```

- [ ] **Step 2: 验证导入正常**

Run: `cd /home/iomgaa/Projects/Scrivai && python -c "from scrivai.io import to_markdown, DocxRenderer; print('io import ok')"`
Expected: `io import ok`

- [ ] **Step 3: Commit**

```bash
git add scrivai/io/__init__.py
git commit -m "refactor(io): update io __init__ to export only to_markdown + DocxRenderer"
```

---

### Task 3: 更新 `scrivai/__init__.py`

**Files:**
- Modify: `scrivai/__init__.py:48-54` (IO import block)
- Modify: `scrivai/__init__.py:175-179` (`__all__` IO section)

- [ ] **Step 1: 替换 IO 导入块（第 48-54 行）**

将：
```python
# IO
from scrivai.io import (
    DocxRenderer,
    doc_to_markdown,
    docx_to_markdown,
    pdf_to_markdown,
)
```

替换为：
```python
# IO
from scrivai.io import DocxRenderer, to_markdown
```

- [ ] **Step 2: 替换 `__all__` 中的 IO 条目（第 175-179 行）**

将：
```python
    # IO
    "docx_to_markdown",
    "doc_to_markdown",
    "pdf_to_markdown",
    "DocxRenderer",
```

替换为：
```python
    # IO
    "to_markdown",
    "DocxRenderer",
```

- [ ] **Step 3: 验证顶层导入正常**

Run: `cd /home/iomgaa/Projects/Scrivai && python -c "from scrivai import to_markdown, DocxRenderer; print('top-level import ok')"`
Expected: `top-level import ok`

- [ ] **Step 4: Commit**

```bash
git add scrivai/__init__.py
git commit -m "refactor(io): update top-level exports — replace 3 converters with to_markdown"
```

---

### Task 4: 重写 `scrivai/cli/io_cmd.py`

**Files:**
- Rewrite: `scrivai/cli/io_cmd.py`

- [ ] **Step 1: 重写 io_cmd.py**

用以下内容完全替换 `scrivai/cli/io_cmd.py`：

```python
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
    c.set_defaults(func=cmd_convert)

    r = sub.add_parser("render", help="docxtpl template rendering")
    r.add_argument("--template", required=True)
    r.add_argument("--context-json", required=True)
    r.add_argument("--output", required=True)
    r.set_defaults(func=cmd_render)
```

- [ ] **Step 2: 验证语法**

Run: `cd /home/iomgaa/Projects/Scrivai && python -c "import ast; ast.parse(open('scrivai/cli/io_cmd.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add scrivai/cli/io_cmd.py
git commit -m "refactor(cli): replace docx2md/doc2md/pdf2md with unified convert subcommand"
```

---

### Task 5: 重写测试 `tests/contract/test_io_smoke.py`

**Files:**
- Rewrite: `tests/contract/test_io_smoke.py`

**注意:** 真实测试文件路径含中文和特殊字符，使用 `Path` 对象和 `REAL_DATA` 常量引用。

- [ ] **Step 1: 重写测试文件**

用以下内容完全替换 `tests/contract/test_io_smoke.py`：

```python
"""Contract tests for scrivai.io — unified to_markdown() + DocxRenderer.

Uses real_data/ files for OCR pipeline smoke tests.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REAL_DATA = Path(__file__).resolve().parents[2] / "real_data"
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "io_samples"

SAMPLE_DOC = REAL_DATA / "2025年政府采购领域“四类”违法违规行为专项整治工作指引.doc"
SAMPLE_DOCX = (
    REAL_DATA
    / "从化区中医医院手术室设备及附件、病房护理及医院设备采购"
    / "从化区中医医院手术室设备及附件、病房护理及医院设备采购.docx"
)
SAMPLE_PDF = (
    REAL_DATA
    / "从化区中医医院手术室设备及附件、病房护理及医院设备采购"
    / "3、从化区中医医院手术室设备及附件、病房护理及医院设备采购"
    / "项目全过程归档资料.pdf"
)
SAMPLE_XLS = REAL_DATA / "附件9 处理处罚标准.xls"


def _monkeyocr_reachable(base_url: str = "http://100.81.95.44:7861") -> bool:
    import requests

    try:
        requests.get(base_url, timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


def _has_soffice() -> bool:
    return bool(shutil.which("libreoffice") or shutil.which("soffice"))


# ─── to_markdown: OCR 主路径 ──────────────────────────────────


@pytest.mark.skipif(not _monkeyocr_reachable(), reason="MonkeyOCR 不可达")
@pytest.mark.skipif(not _has_soffice(), reason="需要 libreoffice 二进制")
def test_to_markdown_doc() -> None:
    """真实 .doc 文件经 LibreOffice → PDF → MonkeyOCR 输出 Markdown。"""
    from scrivai.io import to_markdown

    if not SAMPLE_DOC.is_file():
        pytest.skip(f"测试文件不存在: {SAMPLE_DOC}")

    md = to_markdown(SAMPLE_DOC, timeout=300)
    assert isinstance(md, str)
    assert len(md) > 100
    assert "政府采购" in md


@pytest.mark.skipif(not _monkeyocr_reachable(), reason="MonkeyOCR 不可达")
@pytest.mark.skipif(not _has_soffice(), reason="需要 libreoffice 二进制")
def test_to_markdown_docx() -> None:
    """真实 .docx 文件经 LibreOffice → PDF → MonkeyOCR 输出 Markdown。"""
    from scrivai.io import to_markdown

    if not SAMPLE_DOCX.is_file():
        pytest.skip(f"测试文件不存在: {SAMPLE_DOCX}")

    md = to_markdown(SAMPLE_DOCX, timeout=300)
    assert isinstance(md, str)
    assert len(md) > 100


@pytest.mark.skipif(not _monkeyocr_reachable(), reason="MonkeyOCR 不可达")
def test_to_markdown_pdf() -> None:
    """真实 PDF 直接走 MonkeyOCR。"""
    from scrivai.io import to_markdown

    if not SAMPLE_PDF.is_file():
        pytest.skip(f"测试文件不存在: {SAMPLE_PDF}")

    md = to_markdown(SAMPLE_PDF, timeout=300)
    assert isinstance(md, str)
    assert len(md) > 100


# ─── to_markdown: fallback 路径 ───────────────────────────────


@pytest.mark.skipif(not shutil.which("pandoc"), reason="需要 pandoc 二进制")
def test_to_markdown_fallback_docx(tmp_path: Path) -> None:
    """MonkeyOCR 不可达时 .docx 降级到 pandoc。"""
    from docx import Document

    from scrivai.io import to_markdown

    doc = Document()
    doc.add_heading("Fallback Test", level=1)
    doc.add_paragraph("Hello fallback world.")
    fixture = tmp_path / "fallback.docx"
    doc.save(fixture)

    md = to_markdown(
        fixture,
        ocr_base_url="http://127.0.0.1:1",
        timeout=2,
        fallback=True,
    )
    assert isinstance(md, str)
    assert "Hello fallback world" in md


# ─── to_markdown: 错误路径 ────────────────────────────────────


def test_to_markdown_unsupported(tmp_path: Path) -> None:
    """不支持的格式 → IOError。"""
    from scrivai.io import to_markdown

    fake = tmp_path / "data.xls"
    fake.write_bytes(b"\x00\x01\x02")

    with pytest.raises(IOError, match="Unsupported format"):
        to_markdown(fake)


def test_to_markdown_file_not_found(tmp_path: Path) -> None:
    """文件不存在 → IOError。"""
    from scrivai.io import to_markdown

    with pytest.raises(IOError, match="File not found"):
        to_markdown(tmp_path / "no-such-file.pdf")


# ─── DocxRenderer ─────────────────────────────────────────────


@pytest.fixture
def sample_template(tmp_path: Path) -> Path:
    """用 python-docx 造一个含 docxtpl 占位符的 .docx 模板。"""
    from docx import Document

    doc = Document()
    doc.add_heading("Project: {{ project_name }}", level=1)
    doc.add_paragraph("Author: {{ author }}")
    doc.add_paragraph("Body: {{ body }}")
    out = tmp_path / "template.docx"
    doc.save(out)
    return out


def test_docx_renderer_list_placeholders(sample_template: Path) -> None:
    """list_placeholders 返回去重排序的占位符名列表。"""
    from scrivai.io import DocxRenderer

    renderer = DocxRenderer(sample_template)
    names = renderer.list_placeholders()
    assert names == sorted(set(names))
    assert {"project_name", "author", "body"}.issubset(set(names))


def test_docx_renderer_render(sample_template: Path, tmp_path: Path) -> None:
    """render 写出 docx,文件存在且非空。"""
    from scrivai.io import DocxRenderer

    out = tmp_path / "rendered.docx"
    renderer = DocxRenderer(sample_template)
    result = renderer.render(
        context={"project_name": "X变电站", "author": "yu", "body": "hello"},
        output_path=out,
    )
    assert result == out
    assert out.is_file()
    assert out.stat().st_size > 0


def test_docx_renderer_template_not_found(tmp_path: Path) -> None:
    """模板不存在 → FileNotFoundError。"""
    from scrivai.io import DocxRenderer

    with pytest.raises(FileNotFoundError):
        DocxRenderer(tmp_path / "no-such.docx")


def test_docx_renderer_render_failure_no_halfproduct(sample_template: Path, tmp_path: Path) -> None:
    """渲染异常时不留半成品文件。"""
    from scrivai.io import DocxRenderer

    bad_out = tmp_path / "no-such-dir" / "x.docx"
    renderer = DocxRenderer(sample_template)

    with pytest.raises((IOError, OSError, FileNotFoundError)):
        renderer.render(context={"project_name": "p"}, output_path=bad_out)

    assert not bad_out.exists()


# ─── DocxRenderer: fixture edge cases ─────────────────────────


def test_docx_renderer_list_placeholders_in_loop() -> None:
    """loop_template.docx 含简单占位 + 复杂占位;只断言简单标识符出现。"""
    from scrivai.io import DocxRenderer

    fixture = FIXTURES_DIR / "loop_template.docx"
    assert fixture.is_file(), f"fixture 不存在:{fixture}"

    renderer = DocxRenderer(fixture)
    names = renderer.list_placeholders()
    assert "project_name" in names, f"project_name 必在;actual={names}"


def test_docx_renderer_render_loop(tmp_path: Path) -> None:
    """loop_template.docx 渲染 3 item 后,每 item 应在输出中各出现一次。"""
    from docx import Document as _Doc

    from scrivai.io import DocxRenderer

    fixture = FIXTURES_DIR / "loop_template.docx"
    out = tmp_path / "loop_rendered.docx"

    renderer = DocxRenderer(fixture)
    ctx: dict = {
        "project_name": "Sub-7",
        "items": [{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}],
    }
    result = renderer.render(context=ctx, output_path=out)
    assert result == out
    assert out.is_file()
    assert out.stat().st_size > 0

    rendered = _Doc(str(out))
    text = "\n".join(p.text for p in rendered.paragraphs)
    assert "Sub-7" in text, f"project_name 未渲染;text:\n{text}"
    for name in ("alpha", "beta", "gamma"):
        assert name in text, f"item {name!r} 未渲染;text:\n{text}"
```

- [ ] **Step 2: 运行纯本地测试（不依赖 OCR 的用例）**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai python -m pytest tests/contract/test_io_smoke.py::test_to_markdown_unsupported tests/contract/test_io_smoke.py::test_to_markdown_file_not_found tests/contract/test_io_smoke.py::test_docx_renderer_list_placeholders tests/contract/test_io_smoke.py::test_docx_renderer_render tests/contract/test_io_smoke.py::test_docx_renderer_template_not_found tests/contract/test_io_smoke.py::test_docx_renderer_render_failure_no_halfproduct -v`

Expected: 全部 PASSED

- [ ] **Step 3: 运行 fallback 测试**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai python -m pytest tests/contract/test_io_smoke.py::test_to_markdown_fallback_docx -v`

Expected: PASSED（pandoc 可用时）

- [ ] **Step 4: 运行 OCR 主路径测试（需要 MonkeyOCR 在线）**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai python -m pytest tests/contract/test_io_smoke.py::test_to_markdown_doc tests/contract/test_io_smoke.py::test_to_markdown_docx tests/contract/test_io_smoke.py::test_to_markdown_pdf -v --timeout=600`

Expected: 全部 PASSED（MonkeyOCR + LibreOffice 可用时）；否则 SKIPPED

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_io_smoke.py
git commit -m "test(io): rewrite IO contract tests for unified to_markdown pipeline

Uses real_data/ government procurement documents. Covers OCR main path,
pandoc fallback, unsupported format, and file-not-found error cases."
```

---

### Task 6: 代码质量检查 + ruff 格式化

**Files:**
- All modified files

- [ ] **Step 1: ruff check + fix**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai ruff check scrivai/io/convert.py scrivai/io/__init__.py scrivai/__init__.py scrivai/cli/io_cmd.py tests/contract/test_io_smoke.py --fix`

Expected: 无 error（可能有 auto-fix）

- [ ] **Step 2: ruff format**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai ruff format scrivai/io/convert.py scrivai/io/__init__.py scrivai/__init__.py scrivai/cli/io_cmd.py tests/contract/test_io_smoke.py`

Expected: 格式化完成

- [ ] **Step 3: 如有变更则 commit**

```bash
git add -u
git commit -m "style(io): apply ruff formatting to unified OCR pipeline"
```

---

### Task 7: 全量回归测试

- [ ] **Step 1: 运行全部 unit + contract 测试**

Run: `cd /home/iomgaa/Projects/Scrivai && conda run -n scrivai python -m pytest tests/unit/ tests/contract/ -v --timeout=600`

Expected: 无新增 FAIL。已有的 SKIP 可接受（环境依赖）。如果有旧测试引用了已删除的 `docx_to_markdown` 等函数导致 ImportError，需要在此步修复。

- [ ] **Step 2: 如有修复则 commit**

```bash
git add -u
git commit -m "fix(io): fix remaining references to removed converter functions"
```
