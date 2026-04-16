# 附录 B：Claude Agent SDK 集成

> **版本**: v3（2026-04-15）
> **定位**: 本文是 `docs/design.md` 的附录，专责补充 **Claude Agent SDK 层面的调用模式**。权威信息以 `design.md` 为准；若冲突以 `design.md` 为准。
> **对应章节**: `design.md §5.1 AgentSession 实现要点`

## B.1 为什么要这份附录

`design.md §5.1` 已给出 `_AgentSession.run(...)` 的伪代码骨架，但 PES 三阶段在 `ClaudeAgentOptions` 字段层面的差异、`allowed_tools` 策略、以及"为什么不走 MCP"这类决策都应有固定位置。本附录补这个空缺。

## B.2 Claude Agent SDK 调用范式

Scrivai 通过 `claude_agent_sdk.query()` 异步迭代器消费 SDK：

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(prompt=task_prompt, options=options):
    # message: UserMessage | AssistantMessage | ResultMessage | ToolUseMessage | ...
    ...
```

**不用** `Client` 长连接模式 —— Scrivai 每个 PES 阶段独立调一次 `query()`，阶段间状态通过 workspace 文件传递（见 `design.md §4.1.1`），不共享 SDK 会话。

理由：
1. 每阶段 `allowed_tools` 不同，独立 options 更清晰
2. 阶段间失败可重跑单阶段，不必重放整个会话
3. trajectory 分阶段归档，便于 EvoSkill 评估粒度控制

## B.3 `ClaudeAgentOptions` 字段规范

以下字段在三阶段可能不同（❗ 表示必须按阶段定制），其余统一：

| 字段 | plan | execute | summarize | 说明 |
|---|---|---|---|---|
| `model` | agent.model | agent.model | agent.model | 一般全程同模型 |
| `fallback_model` | 可选 | 可选 | 可选 | 对齐 model 配置 |
| `base_url` / `api_key` | 同 | 同 | 同 | 从 `ModelConfig` 注入 |
| `cwd` | `workspace/working` | `workspace/working` | `workspace/working` | 所有阶段运行在 working/ 内 |
| `system_prompt` ❗ | plan prompt | execute prompt | summarize prompt | `PromptManager` 组装（agent.prompt_text + phase.additional_system_prompt + 上阶段摘要引用） |
| `allowed_tools` ❗ | 见 B.4 | 见 B.4 | 见 B.4 | 每阶段不同 |
| `permission_mode` | `"default"` | `"default"` | `"default"` | 不使用 `"bypassPermissions"` |
| `max_turns` | `phase.max_turns` | `phase.max_turns` | `phase.max_turns` | 从 `PhaseConfig` 读 |
| `hooks` | 同 | 同 | 同 | 见 B.6 |
| `mcp_servers` | `[]` | `[]` | `[]` | **恒空**（见 B.5） |

`PhaseConfig` 字段（见 `design.md §4.1` / `scrivai/models/agent.py`）：

```python
class PhaseConfig(BaseModel):
    additional_system_prompt: str
    allowed_tools: list[str]
    max_turns: int
