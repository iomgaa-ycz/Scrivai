"""Scrivai 异常层级——M0 前置声明,后续里程碑只补行为。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrivai.models.pes import PhaseResult


class ScrivaiError(Exception):
    """所有 Scrivai 异常的根基类。"""


class PESConfigError(ScrivaiError):
    """PESConfig YAML 加载 / schema 校验失败。M0 T0.3 实现。"""


class WorkspaceError(ScrivaiError):
    """WorkspaceManager 错误(run_id 冲突 / fcntl 失败等)。M0.25 T0.4 实现。"""


class TrajectoryWriteError(ScrivaiError):
    """TrajectoryStore 写入失败(SQLite busy 超过重试预算)。M0.25 T0.7 实现。"""


class PhaseError(ScrivaiError):
    """BasePES phase 级失败统一出口。携带 result / error_type / is_retryable。M0.5 T0.6 实现。"""

    def __init__(
        self,
        phase: str,
        message: str,
        *,
        result: PhaseResult | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.result = result


class RateLimitError(ScrivaiError):
    """Claude SDK 速率限制;用于 L1 传输级重试。M0.5 T0.6 实现。"""


class _SDKError(ScrivaiError):
    """LLMClient 边界翻译后的内部异常,只在 BasePES._call_sdk_query → _run_phase 之间存活。

    BasePES._run_phase 的 step 5 except 子句据 error_type 字段构造 PhaseResult,
    再包成 PhaseError 冒泡。业务层永远看不到 _SDKError。

    Attributes:
        error_type: "max_turns_exceeded" / "sdk_other" — 决定 PhaseResult.is_retryable
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
