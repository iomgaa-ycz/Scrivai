"""BasePES — Three-phase (plan → execute → summarize) execution engine."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from scrivai.pes.llm_client import LLMClient

from scrivai.exceptions import PhaseError, _SDKError
from scrivai.models.pes import (
    CancelHookContext,
    FailureHookContext,
    ModelConfig,
    OutputHookContext,
    PESConfig,
    PESRun,
    PhaseConfig,
    PhaseHookContext,
    PhaseResult,
    PhaseTurn,
    PromptHookContext,
    PromptTurnHookContext,
    RunHookContext,
)
from scrivai.models.workspace import WorkspaceHandle
from scrivai.pes.hooks import HookManager
from scrivai.trajectory.store import TrajectoryStore
from scrivai.utils import relaxed_json_loads


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _NullHookManager:
    """Null dispatch used when no hooks are registered (avoids if-hooks checks)."""

    def dispatch(self, hook_name: str, context: object) -> None:
        pass

    def dispatch_non_blocking(self, hook_name: str, context: object) -> None:
        pass


class BasePES:
    """Three-phase (plan → execute → summarize) execution engine base class.

    Subclasses customize behavior by overriding ``_call_sdk_query`` and
    four extension points: ``_build_plan_prompt``, ``_build_execute_prompt``,
    ``_build_summarize_prompt``, and ``_post_summarize``.

    Args:
        config: PES configuration loaded via ``load_pes_config()``.
        model: LLM provider configuration.
        workspace: Isolated workspace handle for this run.
        hooks: Optional hook manager for lifecycle callbacks.
        trajectory_store: Optional trajectory store for run recording.
        runtime_context: Extra parameters passed to extension points
            (e.g., ``output_schema`` for ExtractorPES).
        llm_client: Optional pre-configured LLM client (created
            automatically if not provided).

    Example:
        >>> from scrivai import BasePES, ModelConfig, load_pes_config
        >>> class MyPES(BasePES):
        ...     pass  # override extension points as needed
        >>> pes = MyPES(
        ...     config=load_pes_config(Path("my_pes.yaml")),
        ...     model=ModelConfig(model="claude-sonnet-4-20250514"),
        ...     workspace=ws,
        ... )
        >>> run = await pes.run("Process this document")
    """

    def __init__(
        self,
        *,
        config: PESConfig,
        model: ModelConfig,
        workspace: WorkspaceHandle,
        hooks: HookManager | None = None,
        trajectory_store: TrajectoryStore | None = None,
        runtime_context: dict[str, Any] | None = None,
        llm_client: "LLMClient | None" = None,
    ) -> None:
        self.config = config
        self.model = model
        self.workspace = workspace
        self.hooks: HookManager | _NullHookManager = hooks or _NullHookManager()
        self.trajectory_store = trajectory_store
        self.runtime_context = runtime_context or {}
        # Deferred import to allow BasePES to be imported without the SDK installed.
        if llm_client is None:
            from scrivai.pes.llm_client import LLMClient as _LLMClient

            llm_client = _LLMClient(model)
        self._llm = llm_client

    # ── Public API ────────────────────────────────────────

    async def run(self, task_prompt: str) -> PESRun:
        """Execute the three-phase pipeline and return the completed run.

        Runs plan → execute → summarize sequentially. Each phase validates
        its file-contract outputs and retries on failure (up to ``max_retries``
        configured per phase).

        Args:
            task_prompt: Natural language description of the task.

        Returns:
            A ``PESRun`` with ``status='completed'`` on success, or
            ``status='failed'`` with ``error`` details on failure.

        Raises:
            PhaseError: If a phase exhausts all retries.
        """
        run = PESRun(
            run_id=self.workspace.run_id,
            pes_name=self.config.name,
            status="running",
            task_prompt=task_prompt,
            started_at=_utcnow(),
            model_name=self.model.model,
            provider=self.model.provider or "",
            sdk_version="",
            skills_git_hash=self.workspace.snapshot.skills_git_hash,
            agents_git_hash=self.workspace.snapshot.agents_git_hash,
        )

        try:
            self.hooks.dispatch("before_run", RunHookContext(run=run))
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
            run.error_type = "hook_error"
            run.ended_at = _utcnow()
            self._persist_final_state(run)
            self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))
            return run

        try:
            for phase in ("plan", "execute", "summarize"):
                result = await self._run_phase_with_retry(phase, run, task_prompt)
                run.phase_results[phase] = result
            run.status = "completed"
        except PhaseError as e:
            run.status = "failed"
            run.error = str(e)
            run.error_type = e.result.error_type if e.result else "sdk_other"
        except (KeyboardInterrupt, asyncio.CancelledError) as e:
            run.status = "cancelled"
            run.error = "interrupted"
            run.error_type = "cancelled"
            self.hooks.dispatch_non_blocking(
                "on_run_cancelled",
                CancelHookContext(run=run, reason=type(e).__name__),
            )
            run.ended_at = _utcnow()
            self._persist_final_state(run)
            self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))
            raise
        finally:
            if run.status != "cancelled":
                run.ended_at = run.ended_at or _utcnow()
                self._persist_final_state(run)
                self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))

        return run

    # ── Three-phase entry points ──────────────────────────

    async def plan(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """Entry point for the plan phase."""
        return await self._run_phase_with_retry("plan", run, task_prompt)

    async def execute_phase(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """Entry point for the execute phase."""
        return await self._run_phase_with_retry("execute", run, task_prompt)

    async def summarize(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """Entry point for the summarize phase."""
        return await self._run_phase_with_retry("summarize", run, task_prompt)

    # ── 4 extension points (all have default implementations) ─────────

    async def build_execution_context(self, phase: str, run: PESRun) -> dict[str, Any]:
        """Build the execution context for this phase. Returns empty dict by default."""
        return {}

    async def build_phase_prompt(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        context: dict[str, Any],
        task_prompt: str,
    ) -> str:
        """Render the prompt for this phase. Default concatenates config.prompt_text + phase prompt + task + context."""
        parts: list[str] = []
        if self.config.prompt_text:
            parts.append(self.config.prompt_text)
        if phase_cfg.additional_system_prompt:
            parts.append(phase_cfg.additional_system_prompt)
        parts.append(task_prompt)
        if context:
            parts.append(json.dumps(context, ensure_ascii=False, default=str))
        return "\n\n".join(parts)

    async def postprocess_phase_result(self, phase: str, result: PhaseResult, run: PESRun) -> None:
        """Post-process the LLM response. Default is a no-op. Exceptions become response_parse_error (not retryable)."""
        return None

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        result: PhaseResult,
        run: PESRun,
    ) -> None:
        """Validate required output files. Default validates each rule in required_outputs.

        Exceptions become output_validation_error (retryable).
        """
        working = self.workspace.working_dir
        for rule in phase_cfg.required_outputs:
            if isinstance(rule, str):
                if not (working / rule).exists():
                    raise PhaseError(phase, f"required output missing: {rule}")
            elif isinstance(rule, dict):
                path = working / rule["path"]
                if not path.is_dir():
                    raise PhaseError(phase, f"required directory missing: {rule['path']}")
                pattern = rule.get("pattern", "*")
                min_files = rule.get("min_files", 1)
                found = list(path.glob(pattern))
                if len(found) < min_files:
                    raise PhaseError(
                        phase,
                        f"{rule['path']}: expected >= {min_files} files "
                        f"matching '{pattern}', found {len(found)}",
                    )

    # ── SDK call (subclass override point) ───────────────

    async def _call_sdk_query(
        self,
        phase_cfg: PhaseConfig,
        prompt: str,
        run: PESRun,
        attempt_no: int,
        on_turn: Callable[[PhaseTurn], None],
    ) -> tuple[str, dict[str, Any], list[PhaseTurn]]:
        """Call LLMClient, translating exceptions to _SDKError(error_type=...).

        - _MaxTurnsError → _SDKError("max_turns_exceeded", ...)
        - _SDKExecutionError / CLIConnectionError / ProcessError / ClaudeSDKError / RuntimeError
          → _SDKError("sdk_other", ...)
        - KeyboardInterrupt / CancelledError bubble up directly to BasePES.run()
        """
        from claude_agent_sdk import ClaudeSDKError, CLIConnectionError, ProcessError

        from scrivai.exceptions import _SDKError
        from scrivai.pes.llm_client import _MaxTurnsError, _SDKExecutionError

        try:
            resp = await self._llm.execute_task(
                prompt=prompt,
                system_prompt=self.config.prompt_text + "\n\n" + phase_cfg.additional_system_prompt,
                allowed_tools=phase_cfg.allowed_tools,
                max_turns=phase_cfg.max_turns,
                permission_mode=phase_cfg.permission_mode,
                cwd=self.workspace.working_dir,
                on_turn=on_turn,
            )
            return resp.result, resp.usage, resp.turns
        except _MaxTurnsError as e:
            raise _SDKError("max_turns_exceeded", str(e)) from e
        except _SDKExecutionError as e:
            raise _SDKError("sdk_other", str(e)) from e
        # RuntimeError covers LLMClient.execute_task internal RuntimeError("no ResultMessage received").
        # Sentinel exception; non-SDK RuntimeErrors are also folded into sdk_other (L2 retry fallback).
        except (CLIConnectionError, ProcessError, ClaudeSDKError, RuntimeError) as e:
            raise _SDKError("sdk_other", str(e)) from e

    # ── Internal: phase-level retry ──────────────────────

    async def _run_phase_with_retry(self, phase: str, run: PESRun, task_prompt: str) -> PhaseResult:
        """Wrap phase-level retry logic; dispatches on_phase_failed uniformly."""
        phase_cfg = self.config.phases[phase]
        last_result: PhaseResult | None = None
        for attempt_no in range(phase_cfg.max_retries + 1):
            if attempt_no > 0:
                self._cleanup_phase_outputs(phase, phase_cfg)
            try:
                return await self._run_phase(phase, run, task_prompt, attempt_no)
            except PhaseError as e:
                last_result = e.result
                will_retry = (
                    attempt_no < phase_cfg.max_retries
                    and e.result is not None
                    and e.result.is_retryable
                )
                fail_ctx = FailureHookContext(
                    run=run,
                    phase=phase,
                    attempt_no=attempt_no,
                    will_retry=will_retry,
                    error_type=e.result.error_type if e.result else "sdk_other",
                    phase_result=e.result
                    or PhaseResult(
                        phase=phase,
                        attempt_no=attempt_no,
                        started_at=_utcnow(),
                        error=str(e),
                    ),
                )
                self.hooks.dispatch_non_blocking("on_phase_failed", fail_ctx)
                if not will_retry:
                    raise
        raise PhaseError(phase, "exhausted retries", result=last_result)

    # ── Internal: single phase attempt ──────────────────

    async def _run_phase(
        self,
        phase: str,
        run: PESRun,
        task_prompt: str,
        attempt_no: int,
    ) -> PhaseResult:
        """Complete flow for a single phase attempt (9 steps)."""
        phase_cfg = self.config.phases[phase]

        # 1. before_phase
        try:
            self.hooks.dispatch(
                "before_phase",
                PhaseHookContext(phase=phase, run=run, attempt_no=attempt_no),
            )
        except Exception as e:
            raise self._hook_error(phase, attempt_no, str(e)) from e

        # 2. build_execution_context
        execution_context = await self.build_execution_context(phase, run)

        # 3. Merge context
        context = self._merge_context(
            runtime=self.runtime_context,
            execution=execution_context,
            framework={
                "phase": phase,
                "attempt_no": attempt_no,
                "workspace": self._workspace_payload(),
                "previous_phase_output": self._read_previous_phase_output(phase),
            },
        )

        # 4. build_phase_prompt + before_prompt
        prompt = await self.build_phase_prompt(phase, phase_cfg, context, task_prompt)
        prompt_ctx = PromptHookContext(
            phase=phase,
            run=run,
            attempt_no=attempt_no,
            prompt=prompt,
            context=context,
        )
        try:
            self.hooks.dispatch("before_prompt", prompt_ctx)
        except Exception as e:
            raise self._hook_error(phase, attempt_no, str(e)) from e
        prompt = prompt_ctx.prompt

        # 5. _call_sdk_query
        started_at = _utcnow()
        try:
            response_text, usage, turns = await self._call_sdk_query(
                phase_cfg,
                prompt,
                run,
                attempt_no,
                on_turn=lambda t: self.hooks.dispatch(
                    "after_prompt_turn",
                    PromptTurnHookContext(phase=phase, run=run, attempt_no=attempt_no, turn=t),
                ),
            )
        except PhaseError:
            raise
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as e:
            # _SDKError carries error_type; other Exception (shouldn't reach here, LLMClient already covers) → sdk_other
            error_type = e.error_type if isinstance(e, _SDKError) else "sdk_other"
            # M1.0 contract: all SDK failures have is_retryable=True (L2 phase retry replaces L1 backoff)
            result = PhaseResult(
                phase=phase,
                attempt_no=attempt_no,
                prompt=prompt,
                response_text="",
                turns=[],
                usage={},
                produced_files=self._list_produced_files(phase),
                error=str(e),
                error_type=error_type,
                is_retryable=True,
                started_at=started_at,
                ended_at=_utcnow(),
            )
            raise PhaseError(phase, str(e), result=result) from e

        # 6. Build PhaseResult
        result = PhaseResult(
            phase=phase,
            attempt_no=attempt_no,
            prompt=prompt,
            response_text=response_text,
            turns=turns,
            usage=usage,
            produced_files=self._list_produced_files(phase),
            started_at=started_at,
            ended_at=_utcnow(),
        )

        # 7. Post-process phase result
        try:
            await self.postprocess_phase_result(phase, result, run)
        except PhaseError:
            raise
        except Exception as e:
            result.error = str(e)
            result.error_type = "response_parse_error"
            result.is_retryable = False
            raise PhaseError(phase, str(e), result=result) from e

        # 8. Validate phase outputs
        try:
            await self.validate_phase_outputs(phase, phase_cfg, result, run)
        except PhaseError as e:
            if e.result is None:
                result.error = str(e)
                result.error_type = "output_validation_error"
                result.is_retryable = True
                e.result = result
            raise
        except Exception as e:
            result.error = str(e)
            result.error_type = "output_validation_error"
            result.is_retryable = True
            raise PhaseError(phase, str(e), result=result) from e

        # 9a. on_output_written (only for summarize + after validation passes)
        if phase == "summarize":
            try:
                self.hooks.dispatch(
                    "on_output_written",
                    OutputHookContext(
                        run=run,
                        output_path=self.workspace.working_dir / "output.json",
                        final_output=run.final_output or {},
                    ),
                )
            except Exception as e:
                raise self._hook_error(phase, attempt_no, str(e)) from e

        # 9b. after_phase hook
        try:
            self.hooks.dispatch(
                "after_phase",
                PhaseHookContext(
                    phase=phase,
                    run=run,
                    attempt_no=attempt_no,
                    phase_result=result,
                ),
            )
        except Exception as e:
            raise self._hook_error(phase, attempt_no, str(e)) from e

        return result

    # ── Internal helpers ──────────────────────────────────

    def _hook_error(self, phase: str, attempt_no: int, msg: str) -> PhaseError:
        """Build a hook_error PhaseResult and wrap it in a PhaseError."""
        result = PhaseResult(
            phase=phase,
            attempt_no=attempt_no,
            prompt="",
            response_text="",
            turns=[],
            usage={},
            produced_files=[],
            started_at=_utcnow(),
            ended_at=_utcnow(),
            error=msg,
            error_type="hook_error",
            is_retryable=False,
        )
        return PhaseError(phase, msg, result=result)

    def _persist_final_state(self, run: PESRun) -> None:
        """Write trajectory synchronously; does not depend on the after_run hook."""
        if self.trajectory_store is None:
            return
        self.trajectory_store.finalize_run(
            run_id=run.run_id,
            status=run.status,
            final_output=run.final_output,
            workspace_archive_path=None,
            error=run.error,
            error_type=run.error_type,
        )

    def _cleanup_phase_outputs(self, phase: str, phase_cfg: PhaseConfig) -> None:
        """Clean up outputs before a retry: delete previous-attempt artifacts listed in required_outputs."""
        working = self.workspace.working_dir
        for rule in phase_cfg.required_outputs:
            if isinstance(rule, str):
                (working / rule).unlink(missing_ok=True)
            elif isinstance(rule, dict) and "path" in rule:
                target = working / rule["path"]
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=False)
                elif target.exists():
                    target.unlink()

    def _merge_context(
        self,
        runtime: dict[str, Any],
        execution: dict[str, Any],
        framework: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge three context layers: runtime < execution < framework (later layers override earlier)."""
        merged: dict[str, Any] = {}
        merged.update(runtime)
        merged.update(execution)
        merged.update(framework)
        return merged

    def _read_previous_phase_output(self, phase: str) -> Any:
        """Read previous phase output: execute reads plan.json, summarize reads findings/."""
        working = self.workspace.working_dir
        if phase == "execute":
            plan_json = working / "plan.json"
            if plan_json.exists():
                return relaxed_json_loads(
                    plan_json.read_text(encoding="utf-8"), strict=self.config.strict_json
                )
        elif phase == "summarize":
            findings = working / "findings"
            if findings.is_dir():
                return {
                    f.name: relaxed_json_loads(
                        f.read_text(encoding="utf-8"), strict=self.config.strict_json
                    )
                    for f in sorted(findings.glob("*.json"))
                }
        return None

    def _list_produced_files(self, phase: str) -> list[str]:
        """List relative paths of all files currently under working/."""
        working = self.workspace.working_dir
        result: list[str] = []
        for p in working.rglob("*"):
            if p.is_file() and not p.name.startswith("."):
                result.append(str(p.relative_to(working)))
        return sorted(result)

    def _workspace_payload(self) -> dict[str, str]:
        """Return a compact dict of workspace directory paths."""
        return {
            "working_dir": str(self.workspace.working_dir),
            "data_dir": str(self.workspace.data_dir),
            "output_dir": str(self.workspace.output_dir),
        }

    def _resolve_cli_tools(self) -> list[str]:
        """Merge external_cli_tools from config and runtime_context.

        Deduplicated, order-preserved.
        """
        from_config = self.config.external_cli_tools
        from_runtime = self.runtime_context.get("external_cli_tools", [])
        seen: set[str] = set()
        result: list[str] = []
        for cmd in [*from_config, *from_runtime]:
            if cmd not in seen:
                seen.add(cmd)
                result.append(cmd)
        return result
