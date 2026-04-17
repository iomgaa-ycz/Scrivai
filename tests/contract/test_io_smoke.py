"""M0.75 T0.12 contract tests for IO tools(smoke 级别)。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §4。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# ─── docx_to_markdown ───────────────────────────────────────


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    """用 python-docx 程序化造一份简单 docx fixture。"""
    from docx import Document

    doc = Document()
    doc.add_heading("Test Document", level=1)
    doc.add_paragraph("Hello world from Scrivai IO smoke test.")
    out = tmp_path / "sample.docx"
    doc.save(out)
    return out


@pytest.mark.skipif(not shutil.which("pandoc"), reason="需要 pandoc 二进制")
def test_docx_to_markdown(sample_docx: Path) -> None:
    """pandoc 把 docx 转 markdown,内容含原文。"""
    from scrivai.io import docx_to_markdown

    md = docx_to_markdown(sample_docx)
    assert isinstance(md, str)
    assert "Hello world" in md


@pytest.mark.skipif(
    not (shutil.which("libreoffice") or shutil.which("soffice")),
    reason="需要 libreoffice 二进制",
)
@pytest.mark.skipif(not shutil.which("pandoc"), reason="需要 pandoc 二进制")
def test_doc_to_markdown(tmp_path: Path, sample_docx: Path) -> None:
    """LibreOffice 路径:.docx 直接传也应该成功(同 LibreOffice 能识别即可)。

    严格 .doc 二进制需要 fixture 文件,这里复用 docx 验证 LibreOffice 路径联通。
    """
    from scrivai.io import doc_to_markdown

    md = doc_to_markdown(sample_docx)
    assert isinstance(md, str)
    assert "Hello world" in md


# ─── pdf_to_markdown ───────────────────────────────────────


def _monkeyocr_reachable(base_url: str = "http://100.81.95.44:7861") -> bool:
    import requests

    try:
        requests.get(base_url, timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


@pytest.mark.skipif(not _monkeyocr_reachable(), reason="MonkeyOCR 服务 100.81.95.44:7861 不可达")
def test_pdf_to_markdown_smoke(tmp_path: Path) -> None:
    """走真实 MonkeyOCR 服务的 smoke 测试。

    使用 Reference 目录里的示例 PDF;若不存在跳过(局部环境)。
    """
    from scrivai.io import pdf_to_markdown

    sample = Path("/home/iomgaa/Projects/Scrivai/Reference/市场准入负面清单.pdf")
    if not sample.is_file():
        pytest.skip(f"sample PDF 不存在:{sample}")

    md = pdf_to_markdown(sample, timeout=180)
    assert isinstance(md, str)
    assert len(md) > 0


def test_pdf_to_markdown_unreachable_raises(tmp_path: Path) -> None:
    """服务不可达 → 抛 IOError(明确错误信息)。"""
    from scrivai.io import pdf_to_markdown

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    with pytest.raises(IOError, match="MonkeyOCR"):
        pdf_to_markdown(
            fake_pdf,
            base_url="http://127.0.0.1:1",  # 不存在的端口
            timeout=2,
        )


# ─── DocxRenderer ───────────────────────────────────────


@pytest.fixture
def sample_template(tmp_path: Path) -> Path:
    """用 python-docx 造一个含 docxtpl 占位符的 .docx 模板。

    docxtpl 占位符语法是 {{ var }};python-docx 把它写到一个 run 里就可识别。
    """
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
    """渲染异常时不留半成品文件。

    docxtpl 在缺 context key 时默认渲染为空字符串(不抛错),
    所以这里用 invalid output_path(指向不存在目录)制造 IOError。
    """
    from scrivai.io import DocxRenderer

    bad_out = tmp_path / "no-such-dir" / "x.docx"
    renderer = DocxRenderer(sample_template)

    with pytest.raises((IOError, OSError, FileNotFoundError)):
        renderer.render(context={"project_name": "p"}, output_path=bad_out)

    assert not bad_out.exists()


# ─── M1.5b T1.8 edge DoD ───────────────────────────────────


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "io_samples"


@pytest.mark.skipif(not shutil.which("pandoc"), reason="需要 pandoc 二进制")
def test_docx_to_markdown_preserves_table() -> None:
    """pandoc 把含表格的 docx 转 markdown,保留表格结构(内容 + 表格语法)。"""
    import re

    from scrivai.io import docx_to_markdown

    fixture = FIXTURES_DIR / "table_sample.docx"
    assert fixture.is_file(), f"fixture 不存在:{fixture}"

    md = docx_to_markdown(fixture)
    # 内容必须全部出现
    assert "Checkpoint" in md
    assert "Verdict" in md
    assert "Insulation resistance" in md
    assert "Pass" in md
    assert "Grounding continuity" in md
    assert "Fail" in md
    # pandoc 表格可能走 pipe / grid / simple / multiline 四种 markdown 方言;任一即可
    has_pipe = "|" in md
    has_grid = "+-" in md
    has_simple = bool(re.search(r"^[ \t]*-{5,}", md, re.MULTILINE))
    assert has_pipe or has_grid or has_simple, (
        f"pandoc 输出应保留表格结构(pipe/grid/simple/multiline);实际:{md[:500]}"
    )


def test_docx_renderer_list_placeholders_in_loop() -> None:
    """loop_template.docx 含 `{{ project_name }}` 简单占位 + `{{ item.name }}` 复杂占位;
    现行 list_placeholders 正则 `[a-zA-Z_][a-zA-Z0-9_]*` 只识别简单标识符,
    所以只断言 project_name 必出现,item.name 因含点号不入列表(行为契约)。"""
    from scrivai.io import DocxRenderer

    fixture = FIXTURES_DIR / "loop_template.docx"
    assert fixture.is_file(), f"fixture 不存在:{fixture}"

    renderer = DocxRenderer(fixture)
    names = renderer.list_placeholders()
    assert "project_name" in names, f"project_name 必在;actual={names}"
    # item.name 因含 "." 不被当前正则捕获;不做否定断言(实现可能升级)


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
