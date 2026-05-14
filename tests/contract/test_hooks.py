"""M0.25 T0.5 contract tests for HookManager.

References:
- docs/design.md §4.3
- docs/TD.md T0.5
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.2
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scrivai import HookManager, hookimpl
from scrivai.models.pes import (
    PESRun,
    RunHookContext,
)


def _sample_run(run_id: str = "r1") -> PESRun:
    """构造一个最小合法 PESRun 给所有 context 测试用。"""
    return PESRun(
        run_id=run_id,
        pes_name="extractor",
        task_prompt="dummy",
        model_name="glm-5.1",
        provider="glm",
        sdk_version="0.1.0",
        started_at=datetime.now(timezone.utc),
    )


NINE_HOOK_NAMES = (
    "before_run",
    "before_phase",
    "before_prompt",
    "after_prompt_turn",
    "after_phase",
    "on_phase_failed",
    "on_output_written",
    "on_run_cancelled",
    "after_run",
)


def test_nine_hook_names_registered() -> None:
    """HookManager 必须注册全部 9 个 hookspec,缺一个就抛错。"""
    mgr = HookManager()
    for name in NINE_HOOK_NAMES:
        assert hasattr(mgr._mgr.hook, name), f"missing hookspec: {name}"


def test_hook_registration_and_dispatch() -> None:
    """注册 plugin → dispatch 触发其方法,context 透传无失真。"""
    seen: list[tuple[str, str]] = []

    class Plugin:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            seen.append(("before_run", context.run.run_id))

        @hookimpl
        def after_run(self, context: RunHookContext) -> None:
            seen.append(("after_run", context.run.run_id))

    mgr = HookManager()
    mgr.register(Plugin())
    run = _sample_run("hook-r1")
    mgr.dispatch("before_run", RunHookContext(run=run))
    mgr.dispatch("after_run", RunHookContext(run=run))

    assert seen == [("before_run", "hook-r1"), ("after_run", "hook-r1")]


def test_sync_dispatch_propagates_exception() -> None:
    """dispatch 同步分发:plugin 抛异常,直接冒泡,不被吞。"""

    class BadPlugin:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            raise ValueError("intentional")

    mgr = HookManager()
    mgr.register(BadPlugin())
    with pytest.raises(ValueError, match="intentional"):
        mgr.dispatch("before_run", RunHookContext(run=_sample_run()))


def test_nonblocking_dispatch_catches_exception(caplog) -> None:
    """dispatch_non_blocking:plugin 抛异常,只 loguru 记一次,不冒泡。"""
    from loguru import logger

    class BadPlugin:
        @hookimpl
        def after_run(self, context: RunHookContext) -> None:
            raise RuntimeError("boom")

    mgr = HookManager()
    mgr.register(BadPlugin())

    # 把 loguru 临时桥接到 pytest caplog
    handler_id = logger.add(caplog.handler, level=0, format="{message}")
    try:
        mgr.dispatch_non_blocking("after_run", RunHookContext(run=_sample_run()))
    finally:
        logger.remove(handler_id)

    assert "Hook execution failed" in caplog.text
    assert "after_run" in caplog.text


def test_hook_ordering() -> None:
    """多 plugin 注册:assert pluggy 实际调用顺序(LIFO,后注册先调)。

    若 BasePES (M0.5) 需要 FIFO,届时给 plugins 加 tryfirst/trylast 调整;
    本测试只锚定当前 pluggy 默认行为,防止不知不觉发生变化。
    """
    seen: list[str] = []

    class A:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            seen.append("A")

    class B:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            seen.append("B")

    class C:
        @hookimpl
        def before_run(self, context: RunHookContext) -> None:
            seen.append("C")

    mgr = HookManager()
    mgr.register(A(), name="A")
    mgr.register(B(), name="B")
    mgr.register(C(), name="C")
    mgr.dispatch("before_run", RunHookContext(run=_sample_run()))

    # pluggy 默认:LIFO(后注册先调)
    assert seen == ["C", "B", "A"]
