"""Document → Markdown conversion.

Word files (.doc/.docx) use markitdown (mammoth) for direct local conversion.
PDF files use pluggable OCR backends:
- mineru: MinerU local pipeline (default)
- monkey: Self-hosted MonkeyOCR Docker service
- glm: ZhipuAI GLM-OCR cloud API

External dependencies:
- libreoffice/soffice binary (.doc → .docx conversion)
- markitdown[docx] (Word → Markdown)

All failures raise IOError with an explicit message.
"""

from __future__ import annotations

import atexit
import base64
import difflib
import io
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

logger = logging.getLogger(__name__)

# --- GLM-OCR fixed endpoint ---
_GLM_OCR_URL = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"

_SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx"}


def _to_docx(path: Path, *, target_dir: Path) -> Path:
    """Convert a .doc file to .docx via LibreOffice headless.

    Args:
        path: Source .doc document.
        target_dir: Directory to write the output .docx.
    Returns:
        Path to the generated .docx.
    Raises:
        IOError: LibreOffice unavailable or conversion failed.
    """
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice is None:
        raise OSError("libreoffice/soffice binary not found")

    proc = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(target_dir),
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise OSError(f"LibreOffice docx conversion failed ({path}): {proc.stderr.strip()}")

    converted = target_dir / f"{path.stem}.docx"
    if not converted.is_file():
        raise OSError(f"LibreOffice did not produce expected file: {converted}")
    return converted


