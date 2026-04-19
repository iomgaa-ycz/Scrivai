"""PES execution engine data models: ModelConfig, PESConfig, PESRun, and hook contexts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ────────────────────── 基础配置类 ──────────────────────


class ModelConfig(BaseModel):
    """LLM provider configuration (model ID, base_url, api_key, etc.)."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="Model identifier, e.g. 'claude-sonnet-4-6'.")
    base_url: Optional[str] = Field(default=None, description="API base URL; None uses the SDK default.")
    api_key: Optional[str] = Field(default=None, description="API key; usually read from the environment.")
    provider: Optional[str] = Field(default=None, description="Provider tag: 'anthropic', 'glm', 'minimax', etc.")
    fallback_model: Optional[str] = Field(default=None, description="Fallback model identifier for degraded operation.")


class PhaseConfig(BaseModel):
    """Configuration for a single PES phase (plan, execute, or summarize)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Phase name: one of 'plan', 'execute', or 'summarize'.",
    )
    additional_system_prompt: str = Field(default="", description="Phase-specific system prompt appended to the base prompt.")
    allowed_tools: list[str] = Field(..., description="SDK allowed_tools list for this phase.")
    max_turns: int = Field(default=10, description="Maximum Agent turns per query within this phase.")
    max_retries: int = Field(default=1, description="Phase-level retry count (L2 retry).")
    permission_mode: str = Field(default="default", description="SDK permission_mode for this phase.")
    required_outputs: list[Union[str, dict[str, Any]]] = Field(
        default_factory=list,
        description=(
            "Required output rules: a file path string (passes if file exists) or a directory rule "
            "dict {'path': 'findings/', 'min_files': 1, 'pattern': '*.json'}."
        ),
    )


class PESConfig(BaseModel):
    """PES configuration loaded from a YAML file via ``load_pes_config()``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="PES type name: 'extractor', 'auditor', 'generator', or custom.")
    display_name: str = Field(default="", description="Human-readable display name for business-layer UIs.")
    prompt_text: str = Field(..., description="Base system prompt text.")
    default_skills: list[str] = Field(default_factory=list, description="Skills loaded by default.")
    phases: dict[str, PhaseConfig] = Field(..., description="Phase configurations keyed by phase name.")
    strict_json: bool = Field(
        default=False,
        description="If True, JSON parsing uses strict json.loads and skips fault-tolerant repair.",
    )


# ────────────────────── 运行态 ──────────────────────


class PhaseTurn(BaseModel):
    """A single Agent turn captured in the fine-grained trajectory."""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(..., description="Zero-based turn index within the phase.")
    role: Literal["assistant", "user"] = Field(..., description="'user' indicates a tool result message.")
    content_type: Literal["text", "tool_use", "tool_result", "thinking"]
    data: dict[str, Any] = Field(..., description="Raw message data preserved in full.")
    timestamp: datetime


PhaseErrorType = Literal[
    "sdk_rate_limit",
    "sdk_other",
    "max_turns_exceeded",
    "response_parse_error",
    "output_validation_error",
    "cancelled",
    "hook_error",
]


class PhaseResult(BaseModel):
    """Result of a single phase (plan, execute, or summarize)."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(default=0, description="Attempt index for this phase (0 = first attempt; increments on phase-level retry).")
    prompt: str = Field(default="", description="Final assembled prompt sent to the LLM.")
    response_text: str = Field(default="", description="Final text response from the LLM.")
    turns: list[PhaseTurn] = Field(default_factory=list)
    produced_files: list[str] = Field(
        default_factory=list,
        description="Files written by this phase (relative to working_dir).",
    )
    usage: dict[str, Any] = Field(default_factory=dict, description="SDK token usage statistics.")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(
        default=None, description="Error category (see design §5.3.4)."
    )
    is_retryable: bool = Field(default=False, description="Whether this failure is eligible for a phase-level retry.")


PESRunStatus = Literal["running", "completed", "failed", "cancelled"]


class PESRun(BaseModel):
    """Complete state of a single PES execution run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Caller-assigned globally unique ID; workspace directory shares this name.")
    pes_name: str = Field(..., description="PES type: 'extractor', 'auditor', 'generator', or custom.")
    status: PESRunStatus = Field(default="running", description="Current run status.")
    task_prompt: str = Field(..., description="Task description provided by the business layer.")
    phase_results: dict[str, PhaseResult] = Field(
        default_factory=dict,
        description="Phase results keyed by phase name (multiple retries keep only the last attempt).",
    )
    final_output: Optional[dict[str, Any]] = Field(
        default=None, description="Parsed content of output.json produced by the summarize phase."
    )
    final_output_path: Optional[Path] = Field(
        default=None, description="Absolute path to working/output.json."
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Business-layer extension fields.")
    skills_git_hash: Optional[str] = None
    agents_git_hash: Optional[str] = None
    skills_is_dirty: bool = Field(default=False, description="True if the source git repo had uncommitted changes at snapshot time.")
    model_name: str = Field(..., description="Model identifier used for this run.")
    provider: str = Field(default="", description="Provider tag: 'anthropic', 'glm', 'minimax', etc.")
    sdk_version: str = Field(default="", description="claude-agent-sdk version string.")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(default=None, description="Error category when the run fails.")

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return a minimal dict suitable for injection into a prompt context."""
        return {
            "run_id": self.run_id,
            "pes_name": self.pes_name,
            "status": self.status,
            "phase_results": list(self.phase_results.keys()),
        }


# ────────────────────── 9 个 HookContext ──────────────────────


class HookContext(BaseModel):
    """Base class for all HookContext types; carries the minimum shared state across plugins."""

    model_config = ConfigDict(extra="forbid")

    run: PESRun


class RunHookContext(HookContext):
    """Context for before_run / after_run hooks."""

    pass


class PhaseHookContext(HookContext):
    """Context for before_phase / after_phase hooks."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(..., description="Attempt index for this phase.")
    phase_result: Optional[PhaseResult] = Field(
        default=None, description="Final phase result, available in after_phase."
    )


class PromptHookContext(HookContext):
    """Context for before_prompt hooks; plugins may modify ``context.prompt``."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    prompt: str = Field(..., description="Fully rendered prompt (plugins may modify this field).")
    context: dict[str, Any] = Field(default_factory=dict, description="Merged full prompt context.")


class PromptTurnHookContext(HookContext):
    """Context for after_prompt_turn hooks; fired once per SDK turn."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    turn: PhaseTurn


class FailureHookContext(HookContext):
    """Context for on_phase_failed hooks."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    will_retry: bool = Field(..., description="True if the phase will be retried.")
    error_type: PhaseErrorType
    phase_result: PhaseResult


class OutputHookContext(HookContext):
    """Context for on_output_written hooks (fired once after summarize validates successfully)."""

    output_path: Path
    final_output: dict[str, Any]


class CancelHookContext(HookContext):
    """Context for on_run_cancelled hooks."""

    reason: str = Field(
        default="", description="Cancellation reason (e.g. KeyboardInterrupt or asyncio.CancelledError)."
    )
