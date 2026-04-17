"""M0.75 T0.17 双向契约:验证 qmd 接口未变,scrivai re-export 身份相等。

参考 docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §7.2。
"""

from __future__ import annotations

from pathlib import Path


def test_qmd_top_level_symbols_present() -> None:
    """qmd 顶层必须导出 ChunkRef / SearchResult / CollectionInfo / connect / QmdClient。"""
    import qmd

    for sym in ("ChunkRef", "SearchResult", "CollectionInfo", "connect", "QmdClient"):
        assert hasattr(qmd, sym), f"qmd 缺顶层符号:{sym}"


def test_scrivai_qmd_reexport_identity() -> None:
    """scrivai.ChunkRef is qmd.ChunkRef(re-export 身份相等)。"""
    import qmd

    import scrivai

    assert scrivai.ChunkRef is qmd.ChunkRef
    assert scrivai.SearchResult is qmd.SearchResult
    assert scrivai.CollectionInfo is qmd.CollectionInfo


def test_qmd_collection_methods_signature(tmp_path: Path) -> None:
    """qmd Collection 必须提供:add_document / get_document / list_documents /
    delete_document / hybrid_search。"""
    import qmd

    client = qmd.connect(str(tmp_path / "test.db"))
    coll = client.collection("smoke")

    for method in (
        "add_document",
        "get_document",
        "list_documents",
        "delete_document",
        "hybrid_search",
    ):
        assert hasattr(coll, method), f"qmd Collection 缺方法:{method}"


def test_qmd_basic_crud_works(tmp_path: Path) -> None:
    """qmd 基本 CRUD 走通(冒烟,确保升级后契约未变)。"""
    import qmd

    client = qmd.connect(str(tmp_path / "test.db"))
    coll = client.collection("smoke")

    coll.add_document("doc-1", "hello world", {"k": "v"})
    got = coll.get_document("doc-1")
    assert got is not None
    assert got["id"] == "doc-1"
    assert got["markdown"] == "hello world"

    assert "doc-1" in coll.list_documents()

    coll.delete_document("doc-1")
    assert coll.get_document("doc-1") is None
