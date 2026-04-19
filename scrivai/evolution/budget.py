"""LLMCallBudget — LLM call budget guard during an evolution run."""

from __future__ import annotations


class BudgetExceededError(RuntimeError):
    """Raised when the LLM call budget is exhausted."""


class LLMCallBudget:
    """Tracks and enforces the maximum LLM call count for a single run_evolution call."""

    def __init__(self, limit: int = 500) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._limit = limit
        self._used = 0

    def consume(self, n: int = 1) -> None:
        """Consume n LLM calls; raises BudgetExceededError if the budget would be exceeded."""
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
