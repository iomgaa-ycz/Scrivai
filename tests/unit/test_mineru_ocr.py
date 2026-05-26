"""Unit tests for _mineru_ocr backend (mocked HTTP calls to mineru-router)."""

from __future__ import annotations

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


def _make_success_response(stem: str, md_content: str = "# MinerU output\n\nHello world"):
    """Build a mock requests.Response for a successful /file_parse call."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "task_id": "test-uuid",
        "status": "completed",
        "results": {stem: {"md_content": md_content}},
    }
    return resp


def _make_error_response(status_code: int = 503, text: str = "Service Unavailable"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# --- _mineru_ocr direct tests (with explicit mineru_url to skip auto-start) ---


def test_mineru_basic(tmp_path: Path) -> None:
    """MinerU HTTP call returns Markdown string."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)
    mock_resp = _make_success_response(pdf.stem)

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        MockSession.return_value.post.return_value = mock_resp
        result = _mineru_ocr(pdf, timeout=60, mineru_url="http://fake:8002")

    assert "# MinerU output" in result
    assert "Hello world" in result


def test_mineru_with_page_range(tmp_path: Path) -> None:
    """start_page/end_page are converted to 0-based start_page_id/end_page_id."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 50)
    mock_resp = _make_success_response(pdf.stem)

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        mock_session = MockSession.return_value
        mock_session.post.return_value = mock_resp
        _mineru_ocr(pdf, timeout=60, start_page=10, end_page=20, mineru_url="http://fake:8002")

    call_kwargs = mock_session.post.call_args
    encoder = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
    fields = encoder.fields
    assert fields["start_page_id"] == "9"
    assert fields["end_page_id"] == "19"


def test_mineru_parse_failure(tmp_path: Path) -> None:
    """HTTP error -> IOError."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)
    mock_resp = _make_error_response(503, "Service Unavailable")

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        MockSession.return_value.post.return_value = mock_resp
        with pytest.raises(IOError, match="503"):
            _mineru_ocr(pdf, timeout=60, mineru_url="http://fake:8002")


def test_mineru_task_failed(tmp_path: Path) -> None:
    """Task status != completed -> IOError."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "failed", "error": "model crash"}

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        MockSession.return_value.post.return_value = resp
        with pytest.raises(IOError, match="model crash"):
            _mineru_ocr(pdf, timeout=60, mineru_url="http://fake:8002")


def test_mineru_empty_range(tmp_path: Path) -> None:
    """start_page > end_page returns empty string without HTTP call."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 10)
    result = _mineru_ocr(pdf, timeout=60, start_page=8, end_page=3)
    assert result == ""


def test_mineru_explicit_url_no_auto_start(tmp_path: Path) -> None:
    """Explicit mineru_url skips _MineruRouterManager entirely."""
    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)
    mock_resp = _make_success_response(pdf.stem)

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        mock_session = MockSession.return_value
        mock_session.post.return_value = mock_resp
        with patch("scrivai.io.convert._MineruRouterManager") as MockManager:
            _mineru_ocr(pdf, timeout=60, mineru_url="http://my-router:9000")

    MockManager.assert_not_called()
    call_url = mock_session.post.call_args[0][0]
    assert call_url == "http://my-router:9000/file_parse"


def test_mineru_env_url(tmp_path: Path) -> None:
    """SCRIVAI_MINERU_URL env is used when no explicit URL given."""
    import os

    from scrivai.io.convert import _mineru_ocr

    pdf = _make_pdf(tmp_path, 5)
    mock_resp = _make_success_response(pdf.stem)

    with patch("scrivai.io.convert.requests.Session") as MockSession:
        mock_session = MockSession.return_value
        mock_session.post.return_value = mock_resp
        with patch.dict(os.environ, {"SCRIVAI_MINERU_URL": "http://env-router:8002"}):
            with patch("scrivai.io.convert._MineruRouterManager") as MockManager:
                _mineru_ocr(pdf, timeout=60)

    MockManager.assert_not_called()
    call_url = mock_session.post.call_args[0][0]
    assert call_url == "http://env-router:8002/file_parse"


# --- _MineruRouterManager tests ---


def test_router_manager_auto_start() -> None:
    """Manager starts mineru-router subprocess and polls /health."""
    from scrivai.io.convert import _MineruRouterManager

    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.pid = 12345

    health_resp = MagicMock()
    health_resp.status_code = 200
    health_resp.json.return_value = {"status": "healthy"}

    with (
        patch("shutil.which", return_value="/usr/bin/mineru-router"),
        patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        patch("scrivai.io.convert.requests.Session") as MockSession,
        patch("atexit.register") as mock_atexit,
    ):
        MockSession.return_value.get.return_value = health_resp

        mgr = _MineruRouterManager()
        url = mgr.get_url()

    assert url.startswith("http://127.0.0.1:")
    mock_popen.assert_called_once()
    mock_atexit.assert_called_once()


def test_router_manager_shutdown() -> None:
    """Shutdown terminates the subprocess."""
    from scrivai.io.convert import _MineruRouterManager

    mgr = _MineruRouterManager()
    mock_proc = MagicMock()
    mgr._process = mock_proc
    mgr._started = True

    mgr.shutdown()

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once_with(timeout=10)
    assert mgr._process is None
    assert mgr._started is False


def test_router_manager_process_died() -> None:
    """If router process exits during health wait, raise IOError."""
    from scrivai.io.convert import _MineruRouterManager

    mock_process = MagicMock()
    mock_process.poll.return_value = 1
    mock_process.returncode = 1

    with (
        patch("shutil.which", return_value="/usr/bin/mineru-router"),
        patch("subprocess.Popen", return_value=mock_process),
        patch("atexit.register"),
    ):
        mgr = _MineruRouterManager()
        with pytest.raises(IOError, match="意外退出"):
            mgr.get_url()


# --- to_markdown routing tests (unchanged pattern) ---


def _patch_mineru_backend(mock_fn):
    """Patch _BACKENDS['mineru'] to use mock_fn instead of real _mineru_ocr."""
    return patch.dict("scrivai.io.convert._BACKENDS", {"mineru": mock_fn})


def test_to_markdown_routes_to_mineru(tmp_path: Path) -> None:
    """ocr_backend='mineru' routes to _mineru_ocr."""
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
    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 50)
    mock = MagicMock(return_value="sliced")

    with _patch_mineru_backend(mock):
        to_markdown(pdf, ocr_backend="mineru", start_page=5, end_page=15)

    _, kwargs = mock.call_args
    assert kwargs["start_page"] == 5
    assert kwargs["end_page"] == 15


def test_to_markdown_mineru_receives_url(tmp_path: Path) -> None:
    """mineru_url parameter is passed through to _mineru_ocr."""
    from scrivai.io import to_markdown

    pdf = _make_pdf(tmp_path, 5)
    mock = MagicMock(return_value="ok")

    with _patch_mineru_backend(mock):
        to_markdown(pdf, ocr_backend="mineru", mineru_url="http://custom:9000")

    _, kwargs = mock.call_args
    assert kwargs["mineru_url"] == "http://custom:9000"
