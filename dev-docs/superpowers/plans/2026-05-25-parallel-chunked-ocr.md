# GLM OCR 并行分块处理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GLM OCR 大文件串行处理改为带页面重叠的并行分块处理，大幅缩短 300+ 页文档的转换时间。

**Architecture:** 统一所有 PDF 走 `_glm_ocr_chunked()` 分块路径（小文件自动退化为单 chunk）。分块带 2 页重叠，`ThreadPoolExecutor` 并行调用 `_glm_ocr_single()`，三级去重合并（difflib 归一化 → 比例估算 → 直接拼接）。

**Tech Stack:** Python 3.11, pypdf, difflib, concurrent.futures.ThreadPoolExecutor, requests

**Design Spec:** `dev-docs/superpowers/specs/2026-05-25-parallel-chunked-ocr-design.md`

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `scrivai/io/convert.py` | [MODIFY] | 新增 merge 工具函数 + `_glm_ocr_chunked` + 改写 `_glm_ocr` 和 `to_markdown` 签名 |
| `scrivai/cli/io_cmd.py` | [MODIFY] | 新增 `--chunk-pages` / `--overlap-pages` / `--max-workers` CLI 参数 |
| `tests/unit/test_chunk_merge.py` | [CREATE] | merge 纯函数单元测试 |
| `tests/unit/test_glm_chunked.py` | [CREATE] | `_glm_ocr_chunked` 并行逻辑测试（mock `_glm_ocr_single`） |

---

### Task 1: Merge 工具函数 — 测试

**Files:**
- Create: `tests/unit/test_chunk_merge.py`

- [ ] **Step 1: 编写 merge 工具函数的全部单元测试**

```python
"""Unit tests for chunk merge utilities in scrivai.io.convert."""

from __future__ import annotations

import pytest


def test_find_overlap_boundary_exact_match():
    """重叠区域有完全匹配的行 → 返回中点切割位置。"""
    from scrivai.io.convert import _find_overlap_boundary

    # 模拟 chunk1 尾部和 chunk2 头部有 6 行完全重叠
    prev_lines = [
        "page 1 content line 1",
        "page 1 content line 2",
        "page 2 content line 1",
        "page 2 content line 2",
        # overlap starts here
        "overlap line 1",
        "overlap line 2",
        "overlap line 3",
        "overlap line 4",
        "overlap line 5",
        "overlap line 6",
    ]
    next_lines = [
        "overlap line 1",
        "overlap line 2",
        "overlap line 3",
        "overlap line 4",
        "overlap line 5",
        "overlap line 6",
        # new content
        "page 5 content line 1",
        "page 5 content line 2",
    ]

    result = _find_overlap_boundary(prev_lines, next_lines)
    assert result is not None
    prev_cut, next_cut = result
    # 6 行匹配，中点 = 3，所以 prev 取前 4+3=7 行，next 从第 3 行开始
    assert 0 < prev_cut <= len(prev_lines)
    assert 0 <= next_cut < len(next_lines)
    # 关键：切割后不丢内容
    merged = prev_lines[:prev_cut] + next_lines[next_cut:]
    assert "page 1 content line 1" in merged
    assert "page 5 content line 2" in merged


def test_find_overlap_boundary_whitespace_tolerance():
    """重叠行有前后空白差异 → 归一化后仍能匹配。"""
    from scrivai.io.convert import _find_overlap_boundary

    prev_lines = [
        "line A",
        "line B",
        "  overlap X  ",
        "  overlap Y  ",
        "  overlap Z  ",
    ]
    next_lines = [
        "overlap X",
        "overlap Y",
        "overlap Z",
        "line C",
        "line D",
    ]

    result = _find_overlap_boundary(prev_lines, next_lines)
    assert result is not None


def test_find_overlap_boundary_no_match():
    """完全不同的内容 → 返回 None。"""
    from scrivai.io.convert import _find_overlap_boundary

    prev_lines = ["aaa", "bbb", "ccc", "ddd"]
    next_lines = ["xxx", "yyy", "zzz", "www"]

    result = _find_overlap_boundary(prev_lines, next_lines)
    assert result is None


def test_merge_two_difflib_path():
    """两个有重叠内容的 chunk → 用 difflib 去重合并。"""
    from scrivai.io.convert import _merge_two

    shared = "shared line 1\nshared line 2\nshared line 3\nshared line 4\nshared line 5"
    prev_md = f"prev unique content A\nprev unique content B\n{shared}"
    next_md = f"{shared}\nnext unique content C\nnext unique content D"

    merged = _merge_two(prev_md, next_md, overlap_pages=2, chunk_pages=30)

    assert "prev unique content A" in merged
    assert "next unique content D" in merged
    # 重叠内容不应重复出现
    assert merged.count("shared line 3") == 1


def test_merge_two_ratio_fallback():
    """无匹配内容 → 走比例估算路径，不重复。"""
    from scrivai.io.convert import _merge_two

    prev_md = "A content\n\n" * 28 + "overlap zone\n\n" * 2
    next_md = "different overlap\n\n" * 2 + "B content\n\n" * 28

    merged = _merge_two(prev_md, next_md, overlap_pages=2, chunk_pages=30)

    assert "A content" in merged
    assert "B content" in merged


def test_merge_chunks_single():
    """单个 chunk → 直接返回，不调合并。"""
    from scrivai.io.convert import _merge_chunks

    result = _merge_chunks(["only chunk content"], overlap_pages=2, chunk_pages=30)
    assert result == "only chunk content"


def test_merge_chunks_empty():
    """空列表 → 返回空字符串。"""
    from scrivai.io.convert import _merge_chunks

    result = _merge_chunks([], overlap_pages=2, chunk_pages=30)
    assert result == ""


def test_merge_chunks_multi():
    """3 个有重叠的 chunks → 依次合并，所有独有内容保留。"""
    from scrivai.io.convert import _merge_chunks

    shared_ab = "\n".join([f"shared_ab_{i}" for i in range(6)])
    shared_bc = "\n".join([f"shared_bc_{i}" for i in range(6)])

    chunk_a = "unique_a_1\nunique_a_2\n" + shared_ab
    chunk_b = shared_ab + "\nunique_b_1\nunique_b_2\n" + shared_bc
    chunk_c = shared_bc + "\nunique_c_1\nunique_c_2"

    merged = _merge_chunks([chunk_a, chunk_b, chunk_c], overlap_pages=2, chunk_pages=30)

    assert "unique_a_1" in merged
    assert "unique_b_1" in merged
    assert "unique_c_2" in merged
```

