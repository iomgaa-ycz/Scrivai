"""Knowledge library pydantic models, Library Protocol, and qmd re-exports.

See docs/design.md §4.1 and §4.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# qmd re-export (identity re-export, not a copy): business code imports via scrivai
# and does not need to depend on qmd directly
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
    """A single entry in a Library (corresponds to one qmd chunk)."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(..., description="Unique within the collection.")
    markdown: str = Field(..., description="Text content.")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Passed through from qmd chunk metadata; no semantic interpretation."
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@runtime_checkable
class Library(Protocol):
    """Unified Library Protocol implemented by RuleLibrary, CaseLibrary, and TemplateLibrary."""

    def add(self, entry_id: str, markdown: str, metadata: dict[str, Any]) -> LibraryEntry: ...
    def get(self, entry_id: str) -> Optional[LibraryEntry]: ...
    def list(self) -> List[str]: ...
    def delete(self, entry_id: str) -> None: ...
    def search(
        self, query: str, top_k: int = 5, filters: Optional[dict[str, Any]] = None
    ) -> List[SearchResult]: ...