def _markitdown_convert(docx_path: Path) -> str:
    """Convert a .docx to Markdown via markitdown (mammoth backend).

    Args:
        docx_path: Path to the .docx file.
    Returns:
        Markdown text.
    Raises:
        IOError: Conversion failed.
    """
    from markitdown import MarkItDown

    try:
        result = MarkItDown().convert(docx_path)
    except Exception as e:
        raise OSError(f"markitdown conversion failed ({docx_path}): {e}") from e

    md = result.text_content or ""
    logger.info("markitdown 完成, 输出 Markdown 共 %d 字符", len(md))
    return md


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
        raise OSError(f"MonkeyOCR /parse returned {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise OSError(f"MonkeyOCR processing failed: {data.get('message')}")
    download_url = data.get("download_url")
    if not download_url:
        raise OSError(f"MonkeyOCR response missing download_url: {data}")

    full_url = f"{base}{download_url}" if download_url.startswith("/") else download_url

    zip_resp = session.get(full_url, timeout=timeout)

    if zip_resp.status_code != 200:
        raise OSError(f"MonkeyOCR ZIP download returned {zip_resp.status_code}")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            md_files = [n for n in zf.namelist() if n.endswith(".md")]
            if not md_files:
                raise OSError("No .md file found in MonkeyOCR ZIP")
            return zf.read(md_files[0]).decode("utf-8")
    except zipfile.BadZipFile as e:
        raise OSError(f"MonkeyOCR did not return a valid ZIP: {e}") from e


_GLM_MAX_PAGES = 100
_GLM_MAX_FILE_BYTES = 50 * 1024 * 1024


def _normalize_line(line: str) -> str:
    """Strip whitespace for overlap comparison."""
    return line.strip()


def _find_overlap_boundary(prev_lines: list[str], next_lines: list[str]) -> tuple[int, int] | None:
    """Find cut points in overlapping chunks via normalized difflib matching.

    Searches for the longest common line sequence between the second half
    of *prev_lines* and the first half of *next_lines*. Returns
    (prev_cut, next_cut) so that prev_lines[:prev_cut] + next_lines[next_cut:]
    produces a deduplicated merge. Returns None when no significant
    match is found (< 3 common lines).

    Args:
        prev_lines: Lines from the preceding chunk.
        next_lines: Lines from the following chunk.
    Returns:
        Tuple of cut indices or None.
    """
    prev_norm = [_normalize_line(line) for line in prev_lines]
    next_norm = [_normalize_line(line) for line in next_lines]

    prev_start = len(prev_norm) // 2
    next_end = max((len(next_norm) + 1) // 2, 1)

    sm = difflib.SequenceMatcher(None, prev_norm, next_norm, autojunk=False)
    match = sm.find_longest_match(prev_start, len(prev_norm), 0, next_end)

    if match.size < 3:
        return None

    mid = match.size // 2
    return (match.a + mid, match.b + mid)


def _merge_two(prev_md: str, next_md: str, overlap_pages: int, chunk_pages: int) -> str:
    """Merge two overlapping Markdown chunks with three-tier dedup.

    Tier 1: Normalized difflib matching (~90%+ cases).
    Tier 2: Ratio-based estimation with paragraph boundary (~9%).
    Tier 3: Direct concatenation (defensive fallback, <1%).

    Args:
        prev_md: Markdown from the preceding chunk.
        next_md: Markdown from the following chunk.
        overlap_pages: Number of overlapping pages between chunks.
        chunk_pages: Total pages per chunk.
    Returns:
        Merged Markdown string.
    """
    prev_lines = prev_md.splitlines()
    next_lines = next_md.splitlines()

    # Tier 1: normalized difflib
    boundary = _find_overlap_boundary(prev_lines, next_lines)
    if boundary is not None:
        prev_cut, next_cut = boundary
        return "\n".join(prev_lines[:prev_cut]) + "\n\n" + "\n".join(next_lines[next_cut:])

    # Tier 2: ratio estimation + paragraph boundary
    if chunk_pages > 0:
        overlap_ratio = overlap_pages / chunk_pages
        est_cut = int(len(prev_md) * (1 - overlap_ratio))

        search_start = max(0, est_cut - 500)
        search_end = min(len(prev_md), est_cut + 500)
        best_pos = est_cut
        best_dist = float("inf")

        for i in range(search_start, search_end - 1):
            if prev_md[i] == "\n" and prev_md[i + 1] == "\n":
                dist = abs(i - est_cut)
                if dist < best_dist:
                    best_pos = i
                    best_dist = dist

        next_trim = int(len(next_md) * overlap_ratio)
        # Snap to next newline to avoid cutting mid-word
        nl_pos = next_md.find("\n", next_trim)
        if nl_pos != -1:
            next_trim = nl_pos + 1
        return prev_md[:best_pos].rstrip() + "\n\n" + next_md[next_trim:]

    # Tier 3: direct concatenation
    return prev_md + "\n\n" + next_md


def _merge_chunks(chunks_md: list[str], overlap_pages: int, chunk_pages: int) -> str:
    """Sequentially merge multiple overlapping Markdown chunks.

    Args:
        chunks_md: Ordered list of Markdown strings from each chunk.
        overlap_pages: Number of overlapping pages between adjacent chunks.
        chunk_pages: Total pages per chunk.
    Returns:
        Single merged Markdown string.
    """
    if not chunks_md:
        return ""
    if len(chunks_md) == 1:
        return chunks_md[0]

    result = chunks_md[0]
    for next_md in chunks_md[1:]:
        result = _merge_two(result, next_md, overlap_pages, chunk_pages)
    return result


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
        raise OSError(f"GLM-OCR API returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if "error" in data:
        raise OSError(f"GLM-OCR API error: {data['error']}")

    md_results = data.get("md_results")
    if md_results is None:
        raise OSError(f"GLM-OCR response missing md_results: {list(data.keys())}")
    return md_results


_CHUNK_RETRIES = 2
_GLM_MAX_WORKERS = 3


def _glm_ocr_chunked(
    pdf_path: Path,
    *,
    api_key: str,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
    chunk_pages: int = 30,
    overlap_pages: int = 2,
    max_workers: int = 12,
) -> str:
    """Split a PDF into overlapping chunks, OCR them in parallel, and merge.

    Small PDFs (≤ chunk_pages) degrade to a single chunk with no overhead.

    Args:
        pdf_path: Path to the PDF file.
        api_key: ZhipuAI API key.
        timeout: HTTP timeout in seconds per chunk.
        start_page: User-facing start page (1-based, optional).
        end_page: User-facing end page (1-based, optional).
        chunk_pages: Pages per chunk.
        overlap_pages: Overlapping pages between adjacent chunks.
        max_workers: Max parallel threads.
    Returns:
        Merged Markdown text.
    Raises:
        IOError: Any chunk fails after retries.
    """
    if overlap_pages >= chunk_pages:
        raise ValueError(f"overlap_pages ({overlap_pages}) must be < chunk_pages ({chunk_pages})")

    if max_workers > _GLM_MAX_WORKERS:
        logger.warning(
            "GLM-OCR max_workers %d 超过限制, 已降至 %d",
            max_workers,
            _GLM_MAX_WORKERS,
        )
        max_workers = _GLM_MAX_WORKERS

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)

    first_idx = (start_page - 1) if start_page is not None else 0
    last_idx = (end_page - 1) if end_page is not None else total_pages - 1
    first_idx = max(0, first_idx)
    last_idx = min(total_pages - 1, last_idx)
    selected_count = last_idx - first_idx + 1

    if selected_count <= 0:
        return ""

    # Phase 1: build chunk ranges with overlap
    stride = chunk_pages - overlap_pages
    ranges: list[tuple[int, int]] = []
    chunk_start = first_idx
    while chunk_start <= last_idx:
        chunk_end = min(chunk_start + chunk_pages - 1, last_idx)
        ranges.append((chunk_start, chunk_end))
        chunk_start += stride
        if chunk_start <= last_idx and (last_idx - chunk_start + 1) <= overlap_pages:
            ranges[-1] = (ranges[-1][0], last_idx)
            break

    logger.info(
        "PDF 分块: %d 页 → %d chunks (chunk_pages=%d, overlap=%d, workers=%d)",
        selected_count,
        len(ranges),
        chunk_pages,
        overlap_pages,
        max_workers,
    )

    # Pre-build chunk bytes on main thread (pypdf PdfReader is not thread-safe)
    chunk_bytes_list: list[bytes] = []
    for start, end in ranges:
        writer = PdfWriter()
        for page_idx in range(start, end + 1):
            writer.add_page(reader.pages[page_idx])
        buf = io.BytesIO()
        writer.write(buf)
        chunk_bytes_list.append(buf.getvalue())

    def _process_chunk(idx: int, start: int, end: int) -> tuple[int, str]:
        chunk_bytes = chunk_bytes_list[idx]
        pages_in_chunk = end - start + 1
        logger.info(
            "Chunk %d/%d (页 %d-%d, %d 页, %.1f KB) 开始处理",
            idx + 1,
            len(ranges),
            start + 1,
            end + 1,
            pages_in_chunk,
            len(chunk_bytes) / 1024,
        )

        last_err: Exception | None = None
        for attempt in range(1 + _CHUNK_RETRIES):
            try:
                t0 = time.time()
                md = _glm_ocr_single(chunk_bytes, api_key=api_key, timeout=timeout)
                logger.info("Chunk %d/%d 完成 (%.1fs)", idx + 1, len(ranges), time.time() - t0)
                return (idx, md)
            except (OSError, requests.exceptions.RequestException) as e:
                last_err = e
                if attempt < _CHUNK_RETRIES:
                    wait = 2**attempt
                    logger.warning(
                        "Chunk %d/%d 失败, 重试 %d/%d: %s",
                        idx + 1,
                        len(ranges),
                        attempt + 1,
                        _CHUNK_RETRIES,
                        e,
                    )
                    time.sleep(wait)

        raise OSError(
            f"Chunk {idx + 1} (页 {start + 1}-{end + 1}) 重试 {_CHUNK_RETRIES} 次后仍失败"
        ) from last_err

    # Phase 2: parallel execution
    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(ranges))) as executor:
        futures = {executor.submit(_process_chunk, i, s, e): i for i, (s, e) in enumerate(ranges)}
        try:
            for future in as_completed(futures):
                idx, md = future.result()
                results[idx] = md
        except Exception:
            for f in futures:
                f.cancel()
            raise

    # Phase 3: merge in order
    chunks_md = [results[i] for i in range(len(ranges))]

    logger.info("全部 %d chunks 完成, 开始合并", len(ranges))

    if len(chunks_md) == 1:
        merged = chunks_md[0]
    else:
        merged = _merge_chunks(chunks_md, overlap_pages, chunk_pages)

    logger.info("合并完成, 输出 Markdown 共 %d 字符", len(merged))
    return merged


