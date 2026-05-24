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

import base64  # noqa: F401 - reserved for the GLM backend added in Task 2.
import io
import json  # noqa: F401 - reserved for the GLM backend added in Task 2.
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

# --- MonkeyOCR defaults ---
_DEFAULT_OCR_URL = os.environ.get("SCRIVAI_OCR_BASE_URL", "http://100.81.95.44:7861")
_DEFAULT_UPLOAD_RATE = int(os.environ.get("SCRIVAI_OCR_UPLOAD_RATE", 500 * 1024))

# --- GLM-OCR defaults ---
_GLM_OCR_URL = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
_DEFAULT_GLM_API_KEY = os.environ.get("SCRIVAI_GLM_API_KEY", "")

# --- Backend registry ---
_DEFAULT_BACKEND = os.environ.get("SCRIVAI_OCR_BACKEND", "glm")

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


_BACKENDS: dict[str, Callable[..., str]] = {"monkey": _monkey_ocr}


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
        ocr_base_url: MonkeyOCR service URL override.
        upload_rate: MonkeyOCR max upload speed in bytes/second (0 = unlimited).
        timeout: Per-request HTTP timeout in seconds.
        fallback: Enable pandoc fallback when OCR is unreachable.
    Returns:
        Markdown text.
    Raises:
        ValueError: Unknown backend name or missing GLM API key.
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

    backend = ocr_backend or _DEFAULT_BACKEND
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown OCR backend: {backend!r} (available: {', '.join(sorted(_BACKENDS))})"
        )

    # Phase 1: build backend-specific kwargs
    backend_kwargs: dict[str, Any] = {}
    if backend == "monkey":
        backend_kwargs["base_url"] = ocr_base_url or _DEFAULT_OCR_URL
        backend_kwargs["upload_rate"] = (
            upload_rate if upload_rate is not None else _DEFAULT_UPLOAD_RATE
        )
    elif backend == "glm":
        key = glm_api_key or _DEFAULT_GLM_API_KEY
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
