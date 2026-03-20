"""KnowledgeStore 单元测试。

所有测试 mock qmd，不发真实请求和数据库操作。
"""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from scrivai.knowledge import KnowledgeStore, SearchResult


@dataclass
class MockQmdSearchResult:
    """模拟 qmd.SearchResult。"""

    body: str
    metadata: dict | None
    score: float
    file: str = "test.md"
    title: str = "test"
    collection: str = "default"
    hash: str = "abc123"
    pos: int = 0
    context: str | None = None


def _mock_qmd():
    """构造 qmd mock 对象。"""
    mock_db = MagicMock()
    mock_db.get_document_count.return_value = 5
    mock_db.delete_documents.return_value = 2

    mock_store = MagicMock()
    mock_store.index_document.return_value = {"status": "ok"}

    mock_llm = MagicMock()

    mock_qmd = MagicMock()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm
    return mock_qmd, mock_db, mock_store, mock_llm


@patch("scrivai.knowledge.store.qmd")
def test_init(mock_qmd):
    """验证 __init__ 正确初始化 db/store/llm_backend。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")

    mock_qmd.create_store.assert_called_once_with("/tmp/test.db")
    mock_qmd.create_llm_backend.assert_called_once()
    assert ks._namespace == "test_ns"
    assert ks._db is mock_db
    assert ks._store is mock_store
    assert ks._llm_backend is mock_llm


@patch("scrivai.knowledge.store.qmd")
def test_add_success(mock_qmd):
    """验证 add() 调用 index_document + embed_documents，返回正确条数。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")
    texts = ["文本一", "文本二"]
    metas = [{"type": "a"}, {"type": "b"}]

    result = ks.add(texts, metas)

    assert result == 2
    assert mock_store.index_document.call_count == 2
    mock_store.embed_documents.assert_called_once_with(mock_db, mock_llm)


@patch("scrivai.knowledge.store.qmd")
def test_add_length_mismatch(mock_qmd):
    """验证 add() texts/metadatas 长度不一致时 raise ValueError。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")

    try:
        ks.add(["文本一", "文本二"], [{"type": "a"}])
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "长度不一致" in str(e)


@patch("scrivai.knowledge.store.qmd")
def test_search_conversion(mock_qmd):
    """验证 search() 转换结果格式正确。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    mock_qmd.search.return_value = [
        MockQmdSearchResult(body="内容一", metadata={"type": "a"}, score=0.9),
        MockQmdSearchResult(body="内容二", metadata={"type": "b"}, score=0.8),
    ]

    ks = KnowledgeStore("/tmp/test.db", "test_ns")
    results = ks.search("查询", top_k=2)

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].content == "内容一"
    assert results[0].metadata == {"type": "a"}
    assert results[0].score == 0.9
    mock_qmd.search.assert_called_once()


@patch("scrivai.knowledge.store.qmd")
def test_search_with_filters(mock_qmd):
    """验证 search() filters 参数正确传递。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm
    mock_qmd.search.return_value = []

    ks = KnowledgeStore("/tmp/test.db", "test_ns")
    ks.search("查询", top_k=5, filters={"type": "case"})

    call_kwargs = mock_qmd.search.call_args[1]
    assert call_kwargs["filters"] == {"type": "case"}


@patch("scrivai.knowledge.store.qmd")
def test_count_delegation(mock_qmd):
    """验证 count() 委托调用正确。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")
    result = ks.count(filters={"type": "case"})

    assert result == 5
    mock_db.get_document_count.assert_called_once_with("test_ns", filters={"type": "case"})


@patch("scrivai.knowledge.store.qmd")
def test_delete_empty_filters(mock_qmd):
    """验证 delete() filters 为空时 raise ValueError。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")

    try:
        ks.delete({})
        assert False, "应抛出 ValueError"
    except ValueError as e:
        assert "非空 filters" in str(e)


@patch("scrivai.knowledge.store.qmd")
def test_delete_success(mock_qmd):
    """验证 delete() 正常删除返回条数。"""
    _, mock_db, mock_store, mock_llm = _mock_qmd()
    mock_qmd.create_store.return_value = (mock_db, mock_store)
    mock_qmd.create_llm_backend.return_value = mock_llm

    ks = KnowledgeStore("/tmp/test.db", "test_ns")
    result = ks.delete({"type": "temp"})

    assert result == 2
    mock_db.delete_documents.assert_called_once_with("test_ns", {"type": "temp"})
