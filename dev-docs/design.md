# Scrivai 设计文档

**日期**: 2026-04-15
**项目**: Scrivai
**定位**: 文档审核 / 生成场景下的 **Claude Agent 编排框架**

---

## 1. 定位

Scrivai 是一套**通用的 Agent 执行与进化框架**，面向"基于 Claude Agent SDK 的长文档审核 / 生成"类应用。它提供：

- **BasePES 三阶段执行引擎** + Hook 系统（机制层）
- **三个预置 PES**：Extractor / Auditor / Generator（业务模式层）
- **Workspace 沙箱**：每次 run 的隔离目录 + 可复现快照
- **Knowledge Library**：包装 qmd 的 rules / cases / templates 三种知识库
- **IO 工具**：docx / doc / pdf ↔ markdown，docxtpl 模板渲染
- **TrajectoryStore**：完整的运行轨迹持久化 + 人类反馈记录
- **Skill 进化机制**：EvoSkill 五阶段 + 从轨迹自动构建评测集
- **scrivai-cli**：Agent 通过 Bash 调用的工具命令行

| 维度 | 要点 |
|---|---|
| **知道什么** | Agent SDK 的调用模式、PES 三阶段语义、沙箱化、通用知识库、文档 I/O、CLI 工具规范、Skill 装入约定、轨迹记录、Skill 进化 |
| **不知道什么** | 业务领域（招标 / 政府采购 / 医疗 / 法律）；具体业务 prompt；具体业务 schema |
| **依赖** | qmd-py（向量数据库）、claude-agent-sdk、pydantic v2 |
| **被谁用** | 任何基于 Claude Agent 做"长文档审核 / 生成"的应用 |
| **禁止** | 源码出现业务领域术语（如 `招标 / 政府采购 / 审核点 / 底稿 / 投标人`） |

核心范式：**Agent 是编排者，Python 提供工具（CLI）与沙箱（Workspace）；业务层只需写 prompt + skill + 业务 CLI**。

---

## 2. 系统关系

```
业务应用（如 GovDoc-Auditor）
   │
   │ 1. Python 调用：选择或子类化 PES，传入 model / workspace / task_prompt
   │ 2. Agent 中途通过 Bash 调用 scrivai-cli / qmd / 业务 CLI
   ▼
┌──────────────────────────────────────────────────────────┐
│ Scrivai                                                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ scrivai.pes.BasePES（三阶段执行引擎 + Hook）     │   │
│  │   plan → execute → summarize                     │   │
│  │   双层 context：runtime + execution              │   │
│  │   8 个 hook 触点                                 │   │
│  └──┬───────────────────────────────────────────────┘   │
│     │ 被继承                                             │
│  ┌──▼──────────────┬──────────────┬──────────────┐      │
│  │ ExtractorPES    │ AuditorPES   │ GeneratorPES │      │
│  │ 抽取结构化条目  │ 对照审核     │ 模板生成     │      │
│  └─────────────────┴──────────────┴──────────────┘      │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ WorkspaceManager                                 │   │
│  │   ~/.scrivai/workspaces/<run_id>/                │   │
│  │     working/.claude/(skills|agents)  ← 快照复制  │   │
│  │     data/   output/   logs/   meta.json          │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ TrajectoryStore（SQLite，跨 run 持久化）          │   │
│  │   runs / phases / tool_calls / feedback           │   │
│  │   TrajectoryRecorderHook 自动插入 BasePES         │   │
│  └──┬───────────────────────────────────────────────┘   │
│     │ 累积到足量 (draft, final) pairs                    │
│  ┌──▼──────────────────────────────────────────────┐    │
│  │ EvolutionTrigger → run_evolution                │    │
│  │   从 trajectory 构建 eval_dataset               │    │
│  │   五阶段：Base → Proposer → Generator →         │    │
│  │            Evaluator → Frontier                 │    │
│  │   产出候选 git 分支（人工 PR 合并）             │    │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 工具层                                           │   │
│  │   knowledge/   RuleLibrary / CaseLibrary /       │   │
│  │                TemplateLibrary（qmd 包装）       │   │
│  │   io/          docx2md / doc2md / pdf2md /       │   │
│  │                DocxRenderer                       │   │
│  │   cli/         scrivai-cli library/io/workspace  │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
             │ Python API + qmd CLI
             ▼
        qmd-py（向量数据库）
```

---

## 3. 上游契约：qmd-py

```python
from qmd import (
    ChunkRef, SearchResult, CollectionInfo,
    Collection, QmdClient, connect,
)
```

CLI（Agent 通过 Bash 调）：

```bash
qmd search --collection <name> --query <q> [--top-k 5] [--rerank] [--filters '{}']
qmd document {get,add,delete,list}
qmd collection {info,list}
```

Scrivai 对 qmd 的使用模式：
- `scrivai.knowledge` 内部 `import qmd`（直接用 Python API）
- Agent 通过 Bash 调 `qmd search ...`（不走 Python）
- 业务层通过 `scrivai.build_qmd_client_from_config(db_path)` 拿 QmdClient（不直接 `import qmd`）

固定 collection 约定：

| Scrivai Library | qmd collection 名 | 内容 |
|---|---|---|
| `RuleLibrary` | `"rules"` | 法规 / 指引 / 标准的 markdown 分块 |
| `CaseLibrary` | `"cases"` | 历史定稿（经专家审核的优质样本） |
| `TemplateLibrary` | `"templates"` | 模板文件（供相似度匹配） |

Scrivai re-export qmd 的基础类型以便下游一站式 import:

```python
from scrivai import ChunkRef, SearchResult, CollectionInfo  # 实际来自 qmd
```

**性质声明**:re-export 是**导入便利 / 依赖收敛**,**不是**完整的类型隔离。`scrivai.ChunkRef is qmd.ChunkRef` 身份相等是副作用,不是强契约——业务层若做 `isinstance(x, qmd.ChunkRef)`、使用 qmd 的其他类型、或 qmd 升版本,仍会感知到 qmd 的存在。

若需要**真正的依赖隔离**(如给业务层换一个向量库),应改走 facade pattern——定义 `scrivai.knowledge.SearchProtocol`,业务层只依赖 Protocol,底层换 qmd / Chroma / 其他。MVP **不做**此层封装;若未来有多后端需求,按 §8 走变更流程。

---

## 4. 对外契约

### 4.1 核心数据模型

所有 pydantic + Protocol 定义在 `scrivai/models/*.py`，从 `scrivai/__init__.py` 统一导出。

```python
from scrivai import (
    # PES 数据模型
    PESRun, PESConfig, PhaseConfig, PhaseResult, PhaseTurn,
    ModelConfig,
    # Hook Context(9 个)
    HookContext,
    RunHookContext, PhaseHookContext, PromptHookContext,
    PromptTurnHookContext, FailureHookContext,
    OutputHookContext, CancelHookContext,

    # Workspace
    WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle,

    # Knowledge
    LibraryEntry,

    # Trajectory
    TrajectoryRecord, PhaseRecord, FeedbackRecord,

    # Evolution(M2 自研,详见 §4.6)
    FailureSample, SkillVersion, EvolutionProposal,
    EvolutionScore, EvolutionRunRecord, EvolutionRunConfig,

    # Protocol
    Library, WorkspaceManager,

    # qmd re-export
    ChunkRef, SearchResult, CollectionInfo,
)
```

**`PESRun`** — 一次 PES 执行的完整状态：

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | `str` | 调用方指定，workspace 同名；全局唯一 |
| `pes_name` | `str` | `"extractor"` / `"auditor"` / `"generator"` / 自定义 |
| `status` | `Literal["running", "completed", "failed", "cancelled"]` | 当前状态（`cancelled` 对应用户/系统中断，与 `failed` 区分） |
| `task_prompt` | `str` | 业务层传入的任务描述 |
| `phase_results` | `dict[str, PhaseResult]` | 按 phase 名索引的结果（同 phase 多次重试只留最后一次 attempt） |
| `final_output` | `dict \| None` | summarize 阶段 `output.json` 解析后的内容 |
| `final_output_path` | `Path \| None` | `working/output.json` 绝对路径 |
| `metadata` | `dict[str, Any]` | 业务扩展字段 |
| `skills_git_hash` | `str \| None` | 快照时 skills 的 git hash |
| `agents_git_hash` | `str \| None` | 同上（agents） |
| `skills_is_dirty` | `bool` | 快照时源 git 有未提交修改则 `True` |
| `model_name` | `str` | 使用的模型 id |
| `provider` | `str` | `"anthropic"` / `"glm"` / `"minimax"` 等 |
| `sdk_version` | `str` | `claude-agent-sdk` 的版本号 |
| `started_at` | `datetime` | |
| `ended_at` | `datetime \| None` | |
| `error` | `str \| None` | 失败时的错误信息 |
| `error_type` | `str \| None` | 失败时的错误分类（见 §5.3.4） |

**`PhaseResult`** — 单阶段完整结果：

| 字段 | 类型 | 说明 |
|---|---|---|
| `phase` | `Literal["plan", "execute", "summarize"]` | |
| `attempt_no` | `int` | 本阶段第几次尝试（0 表首次；随 phase 级重试递增） |
| `prompt` | `str` | 最终拼接后的完整 prompt |
| `response_text` | `str` | LLM 最终 text |
| `turns` | `list[PhaseTurn]` | 完整消息流（细粒度） |
| `produced_files` | `list[str]` | 该阶段写入的文件（相对 `working_dir`） |
| `usage` | `dict[str, Any]` | 来自 SDK 的 token 统计 |
| `started_at` / `ended_at` | `datetime` | |
| `error` | `str \| None` | |
| `error_type` | `str \| None` | 错误分类：`sdk_rate_limit` / `sdk_other` / `max_turns_exceeded` / `response_parse_error` / `output_validation_error` / `cancelled` / `hook_error` |
| `is_retryable` | `bool` | 本次失败是否适合 phase 级重试（由 error_type 推导） |

**`PhaseTurn`** — 单次 Agent turn（细粒度轨迹）：

| 字段 | 说明 |
|---|---|
| `turn_index` | 从 0 开始 |
| `role` | `"assistant"` / `"user"`（user 是 tool result） |
| `content_type` | `"text"` / `"tool_use"` / `"tool_result"` / `"thinking"` |
| `data` | 原始消息数据（完整保留） |
| `timestamp` | |

**`PhaseConfig`** — 单阶段配置：

| 字段 | 默认 | 说明 |
|---|---|---|
| `name` | — | `"plan"` / `"execute"` / `"summarize"` |
| `additional_system_prompt` | `""` | 阶段特定的 system prompt 追加 |
| `allowed_tools` | — | SDK 的 allowed_tools 列表 |
| `max_turns` | `10` | 单次 SDK `query()` 内 Agent 最多交互轮数 |
| `max_retries` | `1` | **Phase 级重试次数**（见 §5.3.4 三层重试定义） |
| `permission_mode` | `"default"` | |
| `required_outputs` | `[]` | 必需的产物规则；每条可以是：<br/>①字符串路径 `"plan.md"`（文件存在即通过）<br/>②目录规则 `{"path":"findings/", "min_files":1, "pattern":"*.json"}`（目录下至少 N 个匹配 pattern 的文件） |

**`TrajectoryRecord`** — `TrajectoryStore` 查询返回的**只读视图**,对应 `runs` 表一行(可选联查 phases)。

**与 `PESRun` 的关系**:

- `PESRun` 是**运行时对象**,由 `BasePES.run()` 构造和维护,含内存态的 `phase_results: dict[str, PhaseResult]`(只保留最后一次 attempt)
- `TrajectoryRecord` 是**持久化视图**,由 `TrajectoryStore` 从 SQLite 重建;它的 `phase_records: list[PhaseRecord]` 含**所有 attempt**(首次 + 每次重试)
- 两者**互不替代**:业务层正常流程用 `PESRun`;做事后复盘 / 构建进化数据集用 `TrajectoryRecord`
- 字段基本对应,但 `TrajectoryRecord` 不含 `final_output_path` 等文件系统路径(归档后路径可能失效),改用 `workspace_archive_path` 定位

| 字段 | 类型 | 说明 |

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | `str` | |
| `pes_name` | `str` | |
| `model_name` / `provider` / `sdk_version` | `str` | |
| `skills_git_hash` / `agents_git_hash` | `str \| None` | |
| `status` | `Literal["running","completed","failed","cancelled"]` | |
| `task_prompt` | `str` | |
| `runtime_context` | `dict \| None` | |
| `workspace_archive_path` | `str \| None` | |
| `final_output` | `dict \| None` | |
| `error` / `error_type` | `str \| None` | |
| `started_at` / `ended_at` | `datetime \| None` | |
| `phase_records` | `list[PhaseRecord]` | 子表联查（可选加载） |

**`PhaseRecord`** — 对应 `phases` 表一行（同 `run_id + phase_name` 可能有多条,按 `attempt_no` 区分):

