"""Document format conversion — pandoc / LibreOffice / MonkeyOCR HTTP.

External dependencies:
- pandoc binary (docx → markdown)
- libreoffice/soffice binary (doc → docx)
- MonkeyOCR HTTP service Docker container (default http://100.81.95.44:7861)

All failures raise IOError with an explicit message; no silent fallback.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests


def docx_to_markdown(path: str | Path) -> str:
    """Convert a .docx file to Markdown (UTF-8) using pandoc.

    Args:
        path: Path to the .docx file.
    Returns:
        Markdown text.
    Raises:
        IOError: pandoc unavailable / file not found / conversion failed.
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"File not found: {src}")
    if shutil.which("pandoc") is None:
        raise IOError("pandoc binary not found (run `apt install pandoc` or conda install)")

    proc = subprocess.run(
        ["pandoc", str(src), "-t", "markdown"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise IOError(f"pandoc conversion failed ({src}): {proc.stderr.strip()}")
    return proc.stdout


def doc_to_markdown(path: str | Path) -> str:
    """Convert a .doc file to Markdown via LibreOffice headless (doc → docx) then docx_to_markdown.

    LibreOffice also accepts .docx input, so .docx files can also use this path (redundant but safe).
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"File not found: {src}")
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice is None:
        raise IOError("libreoffice/soffice binary not found")

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(out_dir),
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise IOError(f"LibreOffice docx conversion failed ({src}): {proc.stderr.strip()}")
        # Output filename = original stem + .docx
        converted = out_dir / f"{src.stem}.docx"
        if not converted.is_file():
            raise IOError(f"LibreOffice did not produce expected file: {converted}")
        return docx_to_markdown(converted)


def pdf_to_markdown(
    path: str | Path,
    *,
    base_url: str = "http://100.81.95.44:7861",
    timeout: int = 300,
) -> str:
    """Convert a PDF to Markdown using the MonkeyOCR HTTP service.

    Flow (see Reference/smart-construction-ai/crawler.py):
      1. POST {base_url}/parse to upload the PDF
      2. Read download_url from the response
      3. GET {download_url} to retrieve the ZIP
      4. Extract the .md file contents from the ZIP

    Args:
        path: Path to the .pdf file.
        base_url: MonkeyOCR service URL (hardcoded default; override as needed).
        timeout: Per-request HTTP timeout in seconds.
    Returns:
        Markdown text.
    Raises:
        IOError: Service unreachable / non-200 response / no .md file in ZIP.
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"File not found: {src}")

    base = base_url.rstrip("/")

    # MonkeyOCR is typically an intranet service; bypass system proxy.
    session = requests.Session()
    session.trust_env = False

    try:
        with src.open("rb") as f:
            files = {"file": (src.name, f, "application/pdf")}
            resp = session.post(f"{base}/parse", files=files, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise IOError(f"MonkeyOCR network request failed ({base}): {e}") from e

    if resp.status_code != 200:
        raise IOError(f"MonkeyOCR /parse returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise IOError(f"MonkeyOCR processing failed: {data.get('message')}")
    download_url = data.get("download_url")
    if not download_url:
        raise IOError(f"MonkeyOCR response missing download_url: {data}")

    full_url = f"{base}{download_url}" if download_url.startswith("/") else download_url

    try:
        zip_resp = session.get(full_url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise IOError(f"MonkeyOCR ZIP download failed ({full_url}): {e}") from e

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