- [ ] **Step 2: 运行测试，确认全部失败（函数不存在）**

Run: `conda run -n scrivai pytest tests/unit/test_chunk_merge.py -v 2>&1 | head -40`
Expected: ERRORS — `ImportError: cannot import name '_find_overlap_boundary'`

- [ ] **Step 3: 提交测试文件**

```bash
git add tests/unit/test_chunk_merge.py
git commit -m "test: add unit tests for chunk merge utilities"
```

---

### Task 2: Merge 工具函数 — 实现

**Files:**
- Modify: `scrivai/io/convert.py` (在 `_glm_ocr_single` 函数之前插入，约 line 170 附近)

- [ ] **Step 1: 在 `convert.py` 顶部导入 `difflib`**

在 `import base64` 下方添加：

```python
import difflib
```

（`difflib` 是标准库，按导入顺序放在 `base64` 之后。）

- [ ] **Step 2: 在 `_GLM_MAX_FILE_BYTES` 定义之后、`_glm_ocr_single` 之前，插入 merge 工具函数**

在 `scrivai/io/convert.py` 的 `_GLM_MAX_FILE_BYTES = 50 * 1024 * 1024` 行之后插入：

```python


def _normalize_line(line: str) -> str:
    """Strip whitespace for overlap comparison."""
    return line.strip()


def _find_overlap_boundary(
    prev_lines: list[str], next_lines: list[str]
) -> tuple[int, int] | None:
    """Find cut points in overlapping chunks via normalized difflib matching.

    Searches for the longest common line sequence between the second half
    of *prev_lines* and the first half of *next_lines*. Returns
    ``(prev_cut, next_cut)`` so that ``prev_lines[:prev_cut] + next_lines[next_cut:]``
    produces a deduplicated merge. Returns ``None`` when no significant
    match is found (< 3 common lines).

    Args:
        prev_lines: Lines from the preceding chunk.
        next_lines: Lines from the following chunk.
    Returns:
        Tuple of cut indices or None.
    """
    prev_norm = [_normalize_line(l) for l in prev_lines]
    next_norm = [_normalize_line(l) for l in next_lines]

    prev_start = len(prev_norm) // 2
    next_end = max(len(next_norm) // 2, 1)

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
        best_dist = abs(0)

        for i in range(search_start, search_end - 1):
            if prev_md[i] == "\n" and prev_md[i + 1] == "\n":
                dist = abs(i - est_cut)
                if best_dist == 0 or dist < best_dist:
                    best_pos = i
                    best_dist = dist

        return prev_md[:best_pos].rstrip() + "\n\n" + next_md

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
```

