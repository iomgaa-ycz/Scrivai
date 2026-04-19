"""Case knowledge library wrapping qmd (fixed collection: 'cases')."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scrivai.knowledge.base import _BaseLibrary

if TYPE_CHECKING:
    from qmd import QmdClient


class CaseLibrary(_BaseLibrary):
    """Case knowledge library (fixed collection: 'cases')."""

    def __init__(self, qmd_client: "QmdClient") -> None:
        super().__init__(qmd_client, "cases")
