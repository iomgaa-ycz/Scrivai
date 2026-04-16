"""EvolutionTrigger:从 TrajectoryStore 构建进化评测集(M2 实现)。"""

from __future__ import annotations

from typing import Any


class EvolutionTrigger:
    """从 TrajectoryStore 构建进化评测集。

    M2 T2.2 实现完整逻辑;M0 仅占位以保证顶层 import 可用。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("M2 实现")

    def has_enough_data(self) -> bool:
        raise NotImplementedError("M2 实现")

    def build_eval_dataset(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("M2 实现")