- [ ] **Step 3: 运行测试，确认全部通过**

Run: `conda run -n scrivai pytest tests/unit/test_chunk_merge.py -v`
Expected: 8 passed

- [ ] **Step 4: 提交**

```bash
git add scrivai/io/convert.py
git commit -m "feat(io): add three-tier chunk merge utilities for overlap dedup"
```

---

### Task 3: `_glm_ocr_chunked` 并行分块函数 — 测试

**Files:**
- Create: `tests/unit/test_glm_chunked.py`

- [ ] **Step 1: 编写 `_glm_ocr_chunked` 的单元测试（mock `_glm_ocr_single`）**

```python
"""Unit tests for _glm_ocr_chunked parallel logic (mocked OCR calls)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_pdf(tmp_path: Path, num_pages: int) -> Path:
    """Create a minimal multi-page PDF for testing."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for i in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / f"test_{num_pages}p.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def test_chunked_single_chunk(tmp_path: Path):
    """≤ chunk_pages 的 PDF → 退化为 1 个 chunk，无重叠。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    with patch("scrivai.io.convert._glm_ocr_single", return_value="page content") as mock:
        result = _glm_ocr_chunked(
            pdf, api_key="test", timeout=10, chunk_pages=30, overlap_pages=2, max_workers=2,
        )

    assert mock.call_count == 1
    assert result == "page content"


def test_chunked_multi_chunks(tmp_path: Path):
    """> chunk_pages 的 PDF → 分成多个 chunk 并行处理。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 70)
    call_log: list[int] = []

    def _fake_single(pdf_bytes, *, api_key, timeout):
        from pypdf import PdfReader
        import io as _io

        reader = PdfReader(_io.BytesIO(pdf_bytes))
        n = len(reader.pages)
        call_log.append(n)
        return f"chunk with {n} pages"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_fake_single):
        result = _glm_ocr_chunked(
            pdf, api_key="test", timeout=10, chunk_pages=30, overlap_pages=2, max_workers=4,
        )

    # 70 pages, stride=28: chunk0=p0-29(30p), chunk1=p28-57(30p), chunk2=p56-69(14p) → 3 chunks
    assert len(call_log) == 3
    assert "chunk with" in result


def test_chunked_retries_on_failure(tmp_path: Path):
    """单 chunk 失败重试后成功 → 整体成功。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)
    attempt = {"count": 0}

    def _fail_then_succeed(pdf_bytes, *, api_key, timeout):
        attempt["count"] += 1
        if attempt["count"] <= 2:
            raise IOError("transient failure")
        return "recovered content"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_fail_then_succeed):
        with patch("scrivai.io.convert.time") as mock_time:
            mock_time.time.return_value = 0.0
            mock_time.sleep = lambda _: None
            result = _glm_ocr_chunked(
                pdf, api_key="test", timeout=10, chunk_pages=30, overlap_pages=2, max_workers=1,
            )

    assert result == "recovered content"
    assert attempt["count"] == 3  # 1 initial + 2 retries


def test_chunked_all_retries_exhausted(tmp_path: Path):
    """所有重试用尽 → 抛出 IOError。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    def _always_fail(pdf_bytes, *, api_key, timeout):
        raise IOError("persistent failure")

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_always_fail):
        with patch("scrivai.io.convert.time") as mock_time:
            mock_time.time.return_value = 0.0
            mock_time.sleep = lambda _: None
            with pytest.raises(IOError, match="重试"):
                _glm_ocr_chunked(
                    pdf, api_key="test", timeout=10, chunk_pages=30, overlap_pages=2, max_workers=1,
                )


def test_chunked_start_end_page(tmp_path: Path):
    """指定 start_page/end_page → 只处理指定范围。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 100)
    pages_seen: list[int] = []

    def _count_pages(pdf_bytes, *, api_key, timeout):
        from pypdf import PdfReader
        import io as _io

        reader = PdfReader(_io.BytesIO(pdf_bytes))
        pages_seen.append(len(reader.pages))
        return "ok"

    with patch("scrivai.io.convert._glm_ocr_single", side_effect=_count_pages):
        _glm_ocr_chunked(
            pdf, api_key="test", timeout=10,
            start_page=10, end_page=50,  # 41 pages
            chunk_pages=30, overlap_pages=2, max_workers=2,
        )

    total_pages_processed = sum(pages_seen)
    # 41 pages, stride=28: chunk0=30p, chunk1=13p + overlap → ~2 chunks
    assert len(pages_seen) == 2
    assert total_pages_processed <= 41 + 2  # at most 2 overlap pages


def test_chunked_empty_range(tmp_path: Path):
    """start_page > end_page → 返回空字符串。"""
    from scrivai.io.convert import _glm_ocr_chunked

    pdf = _make_pdf(tmp_path, 10)

    result = _glm_ocr_chunked(
        pdf, api_key="test", timeout=10,
        start_page=5, end_page=3,
        chunk_pages=30, overlap_pages=2, max_workers=1,
    )

    assert result == ""
```

