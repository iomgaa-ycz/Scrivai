"""Template knowledge library wrapping qmd (fixed collection: 'templates')."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scrivai.knowledge.base import _BaseLibrary

if TYPE_CHECKING:
    from qmd import QmdClient


class TemplateLibrary(_BaseLibrary):
    """Template knowledge library (fixed collection: 'templates')."""

    def __init__(self, qmd_client: "QmdClient") -> None:
        super().__init__(qmd_client, "templates")