| 字段 | 类型 |
|---|---|
| `phase_id` / `run_id` / `phase_name` / `attempt_no` / `phase_order` | |
| `prompt` / `response_text` | `str \| None` |
| `produced_files` | `list[str]` |
| `usage` | `dict` |
| `error` / `error_type` / `is_retryable` | `str \| None` / `bool` |
| `started_at` / `ended_at` | `datetime \| None` |

**`FeedbackRecord`** — 对应 `feedback` 表一行:

| 字段 | 类型 | 说明 |
|---|---|---|
| `feedback_id` | `int` | |
| `run_id` | `str` | |
| `input_summary` | `str` | 业务层在 `record_feedback` 时提供的"本次 run 的输入摘要"——进化评测集构建时作为 `question` 的补充内容 |
| `draft_output` | `dict` | Agent 原输出（`final_output` 的拷贝） |
| `final_output` | `dict` | 专家修订定稿 |
| `corrections` | `list[dict] \| None` | 可选的结构化 diff |
| `review_policy_version` | `str \| None` | 当时的审核准则版本,便于按准则分层 |
| `source` | `str` | `"human_expert"` / `"second_review"` / `"gold_set"` 等 |
| `confidence` | `float` | `0.0 - 1.0`;反馈质量打分,训练时可过滤 |
| `submitted_at` | `datetime` | |
| `submitted_by` | `str \| None` | |

**`PESConfig`** — 整个 PES 配置（从 YAML 加载）：

```yaml
name: extractor
display_name: 通用条目抽取
prompt_text: |
  You are a structured information extractor...
default_skills:
  - available-tools
  - search-knowledge
  - inspect-document
phases:
  plan:
    additional_system_prompt: |
      In this phase, draft an extraction strategy.
      Write working/plan.md and working/plan.json.
    allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
    max_turns: 6
    required_outputs: [plan.md, plan.json]
  execute:
    additional_system_prompt: |
      Execute plan.json item by item.
      Write each item's result to working/findings/<id>.json.
    allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill]
    max_turns: 30
    required_outputs: [findings/]
  summarize:
    additional_system_prompt: |
      Aggregate all working/findings/*.json into working/output.json.
    allowed_tools: [Bash, Read, Write]
    max_turns: 4
    required_outputs: [output.json]
```

### 4.2 BasePES 执行引擎

`BasePES` 是**抽象基类**,封装三阶段执行的通用机制。用户(或预置 PES)通过覆盖 **4 个策略方法**精细注入阶段特定逻辑——不再只靠单一 `handle_phase_response`。

```python
from scrivai import BasePES, HookManager, ModelConfig, PESConfig, WorkspaceHandle

class BasePES(ABC):
    def __init__(
        self,
        *,
        config: PESConfig,
        model: ModelConfig,
        workspace: WorkspaceHandle,
        hooks: HookManager | None = None,
        trajectory_store: "TrajectoryStore | None" = None,
        runtime_context: dict[str, Any] | None = None,
    ): ...

    async def run(self, task_prompt: str) -> PESRun:
        """顺序执行 plan → execute → summarize,返回完整 PESRun。"""

    async def _run_phase(self, phase: str, run: PESRun) -> PhaseResult:
        """单阶段执行(详见 §5.1);内部按序调 4 个策略方法。"""

    # ────── 4 个子类扩展点(策略方法) ──────
    # 均有默认实现,子类可选择性覆盖。子类**不必**全部覆盖。

    async def build_execution_context(
        self,
        phase: str,
        run: PESRun,
    ) -> dict[str, Any]:
        """构建本阶段的 execution_context(与 runtime_context 合并前的那部分)。

        注意:此方法返回的是"可变的 execution context",框架随后会把它与
        runtime_context + 框架自动字段合并成完整 prompt context。因此命名是
        `build_execution_context` 而不是 `build_phase_context`——避免暗示它返回
        完整上下文。

        默认实现:返回 `{}`。
        典型覆盖场景:GeneratorPES 在 plan 阶段解析模板占位符,注入 `context["placeholders"]`
        供 prompt 模板使用。
        """
        return {}

    async def build_phase_prompt(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        context: dict[str, Any],
        task_prompt: str,
    ) -> str:
        """渲染本阶段 Agent 看到的 prompt。

        默认实现:`config.prompt_text + phase_cfg.additional_system_prompt + task_prompt + context 序列化`。
        典型覆盖场景:自定义 PES 要注入 few-shot 示例或特殊 context 格式化。
        """
        ...

    async def postprocess_phase_result(
        self,
        phase: str,
        result: PhaseResult,
        run: PESRun,
    ) -> None:
        """响应后处理:解析 Agent 输出,更新 `run.metadata` / `run.final_output`,
        业务侧特殊记账。

        默认实现:`no-op`。
        典型覆盖场景:
        - ExtractorPES summarize:读 output.json → `output_schema.model_validate` → 失败抛 PhaseError
        - GeneratorPES summarize:若 `auto_render=True` → 调 `DocxRenderer.render` 产 docx
        抛异常即判 phase 失败,error_type 统一记为 `response_parse_error`。
        """
        return None

    async def validate_phase_outputs(
        self,
        phase: str,
        phase_cfg: PhaseConfig,
        result: PhaseResult,
        run: PESRun,
    ) -> None:
        """校验必需产物是否完整。

        默认实现:按 `phase_cfg.required_outputs` 的每条规则校验(见 PhaseConfig.required_outputs 字段说明)。
        抛 `PhaseError` 即判 phase 失败,error_type 统一记为 `output_validation_error`。
        典型覆盖场景:AuditorPES execute 追加校验 checkpoint 覆盖率——每个 cp_id 至少有一个 findings 文件。
        """
        ...
```

**扩展点选择指南**:

| 需要什么时候介入 | 覆盖哪个方法 |
|---|---|
| 在 Agent 看到 prompt 之前动态注入数据(如解析模板占位符) | `build_execution_context` |
| 换整个 prompt 拼接方式(加 few-shot、换模板语法) | `build_phase_prompt` |
| Agent 跑完一次 query 之后解析 / 业务归档 / 调下游工具 | `postprocess_phase_result` |
| 对必需产物加额外校验(覆盖率、schema、跨文件约束) | `validate_phase_outputs` |

子类不必覆盖全部 4 个方法;实际预置 PES 最多覆盖 2-3 个。这比"单一 `handle_phase_response` 承担所有差异"更清晰,且避免基类回调爆炸。

**阶段间交互通过 workspace 文件,不依赖 text 字符串**:

| Phase | 必需产物(写入 `working/`) | 默认 `allowed_tools` |
|---|---|---|
| `plan` | `plan.md` + `plan.json`(执行清单) | `[Bash, Read, Write, Edit, Glob, Grep, Skill]` |
| `execute` | `findings/<item_id>.json`(每 plan 项一个文件) | `[Bash, Read, Write, Edit, Glob, Grep, Skill]` |
| `summarize` | `output.json`(唯一最终结构化输出) | `[Bash, Read, Write]`(收紧,避免发散) |

**双层 Context 合并**(构建 prompt 时):

```
runtime_context        (初始化时传入,整次 run 不变)
    ∪
execution_context      (每个 phase 开始时由 build_phase_context 产生)
    ∪
{                      (框架自动注入)
    "phase": "plan|execute|summarize",
    "attempt_no": int,                   (本阶段重试计数)
    "run": PESRun.to_prompt_payload(),
    "workspace": {"working_dir": ..., "data_dir": ..., "output_dir": ...},
    "previous_phase_output": ...        (execute 读 plan,summarize 读 findings)
}
    ↓
渲染到阶段 system_prompt
```

**错误处理汇总**:三种 phase 失败出口统一进 `on_phase_failed` hook(详见 §5.1 伪代码 + §5.3.4 错误矩阵):
1. `_call_sdk_query` 阶段(调 Claude SDK 失败)→ `error_type="sdk_*"` / `"max_turns_exceeded"`
2. `postprocess_phase_result` 抛异常 → `error_type="response_parse_error"`
3. `validate_phase_outputs` 抛异常 → `error_type="output_validation_error"`

`on_phase_failed` 后若 `attempt_no < max_retries` → phase 级重试(整 phase 从 `build_phase_context` 重跑,`attempt_no += 1`,产物重新落盘);超过重试上限 → 中断后续 phase,`run.status = "failed"`。

### 4.3 Hook 系统

BasePES 内置 **9 个触点**,用 `HookManager` 统一 dispatch。所有 Hook Context 都是 pydantic 模型,跨插件共享。

```python
from scrivai import HookManager
from scrivai.pes.hooks import hookimpl

class MyPlugin:
    @hookimpl
    def before_phase(self, context: PhaseHookContext) -> None:
        print(f"starting {context.phase} attempt={context.attempt_no}")

hooks = HookManager()
hooks.register(MyPlugin())
pes = ExtractorPES(..., hooks=hooks)
```

**Hook 清单**:

| Hook | Context | 时机 | 调用模式 |
|---|---|---|---|
| `before_run` | `RunHookContext` | 整次 run 开始前 | 同步(异常中断) |
| `before_phase` | `PhaseHookContext`(含 `attempt_no`) | 每个 phase **每次尝试**开始前(首次 + 每次重试均触发) | 同步 |
| `before_prompt` | `PromptHookContext` | prompt 渲染后、调 SDK 前 | 同步(允许修改 `context.prompt`) |
| `after_prompt_turn` | `PromptTurnHookContext` | 每个 SDK turn 收到后 | 同步 |
| `after_phase` | `PhaseHookContext` | phase **最终**成功完成后(含重试后成功) | 同步 |
| `on_phase_failed` | `FailureHookContext`(含 `attempt_no` / `error_type` / `will_retry`) | phase 本次尝试抛异常时(覆盖 SDK / postprocess / validate 三种失败出口) | 非阻塞 |
| `on_output_written` | `OutputHookContext` | summarize 阶段 `validate_phase_outputs` 通过后、`after_phase` 前触发。只在 summarize 阶段触发一次 | 同步 |
| `on_run_cancelled` | `CancelHookContext` | 收到 `KeyboardInterrupt` / `asyncio.CancelledError` 时 | 非阻塞 |
| `after_run` | `RunHookContext` | 整次 run 结束(finally 块——无论成功/失败/取消都触发) | 非阻塞 |

**严格顺序**(phase 级展开,每个 phase 独立走一遍):

```
before_run
  ↓
for each phase in (plan, execute, summarize):
    ┌─ attempt_no = 0 ─────────────────────────────┐
    │  before_phase(attempt=0)                     │
    │    → before_prompt                           │
    │      → [after_prompt_turn]*                  │
    │  [on_phase_failed(attempt=0, will_retry) 若失败]
    └──────────────────────────────────────────────┘
    [若 will_retry] → 重试 attempt=1 回到 before_phase
    [若最终成功]
       → [on_output_written (仅 summarize 阶段 + validate 通过)]
       → after_phase(该 phase 最终结果)
  [该 phase 失败且无法重试] → 跳出 phase 循环,标记 run.status="failed"
  ↓
[on_run_cancelled (若收到 KeyboardInterrupt/CancelledError)]
  ↓
after_run (finally 一定触发;含最终持久化)
```

**关键点**:
- `after_phase` 是**每个 phase** 独立触发,不是整 run 末尾统一触发
- `on_output_written` 位于 **validate 通过之后、after_phase 之前**(仅 summarize);与 §5.1 伪代码一致
- `on_phase_failed` 只在本次尝试失败时触发;若 `will_retry=True`,再次进入循环时先走 `_cleanup_phase_outputs` 再触发新一轮 `before_phase`

**Hook 异常传播矩阵**(`hook_error` 语义闭合):

| Hook | 同步/非阻塞 | 异常处理 | 映射到 `error_type` | 影响 |
|---|---|---|---|---|
| `before_run` | 同步 | 冒泡到 `run()` 的特殊 except 分支 | `hook_error`(整 run 级) | `run.status="failed"`;不启动 phase 循环;仍触发 `after_run` |
| `before_phase` / `before_prompt` / `after_prompt_turn` / `after_phase` | 同步 | 由 `_run_phase` 捕获,包成 `PhaseError(error_type="hook_error", is_retryable=False)` | `hook_error`(phase 级) | 该 phase 立即失败,不重试;走 `on_phase_failed` hook |
| `on_output_written` | 同步 | 同上 | `hook_error` | summarize 阶段失败;注意这意味着**输出文件已经写成但 hook 崩了**,business 可能需要补偿 |
| `on_phase_failed` / `on_run_cancelled` / `after_run` | 非阻塞 | 仅 loguru.exception 记录;**不影响** run/phase 状态 | — | — |

**非阻塞 hook 的异常永不改变 `run.status`**,这是契约。依赖这些 hook 做关键业务(如持久化)的实现必须在 hook 内部自行重试,不能把异常冒出来。

**限制(当前未覆盖)**:

- **无 archive hook**:`WorkspaceManager.archive` 是业务层显式调的,不在 BasePES 生命周期内;若需要"归档前后"的扩展点,自行在业务代码里做,不走 HookManager
- **无 before_retry / after_retry**:phase 级重试通过 `on_phase_failed.will_retry=True` 观察;如果需要区分"重试前准备"和"首次尝试",检查 `PhaseHookContext.attempt_no`
- **无 on_run_failed**:run 失败状态通过 `after_run.run.status == "failed"` 读取;没有独立 hook

