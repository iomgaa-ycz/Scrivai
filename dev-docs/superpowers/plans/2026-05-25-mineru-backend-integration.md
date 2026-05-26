# MinerU 后端集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MinerU v3.x 作为第三个 OCR 后端集成到 `scrivai/io/convert.py`，与 Monkey OCR、GLM OCR 并列；MinerU 设为默认后端；GLM-OCR 并发硬限为 3。

**Architecture:** 在 `convert.py` 中新增 `_mineru_ocr()` 函数，注册到 `_BACKENDS` 字典。MinerU 通过 `mineru.cli.common.do_parse()` 同步调用，输出到临时目录后读取 `.md` 文件返回。GLM-OCR 入口处 clamp `max_workers` 至 `_GLM_MAX_WORKERS=3`。

**Tech Stack:** mineru[all] (v3.x), pypdf (已有), Python 3.11

**Design doc:** `dev-docs/superpowers/specs/2026-05-25-mineru-backend-integration-design.md`

---

### Task 1: 安装 MinerU 依赖

**Files:**
- Modify: `requirements.txt` 或 `pyproject.toml`（如有依赖声明文件）

- [ ] **Step 1: 安装 mineru[all]**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pip install "mineru[all]"
```

- [ ] **Step 2: 验证安装成功**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/python -c "from mineru.cli.common import do_parse; print('mineru OK')"
```

Expected: `mineru OK`

- [ ] **Step 3: 下载模型（如尚未下载）**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/mineru-models-download
```

- [ ] **Step 4: 验证模型可用**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/python -c "
from mineru.cli.common import do_parse
import tempfile
from pypdf import PdfWriter
import io

w = PdfWriter()
w.add_blank_page(612, 792)
buf = io.BytesIO()
w.write(buf)
pdf_bytes = buf.getvalue()

with tempfile.TemporaryDirectory() as td:
    do_parse(
        output_dir=td,
        pdf_file_names=['test'],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=['ch'],
        backend='pipeline',
        parse_method='auto',
        f_dump_md=True,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=False,
    )
    print('do_parse OK')
"
```

Expected: `do_parse OK`（首次可能需要下载模型，会自动触发）

---

### Task 2: GLM-OCR 并发硬限

**Files:**
- Modify: `scrivai/io/convert.py:338-370`
- Test: `tests/unit/test_glm_chunked.py`

- [ ] **Step 1: 写测试 — max_workers 超限时 clamp 到 3**

在 `tests/unit/test_glm_chunked.py` 末尾追加：

```python
def test_chunked_max_workers_clamped(tmp_path: Path) -> None:
    """max_workers > _GLM_MAX_WORKERS → 被 clamp 至 3 并记录 warning。"""
    from scrivai.io.convert import _glm_ocr_chunked, _GLM_MAX_WORKERS

    pdf = _make_pdf(tmp_path, 10)

    with patch("scrivai.io.convert._glm_ocr_single", return_value="ok") as mock:
        with patch("scrivai.io.convert.logger") as mock_logger:
            _glm_ocr_chunked(
                pdf,
                api_key="test",
                timeout=10,
                chunk_pages=30,
                overlap_pages=2,
                max_workers=12,
            )

    assert mock.call_count == 1
    mock_logger.warning.assert_any_call(
        "GLM-OCR max_workers %d 超过限制, 已降至 %d",
        12,
        _GLM_MAX_WORKERS,
    )


def test_chunked_max_workers_within_limit(tmp_path: Path) -> None:
    """max_workers <= _GLM_MAX_WORKERS → 不 clamp，无 warning。"""
    from scrivai.io.convert import _glm_ocr_chunked, _GLM_MAX_WORKERS

    pdf = _make_pdf(tmp_path, 10)

    with patch("scrivai.io.convert._glm_ocr_single", return_value="ok"):
        with patch("scrivai.io.convert.logger") as mock_logger:
            _glm_ocr_chunked(
                pdf,
                api_key="test",
                timeout=10,
                chunk_pages=30,
                overlap_pages=2,
                max_workers=2,
            )

    # 不应有 clamp 相关的 warning
    for call in mock_logger.warning.call_args_list:
        assert "超过限制" not in str(call)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_glm_chunked.py::test_chunked_max_workers_clamped tests/unit/test_glm_chunked.py::test_chunked_max_workers_within_limit -v
```

Expected: FAIL — `_GLM_MAX_WORKERS` 不存在

- [ ] **Step 3: 实现 clamp 逻辑**

在 `scrivai/io/convert.py` 中，在 `_CHUNK_RETRIES = 2` 之后添加常量：

```python
_GLM_MAX_WORKERS = 3
```

