"""单章生成引擎模块。

提供单章生成能力（原子操作），多章编排由调用方负责。
"""

import logging
from typing import Any

from core.knowledge.store import KnowledgeStore, SearchResult
from core.llm import LLMClient

logger = logging.getLogger(__name__)


class GenerationEngine:
    """单章生成引擎。

    职责：
    1. Jinja2 模板渲染 + 变量注入
    2. 调用 LLM 生成单章内容

    不负责：
    - 多章循环编排
    - 上下文管理（由 GenerationContext 处理）

    Args:
        llm: LLM 客户端
        store: 知识库（用于检索案例/规则，可选）
    """

    def __init__(self, llm: LLMClient, store: KnowledgeStore | None = None) -> None:
        self._llm = llm
        self._store = store

    def generate_chapter(
        self,
        template: str,
        variables: dict[str, Any],
    ) -> str:
        """生成单个章节。

        Args:
            template: Jinja2 章节模板（字符串或文件路径）
            variables: 模板变量字典，通常包含：
                - user_inputs: dict — 用户输入的变量
                - retrieved_cases: list[SearchResult] — RAG 检索结果
                - previous_summary: str — 前文摘要（可选）
                - glossary: dict[str, str] — 术语表（可选）

        Returns:
            生成的章节文本

        核心流程:
            Phase 1: Jinja2 渲染模板 + 变量注入
            Phase 2: 调用 LLM 生成内容
        """
        # Phase 1 & 2: chat_with_template 已封装渲染和调用
        result = self._llm.chat_with_template(template, variables)
        logger.debug("章节生成完成，长度: %d 字符", len(result))
        return result

    def retrieve_cases(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """从知识库检索相关案例。

        便捷方法，用于生成前的 RAG 检索。

        Args:
            query: 检索查询
            top_k: 返回数量
            filters: metadata 过滤条件

        Returns:
            检索结果列表

        Raises:
            RuntimeError: 未配置 KnowledgeStore
        """
        if self._store is None:
            raise RuntimeError("GenerationEngine 未配置 KnowledgeStore，无法检索")

        return self._store.search(query, top_k=top_k, filters=filters)
