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
import time
import zipfile
from pathlib import Path

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

logger = logging.getLogger(__name__)

_DEFAULT_OCR_URL = os.environ.get("SCRIVAI_OCR_BASE_URL", "http://100.81.95.44:7861")
_DEFAULT_UPLOAD_RATE = int(os.environ.get("SCRIVAI_OCR_UPLOAD_RATE", 500 * 1024))

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


def _ocr_to_markdown(pdf_path: Path, *, base_url: str, timeout: int, upload_rate: int) -> str:
    """Send a PDF to MonkeyOCR HTTP service and return Markdown.

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


def to_markdown(
    path: str | Path,
    *,
    ocr_base_url: str | None = None,
    timeout: int = 300,
    fallback: bool = True,
    upload_rate: int | None = None,
) -> str:
    """Convert a document to Markdown.

    Routing:
      .pdf         → MonkeyOCR
      .doc / .docx → LibreOffice headless → PDF → MonkeyOCR

    When fallback=True and MonkeyOCR is unreachable:
      .docx → pandoc direct conversion
      .doc  → LibreOffice → docx → pandoc
      .pdf  → no fallback (raises)

    Config priority (both ocr_base_url and upload_rate):
      function param > environment variable > hardcoded default.

    Args:
        path: Path to the source document (.pdf / .doc / .docx).
        ocr_base_url: MonkeyOCR service URL override.
        timeout: Per-request HTTP timeout in seconds.
        fallback: Enable pandoc fallback for .doc/.docx when OCR is unreachable.
        upload_rate: Max upload speed in bytes/second (0 = unlimited).
            Default from SCRIVAI_OCR_UPLOAD_RATE env or 500 KB/s.
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
        raise IOError(
            f"Unsupported format: {suffix} (supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))})"
        )

    base_url = ocr_base_url or _DEFAULT_OCR_URL
    rate = upload_rate if upload_rate is not None else _DEFAULT_UPLOAD_RATE

    # --- PDF: direct OCR ---
    if suffix == ".pdf":
        return _ocr_to_markdown(src, base_url=base_url, timeout=timeout, upload_rate=rate)

    # --- DOC / DOCX: LibreOffice → PDF → OCR (with optional fallback) ---
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        pdf_path = _to_pdf(src, target_dir=tmp_dir)

        try:
            return _ocr_to_markdown(pdf_path, base_url=base_url, timeout=timeout, upload_rate=rate)
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

            logger.warning("MonkeyOCR 不可达，降级到 pandoc 路径: %s", ocr_err)

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
