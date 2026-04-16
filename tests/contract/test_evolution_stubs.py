"""T0.18 契约测试:Evolution stubs 与 SkillsRootResolver Protocol。"""

from __future__ import annotations

import asyncio

import pytest


def test_evolution_trigger_importable_from_top_level() -> None:
    """scrivai.EvolutionTrigger 顶层可导入。"""
    from scrivai import EvolutionTrigger

    assert EvolutionTrigger is not None


def test_run_evolution_importable_from_top_level() -> None:
    """scrivai.run_evolution 顶层可导入。"""
    from scrivai import run_evolution

    assert callable(run_evolution)


def test_evolution_trigger_init_raises_not_implemented_m2() -> None:
    """EvolutionTrigger() 抛 NotImplementedError 且 message 含 'M2'。"""
    from scrivai import EvolutionTrigger

    with pytest.raises(NotImplementedError, match="M2"):
        EvolutionTrigger()


def test_run_evolution_raises_not_implemented_m2() -> None:
    """run_evolution() 是 async 函数,await 时抛 NotImplementedError。"""
    from scrivai import run_evolution

    with pytest.raises(NotImplementedError, match="M2"):
        asyncio.run(run_evolution())


def test_evolution_package_importable() -> None:
    """scrivai.evolution 包可 import,且不抛异常。"""
    import scrivai.evolution

    assert scrivai.evolution is not None
