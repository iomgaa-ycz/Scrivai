"""HookManager — lightweight pluggy.PluginManager wrapper for PES lifecycle hooks.

References:
- docs/design.md §4.3 (9 hook points + exception propagation matrix)
- docs/TD.md T0.5
- docs/superpowers/specs/2026-04-16-scrivai-m0.25-design.md §4.2

Design notes:
- HookManager exposes only two dispatch methods: synchronous and non-blocking;
  which hook uses which is decided by BasePES (M0.5).
- All 9 hook specs are declared in PESHookSpec.
- All 9 HookContext pydantic types come from scrivai.models.pes (defined in M0).
"""

from __future__ import annotations

import pluggy
from loguru import logger

from scrivai.models.pes import (
    CancelHookContext,
    FailureHookContext,
    HookContext,
    OutputHookContext,
    PhaseHookContext,
    PromptHookContext,
    PromptTurnHookContext,
    RunHookContext,
)

# Module-level markers — fully symmetric with Herald2 (namespace changed to scrivai_pes)
hookspec = pluggy.HookspecMarker("scrivai_pes")
hookimpl = pluggy.HookimplMarker("scrivai_pes")


class PESHookSpec:
    """Spec declarations for all 9 PES hook points (see design §4.3 table)."""

    @hookspec
    def before_run(self, context: RunHookContext) -> None:
        """Fired before the entire run starts (synchronous; exceptions cause run failure)."""

    @hookspec
    def before_phase(self, context: PhaseHookContext) -> None:
        """Fired before each phase attempt (synchronous; exceptions cause phase failure)."""

    @hookspec
    def before_prompt(self, context: PromptHookContext) -> None:
        """Fired after prompt rendering, before SDK call (synchronous; plugins may modify context.prompt)."""

    @hookspec
    def after_prompt_turn(self, context: PromptTurnHookContext) -> None:
        """Fired after each SDK turn is received (synchronous)."""

    @hookspec
    def after_phase(self, context: PhaseHookContext) -> None:
        """Fired after a phase succeeds (synchronous)."""

    @hookspec
    def on_phase_failed(self, context: FailureHookContext) -> None:
        """Fired when a phase attempt fails (non-blocking; exceptions are only logged)."""

    @hookspec
    def on_output_written(self, context: OutputHookContext) -> None:
        """Fired once after summarize output validates, before after_phase (synchronous)."""

    @hookspec
    def on_run_cancelled(self, context: CancelHookContext) -> None:
        """Fired on KeyboardInterrupt or asyncio.CancelledError (non-blocking)."""

    @hookspec
    def after_run(self, context: RunHookContext) -> None:
        """Fired at the end of the run in a finally block (non-blocking)."""


class HookManager:
    """Lightweight pluggy.PluginManager wrapper for PES lifecycle hooks.

    Example::

        mgr = HookManager()
        mgr.register(MyPlugin())
        mgr.dispatch("before_run", RunHookContext(run=run))
    """

    def __init__(self) -> None:
        self._mgr = pluggy.PluginManager("scrivai_pes")
        self._mgr.add_hookspecs(PESHookSpec)

    def register(self, plugin: object, name: str | None = None) -> None:
        """Register a hook plugin (optional name enables pluggy deduplication)."""
        self._mgr.register(plugin, name=name)

    def dispatch(self, hook_name: str, context: HookContext) -> None:
        """Synchronous dispatch; plugin exceptions bubble up to the caller."""
        getattr(self._mgr.hook, hook_name)(context=context)

    def dispatch_non_blocking(self, hook_name: str, context: HookContext) -> None:
        """Non-blocking dispatch; plugin exceptions are logged via loguru but do not propagate."""
        try:
            self.dispatch(hook_name, context)
        except Exception:
            logger.exception("Hook execution failed [hook={}]", hook_name)