在 `_glm_ocr_chunked()` 函数体开头（`if overlap_pages >= chunk_pages:` 检查之后）插入：

```python
    if max_workers > _GLM_MAX_WORKERS:
        logger.warning(
            "GLM-OCR max_workers %d 超过限制, 已降至 %d",
            max_workers,
            _GLM_MAX_WORKERS,
        )
        max_workers = _GLM_MAX_WORKERS
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_glm_chunked.py -v
```

Expected: 全部 PASS（包括原有 6 个 + 新增 2 个）

- [ ] **Step 5: 提交**

```bash
git add scrivai/io/convert.py tests/unit/test_glm_chunked.py
git commit -m "feat(io): add GLM-OCR max_workers hard cap at 3"
```

---

### Task 3: 实现 `_mineru_ocr()` 函数

**Files:**
- Modify: `scrivai/io/convert.py:528` (在 `_BACKENDS` 之前插入)
- Test: `tests/unit/test_mineru_ocr.py` (新建)

- [ ] **Step 1: 写测试 — 基本调用流程**

创建 `tests/unit/test_mineru_ocr.py`：

```python
"""Unit tests for _mineru_ocr backend (mocked do_parse calls)."""

from __future__ import annotations

import io as _io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfWriter


def _make_pdf(tmp_path: Path, num_pages: int) -> Path:
    """Create a minimal multi-page PDF for testing."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / f"test_{num_pages}p.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def _fake_do_parse(
    output_dir: str,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    p_lang_list: list[str],
    **kwargs,
) -> None:
    """Simulate do_parse by writing a .md file to the expected output path."""
    stem = pdf_file_names[0]
    method = kwargs.get("parse_method", "auto")
    out_dir = Path(output_dir) / stem / method
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.md").write_text("# MinerU output\n\nHello world", encoding="utf-8")


def test_mineru_basic(tmp_path: Path) -> None:
    """MinerU 后端基本调用 → 返回 Markdown 字符串。"""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert.do_parse", side_effect=_fake_do_parse):
        result = _mineru_ocr(pdf, timeout=60)

    assert "# MinerU output" in result
    assert "Hello world" in result


def test_mineru_with_page_range(tmp_path: Path) -> None:
    """指定 start_page/end_page → 用 pypdf 切出子 PDF 后传给 do_parse。"""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 50)
    captured_bytes: list[bytes] = []

    def _capture_do_parse(
        output_dir: str,
        pdf_file_names: list[str],
        pdf_bytes_list: list[bytes],
        p_lang_list: list[str],
        **kwargs,
    ) -> None:
        captured_bytes.extend(pdf_bytes_list)
        _fake_do_parse(output_dir, pdf_file_names, pdf_bytes_list, p_lang_list, **kwargs)

    with patch("scrivai.io.convert.do_parse", side_effect=_capture_do_parse):
        _mineru_ocr(pdf, timeout=60, start_page=10, end_page=20)

    # 切出的子 PDF 应只有 11 页 (10-20 inclusive)
    from pypdf import PdfReader

    reader = PdfReader(_io.BytesIO(captured_bytes[0]))
    assert len(reader.pages) == 11


def test_mineru_import_error(tmp_path: Path) -> None:
    """mineru 未安装 → 抛出 IOError。"""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert.do_parse", None):
        with patch.dict("sys.modules", {"mineru": None, "mineru.cli": None, "mineru.cli.common": None}):
            with pytest.raises(IOError, match="mineru"):
                # 重新触发 import
                import importlib
                import scrivai.io.convert as mod
                importlib.reload(mod)
                mod._mineru_ocr(pdf, timeout=60)


def test_mineru_parse_failure(tmp_path: Path) -> None:
    """do_parse 抛异常 → 包装为 IOError。"""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert.do_parse", side_effect=RuntimeError("model crash")):
        with pytest.raises(IOError, match="MinerU"):
            _mineru_ocr(pdf, timeout=60)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_mineru_ocr.py::test_mineru_basic tests/unit/test_mineru_ocr.py::test_mineru_parse_failure -v
```

Expected: FAIL — `_mineru_ocr` 不存在

- [ ] **Step 3: 实现 `_mineru_ocr()`**

在 `scrivai/io/convert.py` 中，`_glm_ocr()` 函数之后、`_BACKENDS` 之前插入：

