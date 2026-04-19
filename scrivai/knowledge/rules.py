"""Rule knowledge library wrapping qmd (fixed collection: 'rules')."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scrivai.knowledge.base import _BaseLibrary

if TYPE_CHECKING:
    from qmd import QmdClient


class RuleLibrary(_BaseLibrary):
    """Rule knowledge library (fixed collection: 'rules')."""

    def __init__(self, qmd_client: "QmdClient") -> None:
        super().__init__(qmd_client, "rules")
