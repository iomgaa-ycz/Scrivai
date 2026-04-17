"""Scrivai 预置 PES — Extractor / Auditor / Generator(M0.75 占位,M1 实现)。

M0.75 仅为 from scrivai import * 提供符号占位;实例化抛 NotImplementedError。
真实实现在 M1 T1.4 / T1.5 / T1.6。
"""

from __future__ import annotations

from typing import Any


class _PresetPESPlaceholder:
    """所有预置 PES 在 M0.75 的共通占位。"""

    _name: str = "preset"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} 在 M1 T1.4-T1.6 实现;M0.75 仅提供顶层符号占位。"
        )


class ExtractorPES(_PresetPESPlaceholder):
    """从文档抽取结构化条目 — M1 T1.4 实现。"""

    _name = "extractor"


class AuditorPES(_PresetPESPlaceholder):
    """对照检查点清单审核 — M1 T1.5 实现。"""

    _name = "auditor"


class GeneratorPES(_PresetPESPlaceholder):
    """按 docxtpl 模板生成 — M1 T1.6 实现。"""

    _name = "generator"


__all__ = ["ExtractorPES", "AuditorPES", "GeneratorPES"]