```python
def _mineru_ocr(
    pdf_path: Path,
    *,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
    """Convert a PDF to Markdown via MinerU local pipeline.

    Uses MinerU's auto mode to intelligently route text-based pages
    through direct extraction and scanned pages through OCR.

    Args:
        pdf_path: Path to the PDF file.
        timeout: Not used by MinerU (kept for backend interface consistency).
        start_page: PDF start page (1-based, optional).
        end_page: PDF end page (1-based, optional).
    Returns:
        Markdown text.
    Raises:
        IOError: MinerU not installed, model missing, or parse failure.
    """
    try:
        from mineru.cli.common import do_parse as _do_parse
    except ImportError:
        raise IOError(
            "mineru 未安装，请运行: pip install 'mineru[all]' && mineru-models-download"
        )

    from pypdf import PdfReader, PdfWriter

    # Phase 1: prepare PDF bytes (optional page slicing)
    if start_page is not None or end_page is not None:
        reader = PdfReader(pdf_path)
        total = len(reader.pages)
        first = max(0, (start_page - 1) if start_page else 0)
        last = min(total - 1, (end_page - 1) if end_page else total - 1)
        if first > last:
            return ""
        writer = PdfWriter()
        for i in range(first, last + 1):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()
        logger.info("MinerU: 切出页 %d-%d (%d 页)", first + 1, last + 1, last - first + 1)
    else:
        pdf_bytes = pdf_path.read_bytes()

    stem = pdf_path.stem

    # Phase 2: call MinerU
    with tempfile.TemporaryDirectory() as td:
        logger.info("MinerU 开始解析: %s (%d KB)", pdf_path.name, len(pdf_bytes) // 1024)
        try:
            _do_parse(
                output_dir=td,
                pdf_file_names=[stem],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=["ch"],
                backend="pipeline",
                parse_method="auto",
                f_dump_md=True,
                f_dump_middle_json=False,
                f_dump_model_output=False,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                f_dump_orig_pdf=False,
                f_dump_content_list=False,
            )
        except Exception as e:
            raise IOError(f"MinerU 解析失败: {e}") from e

        # Phase 3: read output markdown
        md_path = Path(td) / stem / "auto" / f"{stem}.md"
        if not md_path.is_file():
            raise IOError(f"MinerU 未生成预期输出文件: {md_path}")
        md = md_path.read_text(encoding="utf-8")

    logger.info("MinerU 完成, 输出 Markdown 共 %d 字符", len(md))
    return md
```

同时在模块顶部 import 区域**不需要**添加 `from mineru...` 的导入——`_mineru_ocr` 内部延迟导入以支持 mineru 未安装的场景。

但需要在函数体内引用模块级的 `do_parse`，为方便测试 mock，改为模块级延迟绑定。在 `_BACKENDS` 定义之前加一行：

```python
do_parse: Any = None  # lazy-loaded by _mineru_ocr on first call
```

然后 `_mineru_ocr` 内部改为：

```python
    global do_parse
    if do_parse is None:
        try:
            from mineru.cli.common import do_parse as _dp
            do_parse = _dp
        except ImportError:
            raise IOError(
                "mineru 未安装，请运行: pip install 'mineru[all]' && mineru-models-download"
            )
```

调用时使用 `do_parse(...)` 而非 `_do_parse(...)`。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_mineru_ocr.py::test_mineru_basic tests/unit/test_mineru_ocr.py::test_mineru_with_page_range tests/unit/test_mineru_ocr.py::test_mineru_parse_failure -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scrivai/io/convert.py tests/unit/test_mineru_ocr.py
git commit -m "feat(io): add MinerU local pipeline as OCR backend"
```

---

### Task 4: 注册后端 + 修改默认值 + 更新 `to_markdown()`

**Files:**
- Modify: `scrivai/io/convert.py:528` (`_BACKENDS`)
- Modify: `scrivai/io/convert.py:592` (默认后端)
- Modify: `scrivai/io/convert.py:531-625` (`to_markdown` 函数签名 + kwargs 路由)

- [ ] **Step 1: 写测试 — mineru 后端通过 to_markdown 调用**

在 `tests/unit/test_mineru_ocr.py` 末尾追加：

```python
def test_to_markdown_routes_to_mineru(tmp_path: Path) -> None:
    """ocr_backend='mineru' → 路由到 _mineru_ocr。"""
    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert._mineru_ocr", return_value="mineru result") as mock:
        result = to_markdown(pdf, ocr_backend="mineru")

    assert result == "mineru result"
    mock.assert_called_once()


def test_to_markdown_default_backend_is_mineru(tmp_path: Path) -> None:
    """未指定 backend 且无 env → 默认使用 mineru。"""
    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert._mineru_ocr", return_value="default mineru") as mock:
        with patch.dict("os.environ", {}, clear=False):
            # 确保 SCRIVAI_OCR_BACKEND 未设置
            import os
            os.environ.pop("SCRIVAI_OCR_BACKEND", None)
            result = to_markdown(pdf)

    assert result == "default mineru"
    mock.assert_called_once()


