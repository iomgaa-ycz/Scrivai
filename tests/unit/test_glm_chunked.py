"""Unit tests for _glm_ocr_chunked parallel logic (mocked OCR calls)."""

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


def test_chunked_single_chunk(tmp_path: Path) -> None:
    """≤ chunk_pages 的 PDF → 退化为 1 个 chunk，无重叠。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    with patch("scrivai.io.convert._glm_ocr_single", return_value="page content") as mock:
        result = _glm_ocr_chunked(
            pdf,
            api_key="test",
            timeout=10,
            chunk_pages=30,
            overlap_pages=2,
            max_workers=2,
        )

    assert mock.call_count == 1
    assert result == "page content"


def test_chunked_multi_chunks(tmp_path: Path) -> None:
    """> chunk_pages 的 PDF → 分成多个 chunk 并行处理。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 70)
    call_log: list[int] = []

    def _fake_single(pdf_bytes: bytes, *, api_key: str, timeout: int) -> str:
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        n = len(reader.pages)
        call_log.append(n)
        return f"chunk with {n} pages"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_fake_single):
        result = _glm_ocr_chunked(
            pdf,
            api_key="test",
            timeout=10,
            chunk_pages=30,
            overlap_pages=2,
            max_workers=4,
        )

    # 70 pages, stride=28: chunk0=30p, chunk1=30p, chunk2=14p → 3 chunks
    assert len(call_log) == 3
    assert "chunk with" in result


def test_chunked_retries_on_failure(tmp_path: Path) -> None:
    """单 chunk 失败重试后成功 → 整体成功。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)
    attempt = {"count": 0}

    def _fail_then_succeed(pdf_bytes: bytes, *, api_key: str, timeout: int) -> str:
        attempt["count"] += 1
        if attempt["count"] <= 2:
            raise IOError("transient failure")
        return "recovered content"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_fail_then_succeed):
        with patch("scrivai.io.convert.time") as mock_time:
            mock_time.time.return_value = 0.0
            mock_time.sleep = lambda _: None
            result = _glm_ocr_chunked(
                pdf,
                api_key="test",
                timeout=10,
                chunk_pages=30,
                overlap_pages=2,
                max_workers=1,
            )

    assert result == "recovered content"
    assert attempt["count"] == 3


def test_chunked_all_retries_exhausted(tmp_path: Path) -> None:
    """所有重试用尽 → 抛出 IOError。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    def _always_fail(pdf_bytes: bytes, *, api_key: str, timeout: int) -> str:
        raise IOError("persistent failure")

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_always_fail):
        with patch("scrivai.io.convert.time") as mock_time:
            mock_time.time.return_value = 0.0
            mock_time.sleep = lambda _: None
            with pytest.raises(IOError, match="重试"):
                _glm_ocr_chunked(
                    pdf,
                    api_key="test",
                    timeout=10,
                    chunk_pages=30,
                    overlap_pages=2,
                    max_workers=1,
                )


def test_chunked_start_end_page(tmp_path: Path) -> None:
    """指定 start_page/end_page → 只处理指定范围。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 100)
    pages_seen: list[int] = []

    def _count_pages(pdf_bytes: bytes, *, api_key: str, timeout: int) -> str:
        reader = PdfReader(_io.BytesIO(pdf_bytes))
        pages_seen.append(len(reader.pages))
        return "ok"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_count_pages):
        _glm_ocr_chunked(
            pdf,
            api_key="test",
            timeout=10,
            start_page=10,
            end_page=50,
            chunk_pages=30,
            overlap_pages=2,
            max_workers=2,
        )

    # 41 pages (10-50), stride=28: chunk0=30p, chunk1=13p → 2 chunks
    assert len(pages_seen) == 2
    total_pages_processed = sum(pages_seen)
    assert total_pages_processed <= 41 + 2


def test_chunked_empty_range(tmp_path: Path) -> None:
    """start_page > end_page → 返回空字符串。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    result = _glm_ocr_chunked(
        pdf,
        api_key="test",
        timeout=10,
        start_page=5,
        end_page=3,
        chunk_pages=30,
        overlap_pages=2,
        max_workers=1,
    )

    assert result == ""


def test_chunked_max_workers_clamped(tmp_path: Path) -> None:
    """max_workers > _GLM_MAX_WORKERS → 被 clamp 至 3 并记录 warning。"""
    from scrivai.io.convert import _GLM_MAX_WORKERS, _glm_ocr_chunked

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
    from scrivai.io.convert import _glm_ocr_chunked

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

    for call in mock_logger.warning.call_args_list:
        assert "超过限制" not in str(call)
