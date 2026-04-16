"""Knowledge Library 相关 pydantic + Library Protocol + qmd re-export。

参考 docs/design.md §4.1 / §4.7。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# qmd re-export(身份相等,非副本):scrivai 业务侧通过 scrivai 导入,
# 不需要直接依赖 qmd 名字
from qmd import ChunkRef, CollectionInfo, SearchResult

__all__ = [
    "LibraryEntry",
    "Library",
    # qmd re-export
    "ChunkRef",
    "SearchResult",
    "CollectionInfo",
]


class LibraryEntry(BaseModel):
    """Library 中一条记录(对应 qmd 一个 chunk)。"""

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(..., description="collection 内唯一")
    markdown: str = Field(..., description="文本内容")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="透传 qmd chunk metadata,无语义解释"
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@runtime_checkable
class Library(Protocol):
    """统一的 Library Protocol。RuleLibrary / CaseLibrary / TemplateLibrary 都实现它。"""

    def add(self, entry_id: str, markdown: str, metadata: dict[str, Any]) -> LibraryEntry: ...
    def get(self, entry_id: str) -> Optional[LibraryEntry]: ...
    def list(self) -> List[str]: ...
    def delete(self, entry_id: str) -> None: ...
    def search(
        self, query: str, top_k: int = 5, filters: Optional[dict[str, Any]] = None
    ) -> List[SearchResult]: ...
