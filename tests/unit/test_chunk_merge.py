"""Unit tests for chunk merge utilities in scrivai.io.convert."""

from __future__ import annotations


def test_find_overlap_boundary_exact_match():
    """重叠区域有完全匹配的行 → 返回中点切割位置。"""
    from scrivai.io.convert import _find_overlap_boundary

    prev_lines = [
        "page 1 content line 1",
        "page 1 content line 2",
        "page 2 content line 1",
        "page 2 content line 2",
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
        "page 5 content line 1",
        "page 5 content line 2",
    ]

    result = _find_overlap_boundary(prev_lines, next_lines)
    assert result is not None
    prev_cut, next_cut = result
    assert 0 < prev_cut <= len(prev_lines)
    assert 0 <= next_cut < len(next_lines)
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
