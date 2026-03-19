"""DocPipeline 单元测试。

覆盖 OCRAdapter、MonkeyOCRAdapter、DoclingAdapter、MarkdownCleaner、DocPipeline 的核心功能。
"""

import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils.doc_pipeline import (
    DoclingAdapter,
    DocPipeline,
    DocPipelineResult,
    MarkdownCleaner,
    MonkeyOCRAdapter,
    OCRAdapter,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_html_table() -> str:
    """HTML 表格样例。"""
    return """<table>
<tr><th>序号</th><th>名称</th><th>数量</th></tr>
<tr><td>1</td><td>挖掘机</td><td>2台</td></tr>
</table>"""


@pytest.fixture
def sample_latex_text() -> str:
    """包含 LaTeX 符号的文本样例。"""
    return "温度 $45^{\\circ}$，间距 $\\geq$ 100mm，误差 $\\leq 0.5$，步骤 $\\rightarrow$ 完成"


# ═══════════════════════════════════════════════════════════════════════════════
# OCRAdapter 基类测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestOCRAdapterValidation:
    """OCRAdapter._validate_pdf() 测试组。"""

    def test_rejects_non_pdf(self, tmp_path: Path) -> None:
        """非 PDF 文件应抛 ValueError。"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("test content")

        with pytest.raises(ValueError, match="只支持 PDF 文件"):
            MonkeyOCRAdapter("http://localhost").to_markdown(str(txt_file))

    def test_rejects_nonexistent_file(self) -> None:
        """不存在的文件应抛 ValueError。"""
        with pytest.raises(ValueError, match="文件不存在"):
            MonkeyOCRAdapter("http://localhost").to_markdown("/nonexistent/path.pdf")


# ═══════════════════════════════════════════════════════════════════════════════
# MonkeyOCRAdapter 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestMonkeyOCRAdapter:
    """MonkeyOCRAdapter 测试组。"""

    def test_monkey_ocr_success(self, tmp_path: Path) -> None:
        """Mock requests，验证完整 OCR 流程。"""
        # 创建测试 PDF 文件
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        # 创建模拟 ZIP 响应
        md_content = "# 测试文档\n\n这是 OCR 输出的 Markdown 内容。"
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("output.md", md_content)
        zip_data = zip_buffer.getvalue()

        with patch("utils.doc_pipeline.requests") as mock_requests:
            # 模拟 POST /parse 响应
            mock_post_response = MagicMock()
            mock_post_response.json.return_value = {
                "code": 0,
                "data": {"download_url": "http://localhost/download/result.zip"},
            }
            mock_post_response.raise_for_status = MagicMock()

            # 模拟 GET 下载 ZIP 响应
            mock_get_response = MagicMock()
            mock_get_response.content = zip_data
            mock_get_response.raise_for_status = MagicMock()

            mock_requests.post.return_value = mock_post_response
            mock_requests.get.return_value = mock_get_response

            adapter = MonkeyOCRAdapter("http://localhost", timeout=60)
            result = adapter.to_markdown(str(pdf_file))

            assert result == md_content
            mock_requests.post.assert_called_once()
            mock_requests.get.assert_called_once()

    def test_monkey_ocr_api_error(self, tmp_path: Path) -> None:
        """API 返回错误时应抛 RuntimeError。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        with patch("utils.doc_pipeline.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "code": 1,
                "msg": "处理失败",
            }
            mock_response.raise_for_status = MagicMock()
            mock_requests.post.return_value = mock_response

            adapter = MonkeyOCRAdapter("http://localhost")
            with pytest.raises(RuntimeError, match="MonkeyOCR 处理失败"):
                adapter.to_markdown(str(pdf_file))

    def test_monkey_ocr_missing_download_url(self, tmp_path: Path) -> None:
        """API 返回缺少 download_url 时应抛 RuntimeError。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        with patch("utils.doc_pipeline.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.json.return_value = {"code": 0, "data": {}}
            mock_response.raise_for_status = MagicMock()
            mock_requests.post.return_value = mock_response

            adapter = MonkeyOCRAdapter("http://localhost")
            with pytest.raises(RuntimeError, match="缺少 download_url"):
                adapter.to_markdown(str(pdf_file))


# ═══════════════════════════════════════════════════════════════════════════════
# DoclingAdapter 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestDoclingAdapter:
    """DoclingAdapter 测试组。"""

    def test_docling_success(self, tmp_path: Path) -> None:
        """Mock DocumentConverter，验证转换流程。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_document = MagicMock()
        mock_document.export_to_markdown.return_value = "# 测试文档\n\n内容"

        mock_result = MagicMock()
        mock_result.document = mock_document

        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result

        # Mock docling.document_converter 模块
        mock_docling_module = MagicMock()
        mock_docling_module.DocumentConverter.return_value = mock_converter

        with patch.dict(
            "sys.modules",
            {
                "docling": mock_docling_module,
                "docling.document_converter": mock_docling_module,
            },
        ):
            adapter = DoclingAdapter()
            result = adapter.to_markdown(str(pdf_file))

            assert result == "# 测试文档\n\n内容"
            mock_converter.convert.assert_called_once()

    def test_docling_import_error(self, tmp_path: Path) -> None:
        """docling 未安装时应抛 RuntimeError。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        # Mock import to raise ImportError using builtins module
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "docling.document_converter":
                raise ImportError("No module named 'docling'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            adapter = DoclingAdapter()
            with pytest.raises(RuntimeError, match="未安装 docling"):
                adapter.to_markdown(str(pdf_file))

    def test_docling_convert_error(self, tmp_path: Path) -> None:
        """docling 转换失败时应抛 RuntimeError。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_converter = MagicMock()
        mock_converter.convert.side_effect = Exception("转换失败")

        # Mock docling.document_converter 模块
        mock_docling_module = MagicMock()
        mock_docling_module.DocumentConverter.return_value = mock_converter

        with patch.dict(
            "sys.modules",
            {
                "docling": mock_docling_module,
                "docling.document_converter": mock_docling_module,
            },
        ):
            adapter = DoclingAdapter()
            with pytest.raises(RuntimeError, match="Docling 转换失败"):
                adapter.to_markdown(str(pdf_file))


# ═══════════════════════════════════════════════════════════════════════════════
# MarkdownCleaner 正则清洗测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkdownCleanerRegexPhase:
    """MarkdownCleaner 正则清洗阶段测试。"""

    def test_removes_watermark(self) -> None:
        """水印文字应被移除。"""
        text = "施工方案\nCHINA SOUTHERN POWER GRID CO., LTD.\n第一章"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner.clean(text)
        assert "CHINA SOUTHERN POWER GRID" not in result
        assert "施工方案" in result
        assert "第一章" in result

    def test_removes_watermark_case_insensitive(self) -> None:
        """水印移除应忽略大小写。"""
        text = "内容\nchina southern power grid\n后续"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner.clean(text)
        assert "china southern power grid" not in result.lower()

    def test_fixes_long_table_separator(self) -> None:
        """超长表格分隔行应被压缩。"""
        long_sep = "|" + "-" * 300 + "|" + "-" * 300 + "|"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._fix_table_separators(long_sep)
        assert len(result) < 100
        assert "---" in result

    def test_compresses_pure_dash_line(self) -> None:
        """50+ 个纯 '-' 应压缩为 '---'。"""
        result = MarkdownCleaner._fix_table_separators("-" * 100)
        assert result.strip() == "---"

    def test_preserves_normal_separator(self) -> None:
        """正常长度的表格分隔行不应被修改。"""
        normal = "| --- | --- | --- |"
        result = MarkdownCleaner._fix_table_separators(normal)
        assert result == normal

    def test_fixes_broken_separator(self) -> None:
        """以 | 开头但未以 | 结尾的超长分隔行应补齐。"""
        broken = "|" + "-" * 250
        result = MarkdownCleaner._fix_table_separators(broken)
        assert result.strip().endswith("|")

    def test_collapses_blank_lines(self) -> None:
        """3+ 连续空行应压缩为 2 个。"""
        text = "段落一\n\n\n\n\n段落二"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner.clean(text)
        assert "\n\n\n" not in result
        assert "段落一" in result
        assert "段落二" in result


class TestMarkdownCleanerHtmlClean:
    """MarkdownCleaner HTML 清理测试。"""

    def test_html_table_to_markdown(self, sample_html_table: str) -> None:
        """HTML <table> 应转为 Markdown 表格。"""
        result = MarkdownCleaner._clean_html_tags(sample_html_table)
        assert "<table>" not in result
        assert "<tr>" not in result
        assert "| 序号 | 名称 | 数量 |" in result
        assert "| --- | --- | --- |" in result
        assert "| 1 | 挖掘机 | 2台 |" in result

    def test_br_to_newline(self) -> None:
        """<br> 应转为换行符。"""
        result = MarkdownCleaner._clean_html_tags("第一行<br>第二行")
        assert result == "第一行\n第二行"

    def test_br_self_closing(self) -> None:
        """<br/> 自闭合标签应转为换行符。"""
        result = MarkdownCleaner._clean_html_tags("第一行<br/>第二行")
        assert result == "第一行\n第二行"

    def test_removes_span_preserves_text(self) -> None:
        """<span> 标签应移除但保留内部文本。"""
        result = MarkdownCleaner._clean_html_tags('<span style="color:red">重要文本</span>')
        assert result == "重要文本"

    def test_removes_sup_sub(self) -> None:
        """<sub>/<sup> 标签应移除但保留内部文本。"""
        result = MarkdownCleaner._clean_html_tags("H<sub>2</sub>O 和 10<sup>3</sup>")
        assert result == "H2O 和 103"

    def test_hr_to_markdown(self) -> None:
        """<hr> 应转为 Markdown 分隔线。"""
        result = MarkdownCleaner._clean_html_tags("段落一<hr>段落二")
        assert "---" in result

    def test_preserves_plain_text(self) -> None:
        """无 HTML 标签的纯文本应原样返回。"""
        text = "普通施工方案文本，无 HTML 标签。"
        assert MarkdownCleaner._clean_html_tags(text) == text


class TestMarkdownCleanerLatexConversion:
    """MarkdownCleaner LaTeX 符号转换测试。"""

    def test_standalone_geq(self) -> None:
        """$\\geq$ 应转为 ≥。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\geq$")
        assert result == "≥"

    def test_standalone_leq(self) -> None:
        """$\\leq$ 应转为 ≤。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\leq$")
        assert result == "≤"

    def test_degree_with_number(self) -> None:
        """$45^{\\circ}$ 应转为 45°。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$45^{\\circ}$")
        assert result == "45°"

    def test_degree_without_braces(self) -> None:
        """$90^\\circ$ 应转为 90°。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$90^\\circ$")
        assert result == "90°"

    def test_standalone_circ(self) -> None:
        """$\\circ$ 应转为 °。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\circ$")
        assert result == "°"

    def test_comparison_with_value(self) -> None:
        """$\\leq 0.5$ 应转为 ≤0.5。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\leq 0.5$")
        assert result == "≤0.5"

    def test_geq_with_value(self) -> None:
        """$\\geq 100$ 应转为 ≥100。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\geq 100$")
        assert result == "≥100"

    def test_multiple_symbols_in_paragraph(self, sample_latex_text: str) -> None:
        """一段文本中多种 LaTeX 符号应全部正确转换。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols(sample_latex_text)
        assert "$" not in result
        assert "≥" in result
        assert "45°" in result
        assert "≤0.5" in result
        assert "→" in result

    def test_no_false_positive(self) -> None:
        """不含 LaTeX 的普通文本应原样返回。"""
        text = "钢筋间距大于100mm"
        cleaner = MarkdownCleaner(llm=None)
        assert cleaner._convert_latex_symbols(text) == text

    def test_priority_long_match_first(self) -> None:
        """$\\geqslant$ 应完整匹配为 ≥，而非部分匹配 \\geq。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\geqslant$")
        assert result == "≥"

    def test_arrow_symbol(self) -> None:
        """$\\rightarrow$ 应转为 →。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\rightarrow$")
        assert result == "→"

    def test_infinity_symbol(self) -> None:
        """$\\infty$ 应转为 ∞。"""
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._convert_latex_symbols("$\\infty$")
        assert result == "∞"


class TestMarkdownCleanerLLMPhase:
    """MarkdownCleaner LLM 清洗阶段测试。"""

    def test_llm_phase_skipped_when_none(self) -> None:
        """llm=None 时应跳过 LLM 阶段。"""
        text = "测试文本"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner.clean(text)
        assert result == text

    def test_llm_phase_executed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """有 llm 时应执行 LLM 清洗。"""
        # Mock _load_prompt 方法
        cleaner = MarkdownCleaner(llm=MagicMock())

        with patch.object(cleaner, "_load_prompt", return_value="清洗指令"):
            mock_llm = MagicMock()
            mock_llm.chat_with_template.return_value = "清洗后内容"
            cleaner._llm = mock_llm

            with patch.object(cleaner, "_post_process", side_effect=lambda x: x):
                cleaner._llm_clean("测试文本")
                assert mock_llm.chat_with_template.called

    def test_llm_chunk_text(self) -> None:
        """长文本应被正确分块。"""
        cleaner = MarkdownCleaner(llm=None, chunk_size=100)

        # 构造超过 chunk_size 的多段文本
        paragraphs = ["段落" + str(i) + "内容" * 20 for i in range(5)]
        text = "\n\n".join(paragraphs)

        chunks = cleaner._chunk_text(text)
        assert len(chunks) > 1

        # 所有段落内容应被保留
        joined = "\n\n".join(chunks)
        for p in paragraphs:
            assert p in joined

    def test_llm_clean_handles_exception(self, tmp_path: Path) -> None:
        """LLM 调用异常时应保留原文。"""
        cleaner = MarkdownCleaner(llm=MagicMock())

        with patch.object(cleaner, "_load_prompt", return_value="清洗指令"):
            mock_llm = MagicMock()
            mock_llm.chat_with_template.side_effect = Exception("API 错误")
            cleaner._llm = mock_llm

            result = cleaner._llm_clean("原始内容")
            assert "原始内容" in result


class TestMarkdownCleanerPostProcess:
    """MarkdownCleaner._post_process 测试组。"""

    def test_removes_chinese_preamble(self) -> None:
        """中文对话前缀应被移除。"""
        text = "好的，\n## 编制依据"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._post_process(text)
        assert result.startswith("## 编制依据")

    def test_removes_english_preamble(self) -> None:
        """英文对话前缀应被移除。"""
        text = "Sure,\n## Title"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._post_process(text)
        assert result.startswith("## Title")

    def test_removes_code_fence(self) -> None:
        """```markdown 代码块包裹应被移除。"""
        text = "```markdown\n## 标题\n内容\n```"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._post_process(text)
        assert "```" not in result
        assert "## 标题" in result

    def test_removes_suffix(self) -> None:
        """对话后缀应被移除。"""
        text = "正文内容\n以上是处理结果"
        cleaner = MarkdownCleaner(llm=None)
        result = cleaner._post_process(text)
        assert "以上是" not in result
        assert "正文内容" in result

    def test_empty_input(self) -> None:
        """空字符串输入应返回空字符串。"""
        cleaner = MarkdownCleaner(llm=None)
        assert cleaner._post_process("") == ""


# ═══════════════════════════════════════════════════════════════════════════════
# DocPipeline 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestDocPipeline:
    """DocPipeline 测试组。"""

    def test_pipeline_full_flow(self, tmp_path: Path) -> None:
        """端到端流程测试。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        # Mock adapter
        mock_adapter = MagicMock(spec=OCRAdapter)
        mock_adapter.to_markdown.return_value = "# 原始文档\n\nCHINA SOUTHERN POWER GRID\n内容"

        # Mock cleaner
        mock_cleaner = MagicMock(spec=MarkdownCleaner)
        mock_cleaner.clean.return_value = "# 原始文档\n\n内容"

        pipeline = DocPipeline(adapter=mock_adapter, cleaner=mock_cleaner)
        result = pipeline.run(str(pdf_file))

        assert isinstance(result, DocPipelineResult)
        assert "CHINA SOUTHERN POWER GRID" in result.raw_md
        assert "CHINA SOUTHERN POWER GRID" not in result.cleaned_md
        assert "内容" in result.cleaned_md

    def test_pipeline_warnings_word_loss(self, tmp_path: Path) -> None:
        """字数损失过大应生成警告。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_adapter = MagicMock(spec=OCRAdapter)
        mock_adapter.to_markdown.return_value = "x" * 1000

        mock_cleaner = MagicMock(spec=MarkdownCleaner)
        mock_cleaner.clean.return_value = "x" * 100  # 90% 损失

        pipeline = DocPipeline(adapter=mock_adapter, cleaner=mock_cleaner)
        result = pipeline.run(str(pdf_file))

        assert len(result.warnings) > 0
        assert any("字数损失" in w for w in result.warnings)

    def test_pipeline_warnings_hallucination(self, tmp_path: Path) -> None:
        """幻觉短语应生成警告。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_adapter = MagicMock(spec=OCRAdapter)
        mock_adapter.to_markdown.return_value = "原始内容"

        mock_cleaner = MagicMock(spec=MarkdownCleaner)
        mock_cleaner.clean.return_value = "好的，这是处理后的内容"  # 幻觉前缀

        pipeline = DocPipeline(adapter=mock_adapter, cleaner=mock_cleaner)
        result = pipeline.run(str(pdf_file))

        assert any("幻觉" in w for w in result.warnings)

    def test_pipeline_warnings_table_structure(self, tmp_path: Path) -> None:
        """表格结构异常应生成警告。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_adapter = MagicMock(spec=OCRAdapter)
        mock_adapter.to_markdown.return_value = "原始内容"

        mock_cleaner = MagicMock(spec=MarkdownCleaner)
        mock_cleaner.clean.return_value = "内容 | 只有单管道"  # 异常表格

        pipeline = DocPipeline(adapter=mock_adapter, cleaner=mock_cleaner)
        result = pipeline.run(str(pdf_file))

        assert any("管道符" in w for w in result.warnings)

    def test_pipeline_no_warnings(self, tmp_path: Path) -> None:
        """无问题时不生成警告。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

        mock_adapter = MagicMock(spec=OCRAdapter)
        mock_adapter.to_markdown.return_value = "# 文档\n\n正常内容"

        mock_cleaner = MagicMock(spec=MarkdownCleaner)
        mock_cleaner.clean.return_value = "# 文档\n\n正常内容"

        pipeline = DocPipeline(adapter=mock_adapter, cleaner=mock_cleaner)
        result = pipeline.run(str(pdf_file))

        assert len(result.warnings) == 0


class TestDocPipelineResult:
    """DocPipelineResult 数据类测试。"""

    def test_result_structure(self) -> None:
        """结果应包含 raw_md、cleaned_md、warnings。"""
        result = DocPipelineResult(
            raw_md="原始内容",
            cleaned_md="清洗后内容",
            warnings=["警告1"],
        )

        assert result.raw_md == "原始内容"
        assert result.cleaned_md == "清洗后内容"
        assert result.warnings == ["警告1"]

    def test_result_empty_warnings(self) -> None:
        """无警告时 warnings 应为空列表。"""
        result = DocPipelineResult(
            raw_md="内容",
            cleaned_md="内容",
            warnings=[],
        )

        assert result.warnings == []
