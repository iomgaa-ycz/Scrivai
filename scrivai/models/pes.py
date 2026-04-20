"""PES execution engine data models: ModelConfig, PESConfig, PESRun, and hook contexts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ────────────────────── Base configuration classes ──────


class ModelConfig(BaseModel):
    """LLM provider configuration.

    At minimum, provide a ``model`` name. The API key and base URL are read
    from environment variables by default (``ANTHROPIC_API_KEY``,
    ``ANTHROPIC_BASE_URL``).

    Args:
        model: Model identifier (e.g., ``"claude-sonnet-4-20250514"``).
        base_url: API base URL. ``None`` uses the SDK default.
        api_key: API key. Usually read from ``ANTHROPIC_API_KEY`` env var.
        provider: Provider tag for trajectory recording
            (e.g., ``"anthropic"``, ``"glm"``).
        fallback_model: Fallback model identifier for degraded operation.

    Example:
        >>> from scrivai import ModelConfig
        >>> model = ModelConfig(model="claude-sonnet-4-20250514")
        >>> model = ModelConfig(
        ...     model="glm-5.1",
        ...     base_url="https://gateway.example.com",
        ...     api_key="sk-xxx",
        ...     provider="glm",
        ... )
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="Model identifier, e.g. 'claude-sonnet-4-6'.")
    base_url: Optional[str] = Field(default=None, description="API base URL; None uses the SDK default.")
    api_key: Optional[str] = Field(default=None, description="API key; usually read from env.")
    provider: Optional[str] = Field(default=None, description="Provider tag, e.g. anthropic / glm / minimax.")
    fallback_model: Optional[str] = Field(default=None, description="Fallback model identifier for degraded operation.")


class PhaseConfig(BaseModel):
    """Configuration for a single phase (plan, execute, or summarize)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Phase name: one of plan / execute / summarize (BasePES iterates over exactly these three names).",
    )
    allowed_tools: list[str] = Field(..., description="SDK allowed_tools list.")
    max_turns: int = Field(default=10, description="Maximum Agent interaction turns within a single query.")
    max_retries: int = Field(default=1, description="Phase-level retry count (L2 retry).")
    permission_mode: str = Field(default="default", description="SDK permission_mode.")
    required_outputs: list[Union[str, dict[str, Any]]] = Field(
        default_factory=list,
        description=(
            "Required output rules: a string path (file must exist) or a directory rule "
            "{'path':'findings/','min_files':1,'pattern':'*.json'}."
        ),
    )


class PESConfig(BaseModel):
    """Full PES configuration (loaded from YAML)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="PES type name: extractor / auditor / generator / custom.")
    display_name: str = Field(default="", description="Display name for use by the business-layer UI.")
    prompt_text: str = Field(..., description="Base system prompt.")
    default_skills: list[str] = Field(default_factory=list, description="Default skills to load.")
    phases: dict[str, PhaseConfig] = Field(..., description="Phase configurations indexed by phase name.")
    strict_json: bool = Field(
        default=False,
        description="When True, JSON parsing uses strict json.loads mode and skips fault-tolerant repair.",
    )
    external_cli_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Bash command prefixes the agent is allowed to execute. "
            "Business layer injects per-run tools (e.g. 'qmd search --collection tender_001'). "
            "Prompt-level constraint, not SDK-enforced."
        ),
    )


# ────────────────────── Runtime state ───────────────────


class PhaseTurn(BaseModel):
    """A single Agent turn (fine-grained trajectory entry)."""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(..., description="Zero-based turn index.")
    role: Literal["assistant", "user"] = Field(..., description="'user' role represents a tool result.")
    content_type: Literal["text", "tool_use", "tool_result", "thinking"]
    data: dict[str, Any] = Field(..., description="Raw message data (preserved in full).")
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
    """Complete result for a single phase."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(default=0, description="Attempt number for this phase (0 = first; incremented on phase-level retry).")
    prompt: str = Field(default="", description="The fully assembled prompt sent to the LLM.")
    response_text: str = Field(default="", description="Final text response from the LLM.")
    turns: list[PhaseTurn] = Field(default_factory=list)
    produced_files: list[str] = Field(
        default_factory=list,
        description="Files written during this phase (relative to working_dir).",
    )
    usage: dict[str, Any] = Field(default_factory=dict, description="SDK token usage statistics.")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(
        default=None, description="Error category (see design §5.3.4)."
    )
    is_retryable: bool = Field(default=False, description="Whether this failure is suitable for a phase-level retry.")


PESRunStatus = Literal["running", "completed", "failed", "cancelled"]


class PESRun(BaseModel):
    """Complete state of a single PES execution."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Caller-assigned; same as workspace name; globally unique.")
    pes_name: str = Field(..., description="PES type: extractor / auditor / generator / custom.")
    status: PESRunStatus = Field(default="running", description="Current run status.")
    task_prompt: str = Field(..., description="Task description passed in by the business layer.")
    phase_results: dict[str, PhaseResult] = Field(
        default_factory=dict,
        description="Results indexed by phase name (multiple retries of the same phase keep only the last attempt).",
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
    provider: str = Field(default="", description="Provider tag, e.g. anthropic / glm / minimax.")
    sdk_version: str = Field(default="", description="claude-agent-sdk version string.")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(default=None, description="Error category on failure.")

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return a compact dict suitable for injection into prompt context."""
        return {
            "run_id": self.run_id,
            "pes_name": self.pes_name,
            "status": self.status,
            "phase_results": list(self.phase_results.keys()),
        }


# ────────────────────── 9 HookContext types ─────────────────


class HookContext(BaseModel):
    """Base class for all HookContexts; provides the minimal shared context across plugins."""

    model_config = ConfigDict(extra="forbid")

    run: PESRun


class RunHookContext(HookContext):
    """Context for before_run / after_run hooks."""

    pass


class PhaseHookContext(HookContext):
    """Context for before_phase / after_phase hooks."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(..., description="Attempt number for this phase.")
    phase_result: Optional[PhaseResult] = Field(
        default=None, description="Final phase result, present in after_phase."
    )


class PromptHookContext(HookContext):
    """Context for before_prompt hook; allows the hook to modify the prompt."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    prompt: str = Field(..., description="Fully rendered prompt (hooks may modify this field).")
    context: dict[str, Any] = Field(default_factory=dict, description="Merged execution context.")


class PromptTurnHookContext(HookContext):
    """Context for after_prompt_turn hook; fired once per SDK turn."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    turn: PhaseTurn


class FailureHookContext(HookContext):
    """Context for the on_phase_failed hook."""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    will_retry: bool = Field(..., description="Whether this phase will be attempted again.")
    error_type: PhaseErrorType
    phase_result: PhaseResult


class OutputHookContext(HookContext):
    """Context for on_output_written hook (fired once after the summarize phase passes validation)."""

    output_path: Path
    final_output: dict[str, Any]


class CancelHookContext(HookContext):
    """Context for the on_run_cancelled hook."""

    reason: str = Field(
        default="", description="Cancellation reason (KeyboardInterrupt / asyncio.CancelledError)."
    )