- [ ] **Step 2: 运行测试，确认全部失败（函数不存在）**

Run: `conda run -n scrivai pytest tests/unit/test_glm_chunked.py -v 2>&1 | head -30`
Expected: ERRORS — `ImportError: cannot import name '_glm_ocr_chunked'`

- [ ] **Step 3: 提交测试文件**

```bash
git add tests/unit/test_glm_chunked.py
git commit -m "test: add unit tests for _glm_ocr_chunked parallel logic"
```

---

### Task 4: `_glm_ocr_chunked` — 实现

**Files:**
- Modify: `scrivai/io/convert.py` (在 `_merge_chunks` 之后、`_glm_ocr` 之前插入)

- [ ] **Step 1: 在 `_glm_ocr_single` 函数之后、现有 `_glm_ocr` 函数之前，插入 `_glm_ocr_chunked`**

在 `_glm_ocr_single` 函数的 `return md_results` 之后（当前约 line 225），插入：

```python


_CHUNK_RETRIES = 2


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

    def _make_chunk_bytes(start: int, end: int) -> bytes:
        writer = PdfWriter()
        for page_idx in range(start, end + 1):
            writer.add_page(reader.pages[page_idx])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def _process_chunk(idx: int, start: int, end: int) -> tuple[int, str]:
        chunk_bytes = _make_chunk_bytes(start, end)
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
                logger.info(
                    "Chunk %d/%d 完成 (%.1fs)", idx + 1, len(ranges), time.time() - t0
                )
                return (idx, md)
            except (IOError, requests.exceptions.RequestException) as e:
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

        raise IOError(
            f"Chunk {idx + 1} (页 {start + 1}-{end + 1}) "
            f"重试 {_CHUNK_RETRIES} 次后仍失败"
        ) from last_err

    # Phase 2: parallel execution
    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(ranges))) as executor:
        futures = {
            executor.submit(_process_chunk, i, s, e): i for i, (s, e) in enumerate(ranges)
        }
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
```

- [ ] **Step 2: 运行 chunked 测试**

Run: `conda run -n scrivai pytest tests/unit/test_glm_chunked.py -v`
Expected: 6 passed

- [ ] **Step 3: 运行 merge 测试确认无回归**

Run: `conda run -n scrivai pytest tests/unit/test_chunk_merge.py -v`
Expected: 8 passed

- [ ] **Step 4: 提交**

```bash
git add scrivai/io/convert.py
git commit -m "feat(io): add _glm_ocr_chunked with parallel ThreadPoolExecutor and retry"
```

---

### Task 5: 改写 `_glm_ocr` 和 `to_markdown` 签名

**Files:**
- Modify: `scrivai/io/convert.py`

- [ ] **Step 1: 替换 `_glm_ocr` 函数体**

将当前 `_glm_ocr` 函数（从 `def _glm_ocr(` 到 `return "\n\n".join(chunks_md)`）替换为：

```python
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
```

- [ ] **Step 2: 给 `to_markdown` 添加新参数并透传**

在 `to_markdown` 签名中，`fallback: bool = True,` 后面添加：

```python
    # --- chunking (GLM only) ---
    chunk_pages: int = 30,
    overlap_pages: int = 2,
    max_workers: int = 12,
```

在 `elif backend == "glm":` 分支中，`backend_kwargs["end_page"] = end_page` 之后添加：

```python
        backend_kwargs["chunk_pages"] = chunk_pages
        backend_kwargs["overlap_pages"] = overlap_pages
        backend_kwargs["max_workers"] = max_workers
```

