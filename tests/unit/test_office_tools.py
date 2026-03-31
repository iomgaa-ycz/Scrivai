"""office_tools 单元测试。

覆盖 convert_word_to_pdf_via_libreoffice 和 convert_docx_to_markdown_via_pandoc
的核心契约，全部使用 mock，不依赖本机 LibreOffice / Pandoc 安装。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrivai.utils.office_tools import convert_word_to_pdf_via_libreoffice, convert_docx_to_markdown_via_pandoc


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════════


def _make_subprocess_result(returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stderr = b""
    result.stdout = b""
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 正常转换
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertWordToPdfSuccess:
    """正常转换路径测试。"""

    def test_docx_converts_to_pdf(self, tmp_path: Path) -> None:
        """.docx 正常转换，生成文件与 output_path 同名。"""
        input_file = tmp_path / "report.docx"
        input_file.write_bytes(b"fake docx content")
        output_file = tmp_path / "out" / "report.pdf"

        with (
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=_make_subprocess_result()) as mock_run,
        ):
            # LibreOffice 会在 outdir 生成 <stem>.pdf，模拟该文件出现
            produced = output_file.parent / "report.pdf"
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"%PDF-1.4")

            result = convert_word_to_pdf_via_libreoffice(input_file, output_file)

        assert result == output_file
        assert output_file.exists()
        mock_run.assert_called_once()

    def test_doc_converts_to_pdf(self, tmp_path: Path) -> None:
        """.doc 后缀同样被接受。"""
        input_file = tmp_path / "legacy.doc"
        input_file.write_bytes(b"fake doc content")
        output_file = tmp_path / "legacy.pdf"

        with (
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            produced = output_file.parent / "legacy.pdf"
            produced.parent.mkdir(parents=True, exist_ok=True)
            produced.write_bytes(b"%PDF-1.4")

            result = convert_word_to_pdf_via_libreoffice(input_file, output_file)

        assert result == output_file

    def test_output_parent_created_automatically(self, tmp_path: Path) -> None:
        """output_path 的父目录不存在时自动创建。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        nested_output = tmp_path / "a" / "b" / "c" / "doc.pdf"

        assert not nested_output.parent.exists()

        with (
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            nested_output.parent.mkdir(parents=True, exist_ok=True)
            nested_output.write_bytes(b"%PDF-1.4")
            convert_word_to_pdf_via_libreoffice(input_file, nested_output)

        assert nested_output.parent.exists()

    def test_produced_path_renamed_to_target(self, tmp_path: Path) -> None:
        """LibreOffice 生成 <stem>.pdf 与 target_path 不同名时，自动重命名。"""
        input_file = tmp_path / "source.docx"
        input_file.write_bytes(b"fake")
        # 调用方期望输出路径名与输入 stem 不同
        output_file = tmp_path / "renamed_output.pdf"

        with (
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            # LibreOffice 实际产出 source.pdf（stem 与输入同名）
            produced = tmp_path / "source.pdf"
            produced.write_bytes(b"%PDF-1.4")

            result = convert_word_to_pdf_via_libreoffice(input_file, output_file)

        assert result == output_file
        assert output_file.exists()
        assert not produced.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 输入验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertWordToPdfInputValidation:
    """非法输入测试。"""

    @pytest.mark.parametrize("suffix", [".pdf", ".txt", ".xlsx", ".odt", ""])
    def test_rejects_non_word_input(self, tmp_path: Path, suffix: str) -> None:
        """非 .doc/.docx 后缀应抛 ValueError。"""
        input_file = tmp_path / f"file{suffix}"
        input_file.write_bytes(b"content")
        output_file = tmp_path / "out.pdf"

        with pytest.raises(ValueError, match="只支持 .doc / .docx"):
            convert_word_to_pdf_via_libreoffice(input_file, output_file)


# ═══════════════════════════════════════════════════════════════════════════════
# LibreOffice 不可用
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertWordToPdfLibreOfficeNotFound:
    """LibreOffice 命令不存在时的错误处理。"""

    def test_raises_runtime_error_when_command_not_found(self, tmp_path: Path) -> None:
        """找不到 libreoffice_cmd 时抛 RuntimeError，并提示安装。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        output_file = tmp_path / "doc.pdf"

        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="找不到 LibreOffice"):
                convert_word_to_pdf_via_libreoffice(input_file, output_file)

    def test_custom_cmd_not_found_mentions_command(self, tmp_path: Path) -> None:
        """自定义命令找不到时，错误信息包含该命令名。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        output_file = tmp_path / "doc.pdf"

        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="/opt/libreoffice/soffice"):
                convert_word_to_pdf_via_libreoffice(
                    input_file, output_file, libreoffice_cmd="/opt/libreoffice/soffice"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# PDF 未生成
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertWordToPdfMissingOutput:
    """LibreOffice 执行成功但未生成 PDF 时的错误处理。"""

    def test_raises_runtime_error_when_pdf_not_produced(self, tmp_path: Path) -> None:
        """命令返回 0 但磁盘上没有生成 PDF，抛 RuntimeError。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        output_file = tmp_path / "doc.pdf"

        with (
            patch("shutil.which", return_value="/usr/bin/soffice"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            # 不创建任何 PDF 文件，模拟 LibreOffice 静默失败
            with pytest.raises(RuntimeError, match="没有生成 PDF 输出"):
                convert_word_to_pdf_via_libreoffice(input_file, output_file)


# ═══════════════════════════════════════════════════════════════════════════════
# Pandoc: Word → Markdown
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertDocxToMarkdownSuccess:
    """convert_docx_to_markdown_via_pandoc 正常路径测试。"""

    def test_docx_converts_to_markdown(self, tmp_path: Path) -> None:
        """.docx 正常转换，返回目标 Markdown 文件路径。"""
        input_file = tmp_path / "report.docx"
        input_file.write_bytes(b"fake docx content")
        output_file = tmp_path / "out" / "report.md"

        with (
            patch("shutil.which", return_value="/usr/bin/pandoc"),
            patch("subprocess.run", return_value=_make_subprocess_result()) as mock_run,
        ):
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(b"# Report")

            result = convert_docx_to_markdown_via_pandoc(input_file, output_file)

        assert result == output_file
        assert output_file.exists()
        mock_run.assert_called_once()

    def test_output_parent_created_automatically(self, tmp_path: Path) -> None:
        """output_path 父目录不存在时自动创建。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        nested_output = tmp_path / "a" / "b" / "doc.md"

        with (
            patch("shutil.which", return_value="/usr/bin/pandoc"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            nested_output.parent.mkdir(parents=True, exist_ok=True)
            nested_output.write_bytes(b"# Doc")
            convert_docx_to_markdown_via_pandoc(input_file, nested_output)

        assert nested_output.parent.exists()


class TestConvertDocxToMarkdownInputValidation:
    """非法输入测试。"""

    @pytest.mark.parametrize("suffix", [".doc", ".pdf", ".txt", ".docm", ""])
    def test_rejects_non_docx_input(self, tmp_path: Path, suffix: str) -> None:
        """非 .docx 后缀应抛 ValueError。"""
        input_file = tmp_path / f"file{suffix}"
        input_file.write_bytes(b"content")
        output_file = tmp_path / "out.md"

        with pytest.raises(ValueError, match="只支持 .docx 输入"):
            convert_docx_to_markdown_via_pandoc(input_file, output_file)


class TestConvertDocxToMarkdownPandocNotFound:
    """Pandoc 命令缺失时的错误处理。"""

    def test_raises_runtime_error_when_command_not_found(self, tmp_path: Path) -> None:
        """找不到 pandoc 命令时抛 RuntimeError。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        output_file = tmp_path / "doc.md"

        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="Pandoc"):
                convert_docx_to_markdown_via_pandoc(input_file, output_file)


class TestConvertDocxToMarkdownMissingOutput:
    """Pandoc 执行成功但未生成文件时的错误处理。"""

    def test_raises_runtime_error_when_md_not_produced(self, tmp_path: Path) -> None:
        """命令返回 0 但磁盘上没有生成 Markdown，抛 RuntimeError。"""
        input_file = tmp_path / "doc.docx"
        input_file.write_bytes(b"fake")
        output_file = tmp_path / "doc.md"

        with (
            patch("shutil.which", return_value="/usr/bin/pandoc"),
            patch("subprocess.run", return_value=_make_subprocess_result()),
        ):
            with pytest.raises(RuntimeError, match="没有生成 Markdown 输出"):
                convert_docx_to_markdown_via_pandoc(input_file, output_file)
