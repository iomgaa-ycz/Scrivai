"""Built-in PES agents — ExtractorPES, AuditorPES, GeneratorPES (M1.5a T1.4-T1.6).

All three inherit from BasePES with no new constructor parameters;
business parameters are passed via ``runtime_context``.
See docs/design.md §4.4 and docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md.
"""

from __future__ import annotations

from scrivai.agents.auditor import AuditorPES
from scrivai.agents.extractor import ExtractorPES
from scrivai.agents.generator import GeneratorPES

__all__ = ["ExtractorPES", "AuditorPES", "GeneratorPES"]