同时更新 `to_markdown` 的 docstring，在 `fallback` 参数说明之后追加：

```
        chunk_pages: Pages per chunk for GLM-OCR parallel processing (default 30).
        overlap_pages: Overlapping pages between chunks (default 2).
        max_workers: Max parallel threads for GLM-OCR (default 12).
```

- [ ] **Step 3: 运行全部已有测试，确认无回归**

Run: `conda run -n scrivai pytest tests/unit/test_chunk_merge.py tests/unit/test_glm_chunked.py tests/contract/test_io_smoke.py -v -k "not (doc_glm or pdf_glm or to_markdown_doc or to_markdown_docx or to_markdown_pdf)" 2>&1 | tail -20`
Expected: 所有非网络依赖测试通过

- [ ] **Step 4: 运行 ruff 检查**

Run: `conda run -n scrivai ruff check scrivai/io/convert.py --fix && conda run -n scrivai ruff format scrivai/io/convert.py`
Expected: 无错误或自动修复

- [ ] **Step 5: 提交**

```bash
git add scrivai/io/convert.py
git commit -m "feat(io): rewire _glm_ocr to unified chunked path, add params to to_markdown"
```

---

### Task 6: CLI 新增参数

**Files:**
- Modify: `scrivai/cli/io_cmd.py`

- [ ] **Step 1: 在 `cmd_convert` 中透传新参数**

将 `cmd_convert` 函数中的 `to_markdown(...)` 调用替换为：

```python
    md = to_markdown(
        args.input,
        ocr_backend=args.ocr_backend,
        glm_api_key=args.glm_api_key,
        start_page=args.start_page,
        end_page=args.end_page,
        ocr_base_url=args.ocr_base_url,
        timeout=args.timeout,
        fallback=not args.no_fallback,
        upload_rate=args.upload_rate,
        chunk_pages=args.chunk_pages,
        overlap_pages=args.overlap_pages,
        max_workers=args.max_workers,
    )
```

- [ ] **Step 2: 在 `register` 函数中添加 CLI 参数定义**

在 `c.set_defaults(func=cmd_convert)` 之前，`--upload-rate` 参数之后添加：

```python
    c.add_argument(
        "--chunk-pages",
        type=int,
        default=30,
        help="pages per chunk for GLM-OCR parallel processing (default 30)",
    )
    c.add_argument(
        "--overlap-pages",
        type=int,
        default=2,
        help="overlapping pages between chunks (default 2)",
    )
    c.add_argument(
        "--max-workers",
        type=int,
        default=12,
        help="max parallel threads for GLM-OCR (default 12)",
    )
```

- [ ] **Step 3: 运行 ruff 检查**

Run: `conda run -n scrivai ruff check scrivai/cli/io_cmd.py --fix && conda run -n scrivai ruff format scrivai/cli/io_cmd.py`
Expected: 无错误

- [ ] **Step 4: 验证 CLI help 输出**

Run: `conda run -n scrivai python -m scrivai.cli io convert --help 2>&1 | grep -E "(chunk-pages|overlap-pages|max-workers)"`
Expected: 三个新参数出现在 help 输出中

- [ ] **Step 5: 提交**

```bash
git add scrivai/cli/io_cmd.py
git commit -m "feat(cli): add --chunk-pages/--overlap-pages/--max-workers to io convert"
```

---

### Task 7: 全量回归测试 + ruff

**Files:**
- All modified files

- [ ] **Step 1: 全量 ruff 检查**

Run: `conda run -n scrivai ruff check scrivai/io/convert.py scrivai/cli/io_cmd.py --fix && conda run -n scrivai ruff format scrivai/io/convert.py scrivai/cli/io_cmd.py`
Expected: 无错误

- [ ] **Step 2: 运行全部单元测试**

Run: `conda run -n scrivai pytest tests/unit/ -v 2>&1 | tail -30`
Expected: 全部通过

- [ ] **Step 3: 运行 contract 测试（不含网络依赖）**

Run: `conda run -n scrivai pytest tests/contract/test_io_smoke.py -v -k "not (doc_glm or pdf_glm or to_markdown_doc or to_markdown_docx or to_markdown_pdf)" 2>&1 | tail -20`
Expected: 全部通过

- [ ] **Step 4: 如有 ruff 修复，提交**

```bash
git add -u
git commit -m "style: ruff fixes for parallel chunked OCR"
```
