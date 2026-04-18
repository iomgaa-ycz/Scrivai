"""LLMCallBudget 合约测试。"""

from __future__ import annotations

import pytest


def test_basic_consume():
    from scrivai.evolution.budget import LLMCallBudget

    b = LLMCallBudget(limit=10)
    assert b.used == 0
    assert b.remaining == 10
    b.consume(1)
    assert b.used == 1
    b.consume(3)
    assert b.used == 4
    assert b.remaining == 6
    assert not b.is_exhausted


def test_exceed_raises():
    from scrivai.evolution.budget import BudgetExceededError, LLMCallBudget

    b = LLMCallBudget(limit=5)
    b.consume(3)
    with pytest.raises(BudgetExceededError):
        b.consume(3)  # 3+3 > 5


def test_exhausted_flag():
    from scrivai.evolution.budget import LLMCallBudget

    b = LLMCallBudget(limit=5)
    b.consume(5)
    assert b.is_exhausted
    assert b.remaining == 0


def test_default_limit():
    from scrivai.evolution.budget import LLMCallBudget

    b = LLMCallBudget()
    assert b.remaining == 500