def _glm_ocr(
    pdf_path: Path,
    *,
    api_key: str,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
    chunk_pages: int = 30,
    overlap_pages: int = 2,
    max_workers: int = 12,
) -> str:
    """Send a PDF to ZhipuAI GLM-OCR cloud API and return Markdown.

    Splits the PDF into overlapping chunks, processes them in parallel
    via ThreadPoolExecutor, and merges with three-tier dedup. Small PDFs
    (≤ chunk_pages) degrade to a single chunk with no overhead.

    Args:
        pdf_path: Path to the PDF file.
        api_key: ZhipuAI API key.
        timeout: HTTP timeout in seconds.
        start_page: PDF start page (1-based, optional).
        end_page: PDF end page (1-based, optional).
        chunk_pages: Pages per chunk (default 30).
        overlap_pages: Overlapping pages between adjacent chunks (default 2).
        max_workers: Max parallel threads (default 12).
    Returns:
        Markdown text.
    Raises:
        IOError: API error or chunk failure after retries.
    """
    return _glm_ocr_chunked(
        pdf_path,
        api_key=api_key,
        timeout=timeout,
        start_page=start_page,
        end_page=end_page,
        chunk_pages=chunk_pages,
        overlap_pages=overlap_pages,
        max_workers=max_workers,
    )


