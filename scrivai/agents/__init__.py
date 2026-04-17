"""Scrivai 预置 PES — Extractor / Auditor / Generator(M1.5a T1.4-T1.6)。

三个类都继承 BasePES,零新构造参数;业务参数走 runtime_context。
参考 docs/design.md §4.4 和 docs/superpowers/specs/2026-04-17-scrivai-m1.5-design.md。
"""

from __future__ import annotations

from scrivai.agents.auditor import AuditorPES
from scrivai.agents.extractor import ExtractorPES
from scrivai.agents.generator import GeneratorPES

__all__ = ["ExtractorPES", "AuditorPES", "GeneratorPES"]
