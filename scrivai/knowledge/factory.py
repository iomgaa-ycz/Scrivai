"""Knowledge factory — build a QmdClient and the three Library instances."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import qmd

from scrivai.knowledge.cases import CaseLibrary
from scrivai.knowledge.rules import RuleLibrary
from scrivai.knowledge.templates import TemplateLibrary

if TYPE_CHECKING:
    from qmd import QmdClient


def build_qmd_client_from_config(db_path: str | Path) -> "QmdClient":
    """Wrap qmd.connect with a consistent ~ expansion."""
    return qmd.connect(str(Path(db_path).expanduser()))


def build_libraries(
    qmd_client: "QmdClient",
) -> tuple[RuleLibrary, CaseLibrary, TemplateLibrary]:
    """Build all three libraries in one call."""
    return (
        RuleLibrary(qmd_client),
        CaseLibrary(qmd_client),
        TemplateLibrary(qmd_client),
    )
