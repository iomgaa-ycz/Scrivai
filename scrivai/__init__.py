"""Scrivai v3 — Claude Agent 编排框架(M0 地基层)。

完整 Public API 在 M0.75 冻结;本里程碑只暴露:
- qmd 基础类型 re-export(身份相等于 qmd.X)
- Evolution 占位类(M2 实现)

参考 docs/design.md §4.1。
"""

from qmd import ChunkRef, CollectionInfo, SearchResult

from scrivai.evolution import EvolutionTrigger, run_evolution

__all__ = [
    "ChunkRef",
    "CollectionInfo",
    "SearchResult",
    "EvolutionTrigger",
    "run_evolution",
]
