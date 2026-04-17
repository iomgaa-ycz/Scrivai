"""BasePES — 三阶段(plan→execute→summarize)执行引擎抽象基类。

参考:
- docs/design.md §4.2 / §5.1
- docs/superpowers/specs/2026-04-16-scrivai-m0.5-design.md §3.1
"""

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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _NullHookManager:
    """无 hook 时的空 dispatch(避免 if hooks 判断)。"""

    def dispatch(self, hook_name: str, context: object) -> None:
        pass

    def dispatch_non_blocking(self, hook_name: str, context: object) -> None:
        pass


class BasePES:
    """三阶段执行引擎抽象基类。

    子类通过 override _call_sdk_query + 4 个扩展点定制行为。
    M0.5 默认 _call_sdk_query 抛 NotImplementedError;M1 填入真实 SDK。
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
        # 延迟 import(避免无 SDK 场景下 BasePES 无法 import)
        if llm_client is None:
            from scrivai.pes.llm_client import LLMClient as _LLMClient

            llm_client = _LLMClient(model)
        self._llm = llm_client

    # ── 公共 API ──────────────────────────────────────────

    async def run(self, task_prompt: str) -> PESRun:
        """顺序执行 plan → execute → summarize,返回完整 PESRun。"""
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

    # ── 三阶段入口 ────────────────────────────────────────

    async def plan(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """plan 阶段入口。"""
        return await self._run_phase_with_retry("plan", run, task_prompt)

    async def execute_phase(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """execute 阶段入口。"""
        return await self._run_phase_with_retry("execute", run, task_prompt)

    async def summarize(self, run: PESRun, task_prompt: str) -> PhaseResult:
        """summarize 阶段入口。"""
        return await self._run_phase_with_retry("summarize", run, task_prompt)

    # ── 4 个扩展点(全有默认实现) ──────────────────────────

    async def build_execution_context(self, phase: str, run: PESRun) -> dict[str, Any]:
        """构建本阶段的 execution_context。默认返回空 dict。"""
        return {}

    async def build_phase_prompt(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        context: dict[str, Any],
        task_prompt: str,
    ) -> str:
        """渲染本阶段 prompt。默认拼接 config.prompt_text + phase prompt + task + context。"""
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
        """响应后处理。默认 no-op。异常 → response_parse_error(不可重试)。"""
        return None

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        result: PhaseResult,
        run: PESRun,
    ) -> None:
        """校验必需产物。默认按 required_outputs 逐条校验。

        异常 → output_validation_error(可重试)。
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

    # ── SDK 调用(子类 override 点) ────────────────────────

    async def _call_sdk_query(
        self,
        phase_cfg: PhaseConfig,
        prompt: str,
        run: PESRun,
        attempt_no: int,
        on_turn: Callable[[PhaseTurn], None],
    ) -> tuple[str, dict[str, Any], list[PhaseTurn]]:
        """调 LLMClient,翻译异常为 _SDKError(error_type=...)。

        - _MaxTurnsError → _SDKError("max_turns_exceeded", ...)
        - _SDKExecutionError / CLIConnectionError / ProcessError / ClaudeSDKError / RuntimeError
          → _SDKError("sdk_other", ...)
        - KeyboardInterrupt / CancelledError 不接,直接冒泡到 BasePES.run()
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
        # RuntimeError 覆盖 LLMClient.execute_task 内部的 RuntimeError("未收到 ResultMessage")
        # 哨兵异常;非 SDK 来源的 RuntimeError 也归并到 sdk_other(L2 retry 兜底)
        except (CLIConnectionError, ProcessError, ClaudeSDKError, RuntimeError) as e:
            raise _SDKError("sdk_other", str(e)) from e

    # ── 内部:phase 级重试 ────────────────────────────────

    async def _run_phase_with_retry(self, phase: str, run: PESRun, task_prompt: str) -> PhaseResult:
        """包裹 phase 级重试;on_phase_failed 在此统一 dispatch。"""
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

    # ── 内部:单次 phase 尝试 ─────────────────────────────

    async def _run_phase(
        self,
        phase: str,
        run: PESRun,
        task_prompt: str,
        attempt_no: int,
    ) -> PhaseResult:
        """单次 phase 尝试的完整流程(9 步)。"""
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

        # 3. 合并 context
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
            # _SDKError 携带 error_type;其他 Exception(理论上不应到这,LLMClient 已覆盖)→ sdk_other
            error_type = e.error_type if isinstance(e, _SDKError) else "sdk_other"
            # M1.0 契约:所有 SDK 失败 is_retryable=True(L2 phase 重试兜底替代 L1 退避)
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

        # 6. 构造 PhaseResult
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

        # 7. postprocess_phase_result
        try:
            await self.postprocess_phase_result(phase, result, run)
        except PhaseError:
            raise
        except Exception as e:
            result.error = str(e)
            result.error_type = "response_parse_error"
            result.is_retryable = False
            raise PhaseError(phase, str(e), result=result) from e

        # 8. validate_phase_outputs
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

        # 9a. on_output_written(仅 summarize + validate 通过)
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

        # 9b. after_phase
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

    # ── 内部辅助 ──────────────────────────────────────────

    def _hook_error(self, phase: str, attempt_no: int, msg: str) -> PhaseError:
        """构造 hook_error PhaseResult + PhaseError。"""
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
        """sync 写 trajectory;不依赖 after_run hook。"""
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
        """重试前清场:按 required_outputs 删除上一轮产物。"""
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
        """三层 context 合并:runtime < execution < framework。"""
        merged: dict[str, Any] = {}
        merged.update(runtime)
        merged.update(execution)
        merged.update(framework)
        return merged

    def _read_previous_phase_output(self, phase: str) -> Any:
        """读前序 phase 产物:execute 读 plan.json,summarize 读 findings/。"""
        working = self.workspace.working_dir
        if phase == "execute":
            plan_json = working / "plan.json"
            if plan_json.exists():
                return json.loads(plan_json.read_text(encoding="utf-8"))
        elif phase == "summarize":
            findings = working / "findings"
            if findings.is_dir():
                return {
                    f.name: json.loads(f.read_text(encoding="utf-8"))
                    for f in sorted(findings.glob("*.json"))
                }
        return None

    def _list_produced_files(self, phase: str) -> list[str]:
        """列出 working/ 下所有文件的相对路径。"""
        working = self.workspace.working_dir
        result: list[str] = []
        for p in working.rglob("*"):
            if p.is_file() and not p.name.startswith("."):
                result.append(str(p.relative_to(working)))
        return sorted(result)

    def _workspace_payload(self) -> dict[str, str]:
        """workspace 信息精简 dict。"""
        return {
            "working_dir": str(self.workspace.working_dir),
            "data_dir": str(self.workspace.data_dir),
            "output_dir": str(self.workspace.output_dir),
        }