```

## B.4 `allowed_tools` 矩阵

v3 已收紧 summarize 的工具集。三阶段策略如下：

| 工具 | plan | execute | summarize | 备注 |
|---|---|---|---|---|
| `Bash` | ✅ | ✅ | ✅ | CLI 工具调用入口 |
| `Read` | ✅ | ✅ | ✅ | 读 working/ 下文件 |
| `Write` | ✅ | ✅ | ✅ | 写 plan.md / findings / output.json |
| `Edit` | ❌ | ✅ | ❌ | 仅 execute 编辑 findings |
| `Glob` | ✅ | ✅ | ❌ | summarize 不需要探索，避免发散（v3 变更） |
| `Grep` | ✅ | ✅ | ❌ | 同上 |
| `WebSearch` / `WebFetch` | ❌ | ❌ | ❌ | 禁止联网，避免非确定性 |
| `Task`（subagent） | ❌ | ❌ | ❌ | v3 M0–M2 禁用，简化问题 |
| `TodoWrite` | ❌ | ❌ | ❌ | agent 不维护 todo，flow 由 PESRunner 控 |

**强制不变量**：summarize 阶段 `allowed_tools == ["Bash", "Read", "Write"]`。由 `scrivai/llm/tools_policy.py` 集中实现，PESRunner 装配时校验。

## B.5 CLI + Bash vs MCP：决策记录

**决策**：v3 **不使用** MCP server 模式，所有 Scrivai 工具通过 `scrivai-cli <group> <cmd>` + Agent 的 `Bash` tool 暴露。

**理由**：
1. **Herald2 验证**：CLI+Bash 模式已在 Herald2（`Reference/Herald2/`）走通，可预测性高
2. **调试简单**：agent 调的是标准 subprocess，stdout/stderr 可重放；MCP 协议栈增加断点成本
3. **快照兼容**：CLI 二进制在 PATH 里，workspace snapshot 只管 skills；MCP server 要嵌入配置反倒破坏隔离
4. **无状态约束**：CLI 每次调用短进程，不留 session；MCP 长连接会引入隐藏状态

**什么时候会重新评估**：
- 若 Claude Agent SDK 对 MCP 提供原生 trajectory 支持并优于 subprocess logging
- 若单次调用的冷启动开销（python import）在生产中成为瓶颈（M3 再测）

## B.6 Hook 策略

`ClaudeAgentOptions.hooks` 统一装配三类：

```python
hooks = {
    "PreToolUse": [log_tool_call_hook],      # 记录 agent 调用的每个 Bash 命令
    "PostToolUse": [log_tool_result_hook],   # 记录返回值（truncated to 10KB）
    "Stop": [check_phase_output_hook],       # 阶段结束时校验 working/ 下必须产物存在
}
```

- `PreToolUse` / `PostToolUse`：写 `workspace/logs/trajectory_<phase>.jsonl`，EvoSkill 训练数据来源
- `Stop`：校验（plan 阶段必须有 `working/plan.md` + `plan.json`；execute 阶段至少有一个 `findings/*.json`；summarize 阶段必须有 `working/output.json`），未通过则 `PESRunner` 抛 `PhaseContractError`

## B.7 Session 生命周期与错误处理

| 情形 | 处理 |
|---|---|
| 阶段达到 `max_turns` | `PhaseResult.status="max_turns_exceeded"`；下阶段不启动；`AgentRunResult` 整体失败 |
| SDK 抛 `RateLimitError` | 指数退避重试 3 次（1s / 4s / 16s）；仍失败则抛出 |
| SDK 抛 `AnthropicError`（其它） | 不重试，直接冒泡；保留 workspace 供排查 |
| Python 侧 `KeyboardInterrupt` | 取消当前 `query()`；当前阶段记为 `status="interrupted"`；workspace 不清理 |
| Hook `Stop` 校验失败 | 当前阶段记 `status="contract_violation"` + 缺失文件列表；不继续下阶段 |

**取消语义**：SDK 的异步迭代器在 `cancel()` 时会优雅终止，当前工具调用的子进程由 SDK 负责发 SIGTERM。Scrivai 不额外追加 kill -9 逻辑。

## B.8 PES 阶段间契约落地在 SDK 层的表现

`design.md §4.1.1` 规定阶段间通过文件传递（plan.md / findings/ / output.json）。在 SDK 层的具体表现：

1. **plan 阶段的 `system_prompt`** 末尾强制追加：`"After planning, you MUST write working/plan.md and working/plan.json. Do not call execute-phase tools."`
2. **execute 阶段的 `system_prompt`** 开头追加：`"Read working/plan.json first. For each item, write working/findings/<item_id>.json."`（agent 通过 Read 读计划）
3. **summarize 阶段的 `system_prompt`** 开头追加：`"Read all working/findings/*.json. Write working/output.json with the final summary."`

这些追加由 `PromptManager.build_system_prompt(phase, ...)` 固定拼接，agent profile 的 YAML 无需手写。

## B.9 和 design.md 的章节映射

| 本附录章节 | 对应 design.md 章节 |
|---|---|
| B.2 调用范式 | §5.1 |
| B.3 Options 字段 | §5.1（伪代码） |
| B.4 allowed_tools | §4.1 `PhaseConfig` + v3 变更第 5 条 |
| B.5 CLI+Bash vs MCP | §2 系统关系图 + §4.4 |
| B.6 Hooks | §4.5 不变量 |
| B.7 错误处理 | — 新增 |
| B.8 阶段间契约 | §4.1.1 PES 文件契约 |

## B.10 变更纪律

`ClaudeAgentOptions` 字段映射 / `allowed_tools` 矩阵变更 → 先走 `GOVDOC_PROGRAM_PLAN.md §8 变更流程`，同步更新 `design.md §5.1` 与本附录 B.3 / B.4 表格。
