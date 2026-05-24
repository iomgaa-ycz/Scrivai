"""Pluggable document → Markdown conversion with multiple OCR backends.

Supported backends:
- monkey: Self-hosted MonkeyOCR Docker service
- glm: ZhipuAI GLM-OCR cloud API

External dependencies:
- libreoffice/soffice binary (doc/docx → PDF)
- pandoc binary (fallback: docx → markdown)

All failures raise IOError with an explicit message.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

logger = logging.getLogger(__name__)

# --- GLM-OCR fixed endpoint ---
_GLM_OCR_URL = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"

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


def _monkey_ocr(pdf_path: Path, *, base_url: str, timeout: int, upload_rate: int) -> str:
    """Send a PDF to self-hosted MonkeyOCR HTTP service and return Markdown.

    Args:
        pdf_path: Path to the PDF file.
        base_url: MonkeyOCR service URL.
        timeout: Per-request HTTP timeout in seconds.
        upload_rate: Max upload speed in bytes/second (0 = unlimited).
    Returns:
        Markdown text.
    Raises:
        IOError: Service unreachable / non-200 / no .md in ZIP.
        requests.exceptions.RequestException: Network-level failures.
    """
    base = base_url.rstrip("/")

    session = requests.Session()
    session.trust_env = False

    with pdf_path.open("rb") as f:
        encoder = MultipartEncoder(fields={"file": (pdf_path.name, f, "application/pdf")})

        bytes_sent = 0

        def _throttle_callback(monitor: MultipartEncoderMonitor) -> None:
            nonlocal bytes_sent
            if upload_rate <= 0:
                return
            delta = monitor.bytes_read - bytes_sent
            bytes_sent = monitor.bytes_read
            if delta > 0:
                time.sleep(delta / upload_rate)

        monitor = MultipartEncoderMonitor(encoder, _throttle_callback)
        resp = session.post(
            f"{base}/parse",
            data=monitor,
            headers={"Content-Type": monitor.content_type},
            timeout=timeout,
        )

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


_GLM_MAX_PAGES = 100
_GLM_MAX_FILE_BYTES = 50 * 1024 * 1024


def _glm_ocr_single(
    pdf_bytes: bytes,
    *,
    api_key: str,
    timeout: int,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
    """Call GLM-OCR API once for a single PDF payload.

    Args:
        pdf_bytes: Raw PDF bytes (must be ≤ 100 pages and ≤ 50 MB).
        api_key: ZhipuAI API key.
        timeout: HTTP timeout in seconds.
        start_page: API start_page_id (1-based, optional).
        end_page: API end_page_id (1-based, optional).
    Returns:
        Markdown text.
    Raises:
        IOError: API error or unexpected response.
    """
    b64_data = base64.b64encode(pdf_bytes).decode()

    body: dict[str, Any] = {
        "model": "glm-ocr",
        "file": f"data:application/pdf;base64,{b64_data}",
    }
    if start_page is not None:
        body["start_page_id"] = start_page
    if end_page is not None:
        body["end_page_id"] = end_page

    session = requests.Session()
    session.trust_env = False
    resp = session.post(
        _GLM_OCR_URL,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=timeout,
    )

    if resp.status_code != 200:
        raise IOError(f"GLM-OCR API returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if "error" in data:
        raise IOError(f"GLM-OCR API error: {data['error']}")

    md_results = data.get("md_results")
    if md_results is None:
        raise IOError(f"GLM-OCR response missing md_results: {list(data.keys())}")
    return md_results


def _glm_ocr(
    pdf_path: Path,
    *,
    api_key: str,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
    """Send a PDF to ZhipuAI GLM-OCR cloud API and return Markdown.

    Automatically splits PDFs that exceed GLM-OCR limits (100 pages / 50 MB)
    into chunks, processes each chunk, and concatenates the results.

    Args:
        pdf_path: Path to the PDF file.
        api_key: ZhipuAI API key.
        timeout: HTTP timeout in seconds.
        start_page: PDF start page (1-based, optional).
        end_page: PDF end page (1-based, optional).
    Returns:
        Markdown text.
    Raises:
        IOError: API error or unexpected response.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    # Phase 1: resolve user-specified page range (1-based → 0-based index)
    first_idx = (start_page - 1) if start_page is not None else 0
    last_idx = (end_page - 1) if end_page is not None else total_pages - 1
    first_idx = max(0, first_idx)
    last_idx = min(total_pages - 1, last_idx)
    selected_count = last_idx - first_idx + 1

    if selected_count <= 0:
        return ""

    # Phase 2: check if direct call is possible
    file_size = pdf_path.stat().st_size
    if selected_count <= _GLM_MAX_PAGES and file_size <= _GLM_MAX_FILE_BYTES:
        return _glm_ocr_single(
            pdf_path.read_bytes(),
            api_key=api_key,
            timeout=timeout,
            start_page=start_page,
            end_page=end_page,
        )

    # Phase 3: split into chunks and process each
    logger.info(
        "PDF 超出 GLM-OCR 限制 (%d 页 / %.1f MB)，自动分块处理",
        selected_count,
        file_size / 1024 / 1024,
    )

    chunks_md: list[str] = []
    chunk_start = first_idx
    while chunk_start <= last_idx:
        chunk_end = min(chunk_start + _GLM_MAX_PAGES - 1, last_idx)

        writer = PdfWriter()
        for page_idx in range(chunk_start, chunk_end + 1):
            writer.add_page(reader.pages[page_idx])

        buf = io.BytesIO()
        writer.write(buf)
        chunk_bytes = buf.getvalue()

        chunk_num = len(chunks_md) + 1
        chunk_pages = chunk_end - chunk_start + 1
        logger.info(
            "处理分块 %d: 页 %d-%d (%d 页, %.1f KB)",
            chunk_num,
            chunk_start + 1,
            chunk_end + 1,
            chunk_pages,
            len(chunk_bytes) / 1024,
        )

        md = _glm_ocr_single(chunk_bytes, api_key=api_key, timeout=timeout)
        chunks_md.append(md)

        chunk_start = chunk_end + 1

    return "\n\n".join(chunks_md)


