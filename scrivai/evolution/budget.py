"""LLMCallBudget — 进化期间 LLM 调用预算守卫。"""

from __future__ import annotations


class BudgetExceededError(RuntimeError):
    """LLM 调用超预算。"""


class LLMCallBudget:
    """追踪并限制单次 run_evolution 的 LLM 调用总数。"""

    def __init__(self, limit: int = 500) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._limit = limit
        self._used = 0

    def consume(self, n: int = 1) -> None:
        """尝试消耗 n 次调用;若消耗后超预算抛 BudgetExceededError。"""
        if self._used + n > self._limit:
            raise BudgetExceededError(
                f"LLM budget exhausted: used={self._used}, want +{n}, limit={self._limit}"
            )
        self._used += n

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self._limit - self._used)

    @property
    def is_exhausted(self) -> bool:
        return self._used >= self._limit
