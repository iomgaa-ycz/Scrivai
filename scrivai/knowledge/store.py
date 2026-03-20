"""知识库存储模块。

封装 qmd 语义检索库，提供文档索引、搜索、删除等能力。
"""

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import qmd

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """检索结果。

    Attributes:
        content: 匹配文本内容
        metadata: 文档附加信息
        score: 相似度分数
    """

    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


class KnowledgeStore:
    """知识库存储，qmd 薄封装。

    Args:
        db_path: 数据库文件路径
        namespace: 集合命名空间（作为 qmd collection 名）
    """

    def __init__(self, db_path: str, namespace: str) -> None:
        self._namespace = namespace
        self._db, self._store = qmd.create_store(db_path)
        self._llm_backend = qmd.create_llm_backend()

    def add(self, texts: list[str], metadatas: list[dict]) -> int:
        """添加文本到知识库。

        Args:
            texts: 文本列表
            metadatas: 对应的元数据列表，长度必须与 texts 一致

        Returns:
            成功索引的文档数

        Raises:
            ValueError: texts 与 metadatas 长度不一致
        """
        if len(texts) != len(metadatas):
            raise ValueError(f"texts 与 metadatas 长度不一致: {len(texts)} != {len(metadatas)}")

        count = 0
        for text, meta in zip(texts, metadatas):
            file_path = str(uuid.uuid4())
            self._store.index_document(self._namespace, file_path, text, metadata=meta)
            count += 1

        self._store.embed_documents(self._db, self._llm_backend)
        logger.debug("知识库添加 %d 条文档到 [%s]", count, self._namespace)
        return count

    def add_from_directory(self, path: str, pattern: str, metadata: dict) -> int:
        """从目录批量导入文件。

        Args:
            path: 目录路径
            pattern: glob 匹配模式（如 "*.md"）
            metadata: 所有文件共享的元数据

        Returns:
            成功索引的文档数
        """
        files = sorted(Path(path).glob(pattern))
        texts = [f.read_text(encoding="utf-8") for f in files]
        metas = [metadata.copy() for _ in files]
        return self.add(texts, metas)

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[SearchResult]:
        """语义检索。

        Args:
            query: 查询文本
            top_k: 返回结果数上限
            filters: metadata 过滤条件

        Returns:
            检索结果列表
        """
        raw = qmd.search(
            self._db,
            query,
            collection=self._namespace,
            limit=top_k,
            llm_backend=self._llm_backend,
            filters=filters,
        )
        return [
            SearchResult(
                content=r.body,
                metadata=r.metadata or {},
                score=r.score,
            )
            for r in raw
        ]

    def count(self, filters: dict | None = None) -> int:
        """统计文档数量。

        Args:
            filters: metadata 过滤条件

        Returns:
            匹配的文档数
        """
        return self._db.get_document_count(self._namespace, filters=filters)

    def delete(self, filters: dict) -> int:
        """按条件删除文档。

        Args:
            filters: metadata 过滤条件（必填，防止误删全库）

        Returns:
            删除的文档数

        Raises:
            ValueError: filters 为空
        """
        if not filters:
            raise ValueError("delete 操作必须提供非空 filters，防止误删全库")
        return self._db.delete_documents(self._namespace, filters)