_BACKENDS: dict[str, Callable[..., str]] = {"monkey": _monkey_ocr, "glm": _glm_ocr}


def to_markdown(
    path: str | Path,
    *,
    ocr_backend: str | None = None,
    # --- GLM-OCR ---
    glm_api_key: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    # --- MonkeyOCR ---
    ocr_base_url: str | None = None,
    upload_rate: int | None = None,
    # --- common ---
    timeout: int = 300,
    fallback: bool = True,
) -> str:
    """Convert a document to Markdown via pluggable OCR backend.

    Routing:
      .pdf         → OCR backend directly
      .doc / .docx → LibreOffice headless → PDF → OCR backend

    When fallback=True and OCR backend is unreachable:
      .docx → pandoc direct conversion
      .doc  → LibreOffice → docx → pandoc
      .pdf  → no fallback (raises)

    Args:
        path: Source document (.pdf / .doc / .docx).
        ocr_backend: Backend name ("monkey" or "glm"). Default from
            SCRIVAI_OCR_BACKEND env or "glm".
        glm_api_key: GLM-OCR API key override (default from SCRIVAI_GLM_API_KEY env).
        start_page: PDF start page (GLM-OCR only, 1-based).
        end_page: PDF end page (GLM-OCR only, 1-based).
        ocr_base_url: MonkeyOCR service URL (default from SCRIVAI_OCR_BASE_URL env;
            no built-in default — must be configured when using monkey backend).
        upload_rate: MonkeyOCR max upload speed in bytes/second (0 = unlimited).
        timeout: Per-request HTTP timeout in seconds.
        fallback: Enable pandoc fallback when OCR is unreachable.
    Returns:
        Markdown text.
    Raises:
        ValueError: Unknown backend, missing GLM API key, or missing MonkeyOCR URL.
        IOError: Unsupported format / conversion failure / service unreachable.
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"File not found: {src}")

    suffix = src.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise IOError(
            f"Unsupported format: {suffix} (supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))})"
        )

    backend = ocr_backend or os.environ.get("SCRIVAI_OCR_BACKEND", "glm")
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown OCR backend: {backend!r} (available: {', '.join(sorted(_BACKENDS))})"
        )

    # Phase 1: build backend-specific kwargs (env read deferred to call time)
    backend_kwargs: dict[str, Any] = {}
    if backend == "monkey":
        base_url = ocr_base_url or os.environ.get("SCRIVAI_OCR_BASE_URL", "")
        if not base_url:
            raise ValueError(
                "MonkeyOCR URL 未配置: 设置 SCRIVAI_OCR_BASE_URL env 或传入 ocr_base_url 参数"
            )
        backend_kwargs["base_url"] = base_url
        backend_kwargs["upload_rate"] = (
            upload_rate
            if upload_rate is not None
            else int(os.environ.get("SCRIVAI_OCR_UPLOAD_RATE", 500 * 1024))
        )
    elif backend == "glm":
        key = glm_api_key if glm_api_key is not None else os.environ.get("SCRIVAI_GLM_API_KEY", "")
        if not key:
            raise ValueError(
                "GLM API key 未配置: 设置 SCRIVAI_GLM_API_KEY env 或传入 glm_api_key 参数"
            )
        backend_kwargs["api_key"] = key
        if start_page is not None:
            backend_kwargs["start_page"] = start_page
        if end_page is not None:
            backend_kwargs["end_page"] = end_page

    ocr_fn = _BACKENDS[backend]

    # Phase 2: route by suffix
    def _call_ocr(pdf: Path) -> str:
        return ocr_fn(pdf, timeout=timeout, **backend_kwargs)

    if suffix == ".pdf":
        return _call_ocr(src)

    # Phase 3: DOC / DOCX → PDF → OCR (with optional fallback)
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        pdf_path = _to_pdf(src, target_dir=tmp_dir)

        try:
            return _call_ocr(pdf_path)
        except (requests.exceptions.RequestException, IOError) as ocr_err:
            is_network_error = isinstance(ocr_err, requests.exceptions.RequestException) or (
                isinstance(ocr_err, IOError)
                and any(
                    kw in str(ocr_err)
                    for kw in ("network", "unreachable", "timed out", "Connection")
                )
            )

            if not (fallback and is_network_error):
                raise

            logger.warning("OCR 后端 %s 不可达，降级到 pandoc 路径: %s", backend, ocr_err)

            if suffix == ".docx":
                return _pandoc_to_markdown(src)

            # .doc → LibreOffice → docx → pandoc
            docx_path = tmp_dir / f"{src.stem}.docx"
            soffice = shutil.which("libreoffice") or shutil.which("soffice")
            if soffice is None:
                raise IOError("libreoffice/soffice binary not found") from ocr_err

            proc = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(tmp_dir),
                    str(src),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise IOError(
                    f"LibreOffice docx fallback conversion failed ({src}): {proc.stderr.strip()}"
                ) from ocr_err
            if not docx_path.is_file():
                raise IOError(
                    f"LibreOffice did not produce expected file: {docx_path}"
                ) from ocr_err
            return _pandoc_to_markdown(docx_path)
