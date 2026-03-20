"""Scrivai SDK 核心模块。

提供文档生成与审核能力。
"""

from scrivai.audit.engine import AuditEngine, AuditResult
from scrivai.generation.context import GenerationContext
from scrivai.generation.engine import GenerationEngine
from scrivai.knowledge.store import KnowledgeStore, SearchResult
from scrivai.llm import LLMClient, LLMConfig
from scrivai.project import Project, ProjectConfig

__all__ = [
    # 入口
    "Project",
    "ProjectConfig",
    # LLM
    "LLMClient",
    "LLMConfig",
    # 知识库
    "KnowledgeStore",
    "SearchResult",
    # 生成
    "GenerationEngine",
    "GenerationContext",
    # 审核
    "AuditEngine",
    "AuditResult",
]
