"""PES 执行引擎相关 pydantic + 9 个 HookContext。

参考 docs/design.md §4.1 / §4.3。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# ────────────────────── 基础配置类 ──────────────────────


class ModelConfig(BaseModel):
    """LLM 模型配置(model id / base_url / api_key 等)。"""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="模型 id,如 'claude-sonnet-4-6'")
    base_url: Optional[str] = Field(default=None, description="API base URL,None 走 SDK 默认")
    api_key: Optional[str] = Field(default=None, description="API key;通常从 env 读")
    provider: Optional[str] = Field(default=None, description="anthropic / glm / minimax 等")
    fallback_model: Optional[str] = Field(default=None, description="降级模型 id")


class PhaseConfig(BaseModel):
    """单阶段配置(plan / execute / summarize 任一)。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description=("阶段名:固定为 plan / execute / summarize 之一(BasePES 只迭代这三个名字)。"),
    )
    additional_system_prompt: str = Field(default="", description="阶段特定 system prompt 追加")
    allowed_tools: list[str] = Field(..., description="SDK allowed_tools 列表")
    max_turns: int = Field(default=10, description="单次 query 内 Agent 最多交互轮数")
    max_retries: int = Field(default=1, description="Phase 级重试次数(L2 重试)")
    permission_mode: str = Field(default="default", description="SDK permission_mode")
    required_outputs: list[Union[str, dict[str, Any]]] = Field(
        default_factory=list,
        description=(
            "必需产物规则:字符串路径(文件存在即通过)或目录规则 "
            "{'path':'findings/','min_files':1,'pattern':'*.json'}"
        ),
    )


class PESConfig(BaseModel):
    """整个 PES 配置(从 YAML 加载)。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="PES 类型名:extractor / auditor / generator / 自定义")
    display_name: str = Field(default="", description="显示名(给业务层 UI 用)")
    prompt_text: str = Field(..., description="基础 system prompt")
    default_skills: list[str] = Field(default_factory=list, description="默认装入 skills")
    phases: dict[str, PhaseConfig] = Field(..., description="按 phase 名索引的阶段配置")
    strict_json: bool = Field(
        default=False,
        description="True 时 JSON 解析使用 json.loads 严格模式,跳过容错修复",
    )


# ────────────────────── 运行态 ──────────────────────


class PhaseTurn(BaseModel):
    """单次 Agent turn(细粒度轨迹)。"""

    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(..., description="从 0 开始")
    role: Literal["assistant", "user"] = Field(..., description="user 是 tool result")
    content_type: Literal["text", "tool_use", "tool_result", "thinking"]
    data: dict[str, Any] = Field(..., description="原始消息数据(完整保留)")
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
    """单阶段完整结果。"""

    model_config = ConfigDict(extra="forbid")

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(default=0, description="本阶段第几次尝试(0 表首次;随 phase 级重试递增)")
    prompt: str = Field(default="", description="最终拼接后的完整 prompt")
    response_text: str = Field(default="", description="LLM 最终 text")
    turns: list[PhaseTurn] = Field(default_factory=list)
    produced_files: list[str] = Field(
        default_factory=list,
        description="该阶段写入的文件(相对 working_dir)",
    )
    usage: dict[str, Any] = Field(default_factory=dict, description="SDK token 统计")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(
        default=None, description="错误分类(详见 design §5.3.4)"
    )
    is_retryable: bool = Field(default=False, description="本次失败是否适合 phase 级重试")


PESRunStatus = Literal["running", "completed", "failed", "cancelled"]


class PESRun(BaseModel):
    """一次 PES 执行的完整状态。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="调用方指定;workspace 同名;全局唯一")
    pes_name: str = Field(..., description="extractor / auditor / generator / 自定义")
    status: PESRunStatus = Field(default="running", description="当前状态")
    task_prompt: str = Field(..., description="业务层传入的任务描述")
    phase_results: dict[str, PhaseResult] = Field(
        default_factory=dict,
        description="按 phase 名索引的结果(同 phase 多次重试只留最后一次 attempt)",
    )
    final_output: Optional[dict[str, Any]] = Field(
        default=None, description="summarize 阶段 output.json 解析内容"
    )
    final_output_path: Optional[Path] = Field(
        default=None, description="working/output.json 绝对路径"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="业务扩展字段")
    skills_git_hash: Optional[str] = None
    agents_git_hash: Optional[str] = None
    skills_is_dirty: bool = Field(default=False, description="快照时源 git 有未提交修改则 True")
    model_name: str = Field(..., description="使用的模型 id")
    provider: str = Field(default="", description="anthropic / glm / minimax 等")
    sdk_version: str = Field(default="", description="claude-agent-sdk 版本号")
    started_at: datetime
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    error_type: Optional[PhaseErrorType] = Field(default=None, description="失败时的错误分类")

    def to_prompt_payload(self) -> dict[str, Any]:
        """返回供 prompt context 注入的精简 dict。"""
        return {
            "run_id": self.run_id,
            "pes_name": self.pes_name,
            "status": self.status,
            "phase_results": list(self.phase_results.keys()),
        }


# ────────────────────── 9 个 HookContext ──────────────────────


class HookContext(BaseModel):
    """所有 HookContext 的基类,跨插件共享的最小语境。"""

    model_config = ConfigDict(extra="forbid")

    run: PESRun


class RunHookContext(HookContext):
    """before_run / after_run 上下文。"""

    pass


class PhaseHookContext(HookContext):
    """before_phase / after_phase 上下文。"""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int = Field(..., description="本阶段第几次尝试")
    phase_result: Optional[PhaseResult] = Field(
        default=None, description="after_phase 时携带最终结果"
    )


class PromptHookContext(HookContext):
    """before_prompt 上下文,允许修改 prompt。"""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    prompt: str = Field(..., description="渲染后的完整 prompt(允许 hook 修改)")
    context: dict[str, Any] = Field(default_factory=dict, description="合并后的完整 context")


class PromptTurnHookContext(HookContext):
    """after_prompt_turn 上下文,每个 SDK turn 触发一次。"""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    turn: PhaseTurn


class FailureHookContext(HookContext):
    """on_phase_failed 上下文。"""

    phase: Literal["plan", "execute", "summarize"]
    attempt_no: int
    will_retry: bool = Field(..., description="是否会再次尝试本 phase")
    error_type: PhaseErrorType
    phase_result: PhaseResult


class OutputHookContext(HookContext):
    """on_output_written 上下文(仅 summarize 阶段 validate 通过后触发一次)。"""

    output_path: Path
    final_output: dict[str, Any]


class CancelHookContext(HookContext):
    """on_run_cancelled 上下文。"""

    reason: str = Field(
        default="", description="取消原因(KeyboardInterrupt / asyncio.CancelledError)"
    )
