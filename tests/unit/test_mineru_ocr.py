"""Unit tests for _mineru_ocr backend (mocked do_parse calls)."""

from __future__ import annotations

import io as _io
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter


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
    """MinerU basic call returns Markdown string."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert._do_parse", side_effect=_fake_do_parse):
        result = _mineru_ocr(pdf, timeout=60)

    assert "# MinerU output" in result
    assert "Hello world" in result


def test_mineru_with_page_range(tmp_path: Path) -> None:
    """start_page/end_page slices PDF before passing to do_parse."""
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

    with patch("scrivai.io.convert._do_parse", side_effect=_capture_do_parse):
        _mineru_ocr(pdf, timeout=60, start_page=10, end_page=20)

    reader = PdfReader(_io.BytesIO(captured_bytes[0]))
    assert len(reader.pages) == 11


def test_mineru_parse_failure(tmp_path: Path) -> None:
    """do_parse raises exception -> wrapped as IOError."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)

    with patch("scrivai.io.convert._do_parse", side_effect=RuntimeError("model crash")):
        with pytest.raises(IOError, match="MinerU"):
            _mineru_ocr(pdf, timeout=60)


def test_mineru_empty_range(tmp_path: Path) -> None:
    """start_page > end_page returns empty string."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 10)

    result = _mineru_ocr(pdf, timeout=60, start_page=8, end_page=3)

    assert result == ""


def _patch_mineru_backend(mock_fn):
    """Patch _BACKENDS['mineru'] to use mock_fn instead of real _mineru_ocr."""
    return patch.dict("scrivai.io.convert._BACKENDS", {"mineru": mock_fn})


def test_to_markdown_routes_to_mineru(tmp_path: Path) -> None:
    """ocr_backend='mineru' routes to _mineru_ocr."""
    from unittest.mock import MagicMock

    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 5)
    mock = MagicMock(return_value="mineru result")

    with _patch_mineru_backend(mock):
        result = to_markdown(pdf, ocr_backend="mineru")

    assert result == "mineru result"
    mock.assert_called_once()


def test_to_markdown_default_backend_is_mineru(tmp_path: Path) -> None:
    """No backend specified + no env -> defaults to mineru."""
    import os
    from unittest.mock import MagicMock

    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 5)
    mock = MagicMock(return_value="default mineru")

    with _patch_mineru_backend(mock):
        env_backup = os.environ.pop("SCRIVAI_OCR_BACKEND", None)
        try:
            result = to_markdown(pdf)
        finally:
            if env_backup is not None:
                os.environ["SCRIVAI_OCR_BACKEND"] = env_backup

    assert result == "default mineru"
    mock.assert_called_once()


def test_to_markdown_mineru_receives_page_range(tmp_path: Path) -> None:
    """MinerU backend receives start_page/end_page kwargs."""
    from unittest.mock import MagicMock

    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 50)
    mock = MagicMock(return_value="sliced")

    with _patch_mineru_backend(mock):
        to_markdown(pdf, ocr_backend="mineru", start_page=5, end_page=15)

    _, kwargs = mock.call_args
    assert kwargs["start_page"] == 5
    assert kwargs["end_page"] == 15