class _MineruRouterManager:
    """Manage a mineru-router subprocess lifecycle.

    Auto-starts the router on first get_url() call. Registers atexit
    cleanup to terminate the subprocess on program exit.
    """

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._url: str = ""
        self._started = False

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def get_url(self) -> str:
        if self._started:
            return self._url
        with self._lock:
            if self._started:
                return self._url
            self._url = self._auto_start()
            self._started = True
            return self._url

    def _auto_start(self) -> str:
        cmd = shutil.which("mineru-router")
        if cmd is None:
            # Fallback: look in the same bin dir as the running Python interpreter
            import sys

            candidate = Path(sys.executable).parent / "mineru-router"
            if candidate.is_file():
                cmd = str(candidate)
            else:
                raise OSError("mineru-router 未找到，请运行: pip install 'mineru[all]'")

        port = self._find_free_port()
        self._process = subprocess.Popen(
            [cmd, "--host", "127.0.0.1", "--port", str(port), "--local-gpus", "auto"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        atexit.register(self.shutdown)

        base = f"http://127.0.0.1:{port}"
        self._wait_healthy(base, timeout=300)
        logger.info("mineru-router 已启动: %s (pid=%d)", base, self._process.pid)
        return base

    def _wait_healthy(self, base: str, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        interval = 1.0
        session = requests.Session()
        session.trust_env = False
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                raise OSError(f"mineru-router 进程意外退出 (returncode={self._process.returncode})")
            try:
                r = session.get(f"{base}/health", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "healthy":
                        return
            except requests.exceptions.RequestException:
                pass
            time.sleep(interval)
            interval = min(interval * 1.5, 10.0)
        raise OSError(f"mineru-router 在 {timeout}s 内未就绪")

    def shutdown(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=10)
        except Exception:
            self._process.kill()
        finally:
            self._process = None
            self._started = False


_router_manager: _MineruRouterManager | None = None


def _mineru_ocr(
    pdf_path: Path,
    *,
    timeout: int = 3600,
    start_page: int | None = None,
    end_page: int | None = None,
    mineru_url: str | None = None,
) -> str:
    """Convert a PDF to Markdown via MinerU HTTP API (mineru-router).

    Calls a mineru-router process via POST /file_parse. The router is
    auto-started on first call if no URL is provided.

    Args:
        pdf_path: Path to the PDF file.
        timeout: HTTP timeout in seconds.
        start_page: PDF start page (1-based, optional).
        end_page: PDF end page (1-based, optional).
        mineru_url: Explicit mineru-router URL (default from
            SCRIVAI_MINERU_URL env, or auto-start).
    Returns:
        Markdown text.
    Raises:
        IOError: Router unavailable or parse failure.
    """
    if start_page is not None and end_page is not None and start_page > end_page:
        return ""

    # Phase 1: resolve router URL
    url = mineru_url or os.environ.get("SCRIVAI_MINERU_URL", "")
    if url:
        base = url.rstrip("/")
    else:
        global _router_manager
        if _router_manager is None:
            _router_manager = _MineruRouterManager()
        base = _router_manager.get_url()

    # Phase 2: POST /file_parse with multipart/form-data
    session = requests.Session()
    session.trust_env = False

    start_id = str((start_page - 1) if start_page is not None else 0)
    end_id = str((end_page - 1) if end_page is not None else 99999)

    logger.info("MinerU (HTTP) 开始解析: %s", pdf_path.name)

    with pdf_path.open("rb") as f:
        encoder = MultipartEncoder(
            fields={
                "files": (pdf_path.name, f, "application/pdf"),
                "backend": "pipeline",
                "parse_method": "auto",
                "return_md": "true",
                "start_page_id": start_id,
                "end_page_id": end_id,
            }
        )
        resp = session.post(
            f"{base}/file_parse",
            data=encoder,
            headers={"Content-Type": encoder.content_type},
            timeout=timeout,
        )

    # Phase 3: parse response (200=completed, 409=failed with detail JSON)
    if resp.status_code not in (200, 409):
        raise OSError(f"mineru-router /file_parse returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if data.get("status") != "completed":
        err = data.get("error", data.get("status", "unknown"))
        raise OSError(f"mineru-router 任务失败: {err}")

    results = data.get("results", {})
    stem = pdf_path.stem
    entry = results.get(stem)
    if entry is None and results:
        entry = next(iter(results.values()))
    if entry is None:
        raise OSError(f"mineru-router 响应无结果: {list(data.keys())}")

    md = entry.get("md_content", "")
    logger.info("MinerU (HTTP) 完成, 输出 Markdown 共 %d 字符", len(md))
    return md


_BACKENDS: dict[str, Callable[..., str]] = {
    "monkey": _monkey_ocr,
    "glm": _glm_ocr,
    "mineru": _mineru_ocr,
}


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
    # --- MinerU ---
    mineru_url: str | None = None,
    # --- common ---
    timeout: int = 300,
    fallback: bool = True,
    # --- chunking (GLM only) ---
    chunk_pages: int = 30,
    overlap_pages: int = 2,
    max_workers: int = 12,
) -> str:
    """Convert a document to Markdown.

    Routing:
      .pdf         → OCR backend (mineru / glm / monkey)
      .docx        → markitdown (local, no OCR)
      .doc         → LibreOffice → .docx → markitdown

    Args:
        path: Source document (.pdf / .doc / .docx).
        ocr_backend: OCR backend for PDF files ("mineru", "monkey", or "glm").
            Default from SCRIVAI_OCR_BACKEND env or "mineru".
        glm_api_key: GLM-OCR API key override (default from SCRIVAI_GLM_API_KEY env).
        start_page: PDF start page (GLM/MinerU, 1-based).
        end_page: PDF end page (GLM/MinerU, 1-based).
        ocr_base_url: MonkeyOCR service URL (default from SCRIVAI_OCR_BASE_URL env).
        upload_rate: MonkeyOCR max upload speed in bytes/second (0 = unlimited).
        mineru_url: MinerU router URL (default from SCRIVAI_MINERU_URL env;
            leave empty to auto-start a local mineru-router).
        timeout: Per-request HTTP timeout in seconds.
        fallback: Unused (kept for API compatibility).
        chunk_pages: Pages per chunk for GLM-OCR parallel processing (default 30).
        overlap_pages: Overlapping pages between chunks (default 2).
        max_workers: Max parallel threads for GLM-OCR (default 12).
    Returns:
        Markdown text.
    Raises:
        ValueError: Unknown backend, missing GLM API key, or missing MonkeyOCR URL.
        IOError: Unsupported format / conversion failure / service unreachable.
    """
    src = Path(path)
    if not src.is_file():
        raise OSError(f"File not found: {src}")

    suffix = src.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise OSError(
            f"Unsupported format: {suffix} (supported: {', '.join(sorted(_SUPPORTED_SUFFIXES))})"
        )

    # Phase 1: Word files → markitdown (local, no OCR)
    if suffix == ".docx":
        return _markitdown_convert(src)

    if suffix == ".doc":
        with tempfile.TemporaryDirectory() as td:
            docx_path = _to_docx(src, target_dir=Path(td))
            return _markitdown_convert(docx_path)

    # Phase 2: PDF → OCR backend
    backend = ocr_backend or os.environ.get("SCRIVAI_OCR_BACKEND", "mineru")
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown OCR backend: {backend!r} (available: {', '.join(sorted(_BACKENDS))})"
        )

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
        backend_kwargs["chunk_pages"] = chunk_pages
        backend_kwargs["overlap_pages"] = overlap_pages
        backend_kwargs["max_workers"] = max_workers
    elif backend == "mineru":
        if start_page is not None:
            backend_kwargs["start_page"] = start_page
        if end_page is not None:
            backend_kwargs["end_page"] = end_page
        if mineru_url is not None:
            backend_kwargs["mineru_url"] = mineru_url

    ocr_fn = _BACKENDS[backend]
    return ocr_fn(src, timeout=timeout, **backend_kwargs)
