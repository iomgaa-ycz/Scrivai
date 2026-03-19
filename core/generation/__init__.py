"""生成模块。

提供单章生成引擎和上下文工具。
"""

from core.generation.context import GenerationContext
from core.generation.engine import GenerationEngine

__all__ = ["GenerationEngine", "GenerationContext"]
