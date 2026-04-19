"""Scrivai IO utilities — document format conversion and docxtpl rendering.

See docs/design.md §4.8 and docs/superpowers/specs/2026-04-16-scrivai-m0.75-design.md §4.
"""

from scrivai.io.convert import doc_to_markdown, docx_to_markdown, pdf_to_markdown
from scrivai.io.render import DocxRenderer

__all__ = [
    "docx_to_markdown",
    "doc_to_markdown",
    "pdf_to_markdown",
    "DocxRenderer",
]
