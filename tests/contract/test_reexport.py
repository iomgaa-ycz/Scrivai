"""qmd re-export 身份相等契约测试。

scrivai.ChunkRef 应当与 qmd.ChunkRef 是同一个对象(身份相等,非副本)。
"""

from __future__ import annotations

import qmd


def test_chunk_ref_identity_from_models_knowledge() -> None:
    """从 scrivai.models.knowledge 导入的 ChunkRef 与 qmd.ChunkRef 身份相等。"""
    from scrivai.models.knowledge import ChunkRef

    assert ChunkRef is qmd.ChunkRef


def test_search_result_identity_from_models_knowledge() -> None:
    from scrivai.models.knowledge import SearchResult

    assert SearchResult is qmd.SearchResult


def test_collection_info_identity_from_models_knowledge() -> None:
    from scrivai.models.knowledge import CollectionInfo

    assert CollectionInfo is qmd.CollectionInfo


def test_chunk_ref_identity_from_models_aggregate() -> None:
    """从 scrivai.models 聚合层导入的 ChunkRef 也身份相等。"""
    from scrivai.models import ChunkRef

    assert ChunkRef is qmd.ChunkRef


def test_chunk_ref_identity_from_scrivai_top_level() -> None:
    """scrivai.ChunkRef is qmd.ChunkRef(顶层 re-export 身份相等)。"""
    import scrivai

    assert scrivai.ChunkRef is qmd.ChunkRef


def test_search_result_identity_from_scrivai_top_level() -> None:
    import scrivai

    assert scrivai.SearchResult is qmd.SearchResult


def test_collection_info_identity_from_scrivai_top_level() -> None:
    import scrivai

    assert scrivai.CollectionInfo is qmd.CollectionInfo