**内置 Hook**:

- `TrajectoryRecorderHook`(`scrivai.trajectory.hooks`):自动把每个触点的信息落盘到 TrajectoryStore;订阅全部 9 个 hook
- `PhaseLogHook`(`scrivai.pes.hooks`):把 prompt / response / turns dump 到 `workspace.logs_dir / phase-<phase>-attempt-<N>.log.json`

**实现选型**:`HookManager` 基于 [pluggy](https://pluggy.readthedocs.io/) 或等价的轻量 dispatcher(`dict[str, list[Callable]]`),MVP 用后者即可。

### 4.4 预置 PES 三兄弟

三个预置 PES 都继承 `BasePES`，封装"文档类场景"的常见业务模式。每个都有默认的 PESConfig、默认 skill 组合、默认输出解析逻辑——用户可以部分覆盖。

**构造签名契约**(三个 PES 统一):三个预置 PES 的构造签名等同 `BasePES.__init__`,**不引入任何新构造参数**(Herald2 模式,参考 `core/pes/{draft,feature_extract,mutate}.py`)。业务参数通过 `runtime_context: dict` 字段延迟注入,各字段在子类的 `build_execution_context` / `postprocess_phase_result` / `validate_phase_outputs` 中按需取值。缺失必需字段时,子类在首次用到它的扩展点方法里抛 `ValueError`,由 `BasePES._run_phase` 统一归并为 `error_type="response_parse_error"`(不可重试)。

skill 管理完全由 `WorkspaceManager` 负责(§5.2 `copytree(project_root/skills, working/.claude/skills)`),PES 层不涉及任何 skill 参数或传递逻辑。

#### 4.4.1 ExtractorPES — 抽取结构化条目

**用途**：从文档抽取结构化条目（审核点、关键条款、需求项、FAQ 等）

**默认输出形态**：

```json
{
  "items": [
    {"id": "item-001", "content": "...", "source_ref": {"char_start": 1024, "char_end": 1200}},
    ...
  ],
  "total": 42,
  "coverage_summary": "已覆盖文档 3/5 章节..."
}
```

**runtime_context 业务字段**(业务层通过 `runtime_context=dict(...)` 注入):

| 字段 | 类型 | 必需 | 作用 |
|---|---|---|---|
| `output_schema` | `type[BaseModel]` | ✅ | summarize 阶段校验 working/output.json |

**prompt / skill / config 定制**:
- prompt 话术:修改 `scrivai/agents/extractor.yaml` 或业务层复制后 `load_pes_config(my.yaml)` 传 `config=`
- skill:由 Workspace 的 `project_root/skills/` copytree 注入,PES 层不参与(§4.9 + §5.2)
- 完整 PESConfig 替换:直接把自定义 PESConfig 实例传 `config=`

**扩展点职责**:

| Phase | 动作 |
|---|---|
| `plan` | 默认 `required_outputs=[plan.md, plan.json]` |
| `execute` | `validate_phase_outputs` 校验每个 plan item 有对应的 `findings/<id>.json` |
| `summarize` | `postprocess_phase_result` 读 `output.json`,用 `output_schema` 校验(失败 → `response_parse_error`) |

#### 4.4.2 AuditorPES — 对照审核

**用途**：对照一份检查点清单，审核文档合规性

**默认输入**：`task_prompt` 中约定的 `checkpoints` 列表（每项至少含 `id / description`）

**默认输出形态**：

```json
{
  "findings": [
    {
      "checkpoint_id": "cp-001",
      "verdict": "合格|不合格|不适用|需要澄清",
      "evidence": [{"chunk_id": "...", "quote": "..."}],
      "reasoning": "..."
    },
    ...
  ],
  "summary": {"total": 30, "合格": 22, "不合格": 5, "需要澄清": 3}
}
```

**runtime_context 业务字段**:

| 字段 | 类型 | 必需 | 默认 | 作用 |
|---|---|---|---|---|
| `output_schema` | `type[BaseModel]` | ✅ | — | summarize 阶段 schema 校验 |
| `verdict_levels` | `list[str]` | — | `["合格","不合格","不适用","需要澄清"]` | finding.verdict 合法集合 |
| `evidence_required` | `bool` | — | `True` | 每 finding 是否必须含 evidence |

**业务层前置**:在 `pes.run()` 之前把 checkpoints 以 `[{id, description, ...}]` 写入 `workspace.data_dir/checkpoints.json`;execute 阶段覆盖率校验基于此文件。

**prompt / skill / config 定制**:同 ExtractorPES,默认 YAML 在 `scrivai/agents/auditor.yaml`。

**扩展点职责**:

| Phase | 动作 |
|---|---|
| `execute` | `validate_phase_outputs` 校验 checkpoints 覆盖率(data/checkpoints.json 的 cp_id 集合 = findings/*.json stem 集合) |
| `summarize` | `postprocess_phase_result` 校验 schema + 每 verdict ∈ verdict_levels + evidence_required=True 时 evidence 非空 |

#### 4.4.3 GeneratorPES — 按模板生成

**用途**：按 docxtpl 模板 + 检索到的素材生成最终文档

**默认输入**：`template_path`（Path），`context_hints`（dict，暗示需要填充的占位符）

**默认输出形态**：

```json
{
  "sections": [
    {"placeholder": "project_name", "content": "...", "source_refs": [...]}
  ],
  "rendered_docx_path": "output/final.docx"
}
```

**runtime_context 业务字段**:

| 字段 | 类型 | 必需 | 默认 | 作用 |
|---|---|---|---|---|
| `template_path` | `Path` | ✅ | — | docxtpl 模板路径(plan 阶段解析占位符) |
| `context_schema` | `type[BaseModel]` | ✅ | — | summarize 阶段 schema 校验 |
| `auto_render` | `bool` | — | `False` | summarize 结束是否自动渲染 `output/final.docx` |

**`auto_render` 默认 False 的理由**:docxtpl 模板制作约束(§4.8)较脆弱——模板必须手工 Word 制作、单 cell 内不嵌套循环、不支持表中表。默认关闭以避免 summarize 阶段因模板限制失败;业务层在确认模板符合 docxtpl 约束后显式 `auto_render=True` 开启。未开启时,summarize 只校验 context schema 并写 `output.json`,docx 渲染由业务层自己调 `DocxRenderer` 做。

**prompt / skill / config 定制**:同 ExtractorPES,默认 YAML 在 `scrivai/agents/generator.yaml`。

**扩展点职责**:

| Phase | 动作 |
|---|---|
| `plan` | `build_execution_context` 解析模板占位符注入 `context["placeholders"]`;`validate_phase_outputs` 校验 `plan.json.fills` 覆盖所有占位符 |
| `execute` | `validate_phase_outputs` 校验每个占位符有 `findings/<placeholder>.json` |
| `summarize` | `postprocess_phase_result` 校验 context schema;**若** `auto_render=True` → 用 `DocxTemplate.render` 产 `output/final.docx` |

### 4.5 TrajectoryStore — 轨迹持久化

**定位**：独立于 workspace 的**跨 run 持久化存储**。每次 run 的**每个 turn**、**每次 tool 调用**、**完整 prompt 与响应**都落盘，用于事后复盘 + 进化训练集构建。

**存储**：SQLite 单文件，默认 `~/.scrivai/trajectories.sqlite`，可通过 `SCRIVAI_TRAJECTORY_DB` 覆盖。

**表结构**：

```sql
-- 每次 PES run 的主记录
CREATE TABLE runs (
    run_id                 TEXT PRIMARY KEY,
    pes_name               TEXT NOT NULL,
    model_name             TEXT NOT NULL,
    provider               TEXT NOT NULL,     -- anthropic / glm / minimax / ...
    sdk_version            TEXT NOT NULL,     -- claude-agent-sdk 版本号
    skills_git_hash        TEXT,
    agents_git_hash        TEXT,
    skills_is_dirty        INTEGER NOT NULL DEFAULT 0,   -- 0/1 布尔
    status                 TEXT NOT NULL,     -- running / completed / failed / cancelled
    task_prompt            TEXT NOT NULL,
    runtime_context        JSON,
    workspace_archive_path TEXT,
    final_output           JSON,              -- output.json 内容
    error                  TEXT,
    error_type             TEXT,              -- 详见 §5.3.4 分类
    started_at             TEXT NOT NULL,
    ended_at               TEXT
);
CREATE INDEX idx_runs_pes_name ON runs(pes_name);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_started_at ON runs(started_at);

-- 每个 phase 的详细记录(含重试:同 run_id+phase_name 可能多行,靠 attempt_no 区分)
CREATE TABLE phases (
    phase_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    phase_name      TEXT NOT NULL,            -- plan / execute / summarize
    phase_order     INTEGER NOT NULL,         -- 0=plan, 1=execute, 2=summarize
    attempt_no      INTEGER NOT NULL DEFAULT 0,   -- 本 phase 第几次尝试
    prompt          TEXT,
    response_text   TEXT,
    produced_files  JSON,
    usage           JSON,
    error           TEXT,
    error_type      TEXT,                     -- sdk_rate_limit / sdk_other / max_turns_exceeded /
                                              -- response_parse_error / output_validation_error /
                                              -- cancelled / hook_error / None
    is_retryable    INTEGER,                  -- 0/1;该次失败是否适合 phase 级重试
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    UNIQUE(run_id, phase_name, attempt_no)
);
CREATE INDEX idx_phases_run_id ON phases(run_id);

-- 每次 SDK turn(细粒度)
CREATE TABLE turns (
    turn_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id      INTEGER NOT NULL REFERENCES phases(phase_id),
    turn_index    INTEGER NOT NULL,
    role          TEXT NOT NULL,              -- assistant / user
    content_type  TEXT NOT NULL,              -- text / tool_use / tool_result / thinking
    data          JSON NOT NULL,
    timestamp     TEXT NOT NULL
);
CREATE INDEX idx_turns_phase_id ON turns(phase_id);

-- 每次 tool 调用
CREATE TABLE tool_calls (
    tool_call_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id       INTEGER NOT NULL REFERENCES turns(turn_id),
    tool_name     TEXT NOT NULL,              -- Bash / Read / Write / Skill / ...
    tool_input    JSON,
    tool_output   TEXT,
    status        TEXT,                       -- success / error / timeout
    duration_ms   INTEGER,
    timestamp     TEXT NOT NULL
);
CREATE INDEX idx_tool_calls_tool_name ON tool_calls(tool_name);

-- 人类反馈(业务层在专家修订后写入)
CREATE TABLE feedback (
    feedback_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                 TEXT NOT NULL REFERENCES runs(run_id),
    input_summary          TEXT NOT NULL,     -- 业务层提供的"本次 run 输入摘要";进化时作 question 一部分
    draft_output           JSON NOT NULL,     -- Agent 原始输出(等于 run.final_output 的副本)
    final_output           JSON NOT NULL,     -- 人类修订后定稿
    corrections            JSON,              -- 可选:结构化 diff
    review_policy_version  TEXT,              -- 当时的审核准则版本
    source                 TEXT NOT NULL DEFAULT 'human_expert', -- human_expert / second_review / gold_set
    confidence             REAL NOT NULL DEFAULT 1.0, -- 0.0-1.0;反馈质量
    submitted_at           TEXT NOT NULL,
    submitted_by           TEXT
);
CREATE INDEX idx_feedback_run_id ON feedback(run_id);
CREATE INDEX idx_feedback_source ON feedback(source);

-- SQLite 启用 WAL
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=3000;    -- 3s(见下方时间预算)
```

**并发模型**:

- 默认**每线程一连接**(`threading.local` 或显式 pool);不允许跨线程共享 connection
- 单进程内 async 场景:推荐 `aiosqlite` 或把 record_* 放进 `asyncio.to_thread`(框架默认策略:每次 record 都拿独立连接、跑完即关,靠 WAL 保证并发)
- 多进程并发写同一 `trajectories.sqlite` **允许**(WAL 支持),但不是 MVP 目标
- 事务边界:`start_run / finalize_run` 各自一个事务;`record_phase_*` 各自一个事务;`record_turn / record_tool_call` 允许 batched 事务(由内部 flush 周期控制)

**写入时间预算**(避免 busy + 重试叠加出长尾):

| 层级 | 预算 | 说明 |
|---|---|---|
| SQLite `busy_timeout` | 3s | 单次等锁上限 |
| 框架重试 | 最多 1 次(间隔 0.5s) | 仅对 `SQLITE_BUSY`;其他错误不重试 |
| 总 DB 写尾延迟 | ≤ 6.5s | = 3 + 0.5 + 3 |
| `record_turn` P99 | < 10ms(见 §9) | 无争用场景 |

超出总预算 → 抛 `TrajectoryWriteError`,loguru 记录;**不影响** run / phase 状态(`on_phase_failed` 非阻塞)。

**索引细节**(查询优化):

- `phases(run_id, phase_order, attempt_no)`:支撑按 run 联查所有 attempt
- `feedback(submitted_at)`:支撑时间维度筛查
- `tool_calls(turn_id)`:已通过 FK 隐式索引,若查询密集可补显式 `CREATE INDEX`

**Python API**：

```python
from scrivai import TrajectoryStore

store = TrajectoryStore(db_path=None)  # None → 默认路径

# 自动写入（通过 TrajectoryRecorderHook；用户无需直接调）
# store.start_run(run_id, pes_name, ...)
# store.record_phase_start(run_id, phase_name)
# store.record_turn(phase_id, turn_index, role, content_type, data)
# store.record_tool_call(turn_id, tool_name, tool_input, tool_output)
# store.record_phase_end(phase_id, response_text, produced_files, usage, error)
# store.finalize_run(run_id, status, final_output, workspace_archive_path, error)

# 业务层手动写入反馈
store.record_feedback(
    run_id="abc123",
    draft_output={...},     # Agent 原输出
    final_output={...},     # 专家定稿
    corrections=[...],      # 可选
    submitted_by="expert_01",
)

# 查询
run = store.get_run("abc123")                           # -> TrajectoryRecord
runs = store.list_runs(pes_name="extractor", limit=50)  # 按类型筛
pairs = store.get_feedback_pairs(pes_name="extractor")  # -> list[(draft, final, run_id)]
```

**`TrajectoryRecorderHook`** —— 插入 BasePES hook 系统，对用户透明：

```python
from scrivai import TrajectoryStore, TrajectoryRecorderHook, HookManager

store = TrajectoryStore()
hooks = HookManager()
hooks.register(TrajectoryRecorderHook(store))

pes = ExtractorPES(..., hooks=hooks, trajectory_store=store)
result = await pes.run(task_prompt="...")
# 全部 phases / turns / tool_calls 已落盘
```

### 4.6 Evolution —— Skill 进化(M2 自研实现)

进化机制的核心思想:**Agent 不变,只优化 SKILL.md 的措辞**。M2 自研方案**放弃 EvoSkill 兼容层**,改用 SQLite DAG + 真实 PES replay + Python SDK 控制台。详细设计见 `docs/superpowers/specs/2026-04-17-scrivai-m2-design.md`。

#### 4.6.1 数据模型(`scrivai.models.evolution`)

- `FailureSample` —— 单条失败样本,含 trajectory 摘要
- `SkillVersion` —— 版本 DAG 节点(snapshot + diff 双存)
- `EvolutionProposal` —— Proposer 单次产出
- `EvolutionScore` —— hold-out 评分
- `EvolutionRunRecord` —— 一次 run_evolution 完整记录
- `EvolutionRunConfig` —— 运行配置

M0 预留的 `FeedbackExample / EvolutionConfig / EvolutionRun / Evaluator / SkillsRootResolver` **已全部删除**(M2 放弃 EvoSkill 兼容)。

#### 4.6.2 `EvolutionTrigger` —— 从 trajectory 拉反馈

```python
from scrivai import EvolutionTrigger

trigger = EvolutionTrigger(
    trajectory_store=store, pes_name="extractor", skill_name="available-tools",
    evaluator_fn=my_evaluator, min_confidence=0.7, failure_threshold=0.5,
)
if trigger.has_enough_data(min_samples=10):
    train, hold_out = trigger.collect_failures(hold_out_ratio=0.3, random_seed=42)
```

- 返回 `(train_failures, hold_out_samples)` 两个 `list[FailureSample]`
- 每条样本 `.trajectory_summary` 保留 plan/execute/summarize 响应(各截断 800 字)

#### 4.6.3 `run_evolution` —— 自研进化循环

```python
from scrivai import run_evolution, EvolutionRunConfig, build_workspace_manager

record = await run_evolution(
    config=EvolutionRunConfig(
        pes_name="extractor", skill_name="available-tools",
        max_iterations=5, n_proposals_per_iter=3, frontier_size=3,
        no_improvement_limit=2, max_llm_calls=500,
        hold_out_ratio=0.3, min_confidence=0.7, failure_threshold=0.5,
        proposer_model="glm-5.1",
    ),
    trajectory_store=store,
    workspace_mgr=build_workspace_manager(),
    pes_factory=lambda name, ws: ExtractorPES(config=pes_cfg, model=model_cfg,
                                               workspace=ws, runtime_context=...),
    evaluator_fn=my_evaluator_fn,
    source_project_root=Path("./"),
    llm_client=LLMClient(model_cfg),
)
```

**内部五阶段**(整体思路同 EvoSkill,但全部自研):

1. **Baseline**:从 `source_project_root/skills/<skill_name>/` 读当前内容建 baseline version,在 hold_out 上评
2. **Proposer**(单次 LLM call 产 N 个候选):输入 = 当前 SKILL.md + failures + rejected history
3. **Candidate save**:入库(snapshot + unified diff + change_summary)
4. **Evaluator**:为每个候选建临时 project_root(copytree + overwrite target skill),用真实 PES replay hold_out
5. **Frontier**:贪心 top-K 维护;超 `no_improvement_limit` 无提升则 break

**输出** `EvolutionRunRecord` 含:
- `baseline_version_id` / `baseline_score`
- `best_version_id` / `best_score`(若超过 baseline,否则为 `None`)
- `candidate_version_ids`(所有候选 id)
- `iterations_history`(逐轮详情)
- `status`:`running / completed / failed / budget_exceeded`

#### 4.6.4 `promote` —— 手动上线候选

```python
from scrivai import promote

promote(
    version_id="extractor:available-tools:...",
    source_project_root=Path("./"),
)
# → 备份当前 skills/available-tools/ 到 skills/available-tools/.backup/evo-<ts>/
# → 把 version.content_snapshot 写入 skills/available-tools/
# → 更新 SkillVersion.status = 'promoted'
```

**安全约束**:
- 进化期间**不写**主仓 `skills/`;只写 `~/.scrivai/evolution.db` + 临时目录
- `promote` 是**Python SDK**(无 CLI),业务方显式调用
- 默认 `backup=True`;备份路径在 `skills/<name>/.backup/evo-<ts>/`,可回退

#### 4.6.5 LLM 调用预算

`LLMCallBudget(limit=500)` 由 runner 自动创建并传给 Proposer / Evaluator。超限抛 `BudgetExceededError`,runner 捕获后把 `status` 设 `budget_exceeded` 并落盘。

#### 4.6.6 与原 EvoSkill 方案的差异

| 维度 | 原 M2(EvoSkill) | M2 自研 |
|---|---|---|
| 数据来源 | CSV 评测集 | 直接查 trajectory.db |
| 版本存储 | git 分支 | SQLite DAG(独立 evolution.db) |
| cwd 耦合 | 硬编码 `.claude/skills/`(需 SkillsRootResolver 胶带) | 临时 project_root → workspace copytree |
| Base agent | 内置通用 | **重跑真实 ExtractorPES / AuditorPES / GeneratorPES** |
| 进化类型 | skill_only / prompt_only | FIX(MVP);DERIVED/CAPTURED 延到 M3 |
| Promote | git checkout | `scrivai.evolution.promote()` |
| 依赖 | dspy/GEPA/git | 零新依赖 |

### 4.7 Knowledge Library

三个 Library 都实现 `Library` Protocol，底层落在 qmd 的三个固定 collection。

```python
from scrivai import (
    Library,                                      # Protocol
    RuleLibrary, CaseLibrary, TemplateLibrary,    # 具体实现
    LibraryEntry,                                 # pydantic
    build_libraries,                              # 工厂
    build_qmd_client_from_config,                 # 底层工厂
)

qmd = build_qmd_client_from_config(db_path="~/.qmd/db.sqlite")
rules, cases, templates = build_libraries(qmd)

# 基本操作
entry = rules.add(entry_id="rule-001", markdown="...", metadata={"title": "..."})
hits = rules.search(query="围标串标", top_k=5, filters={"type": "law"})
entry = rules.get("rule-001")
all_ids = rules.list()
rules.delete("rule-001")
```

**`LibraryEntry`**（pydantic）：

| 字段 | 说明 |
|---|---|
| `entry_id` | collection 内唯一 |
| `markdown` | 文本内容 |
| `metadata` | 透传 qmd chunk metadata；无语义解释 |
| `created_at` / `updated_at` | ISO 时间戳 |

**持久化策略**：entry 元数据**完全持久化在 qmd chunk metadata**；Library 不维护额外内存状态。

### 4.8 IO 工具

独立的文件转换与渲染工具，不依赖 BasePES / TrajectoryStore，可被业务层直接调、可被 Agent 通过 Bash 调、可被 GeneratorPES 内部调。

```python
from pathlib import Path
from scrivai import docx_to_markdown, doc_to_markdown, pdf_to_markdown, DocxRenderer

md: str = docx_to_markdown("tender.docx")           # pandoc
md: str = doc_to_markdown("legacy.doc")             # LibreOffice → docx → pandoc
md: str = pdf_to_markdown("scan.pdf")               # MonkeyOCR HTTP(base_url 可覆盖)

renderer = DocxRenderer(template_path="workpaper_template.docx")
placeholders: list[str] = renderer.list_placeholders()
renderer.render(context={"project_name": "X变电站", ...}, output_path="out.docx")
```

**`pdf_to_markdown` 的 OCR 路径**（M0.75 实施偏离，M1.5b 同步）：不走 docling 而走 **MonkeyOCR HTTP 服务**（默认 `base_url="http://100.81.95.44:7861"`，由调用方按需覆盖）。流程：POST `/parse` 上传 PDF → 取 `download_url` → GET ZIP → 从 ZIP 抽 `.md` 文件内容。服务不可达时抛 `IOError`，不静默回退。与设计文档最初设想的 docling 本地依赖不同，采用 HTTP 服务的原因：(1) 复用现网已部署的 MonkeyOCR，避免本地 docling 模型加载体积；(2) 业务方可指向自建 OCR。接口签名保持 `pdf_to_markdown(path, *, base_url=..., timeout=...) -> str`，**不含 `ocr=True` 参数**（始终走 OCR）。

**DocxRenderer 模板制作约束**（docxtpl 限制）：

1. **模板必须由 Word / LibreOffice 手工制作**——不能用 python-docx 程序化生成（jinja 标签会被拆到多个 `<w:r>` 导致解析失败）
2. **单 cell 内不支持嵌套 `{% for %}`**——用 jinja2 过滤器（如 `{{ items | join('; ') }}`）扁平化
3. **避免表中表（nested tables）**
4. **退路**：若 docxtpl 不够用，直接 `python-docx` 手写渲染器；`DocxRenderer` 公共 API 不变，仅换底层实现

### 4.9 WorkspaceManager

为每次 PES run 创建隔离的沙箱目录，快照依赖的 skills/agents，成功后归档 `tar.gz`，失败保留现场。

```python
from scrivai import WorkspaceSpec, WorkspaceHandle, build_workspace_manager

ws_mgr = build_workspace_manager(
    workspaces_root="~/.scrivai/workspaces",
    archives_root="~/.scrivai/archives",
)

workspace: WorkspaceHandle = ws_mgr.create(WorkspaceSpec(
    run_id="audit_2026-04-15_abc",
    project_root=Path("GovDoc-Auditor"),   # 含业务 skills/ 和 agents/
    data_inputs={
        "tender.md": Path("/data/storage/tender_abc.md"),
        "checkpoints.json": Path("/data/storage/checkpoints_abc.json"),
    },
    extra_env={"GOVDOC_DB_PATH": "/data/app.sqlite"},
    force=False,              # run_id 冲突时：True 覆盖，False 抛 WorkspaceError
))

# 运行 PES
result = await ExtractorPES(..., workspace=workspace).run(task_prompt="...")

# 归档（业务层控制时机）
archive_path = ws_mgr.archive(workspace, success=result.status == "completed")
```

**`WorkspaceHandle` 目录结构**：

```
~/.scrivai/workspaces/<run_id>/
├── working/                   ← Agent 的 cwd
│   ├── .claude/
│   │   ├── skills/            ← 从 project_root/skills/ shutil.copytree 快照
│   │   └── agents/            ← 从 project_root/agents/ 快照
│   ├── plan.md, plan.json     ← plan phase 产物
│   ├── findings/*.json        ← execute phase 产物
│   └── output.json            ← summarize phase 产物
├── data/                      ← data_inputs 的内容快照（跨机可归档）
├── output/                    ← 对外最终产物（业务层填充）
├── logs/
│   ├── plan.json              ← PhaseLogHook 写
│   ├── execute.json
│   └── summarize.json
└── meta.json                  ← WorkspaceSnapshot 元信息
```

**关键机制**：

- **内容快照(MVP 临时实现)**:`shutil.copytree(symlinks=False)` 复制 skills / agents / data_inputs;不使用 symlink(跨机归档可复盘;main 分支变更不污染运行中的 run)。**临时**标注的含义:这是 MVP 简单方案,当 skills 资产增长 / 高频 run 出现时,应切换到:
  - **hardlink 方案**:同 inode 的硬链接替代复制(前提:同文件系统;M2 可加)
  - **content-addressed cache**:按内容 hash 缓存,同 hash 复用(M3 以后)
  - **资产白名单**:skills 目录只快照 SKILL.md + 小型元数据,大 asset 通过引用获取
  M0/M1 接受 `shutil.copytree`;M2 末评估升级。
- **并发锁**：`fcntl` 文件锁防两进程撞 run_id；`force=True` 才允许覆盖
- **Git hash 记录**：`WorkspaceSnapshot.skills_git_hash / agents_git_hash` 写入 `meta.json`，支持回溯
- **归档**：`archive(success=True)` 打包完整可复现集（`.claude/ + data/ + output/ + logs/ + meta.json`）到 `<run_id>.tar.gz` 并删除原目录
- **失败保留**：`archive(success=False)` 写 `.failed` 标记，不动目录；30 天后 `cleanup_old` 清理

### 4.10 CLI 命令规范

入口：`scrivai-cli <group> <subcommand> [args]`，等价 `python -m scrivai.cli <group> <subcommand>`

#### 4.10.1 双受众设计

`scrivai-cli` 是**单一二进制，两类受众**。按子命令组划分职责：

| 子命令组 | **Agent**（通过 Bash 调） | **业务层**（Python subprocess 或 shell） |
|---|:-:|:-:|
| `library {search, get, list}` | ✅ 主要用户 | ✅ 脚本化使用 |
| `io {docx2md, doc2md, pdf2md, render}` | ✅ 主要用户 | ✅ 预处理 / pipeline 脚本 |
| `workspace {create, archive, cleanup}` | ❌ **不给 Agent** | ✅ 生命周期管理 |
| `trajectory {record-feedback, list, get-run, build-eval-dataset}` | ❌ **不给 Agent** | ✅ 专家修订闭环 + 进化触发 |

**职责划分的性质——这是约定,不是安全边界**:

1. **`available-tools/SKILL.md`**:Agent 的"权威命令手册",**只列 `library` 和 `io` 两组**。这是 prompt 层的**可发现性降级**,不是权限隔离——如果 Agent 从别处学到命令名,`Bash` 仍然能调成功。
2. **`PhaseConfig.allowed_tools`**:`Bash` 允许 Agent 调命令,具体调什么由 SKILL.md 引导。
3. **业务层的两条路**:Python API(首选,如 `store.record_feedback(...)`)或 CLI(备选,如 `scrivai-cli trajectory record-feedback ...`)。Agent 只有 CLI 一条路(不能 `import scrivai`)。

**安全边界声明**:

- Scrivai **不依赖 CLI 分组做安全隔离**。
- 本版本(MVP)**接受**此"隐藏命令"方案——成本低、对当前威胁模型够用(LLM 不会主动探测文档外的命令)。**当前不提供运行时门禁**。
- **未来方案**(M3+ 或业务层自行实现):若需要真正阻断 Agent 访问 `workspace` / `trajectory`,可选:
  - 拆成两个入口二进制(如 `scrivai-admin-cli`)
  - 在 CLI 里通过 `SCRIVAI_CALLER_ROLE` 环境变量做运行时拒绝(Agent 侧 env 设 `agent`,业务侧设 `admin`)
- 风险登记在案。

**设计权衡**:不拆两个二进制,因为:

- 单一安装点(`pip install scrivai` 得一个 `scrivai-cli`)
- 共享 env / JSON / 退出码约定
- Agent 意外调 `workspace cleanup` 也基本无害(默认清 30 天前的,不影响当前 run)

#### 4.10.2 通用约定

- JSON 到 stdout（`json.dumps(..., ensure_ascii=False)`）
- 错误 JSON 到 stderr，exit 1
- 环境变量回退：`SCRIVAI_PROJECT_ROOT`、`QMD_DB_PATH`、`SCRIVAI_WORKSPACE_ROOT`、`SCRIVAI_ARCHIVES_ROOT`、`SCRIVAI_TRAJECTORY_DB`
- CLI 每个子命令的 JSON 输出 schema 在契约测试中和对应 Python API `.model_dump(mode="json")` 严格一致

#### 4.10.3 Agent 可见命令（写入 `available-tools/SKILL.md`）

```bash
# library —— Agent 在 execute 阶段查知识库的主要工具
scrivai-cli library search --type rules|cases|templates --query <q> [--top-k 5] [--filters '{}']
scrivai-cli library get    --type rules|cases|templates --entry-id <id>
scrivai-cli library list   --type rules|cases|templates [--filters '{}']

# io —— Agent 中途转换附件格式
scrivai-cli io docx2md --input <path> [--output <path>]
scrivai-cli io doc2md  --input <path> [--output <path>]
scrivai-cli io pdf2md  --input <path> [--output <path>] [--ocr]
scrivai-cli io render  --template <path> --context-json <path> --output <path>
```

#### 4.10.4 业务层专用命令（**不**写入 `available-tools/SKILL.md`）

```bash
# workspace —— 业务层在 run 生命周期节点调
scrivai-cli workspace create   --run-id <id> --project-root <path> --data <name>=<path>... [--env KEY=VAL...]
scrivai-cli workspace archive  --run-id <id> --success|--failed
scrivai-cli workspace cleanup  [--days 30]

# trajectory —— 业务层记录专家反馈 + 进化前构建评测集
scrivai-cli trajectory record-feedback --run-id <id> --draft <path> --final <path> [--corrections <path>]
scrivai-cli trajectory list [--pes-name <name>] [--limit 50]
scrivai-cli trajectory get-run --run-id <id>
scrivai-cli trajectory build-eval-dataset --pes-name <name> --output <csv-path>
```

业务层通常优先用 Python API（`ws_mgr.create(...)` / `store.record_feedback(...)`）；CLI 作为 shell 脚本 / CI/CD / 运维手工操作的备选。

### 4.11 通用 Skill 包（`Scrivai/skills/`）

```
Scrivai/skills/
├── available-tools/SKILL.md     ← CLI 命令 manifest
├── search-knowledge/SKILL.md    ← 如何调 library search
├── inspect-document/SKILL.md    ← 如何从 chunk_id 反查原文
└── render-output/SKILL.md       ← 如何构造 docxtpl 上下文
```

业务层可在自己的 `skills/` 里**同名覆盖**或**追加新 skill**；WorkspaceManager 快照时合并 project_root 下所有 skill 到 `working/.claude/skills/`。

**`available-tools/SKILL.md` 的作用**：Agent 的权威命令参考手册——**只列 Agent 可见的子命令**（见 §4.10.3）。枚举 `scrivai-cli library / io`、`qmd`、业务 CLI 的 Agent 可见子命令的参数、输出 JSON shape、典型错误。Agent 在任何 phase 都可 `Read .claude/skills/available-tools/SKILL.md` 避免 prompt 漂移瞎调命令。所有预置 PES 的 `default_skills` 默认含 `available-tools`。

**严禁**把 §4.10.4 的业务层专用命令（`workspace` / `trajectory`）写入 `available-tools/SKILL.md`——这是框架层面的信息隔离边界。契约测试会校验这一点。

**SKILL.md 格式**（Anthropic 约定）：

```markdown
---
name: search-knowledge
description: |
  Use when you need to look up rules, historical cases, or templates from
  the knowledge base. Returns ranked matches with chunk references for
  citation.
---

# Search Knowledge Skill

## When to use
- 需要查找相关法规 / 历史案例 / 模板
- 需要为某个判断找证据支撑

## How to use
Invoke via Bash:
```bash
scrivai-cli library search --type rules --query "<query>" --top-k 5
```

## Output
JSON list of SearchResult（见 available-tools/SKILL.md 完整 schema）

## Tips
- 同一查询可换 2-3 个表述提高召回
- 引用时必须带 chunk_id 便于回溯
```

### 4.12 通用 Agent Profile 包（`Scrivai/agents/`）

```
Scrivai/agents/
├── extractor.yaml     ← ExtractorPES 默认配置
├── auditor.yaml       ← AuditorPES 默认配置
└── generator.yaml     ← GeneratorPES 默认配置
```

YAML schema 严格匹配 §4.1 的 `PESConfig`。业务层可通过 `config_override` 传入自定义 PESConfig，或在业务项目的 `agents/` 下写同名 YAML 覆盖。

### 4.13 不变量(契约测试覆盖)

1. `WorkspaceManager.create` 产出的 `WorkspaceHandle` 目录结构完整;`working/.claude/skills/` 是从 `project_root/skills/` 的**内容快照**(非 symlink)
2. `WorkspaceManager.archive(success=True)` 打包 `.claude/ + data/ + output/ + logs/ + meta.json` 到 `<run_id>.tar.gz` 并删除原目录
3. `WorkspaceManager.archive(success=False)` 不动目录,写 `.failed` 标记
4. `BasePES.run` 严格按 plan → execute → summarize 顺序;plan 失败则后续不跑;任一 phase 失败则 `run.status = "failed"`;被取消则 `"cancelled"`
5. Phase 间交互通过 workspace 文件;三种失败出口(`sdk_*` / `response_parse_error` / `output_validation_error`)**必须**触发 `on_phase_failed` hook
6. Phase 级重试:`attempt_no < max_retries` 时自动从 `build_phase_context` 重跑;每次尝试的 `PhaseResult` 都落 `phases` 表新行(唯一键 `(run_id, phase_name, attempt_no)`)
7. `summarize` 的 `allowed_tools` 默认收紧到 `[Bash, Read, Write]`
8. `PESRun.final_output_path = workspace.working_dir / "output.json"`;业务层**应优先读此文件**而非 `PhaseResult.response_text`
9. `TrajectoryStore` 记录完整 turns(细粒度到每个 SDK message);phases 表与 runs 表通过 `run_id` 一致;`runs.provider` / `sdk_version` 必填
10. `TrajectoryStore.get_feedback_pairs(pes_name)` 返回的 pair 数 = 该 pes_name 下所有满足 `min_confidence` 阈值的 `feedback` 行数
11. `EvolutionTrigger.build_eval_dataset` 产出的 CSV 必含 `question / ground_truth / category` 三列;同一输入集**字节级可重复**
12. `FeedbackExample.ground_truth` 按 `sort_keys=True, separators=(",", ":")` 序列化
13. Library 的 `entry_id` 在 collection 内唯一;metadata 透传 qmd chunk metadata 不解释
14. `DocxRenderer.render` 成功即产出完整文件;失败不留半成品
15. 所有 CLI 命令在缺失必备 env var 时给出明确的 stderr JSON `{"error": "missing env var: ..."}`
16. **Hook 调用顺序严格**(phase 级展开):
    ```
    before_run
      → 对每个 phase in (plan, execute, summarize):
          (before_phase(attempt=N) → before_prompt → [after_prompt_turn]*
             → [on_phase_failed(attempt=N, will_retry) (若失败)]
             → [attempt=N+1 (若 will_retry,重试前先 _cleanup_phase_outputs)]
          )*
          → [on_output_written (仅 summarize validate 通过后)]
          → after_phase (该 phase 最终成功)
      → [on_run_cancelled (若取消)]
      → after_run (finally 一定触发)
    ```
17. `on_output_written` **只在 summarize 阶段、`validate_phase_outputs` 通过后、`after_phase` 前**触发一次
18. `on_run_cancelled` 触发时 `run.status = "cancelled"`;workspace **不归档、不清理**,保留现场;`_persist_final_state` 仍执行
19. **Phase 级重试前清场**:`attempt_no > 0` 时,框架先按 `phase_cfg.required_outputs` 规则删除上一轮的文件 / 目录,避免 `required_outputs` 被旧产物"假成功"
20. **`run()` 最终状态持久化**:成功 / 失败 / 取消 / before_run hook 异常四条路径,都保证 `_persist_final_state(run)` 被调用一次(不依赖 `after_run` hook)
21. **Hook 异常处理**:
    - 同步 hook(`before_run` / `before_phase` / `before_prompt` / `after_prompt_turn` / `after_phase` / `on_output_written`)异常 → 映射 `error_type="hook_error"`,`is_retryable=False`;`before_run` 异常使 run 级失败,其他使 phase 级失败
    - 非阻塞 hook(`on_phase_failed` / `on_run_cancelled` / `after_run`)异常 **永远** 只记录日志,不改变 run / phase 状态
22. `SkillsRootResolver.__enter__` 返回路径上 `<返回值>/.claude/skills/` 可被 EvoSkill 读到;`__exit__` 清理临时资源。**`chdir`** 不由 resolver 做,而是 `run_evolution` 在 resolver 上下文内部自行 `chdir`
23. `available-tools/SKILL.md` 的内容**只含** §4.10.3 的 Agent 可见子命令;`grep -E "workspace|trajectory" skills/available-tools/SKILL.md` 必须零结果(prompt 层可发现性约定,**不是安全边界**)

---

## 5. 内部架构

```
Scrivai/
├── scrivai/
│   ├── __init__.py               ← Public API(§4)
│   ├── exceptions.py
│   ├── models/                    ← pydantic + Protocol(单一真相)
│   │   ├── pes.py                  (PESRun, PESConfig, PhaseConfig, PhaseResult, PhaseTurn, ModelConfig, HookContext 等)
│   │   ├── workspace.py            (WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle, WorkspaceManager Protocol)
│   │   ├── knowledge.py            (LibraryEntry, Library Protocol)
│   │   ├── trajectory.py           (TrajectoryRecord, FeedbackRecord)
│   │   └── evolution.py            (EvolutionConfig, EvolutionRun, Evaluator Protocol)
│   ├── pes/                       ← BasePES 执行引擎
│   │   ├── base.py                 (BasePES 抽象类)
│   │   ├── hooks.py                (HookManager + 内置 hook)
│   │   ├── registry.py             (PESRegistry)
│   │   ├── config.py               (PESConfig YAML 加载)
│   │   └── messages.py             (SDK 消息解析)
│   ├── agents/                    ← 三个预置 PES
│   │   ├── extractor.py
│   │   ├── auditor.py
│   │   └── generator.py
│   ├── workspace/
│   │   └── manager.py              (WorkspaceManager 实现)
│   ├── knowledge/
│   │   ├── base.py                 (Library 基类)
│   │   ├── rules.py
│   │   ├── cases.py
│   │   ├── templates.py
│   │   └── factory.py              (build_libraries, build_qmd_client_from_config)
│   ├── io/
│   │   ├── convert.py              (docx/doc/pdf → md)
│   │   └── render.py               (DocxRenderer)
│   ├── trajectory/
│   │   ├── store.py                (TrajectoryStore SQLite)
│   │   ├── hooks.py                (TrajectoryRecorderHook)
│   │   └── feedback.py
│   ├── evolution/
│   │   ├── trigger.py              (EvolutionTrigger)
│   │   ├── runner.py               (run_evolution)
│   │   └── evaluator.py
│   ├── cli/
│   │   ├── __main__.py             (scrivai-cli 路由)
│   │   ├── library.py
│   │   ├── io.py
│   │   ├── workspace.py
│   │   └── trajectory.py
│   └── testing/
│       ├── mock_pes.py             (MockPES:按预录 trajectory 回放)
│       ├── tmp_workspace.py        (临时目录 WorkspaceManager)
│       ├── fake_trajectory.py      (内存版 TrajectoryStore)
│       └── contract.py             (pytest plugin,供下游复用)
├── skills/                        ← 通用 SKILL.md
│   ├── available-tools/SKILL.md
│   ├── search-knowledge/SKILL.md
│   ├── inspect-document/SKILL.md
│   └── render-output/SKILL.md
├── agents/                        ← 通用 PES YAML 配置
│   ├── extractor.yaml
│   ├── auditor.yaml
│   └── generator.yaml
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── design.md                   (本文)
│   └── TD.md
└── pyproject.toml
```

### 5.0 模块依赖拓扑

允许的 import 方向(上游 → 下游):

```
            ┌─────────────┐
            │   models    │  ← 被所有模块依赖;自身仅依赖 pydantic + qmd 类型
            └──────┬──────┘
                   │
       ┌───────────┼───────────┬───────────┬───────────┐
       ▼           ▼           ▼           ▼           ▼
   ┌───────┐  ┌─────────┐  ┌────────┐  ┌──────┐  ┌───────┐
   │  io   │  │knowledge│  │workspace│  │cli   │  │testing│
   └───┬───┘  └────┬────┘  └────┬────┘  └──────┘  └───┬───┘
       │           │            │                     │
       └───────────┴───────┬────┘                     │
                           ▼                          │
                    ┌──────────────┐                  │
                    │     pes      │  ◀───────────────┘
                    │ (BasePES +   │   (testing 仅用于 tests,
                    │  HookManager)│    不进生产代码)
                    └──────┬───────┘
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
           ┌────────┐ ┌──────────┐ ┌────────────┐
           │ agents │ │trajectory│ │ evolution  │
           │(三预置 │ │(Store +  │ │(Trigger +  │
           │ PES)   │ │ Recorder │ │ run_evo)   │
           │        │ │ Hook)    │ │            │
           └────────┘ └──────────┘ └────────────┘

cli 独立层:聚合 knowledge / io / workspace / trajectory 为 subcommand,
          不被 pes / agents 直接 import
```

**禁止的反向依赖**:

- `models` 禁止 import 任何其它 scrivai 子模块(自身只依赖 pydantic + qmd)
- `io / knowledge / workspace` 不能 import `pes`(防止循环)
- `knowledge / io / workspace / trajectory` 不能 import `cli`(cli 是它们的封装,反向依赖会形成环)
- `pes` 不能 import `agents / evolution`(预置 PES 和进化是 pes 的扩展,不是 pes 依赖)
- `testing` 只能被 `tests/` 目录 import,不能出现在 `scrivai/` 生产代码里

**特殊说明**:
- `trajectory/hooks.py`(`TrajectoryRecorderHook`)虽在 trajectory 模块,但其作为 BasePES hook 插件只依赖 `models` 中的 HookContext 类型;**不** import `pes/base.py`
- `evolution` 是 M2 启用模块;M0/M1 只写 `scrivai/models/evolution.py` 中的类型定义,实现留空

### 5.1 `BasePES.run` 和 `_run_phase` 关键流程

#### 5.1.1 `run()` 顶层

```python
async def run(self, task_prompt: str) -> PESRun:
    run = PESRun(
        run_id=self.workspace.run_id,
        pes_name=self.config.name,
        status="running",
        task_prompt=task_prompt,
        started_at=datetime.now(timezone.utc),
        model_name=self.model.model,
        provider=self.model.provider,
        sdk_version=claude_agent_sdk.__version__,
        skills_git_hash=self.workspace.snapshot.skills_git_hash,
        agents_git_hash=self.workspace.snapshot.agents_git_hash,
        skills_is_dirty=self.workspace.snapshot.skills_is_dirty,
    )

    # before_run 是同步 hook;异常直接冒泡为 run_status="failed" + error_type="hook_error"
    try:
        self.hooks.dispatch("before_run", RunHookContext(run=run))
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        run.error_type = "hook_error"
        run.ended_at = datetime.now(timezone.utc)
        self._persist_final_state(run)
        # after_run 仍然触发(非阻塞);然后冒泡
        self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))
        raise

    try:
        for phase in ("plan", "execute", "summarize"):
            result = await self._run_phase_with_retry(phase, run, task_prompt)
            run.phase_results[phase] = result
        run.status = "completed"

    except PhaseError as e:
        run.status = "failed"
        run.error = str(e)
        run.error_type = e.result.error_type if e.result else "sdk_other"
        # _run_phase_with_retry 内部已按 attempt 触发了 on_phase_failed
    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        run.status = "cancelled"
        run.error = "interrupted"
        run.error_type = "cancelled"
        self.hooks.dispatch_non_blocking(
            "on_run_cancelled",
            CancelHookContext(run=run, reason=type(e).__name__),
        )
        # 【#22 finalize 责任】取消也要确保最终状态落盘——不依赖 hook
        run.ended_at = datetime.now(timezone.utc)
        self._persist_final_state(run)
        self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))
        raise   # 让调用方感知取消
    finally:
        # 【#22 finalize 责任】成功 / 失败两条路径统一在这里完成最终持久化
        # 取消路径已在 except 分支里处理过,这里 already_finalized 跳过
        if run.status != "cancelled":
            run.ended_at = run.ended_at or datetime.now(timezone.utc)
            self._persist_final_state(run)
            self.hooks.dispatch_non_blocking("after_run", RunHookContext(run=run))

    return run


def _persist_final_state(self, run: PESRun) -> None:
    """显式把 run 的最终状态写到 TrajectoryStore,**不依赖** after_run hook。

    这样即便:
    - 业务层忘记注册 TrajectoryRecorderHook
    - 某个非阻塞 hook 异常
    - cancel 路径上不让 after_run 成为数据完整性依赖
    runs 表仍会有正确的 status + error + ended_at + workspace_archive_path。
    """
    if self.trajectory_store is None:
        return
    self.trajectory_store.finalize_run(
        run_id=run.run_id,
        status=run.status,
        final_output=run.final_output,
        workspace_archive_path=None,  # 业务层 archive 后再补 update_archive_path
        error=run.error,
        error_type=run.error_type,
    )
```

**`run()` 的调用约定**(Codex #13 + #22 闭环):

- **正常完成** → 返回 `PESRun(status="completed")`
- **Phase 失败 / before_run hook 失败** → 返回 `PESRun(status="failed")`,**不 raise**(调用方检查 `.status`)
- **KeyboardInterrupt / CancelledError** → `PESRun` 已持久化 `status="cancelled"` 到 trajectory,但**向上 re-raise**(调用方应捕获并归档 workspace)
- 三条路径都保证 `_persist_final_state` 被调用一次

#### 5.1.2 `_run_phase_with_retry()` —— 包裹 phase 级重试

```python
async def _run_phase_with_retry(self, phase, run, task_prompt) -> PhaseResult:
    phase_cfg = self.config.phases[phase]
    last_result = None
    # attempt_no 是 **0-based**:首次尝试=0,首次重试=1;max_retries=1 → 最多跑 2 次
    for attempt_no in range(phase_cfg.max_retries + 1):
        if attempt_no > 0:
            # 【#19 重试前清场】删除该 phase 上一轮产生的文件,避免 required_outputs 被旧产物"假成功"
            self._cleanup_phase_outputs(phase, phase_cfg)
        try:
            result = await self._run_phase(phase, run, task_prompt, attempt_no)
            return result  # 成功即返回
        except PhaseError as e:
            last_result = e.result
            will_retry = (
                attempt_no < phase_cfg.max_retries
                and e.result.is_retryable
            )
            self.hooks.dispatch_non_blocking(
                "on_phase_failed",
                FailureHookContext(
                    phase=phase,
                    run=run,
                    result=e.result,
                    attempt_no=attempt_no,
                    will_retry=will_retry,
                    error_type=e.result.error_type,
                ),
            )
            if not will_retry:
                raise  # 冒泡到 run(),触发 run.status="failed"
    # 理论不可达;保险:
    raise PhaseError(phase, "exhausted retries", result=last_result)


def _cleanup_phase_outputs(self, phase: str, phase_cfg: PhaseConfig) -> None:
    """按 phase_cfg.required_outputs 的每条规则删除上一轮产物。

    规则处理:
    - 字符串路径 `"plan.md"` → 若存在则 `unlink()`
    - 目录规则 `{"path":"findings/", ...}` → `rmtree()`(整个目录)
    - **同时**:扫描 working/ 下该 phase 的所有产出(通过 `_list_produced_files(phase)`
      的反向记录),确保没有遗漏(防御性)
    - logs_dir 里该 phase 的旧日志保留(按 attempt_no 区分文件名,不会覆盖)
    - 清场失败(如权限错)→ 抛 `WorkspaceError`,视为不可重试的 run 级失败
    """
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
```

**重试前清场语义**(契约):
- 每次 `attempt_no > 0` 时,先清该 phase 的所有 required_outputs(文件 unlink,目录 rmtree)
- 清场**不**清理前序 phase 的产物(plan 的 plan.md 不会因为 execute 重试被删)
- 清场失败 → `WorkspaceError`,run 级失败;不尝试重试
- `logs_dir` 下的 `phase-<phase>-attempt-<N>.log.json` 按 attempt 分文件,不相互覆盖

#### 5.1.3 `_run_phase()` —— 单次尝试

```python
async def _run_phase(self, phase, run, task_prompt, attempt_no: int) -> PhaseResult:
    """单次 phase 尝试。**所有**同步 hook 异常(before_phase/before_prompt/after_prompt_turn/
    after_phase/on_output_written)都会被包成 `PhaseError(error_type="hook_error", is_retryable=False)`。
    """
    phase_cfg = self.config.phases[phase]

    # 同步 hook 异常 → hook_error(不可重试)
    try:
        self.hooks.dispatch("before_phase",
                            PhaseHookContext(phase=phase, run=run, attempt_no=attempt_no))
    except Exception as e:
        result = PhaseResult(phase=phase, attempt_no=attempt_no, prompt="",
                             response_text="", turns=[], usage={},
                             produced_files=[], started_at=datetime.now(timezone.utc),
                             error=str(e), error_type="hook_error", is_retryable=False,
                             ended_at=datetime.now(timezone.utc))
        raise PhaseError(phase, str(e), result=result) from e

    # 1. 构建 execution_context(子类扩展点 1)
    execution_context = await self.build_execution_context(phase, run)

    # 2. 合并双层 context + 框架自动字段
    context = self._merge_context(
        runtime=self.runtime_context,
        execution=execution_context,
        framework={
            "phase": phase,
            "attempt_no": attempt_no,
            "run": run.to_prompt_payload(),
            "workspace": self.workspace.to_prompt_payload(),
            "previous_phase_output": self._read_previous_phase_output(phase),
        },
    )

    # 3. 渲染 prompt(子类扩展点 2)
    prompt = await self.build_phase_prompt(phase, phase_cfg, context, task_prompt)

    prompt_ctx = PromptHookContext(phase=phase, run=run, attempt_no=attempt_no,
                                   prompt=prompt, context=context)
    try:
        self.hooks.dispatch("before_prompt", prompt_ctx)
    except Exception as e:
        result = PhaseResult(phase=phase, attempt_no=attempt_no, prompt=prompt,
                             response_text="", turns=[], usage={},
                             produced_files=[], started_at=datetime.now(timezone.utc),
                             error=str(e), error_type="hook_error", is_retryable=False,
                             ended_at=datetime.now(timezone.utc))
        raise PhaseError(phase, str(e), result=result) from e
    prompt = prompt_ctx.prompt  # hook 可修改

    # 4. 调 SDK(唯一可能抛 SDK 相关异常的段落)
    started_at = datetime.now(timezone.utc)
    turns = []
    response_text = ""
    usage = {}
    error: str | None = None
    error_type: str | None = None
    result: PhaseResult | None = None

    try:
        try:
            # after_prompt_turn 同步 dispatch;异常会从 _call_sdk_query 透传上来
            # → 落到外层 except Exception 分支,映射成 hook_error(is_retryable=False)
            response_text, usage, turns = await self._call_sdk_query(
                phase_cfg, prompt, run, attempt_no,
                on_turn=lambda t: self.hooks.dispatch(
                    "after_prompt_turn",
                    PromptTurnHookContext(phase=phase, run=run,
                                          attempt_no=attempt_no, turn=t),
                ),
            )
        except _SDKError as e:
            # _SDKError 由 BasePES._call_sdk_query 翻译 LLMClient 内部异常构造
            error_type = e.error_type   # "max_turns_exceeded" / "sdk_other"
            error = str(e)
            raise
        except (KeyboardInterrupt, asyncio.CancelledError):
            error_type = "cancelled"
            raise   # 不包成 PhaseError,让 run() 的 finally 处理

        # 5. 构造 PhaseResult
        result = PhaseResult(
            phase=phase,
            attempt_no=attempt_no,
            prompt=prompt,
            response_text=response_text,
            turns=turns,
            usage=usage,
            produced_files=self._list_produced_files(phase),
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
        )

        # 6. 子类响应后处理(子类扩展点 3)
        try:
            await self.postprocess_phase_result(phase, result, run)
        except Exception as e:
            result.error = str(e)
            result.error_type = "response_parse_error"
            result.is_retryable = False  # 解析错误一般不值得重试
            raise PhaseError(phase, str(e), result=result) from e

        # 7. 校验必需产物(子类扩展点 4)
        try:
            await self.validate_phase_outputs(phase, phase_cfg, result, run)
        except Exception as e:
            result.error = str(e)
            result.error_type = "output_validation_error"
            result.is_retryable = True  # 产物校验失败允许重跑
            raise PhaseError(phase, str(e), result=result) from e

        # 8. summarize 阶段特殊 hook:on_output_written(同步;异常 → hook_error)
        if phase == "summarize":
            try:
                self.hooks.dispatch(
                    "on_output_written",
                    OutputHookContext(
                        run=run,
                        output_path=self.workspace.working_dir / "output.json",
                        output=run.final_output,   # 由 postprocess_phase_result 填充到 run.final_output
                    ),
                )
            except Exception as e:
                result.error = str(e)
                result.error_type = "hook_error"
                result.is_retryable = False
                raise PhaseError(phase, str(e), result=result) from e

        # 9. after_phase(同步;异常 → hook_error)
        try:
            self.hooks.dispatch("after_phase",
                                PhaseHookContext(phase=phase, run=run,
                                                 attempt_no=attempt_no, result=result))
        except Exception as e:
            result.error = str(e)
            result.error_type = "hook_error"
            result.is_retryable = False
            raise PhaseError(phase, str(e), result=result) from e

        return result

    except PhaseError:
        raise  # 已在 step 6/7 构造好 result
    except Exception as e:
        # SDK 异常路径:包装成 PhaseError
        if result is None:
            result = PhaseResult(
                phase=phase, attempt_no=attempt_no, prompt=prompt,
                response_text=response_text, turns=turns, usage=usage,
                produced_files=self._list_produced_files(phase),
                error=error or str(e),
                error_type=error_type or "sdk_other",
                is_retryable=(error_type in ("sdk_rate_limit", "max_turns_exceeded")),
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
            )
        raise PhaseError(phase, result.error, result=result) from e
```

**SDK 0.1.61 异常模型**:SDK 不通过 `RateLimitError` / `MaxTurnsExceeded` / `AnthropicError` 异常表达错误,而是通过消息字段(`ResultMessage.is_error` + `stop_reason` / `AssistantMessage.error`)。Scrivai 的策略:`LLMClient`(`scrivai/pes/llm_client.py`)在边界把消息流错误翻译为模块内部异常 `_MaxTurnsError` / `_SDKExecutionError`,`BasePES._call_sdk_query` 再统一映射为 `_SDKError(error_type=...)`。`_run_phase` step 5 据此组装 PhaseResult。SDK 升级时,只需改 `LLMClient`,`BasePES` 零改动。

**关键点**:
- **三种失败出口**(SDK 异常 / postprocess 抛 / validate 抛)**都**通过 `PhaseError` 包装,带 `result: PhaseResult`
- **on_phase_failed**在 `_run_phase_with_retry` 统一 dispatch,所有失败路径都能触发
- **重试决策**由 `result.is_retryable` 控制:max_turns / sdk_other / output_validation 允许重试;response_parse / cancelled 不重试
- **on_output_written** 只在 summarize 且 validate 通过后、after_phase 前触发一次
- **KeyboardInterrupt / CancelledError** 不包 PhaseError,直接冒泡到 `run()` 的 cancel 分支

### 5.2 WorkspaceManager.create 关键流程

```python
def create(self, spec: WorkspaceSpec) -> WorkspaceHandle:
    root = self.workspaces_root / spec.run_id
    lock_path = self.workspaces_root / f".{spec.run_id}.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise WorkspaceError(f"workspace {spec.run_id} is locked")

    try:
        if root.exists():
            if not spec.force:
                raise WorkspaceError(f"workspace already exists: {root}")
            shutil.rmtree(root)

        working, data, output, logs = [root / d for d in ("working", "data", "output", "logs")]
        for d in (working, data, output, logs):
            d.mkdir(parents=True, exist_ok=True)

        claude_dir = working / ".claude"
        claude_dir.mkdir()
        for sub in ("skills", "agents"):
            src = spec.project_root / sub
            if src.exists():
                shutil.copytree(src, claude_dir / sub, symlinks=False)

        for name, src in spec.data_inputs.items():
            dst = data / name
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False)
            else:
                shutil.copy2(src, dst)

        snapshot = WorkspaceSnapshot(
            skills_git_hash=self._git_hash(spec.project_root),
            agents_git_hash=self._git_hash(spec.project_root),
            snapshot_at=datetime.now(timezone.utc).isoformat(),
        )
        (root / "meta.json").write_text(json.dumps({
            "run_id": spec.run_id,
            "project_root": str(spec.project_root.resolve()),
            "data_inputs": {k: str(v) for k, v in spec.data_inputs.items()},
            "extra_env": spec.extra_env,
            "snapshot": snapshot.model_dump(),
        }, ensure_ascii=False, indent=2))

        return WorkspaceHandle(
            run_id=spec.run_id, root_dir=root,
            working_dir=working, data_dir=data,
            output_dir=output, logs_dir=logs,
            snapshot=snapshot,
        )  # meta.json 路径通过 root_dir / "meta.json" 派生，不作为字段存储
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        lock_path.unlink(missing_ok=True)
```

### 5.3 Claude Agent SDK 集成要点

#### 5.3.1 调用范式:stateless `query()` per phase

Scrivai 通过 `claude_agent_sdk.query()` 异步迭代器消费 SDK。**每个 PES 阶段独立调一次 `query()`**,不使用 `Client` 长连接模式,阶段间状态完全通过 workspace 文件传递。

**理由**:

1. 每阶段 `allowed_tools` 不同,独立 options 更清晰
2. 阶段失败可单独重跑,不必重放整个会话
3. trajectory 按阶段归档,便于 EvoSkill 评估粒度控制
4. 避免 SDK 会话隐藏状态对运行可复现性的污染

```python
async for message in query(prompt=phase_prompt, options=options):
    # message: AssistantMessage | UserMessage | ResultMessage
    ...
```

#### 5.3.2 不使用 MCP 的决策

Scrivai 所有工具通过 `scrivai-cli` + Agent 的 `Bash` tool 暴露,**不使用** MCP server 模式。理由:

1. **调试简单**:Agent 调的是标准 subprocess,stdout/stderr 可完整重放;MCP 协议栈增加断点成本
2. **快照兼容**:CLI 二进制在 PATH 里,workspace snapshot 只管 skills;MCP server 要嵌入配置反倒破坏隔离
3. **无状态约束**:CLI 每次调用短进程,不留 session;MCP 长连接会引入隐藏状态

**重新评估时机**:若单次 CLI 冷启动开销在生产中成为瓶颈(M3 末测),或 SDK 对 MCP 提供原生 trajectory 支持且优于 subprocess logging。

#### 5.3.3 `allowed_tools × phase` 矩阵

| 工具 | plan | execute | summarize | 备注 |
|---|:-:|:-:|:-:|---|
| `Bash` | ✅ | ✅ | ✅ | CLI 工具调用入口 |
| `Read` | ✅ | ✅ | ✅ | 读 `working/` 下文件 |
| `Write` | ✅ | ✅ | ✅ | 写 `plan.md / findings / output.json` |
| `Edit` | ✅ | ✅ | ❌ | summarize 不编辑,只聚合 |
| `Glob` | ✅ | ✅ | ❌ | summarize 不探索,避免发散 |
| `Grep` | ✅ | ✅ | ❌ | 同上 |
| `Skill` | ✅ | ✅ | ❌ | summarize 阶段已有所有 findings,不需要再查 skill |
| `WebSearch / WebFetch` | ❌ | ❌ | ❌ | 禁止联网,避免非确定性 |
| `Task`(subagent) | ❌ | ❌ | ❌ | MVP 禁用,简化问题 |
| `TodoWrite` | ❌ | ❌ | ❌ | flow 由 BasePES 控,Agent 不维护 todo |

**强制不变量**:summarize 阶段 `allowed_tools == ["Bash", "Read", "Write"]`。预置 PES 默认配置 + `PESConfig` YAML 加载时校验。

#### 5.3.4 三层重试机制

Scrivai 的重试是**分层的**,每层职责明确:

| 层 | 触发 | 实现位置 | 重试策略 | 是否计入 `attempt_no` |
|---|---|---|---|---|
| ~~L1 传输级~~ | (M1.0 不实现) | — | 推迟到 M2 T2.5 视压测结果决定 | — |
| **L2 Phase 级** | 任何 SDK 失败 / `output_validation_error` | `_run_phase_with_retry` | 最多 `phase_cfg.max_retries + 1` 次(默认 1 次重试,即最多跑 2 遍) | 是(`attempt_no += 1`) |
| **L3 Run 级** | L2 最终失败 | 无(不重试) | `run.status = "failed"` | — |

**M1.0 契约**:所有 SDK 失败(包括 rate limit / 网络超时 / SDK 内部错误)统一归并到 `error_type="sdk_other"`,`is_retryable=True`,由 L2 phase 级重试兜底。**不实现** L1 传输级精确退避(SDK 0.1.61 提供的 `RateLimitInfo.resets_at` 在 M2 压测后再决定是否启用)。

**is_retryable 决策表**(决定是否走 L2 重试):

| `error_type` | `is_retryable` | 理由 |
|---|---|---|
| `max_turns_exceeded` | ✅ | 可能首次超限,重新规划能更简洁 |
| `sdk_other` | ✅ | M1.0 契约:任何 SDK 失败(rate limit / 网络 / SDK 内部)都允许重试,L2 phase 级兜底 |
| `response_parse_error` | ❌ | Agent 输出格式错,重跑大概率还错;需改 prompt / skill |
| `output_validation_error` | ✅ | 产物缺失或不合规,Agent 重跑可能补全 |
| `cancelled` | ❌ | 用户/系统中断,不应自动恢复 |
| `hook_error` | ❌ | 插件 bug,重跑会重复触发 |

**完整错误 → 状态映射**:

| 情形 | 层级 | `PhaseResult.error_type` | `will_retry` | 最终影响 |
|---|---|---|---|---|
| 阶段达 `max_turns` | L2 | `max_turns_exceeded` | 看 `attempt_no < max_retries` | 若仍失败 → run.status="failed" |
| 任何 SDK 失败(rate limit / 网络 / 其他)| L2 | `sdk_other` | 看 `attempt_no < max_retries` | 重试耗尽 → run.status="failed" |
| `postprocess_phase_result` 抛异常 | — | `response_parse_error` | ❌ | run.status="failed" |
| `validate_phase_outputs` 抛异常 | L2 | `output_validation_error` | ✅ 允许重试 | 重试耗尽后 run.status="failed" |
| `KeyboardInterrupt` / `CancelledError` | — | `cancelled` | ❌ | run.status="cancelled";workspace **不归档** |
| Hook 抛异常(同步 dispatch) | — | `hook_error` | ❌ | run.status="failed" |
| Hook 抛异常(非阻塞 dispatch) | — | — | — | 仅 loguru 记录,不影响 run |

#### 5.3.5 SDK Hooks 与 BasePES Hooks 的区别

两个概念同名但作用层次不同:

| 维度 | **SDK Hooks**(Claude Agent SDK 提供) | **BasePES Hooks**(Scrivai 提供) |
|---|---|---|
| 位置 | `ClaudeAgentOptions.hooks` | `scrivai.HookManager` |
| 触发点 | Agent 调 tool 前/后、会话结束 | phase 开始/结束、run 开始/结束、prompt 渲染后、turn 收到后 |
| 作用 | 观察 Agent 的 tool 调用 | 控制 PES 三阶段流程 + 插件扩展 |
| 用途示例 | 拦截写 `output.json` 并校验 schema | 插入 TrajectoryRecorderHook 写数据库 |

两者**并存、互补**。`TrajectoryRecorderHook` 属于 BasePES Hooks,记录 phase 级事件;SDK hooks 如需使用(例如细粒度 tool call 校验),由 BasePES 在构造 `ClaudeAgentOptions` 时装配,不对外暴露。

#### 5.3.6 SDK 适配单点 + 多供应商策略

SDK 0.1.61 通过**消息字段**(`ResultMessage.is_error` / `AssistantMessage.error`)而非异常表达错误。Scrivai 的策略:**`LLMClient`(`scrivai/pes/llm_client.py`)在边界把消息流错误翻译为模块内部异常**(`_MaxTurnsError` / `_SDKExecutionError`),`BasePES._call_sdk_query` 再映射为 `_SDKError(error_type=...)`。这是单点适配:SDK 升级或换供应商时,只改 `LLMClient`,`BasePES` 零改动。

**多供应商**:`ModelConfig.base_url + api_key` 通过 `ClaudeAgentOptions(env={"ANTHROPIC_BASE_URL": ..., "ANTHROPIC_AUTH_TOKEN": ...})` 注入 SDK 子进程 env;主进程 env 不污染,并发安全。`base_url` / `api_key` 为 `None` 时 SDK 继承父进程 env(`.env` 加载的默认值)。若本机设有 http/https proxy,通常要把私有网关 IP 加入 `NO_PROXY`(见 `.env.example`)。

**未来方案**(M2+ 评估):引入内部 `AgentDriver Protocol` —— 把 `LLMClient` 抽象化以支持非 SDK 供应商(自研 Agent loop / OpenAI Assistants / Vertex AI 等)。多供应商需求到来时再做,不在 M1 范围。

#### 5.3.7 `LLMClient` 接口约定

`LLMClient.execute_task(...)` 是 `BasePES` 与 SDK 之间的**唯一适配点**。接口约定:

| 方面 | 约定 |
|---|---|
| 输入 | `prompt / system_prompt / allowed_tools / max_turns / permission_mode / cwd / extra_env / on_turn` |
| 输出 | `LLMResponse(result, turns, usage, duration_ms, session_id)` |
| 异常 | `_MaxTurnsError` / `_SDKExecutionError` / `RuntimeError("未收到 ResultMessage")` / SDK 原生异常透传(`CLIConnectionError` / `ProcessError` / `ClaudeSDKError`) |
| 内部重试 | **无** —— L2 phase 级重试由 `BasePES._run_phase_with_retry` 负责 |
| 副作用 | 调 `on_turn(turn)` 回调通知 BasePES dispatch `after_prompt_turn` hook;**不**写文件、**不**改 env、**不**记 trajectory(后者由 hook 系统统一处理) |

**测试约定**:
- 单测通过 `unittest.mock.patch("scrivai.pes.llm_client.query", ...)` 替换 SDK 入口
- 集成测通过 `BasePES(llm_client=mock_llm_client)` 注入,绕过 LLMClient 内部细节
- 真 SDK smoke 测必须用 `pytest.mark.skipif(not os.getenv("ANTHROPIC_AUTH_TOKEN"))`

后续若多供应商需求来,只需写新 driver 实现同接口(后改为 `AgentDriver Protocol`),`BasePES` 零改动。

### 5.4 MVP 可观测性范围(未解决项,降格表述)

**当前有的**:
- `TrajectoryStore`:完整 runs / phases / turns / tool_calls / feedback 持久化,SQL 可查
- `PhaseLogHook`:每 phase 每 attempt 的 prompt / response / turns JSON dump 到 `workspace.logs_dir/`
- loguru 日志:phase 启动 / 结束 / 失败的文本日志

**当前没有**:
- Metrics(计数器 / 直方图):没有 run / phase duration 的聚合指标;没有 retry / tool_call 计数
- Traces(OpenTelemetry / Jaeger):没有跨 phase / 跨 tool_call 的 trace context
- Dashboard:没有 trajectory 的 UI 查看器(查询只能走 SQL 或 `scrivai-cli trajectory`)

**评估点**:MVP 认为"SQL + 日志"对初期调试足够;metrics/traces 的优先级是 M2 P1(`TD.md T2.7`)。**不要**假设当前框架已具备完整 observability——排错主要靠人工看文件 / SQL 查询。

**M2 最低目标**(若采纳):run/phase duration、失败计数、retry 计数、tool_call 次数、archive 大小——5 个计数器。不一定接 OTEL,但指标面要定义出来。

---

## 6. 业务应用怎么用 Scrivai

```python
import asyncio, os
from pathlib import Path
from pydantic import BaseModel

from scrivai import (
    ExtractorPES, ModelConfig, WorkspaceSpec,
    HookManager, TrajectoryStore, TrajectoryRecorderHook,
    build_workspace_manager, build_qmd_client_from_config,
    build_libraries,
)

# 业务 schema
class GovCheckpoint(BaseModel):
    id: str
    description: str
    category: str
    severity: str

class ExtractionOutput(BaseModel):
    items: list[GovCheckpoint]

async def run_extraction(guide_path: Path, run_id: str):
    # 1. 连 qmd
    qmd_client = build_qmd_client_from_config(db_path=os.environ["QMD_DB_PATH"])
    rules, cases, templates = build_libraries(qmd_client)

    # 2. 创建 workspace
    ws_mgr = build_workspace_manager()
    workspace = ws_mgr.create(WorkspaceSpec(
        run_id=run_id,
        project_root=Path.cwd(),  # 业务项目根(含 skills/ 和 agents/)
        data_inputs={"guide.md": guide_path},
    ))

    # 3. 配置轨迹记录(插入 hook)
    store = TrajectoryStore()
    hooks = HookManager()
    hooks.register(TrajectoryRecorderHook(store))

    # 4. 选择预置 PES + 业务覆盖
    pes = ExtractorPES(
        output_schema=ExtractionOutput,
        extra_skills=["gov-domain-rules"],  # 业务追加 skill
        model=ModelConfig(
            model="claude-sonnet-4-6",
            api_key=os.environ["ANTHROPIC_API_KEY"],
        ),
        workspace=workspace,
        hooks=hooks,
        trajectory_store=store,
    )

    # 5. 跑一次
    result = await pes.run(task_prompt=f"""
        从 data/guide.md 中抽取所有审核点,每个含 id/description/category/severity 字段。
        最终输出 output.json 格式:{{"items": [GovCheckpoint, ...]}}
    """)

    # 6. 归档
    ws_mgr.archive(workspace, success=result.status == "completed")

    # 7. 业务层拿到结果落自己的数据库
    if result.status == "completed":
        items = ExtractionOutput.model_validate(result.final_output).items
        # ... 存 app.sqlite ...

    return result.run_id

# 后来专家审核修改后
def record_expert_correction(run_id: str, draft: dict, final: dict):
    store = TrajectoryStore()
    store.record_feedback(
        run_id=run_id,
        draft_output=draft,
        final_output=final,
        submitted_by="expert_01",
    )

# 积累若干后手动触发进化
async def trigger_evolution():
    from scrivai import EvolutionTrigger, EvolutionConfig, run_evolution

    store = TrajectoryStore()
    trigger = EvolutionTrigger(store, pes_name="extractor", min_feedback_pairs=10)

    if not trigger.has_enough_data():
        return None

    dataset_csv = trigger.build_eval_dataset(
        output_path=Path("~/.scrivai/eval/extractor.csv"),
    )

    class IoUEvaluator:
        def __call__(self, q, pred, gt) -> float:
            # 业务实现:比较 items 的 IoU
            ...

    evo_run = await run_evolution(
        config=EvolutionConfig(
            task_name="extractor_2026-04-15",
            model="claude-sonnet-4-6",
            eval_dataset_csv=dataset_csv,
            max_iterations=5,
        ),
        evaluator=IoUEvaluator(),
    )
    return evo_run.promoted_branch

asyncio.run(run_extraction(Path("guide.md"), "extract_001"))
```

---

## 7. 配置

业务层传给 Scrivai 的 `scrivai.yaml`(示例):

```yaml
model:
  model: claude-sonnet-4-6
  base_url: https://api.anthropic.com
  api_key: ${ANTHROPIC_API_KEY}
  fallback_model: claude-haiku-4-5

qmd:
  db_path: ./data/qmd.sqlite

workspace:
  workspaces_root: ~/.scrivai/workspaces
  archives_root: ~/.scrivai/archives
  cleanup_days: 30

trajectory:
  db_path: ~/.scrivai/trajectories.sqlite

evolution:
  proposer_model: claude-sonnet-4-6
  frontier_size: 5
  max_iterations: 5
  cache_dir: ~/.scrivai/cache/evolution
```

---

## 8. 非目标(YAGNI)

- 流式输出(中间消息用于日志,但对外不暴露 stream API)
- 多 Agent 互相调用(MVP 单 PES + 三阶段)
- 跨进程任务调度(业务层用 FastAPI BackgroundTasks 即可)
- prompt 版本管理(EvoSkill 的 git 分支即事实版本管理)
- 多模态 prompt
- Windows 支持(MVP Linux/macOS)
- 自动合并 EvoSkill 候选到 main(必须人工 PR)
- trajectory 的 UI 查看器(查询通过 SQL 或 CLI 即可)
- TrajectoryStore 跨机同步(MVP 本地单进程)

---

## 9. 性能目标

**前置假设**(打破则目标失效):

- `project_root/skills/` + `project_root/agents/` 总大小 **≤ 5 MB**(纯 SKILL.md + YAML + 小型 asset)
- 单个 `data_input` 文件 ≤ 50 MB
- `trajectories.sqlite` ≤ 10 GB(超过应 `scrivai-cli trajectory prune`)

**目标**:

| 指标 | 目标 | 条件 |
|---|---|---|
| `BasePES.run` 端到端(含 LLM) | ≤ 5 分钟 | 中等任务:10 子项 × 50 页文档 |
| `WorkspaceManager.create` P95 | < 100 ms | skills+agents ≤ 5 MB |
| `WorkspaceManager.create` P95 | < 500 ms | skills+agents ≤ 50 MB(降级目标) |
| `WorkspaceManager.archive` P95 | < 5 s | 含 tar.gz,workspace 总大小 ≤ 100 MB |
| `scrivai-cli` 命令冷启动 P50 | < 300 ms | 不含真实 IO / 检索 |
| `TrajectoryStore.record_turn` P99 | < 10 ms | 单 turn ≤ 10 KB;WAL 模式,无争用 |
| `TrajectoryStore.get_feedback_pairs(pes_name)` P95 | < 200 ms | ≤ 1000 条 feedback;加 `min_confidence` 索引 |
| `TrajectoryStore.list_runs(pes_name, limit=50)` P95 | < 50 ms | ≤ 10k runs |

**skills 超限时的处理**:

- `WorkspaceManager.create` 发现 skills+agents 总大小 > 50 MB → loguru 打 WARNING + 继续执行
- 超过 100 MB → 抛 `WorkspaceError`(避免误配置把大模型 checkpoint 放进 skills)
- 业务层需自觉:大资产(如参考文档、模板库)应放 `data_inputs/`,不放 skills

**大小测量口径**(避免实现漂移):

- 按 `project_root/skills/` 和 `project_root/agents/` **两目录**分别测,相加
- 统计方法等价于 `du -sb --exclude='.git' --no-dereference <dir>`(字节数;不跟随 symlink;排除 `.git` 目录)
- 隐藏文件(`.*` 开头)**计入**(除 `.git` 外);SKILL.md / asset 命名不应以 `.` 开头,否则自觉
- 测量点:`WorkspaceManager.create` **复制前**(`shutil.copytree` 调用前)
- 超限错误消息须包含两个目录的实际大小,帮助排查

---

详细任务分解见 `TD.md`。