def test_to_markdown_mineru_with_start_end_page(tmp_path: Path) -> None:
    """MinerU 后端接收 start_page/end_page 参数。"""
    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 50)

    with patch("scrivai.io.convert._mineru_ocr", return_value="sliced") as mock:
        to_markdown(pdf, ocr_backend="mineru", start_page=5, end_page=15)

    call_kwargs = mock.call_args
    assert call_kwargs.kwargs.get("start_page") == 5 or 5 in call_kwargs.args
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_mineru_ocr.py::test_to_markdown_routes_to_mineru tests/unit/test_mineru_ocr.py::test_to_markdown_default_backend_is_mineru -v
```

Expected: FAIL — `_BACKENDS` 没有 `"mineru"`

- [ ] **Step 3: 修改 `_BACKENDS` 注册和默认值**

在 `scrivai/io/convert.py` 中修改：

```python
_BACKENDS: dict[str, Callable[..., str]] = {
    "monkey": _monkey_ocr,
    "glm": _glm_ocr,
    "mineru": _mineru_ocr,
}
```

修改 `to_markdown()` 内的默认后端：

```python
    backend = ocr_backend or os.environ.get("SCRIVAI_OCR_BACKEND", "mineru")
```

- [ ] **Step 4: 修改 `to_markdown()` kwargs 路由**

在 `to_markdown()` 函数体的 Phase 1 kwargs 构建区域，增加 mineru 分支：

```python
    elif backend == "mineru":
        if start_page is not None:
            backend_kwargs["start_page"] = start_page
        if end_page is not None:
            backend_kwargs["end_page"] = end_page
```

同时更新 docstring：
- `ocr_backend` 参数说明改为：`Backend name ("monkey", "glm", or "mineru"). Default from SCRIVAI_OCR_BACKEND env or "mineru".`
- `start_page` 说明改为：`PDF start page (GLM/MinerU, 1-based).`
- `end_page` 说明改为：`PDF end page (GLM/MinerU, 1-based).`

更新模块 docstring（文件顶部第 1-6 行）：

```python
"""Pluggable document → Markdown conversion with multiple OCR backends.

Supported backends:
- monkey: Self-hosted MonkeyOCR Docker service
- glm: ZhipuAI GLM-OCR cloud API
- mineru: MinerU local pipeline (default)
...
```

- [ ] **Step 5: 运行全部测试**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/test_mineru_ocr.py tests/unit/test_glm_chunked.py -v
```

Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add scrivai/io/convert.py tests/unit/test_mineru_ocr.py
git commit -m "feat(io): register mineru backend and set as default"
```

---

### Task 5: 更新 CLI

**Files:**
- Modify: `scrivai/cli/io_cmd.py:60-96`

- [ ] **Step 1: 更新 help 文本**

在 `scrivai/cli/io_cmd.py` 中修改三处 help 文本：

```python
    c.add_argument(
        "--ocr-backend",
        default=None,
        help="OCR backend: monkey | glm | mineru (default from SCRIVAI_OCR_BACKEND env or 'mineru')",
    )
```

```python
    c.add_argument(
        "--max-workers",
        type=int,
        default=12,
        help="max parallel threads for GLM-OCR (default 12, hard cap 3)",
    )
```

```python
    c.add_argument(
        "--start-page", type=int, default=None, help="PDF start page, 1-based (GLM/MinerU)"
    )
    c.add_argument(
        "--end-page", type=int, default=None, help="PDF end page, 1-based (GLM/MinerU)"
    )
```

- [ ] **Step 2: 验证 CLI help 输出**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/python -m scrivai.cli io convert --help
```

Expected: help 文本显示 `monkey | glm | mineru (default from SCRIVAI_OCR_BACKEND env or 'mineru')`

- [ ] **Step 3: 提交**

```bash
git add scrivai/cli/io_cmd.py
git commit -m "docs(cli): update io convert help for mineru backend"
```

---

### Task 6: 全量回归测试 + 代码质量

- [ ] **Step 1: ruff 检查 + 格式化**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/python -m ruff check scrivai/io/convert.py scrivai/cli/io_cmd.py --fix
/home/iomgaa/miniconda3/envs/scrivai/bin/python -m ruff format scrivai/io/convert.py scrivai/cli/io_cmd.py
```

- [ ] **Step 2: 全量单元测试**

```bash
/home/iomgaa/miniconda3/envs/scrivai/bin/pytest tests/unit/ -v
```

Expected: 全部 PASS

- [ ] **Step 3: 修复任何失败的测试**

如有失败，修复后重新运行。

- [ ] **Step 4: 提交（如有修复）**

```bash
git add -u
git commit -m "fix(io): address ruff/test issues from mineru integration"
```
