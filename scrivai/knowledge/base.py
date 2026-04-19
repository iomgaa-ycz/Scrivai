"""_BaseLibrary — shared base class for the three Library types.

Directly proxies a qmd Collection's add_document / get_document / list_documents /
delete_document / hybrid_search; holds no in-memory state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from scrivai.models.knowledge import LibraryEntry

if TYPE_CHECKING:
    from qmd import Collection, QmdClient, SearchResult


class _BaseLibrary:
    """Shared implementation for RuleLibrary / CaseLibrary / TemplateLibrary.

    Subclasses only need to pass collection_name in __init__.
    """

    def __init__(self, qmd_client: "QmdClient", collection_name: str) -> None:
        self._collection_name = collection_name
        self._coll: Collection = qmd_client.collection(collection_name)

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def add(self, entry_id: str, markdown: str, metadata: dict[str, Any]) -> LibraryEntry:
        """Write a qmd chunk; entry_id must be unique within the collection.

        Raises ValueError on duplicate; qmd's add_document has no uniqueness check so we
        do a get first.
        """
        if self._coll.get_document(entry_id) is not None:
            raise ValueError(
                f"entry_id {entry_id!r} already exists in collection {self._collection_name!r}"
            )
        self._coll.add_document(entry_id, markdown, metadata)
        return LibraryEntry(entry_id=entry_id, markdown=markdown, metadata=dict(metadata))

    def get(self, entry_id: str) -> Optional[LibraryEntry]:
        """Fetch by document_id; returns None if not found."""
        doc = self._coll.get_document(entry_id)
        if doc is None:
            return None
        return LibraryEntry(
            entry_id=doc["id"],
            markdown=doc["markdown"],
            metadata=dict(doc.get("metadata") or {}),
        )

    def list(self) -> list[str]:
        """Return all entry_ids in the collection."""
        return self._coll.list_documents()

    def delete(self, entry_id: str) -> None:
        """Delete an entry from the collection; no error if not found (qmd behaviour)."""
        self._coll.delete_document(entry_id)

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list["SearchResult"]:
        """Proxy to qmd hybrid_search."""
        return self._coll.hybrid_search(query, top_k=top_k, filters=filters)
