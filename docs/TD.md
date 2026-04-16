# Scrivai 任务分解

**日期**: 2026-04-15
**开发分支系列**: `feat/scrivai-m0` · `feat/scrivai-m0.25` · `feat/scrivai-m0.5` · `feat/scrivai-m0.75`(按子里程碑各自拉分支,见下方 M0 系列章节)

---

## 里程碑总览

M0 按依赖拓扑拆为 **4 个独立可验证的子里程碑**(M0 / M0.25 / M0.5 / M0.75),每个子里程碑有自己的分支、PR、契约测试集和 DoD,可独立合入 main 后再拉下一个分支。

| 里程碑 | 周期 | 主题 | 独立 DoD / 集成节点 |
|---|---|---|---|
| **M0**(地基层) | Week 1(~3.3d) | legacy 清理 + 所有 pydantic / Protocol 模型 + PES config YAML loader + Evolution 占位 | `test_models / test_pes_config / test_reexport / test_evolution_stubs` 全绿;`mypy --strict scrivai/models/` 通过 |
| **M0.25**(基础设施层) | Week 1.5-2(~6d) | WorkspaceManager + HookManager + TrajectoryStore + Testing helpers | `test_workspace / test_hooks / test_trajectory_store` 全绿;`TempWorkspaceManager / FakeTrajectoryStore` 可独立使用 |
| **M0.5**(PES 核心层) | Week 2-3(~6.3d) | BasePES(4 扩展点 + L1/L2 重试 + cancel + hook_error) + MockPES + TrajectoryRecorderHook | `test_base_pes / test_mock_pes / test_trajectory_hook` 全绿 |
| **M0.75**(外围 + API 冻结 + I0) | Week 3-4(~9d) | Knowledge Libraries + IO + CLI + 通用 Skills/Agents 内容 + contract plugin + qmd 契约双向验证 + Public API 最终冻结 | 全量 `tests/contract/` 绿;`from scrivai import *` 对齐 design §4.1 清单;**I0 集成节点通过** |
| **M1** | Week 4-6 | 真实 Claude Agent SDK 接入(L1 退避) + 三个预置 PES(ExtractorPES/AuditorPES/GeneratorPES) + 真实 Library 接 qmd + IO 完整 + 通用 skill 完善 | I1:用真 SDK 跑通小 fixture 端到端,三个预置 PES 各跑一遍 |
| **M2** | Week 7-8.5 | FeedbackExample + EvolutionTrigger + SkillsRootResolver 两个内置实现 + run_evolution 接通 EvoSkill + 并发压测 + trajectory 查询优化 | I2:从积累的 feedback pairs 自动构建 eval_dataset,跑出至少一个候选分支,业务层无需建 symlink |
| **M3** | Week 9 | 清理 + README + PyPI 0.1.0 | I3:`git grep` 旧符号零结果,业务术语零泄漏 |

**M0 系列总估时**:~24.6d(含 0.5d legacy 清理 buffer;等价于原 v2 版本 M0 的 ~22d + 清理开销)。

---

## M0 系列:契约冻结 + 基础设施(Week 1-4)

分 4 个独立可验证的子里程碑,按依赖拓扑逐层构建。每个子里程碑有清晰的前置依赖、独立 DoD,可单独在 feature 分支迭代、review、合并到 main。

| 子里程碑 | 周期 | 包含任务 | 依赖 | 独立 DoD 摘要 |
|---|---|---|---|---|
| M0(地基层) | Week 1(~3.3d) | legacy 清理 + T0.2 + T0.3 + T0.18 | —— | 模型 / config / protocol / stubs 四类契约测试全绿 |
| M0.25(基础设施层) | Week 1.5-2(~6d) | T0.4 + T0.5 + T0.7 + T0.10 | M0 | workspace / hook / trajectory 三类契约测试全绿 + testing helpers 可用 |
| M0.5(PES 核心层) | Week 2-3(~6.3d) | T0.6 + T0.8 + T0.9 | M0, M0.25 | BasePES + MockPES + TrajectoryRecorderHook 三类契约测试全绿 |
| M0.75(外围 + API 冻结 + I0) | Week 3-4(~9d) | T0.1 + T0.11 + T0.12 + T0.13 + T0.14 + T0.15 + T0.16 + T0.17 | M0, M0.25, M0.5 | 全量 `tests/contract/` 绿 + I0 集成节点通过 + `from scrivai import *` 对齐 §4.1 |

**分支策略建议**(按团队 git 习惯可调):

- M0 → `feat/scrivai-m0-foundation`
- M0.25 → `feat/scrivai-m0.25-infra`
- M0.5 → `feat/scrivai-m0.5-pes-core`
- M0.75 → `feat/scrivai-m0.75-peripherals-and-i0`

四个子里程碑各自独立 PR、独立合并到 `main`;后一个从前一个合并后的 main 拉分支(避免 stack 管理成本)。

**读者导航**:T0.1 - T0.18 的**详细 DoD / 契约测试 / 估时**仍保留在下方各自原条目中(不重复),本节仅按"独立可验证"的目标,说明每个子里程碑包含哪些条目、前置依赖、聚合 DoD。

---

### 子里程碑 M0:地基层(Week 1)

**主题**:清空 legacy v2 代码 + 定义所有数据模型与 Protocol + Evolution 占位。`scrivai/__init__.py` 在本里程碑保持空白(完整冻结延迟到 M0.75 T0.1,此时所有后端实现都就绪)。

**前置动作(legacy 清理)** —— 独立 commit,message 模板 `refactor: clean legacy v2 code for v3 foundation`:

删除以下 legacy 路径:

- `scrivai/audit/`
- `scrivai/generation/`
- `scrivai/knowledge/store.py`
- `scrivai/llm.py`
- `scrivai/project.py`
- `scrivai/chunkers.py`
- `scrivai/utils/`(到 M0.75 T0.12 由 `scrivai/io/` 重写,此处先删)
- `tests/unit/test_audit.py` / `tests/unit/test_generation_real.py` / `tests/integration/test_*_flow.py` 等所有引用已删 API 的 legacy 测试

清空 `scrivai/__init__.py`(只保留 docstring,不 import 任何符号)。

**包含任务**:T0.2 · T0.3 · T0.18(详见下方原条目)

**独立 DoD**:

- ✅ legacy 清理干净:`git grep -E "LLMClient|AuditEngine|GenerationEngine|ProjectConfig|KnowledgeStore" -- scrivai/ tests/` 零结果
- ✅ `mypy --strict scrivai/models/` 通过
- ✅ `pytest tests/contract/test_models.py tests/contract/test_reexport.py tests/contract/test_pes_config.py tests/contract/test_evolution_stubs.py -v` 全绿
- ✅ `from scrivai.models.pes import PESRun, PESConfig, PhaseConfig, PhaseResult, PhaseTurn, ModelConfig` 及 9 个 HookContext 全部可导入
- ✅ `from scrivai.models.evolution import SkillsRootResolver, EvolutionConfig, EvolutionRun, FeedbackExample, Evaluator` 可导入
- ✅ `scrivai/evolution/__init__.py` 存在;`scrivai.EvolutionTrigger` / `run_evolution` 从顶层可 import,调用抛 `NotImplementedError("M2 实现")`
- ✅ `scrivai.ChunkRef is qmd.ChunkRef` 身份相等验证通过

**不在本里程碑**:不实现 WorkspaceManager / HookManager / TrajectoryStore / BasePES / CLI / IO / Library —— 这些都是后续子里程碑的内容。

---

### 子里程碑 M0.25:基础设施层(Week 1.5-2)

**主题**:三个**无 PES 依赖**的基础设施 —— 隔离沙箱、hook 分发、轨迹存储,外加配套的 testing helpers。本层实现后,即使不写 BasePES,业务层也能用这三个独立能力。

**包含任务**:T0.4 · T0.5 · T0.7 · T0.10(详见下方原条目)

**前置依赖**:M0 已合并到 main(models 可 import,PESConfig 可 YAML 加载)

**独立 DoD**:

- ✅ `pytest tests/contract/test_workspace.py -v` 全绿(目录树完整 / 内容快照 / fcntl 并发锁 / force 覆盖 / 归档可移植 / cleanup 按 mtime)
- ✅ `pytest tests/contract/test_hooks.py -v` 全绿(9 个 hook 名注册 / 同步分发异常透传 / 非阻塞分发异常吞噬 / 注册顺序保持)
- ✅ `pytest tests/contract/test_trajectory_store.py -v` 全绿(schema 新字段 / attempt_no 唯一约束 / WAL 双线程并发 / busy 重试)
- ✅ `TempWorkspaceManager` 和 `FakeTrajectoryStore` 可独立被下游单测 import(无需 BasePES)
- ✅ 本层新增符号(`WorkspaceManager / WorkspaceSpec / WorkspaceHandle / build_workspace_manager / HookManager / hookimpl / TrajectoryStore / TempWorkspaceManager / FakeTrajectoryStore`)加入 `scrivai/__init__.py` 增量清单(**不要求**完整对齐 §4.1,只加本层能真正支撑的符号)

**不在本里程碑**:不实现 BasePES / MockPES / TrajectoryRecorderHook —— 它们需要组合上述三层并引入策略方法 / 重试逻辑,放 M0.5。

---

### 子里程碑 M0.5:PES 核心层(Week 2-3)

**主题**:`BasePES` 抽象类 + 测试双(`MockPES`)+ 跨 hook 的 `TrajectoryRecorderHook`。这是整个 Scrivai 框架的核心机制,也是最需要 ultrathink 的一层 —— 所有"三阶段语义 / 9 hook 严格顺序 / 三层重试 / cancel 与 hook_error 映射"的契约都在本层落定。

**包含任务**:T0.6 · T0.8 · T0.9(详见下方原条目)

**前置依赖**:M0 + M0.25 都已合并到 main

**独立 DoD**:

- ✅ `pytest tests/contract/test_base_pes.py -v` 全绿(T0.6 列出的 15+ 测试,覆盖:三阶段顺序 / plan 失败跳过后续 / 9 hook 严格顺序含 `on_output_written` 位置 / 双层 context 合并 / required_outputs 结构化规则 / attempt_no 重试 / postprocess 不重试 / 重试前清场 / cancellation hook + `_persist_final_state` / `on_output_written` 仅 summarize 触发一次 / 扩展点选择性覆盖 / hook_error 映射 phase 失败 / before_run hook 异常使整 run 失败 / 非阻塞 hook 异常不改变 run 状态 / `_persist_final_state` 在 4 条路径都调一次 / summarize after_phase 异常使 run 失败)
- ✅ `pytest tests/contract/test_mock_pes.py -v` 全绿
- ✅ `pytest tests/contract/test_trajectory_hook.py -v` 全绿(MockPES 跑一次 → runs / phases / turns / tool_calls 表全部有对应记录;turns 里的 tool_use / tool_result 正确拆解到 tool_calls 表)
- ✅ 本层新增符号(`BasePES / MockPES / TrajectoryRecorderHook / PhaseLogHook`)加入 `scrivai/__init__.py` 增量清单

**不在本里程碑**:不实现三个预置 PES(ExtractorPES / AuditorPES / GeneratorPES)—— 它们属于 M1 的"业务模式层"。本里程碑只验证"机制层"正确,对"业务模式层"留接口(通过 4 个策略方法的默认实现)。

---

### 子里程碑 M0.75:外围 + API 冻结 + I0 集成(Week 3-4)

**主题**:补齐所有外围模块(Knowledge Libraries / IO 工具 / CLI / 通用 Skills 内容 / 通用 Agents YAML / Contract pytest plugin / qmd 双向契约),完成 `from scrivai import *` 的最终冻结,跑通 **I0 集成节点**。

**包含任务**:T0.1 · T0.11 · T0.12 · T0.13 · T0.14 · T0.15 · T0.16 · T0.17(详见下方原条目)

**前置依赖**:M0 + M0.25 + M0.5 都已合并到 main(至此所有后端类实现就绪,T0.1 才能真正冻结对外契约)

**独立 DoD**:

- ✅ 全量契约测试:`pytest tests/contract/ -v` 全绿(覆盖 T0.1 - T0.18 的所有 `tests/contract/test_*.py`)
- ✅ 跨项目契约:`pytest --pyargs scrivai.testing.contract --pyargs qmd.testing.contract` 全绿
- ✅ Public API:`from scrivai import *` 严格对齐 design.md §4.1 顶层 import 清单(`tests/contract/test_public_api.py::test_import_surface` 保证)
- ✅ CLI 可用:`scrivai-cli library|io|workspace|trajectory <子命令>` 四组命令全部可跑;冷启动 P50 < 300ms;每个子命令 JSON shape 与对应 Python API `.model_dump(mode="json")` 一致
- ✅ Skill 信息隔离:`grep -E "workspace|trajectory" skills/available-tools/SKILL.md` 零结果
- ✅ **I0 集成节点通过**:用 `MockPES` + `FakeQmdClient` 跑通:
  - PES 三阶段严格顺序(plan → execute → summarize)
  - 三种失败路径分别触发 `on_phase_failed`(sdk / postprocess / validate)
  - cancel 路径触发 `on_run_cancelled` + `_persist_final_state` 被调
  - Trajectory 全表落盘(含 `attempt_no` 在 `phases` 表的唯一约束 `UNIQUE(run_id, phase_name, attempt_no)`)

**M0 系列总 DoD**(等价于原 v2 版本的 "M0 DoD 汇总"):T0.1 - T0.18 全完成;`tests/contract/` 全绿;I0 集成节点通过。

---

### T0.1 `scrivai/__init__.py` Public API 冻结

- **DoD**:
  - 严格对齐 design.md §4.1 的顶层 import 清单
  - 包含:
    - pydantic:`PESRun, PESConfig, PhaseConfig, PhaseResult, PhaseTurn, ModelConfig, WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle, LibraryEntry, TrajectoryRecord, PhaseRecord, FeedbackRecord, EvolutionConfig, EvolutionRun, FeedbackExample`
    - Hook Contexts(9 个):`HookContext, RunHookContext, PhaseHookContext, PromptHookContext, PromptTurnHookContext, FailureHookContext, OutputHookContext, CancelHookContext`
    - Protocol:`Library, WorkspaceManager, Evaluator, SkillsRootResolver`
    - 抽象类:`BasePES, HookManager`
    - 预置 PES:`ExtractorPES, AuditorPES, GeneratorPES`
    - 工厂:`build_workspace_manager, build_qmd_client_from_config, build_libraries, load_pes_config`
    - 知识库:`RuleLibrary, CaseLibrary, TemplateLibrary`
    - 轨迹:`TrajectoryStore, TrajectoryRecorderHook, PhaseLogHook, EvolutionTrigger, run_evolution`
    - IO:`docx_to_markdown, doc_to_markdown, pdf_to_markdown, DocxRenderer`
    - qmd re-export:`ChunkRef, SearchResult, CollectionInfo`
    - Testing re-export:`MockPES, TempWorkspaceManager, FakeTrajectoryStore`(来自 `scrivai.testing`)
  - `from scrivai import *` 得到上述全部名字
- **优先级**:P0
- **依赖**:无
- **契约测试**:`tests/contract/test_public_api.py::test_import_surface`
- **估时**:0.5d

### T0.2 `scrivai/models/` pydantic + Protocol 集中定义

- **DoD**:
  - `scrivai/models/pes.py`:
    - `PESRun`(含 `status: Literal["running","completed","failed","cancelled"]` + `provider` / `sdk_version` / `skills_is_dirty` / `error_type` 字段)
    - `PESConfig / PhaseConfig / PhaseResult(含 attempt_no/error_type/is_retryable) / PhaseTurn / ModelConfig`
    - **9 个 HookContext**(含新增 `CancelHookContext`):所有 `PhaseHookContext / PromptHookContext / PromptTurnHookContext / FailureHookContext` 都含 `attempt_no` 字段;`FailureHookContext` 额外含 `will_retry` 和 `error_type`
  - `scrivai/models/workspace.py`:WorkspaceSpec / WorkspaceSnapshot / WorkspaceHandle + WorkspaceManager Protocol
  - `scrivai/models/knowledge.py`:LibraryEntry + Library Protocol
  - `scrivai/models/trajectory.py`:**`TrajectoryRecord / PhaseRecord / FeedbackRecord`**(对应 DB schema,字段与 design.md §4.1 / §4.5 完全匹配)
  - `scrivai/models/evolution.py`:
    - `EvolutionConfig / EvolutionRun / FeedbackExample` pydantic
    - `Evaluator` Protocol:`(question: str, predicted: str, ground_truth: str) -> float`
    - **`SkillsRootResolver`** Protocol(M0 只定义,M2 实现)
  - 所有字段有中文 docstring
  - `model_dump()` / `model_validate()` 往返稳定
  - `mypy --strict scrivai/models/` 通过
  - `scrivai.ChunkRef is qmd.ChunkRef` 验证通过(re-export 身份相等,非副本)
- **优先级**:P0
- **依赖**:T0.1
- **契约测试**:`tests/contract/test_models.py`、`tests/contract/test_reexport.py`
- **估时**:2d(原 1.5d + 0.5d 新增类型)

### T0.3 `scrivai/pes/config.py` YAML 加载

- **DoD**:
  - `load_pes_config(yaml_path: Path) -> PESConfig`
  - 支持 `${ENV_VAR}` 环境变量插值
  - schema 校验失败抛 `PESConfigError`
  - 覆盖规则:用户 YAML > 内置默认(每种预置 PES 有一份默认 YAML)
- **优先级**:P0
- **依赖**:T0.2
- **契约测试**:`tests/contract/test_pes_config.py`
- **估时**:0.5d

### T0.4 `WorkspaceManager` 实现

- **DoD**:按设计文档 §5.2 伪代码实现:
  - `shutil.copytree(symlinks=False)` 内容快照 skills / agents / data_inputs
  - `fcntl.flock` 文件锁防并发撞 run_id
  - `WorkspaceSpec.force` 字段:默认 reject,True 覆盖
  - `WorkspaceSnapshot` 含 `skills_git_hash / agents_git_hash / snapshot_at`
  - `meta.json` 完整写入
  - `archive(success=True)`:打包 `.claude/ + data/ + output/ + logs/ + meta.json` 到 `tar.gz`,删除原目录
  - `archive(success=False)`:写 `.failed` 标记,不动目录
  - `cleanup_old(days=30)`:同时清 archives 和 failed workspace
  - `build_workspace_manager(workspaces_root, archives_root)` 工厂
  - 契约测试:
    - `test_create_directory_structure`(目录树完整)
    - `test_snapshot_preserves_skills`(源修改后 workspace 不变)
    - `test_concurrent_create_rejected`(两进程同时 create 同 run_id)
    - `test_force_recreate`
    - `test_archive_portability`(归档拷到 `/tmp` 解压可读)
    - `test_cleanup_respects_mtime`
  - Linux + macOS 通过;Windows 标记 xfail
- **优先级**:P0
- **依赖**:T0.2
- **契约测试**:`tests/contract/test_workspace.py`
- **估时**:2.5d

### T0.5 `scrivai/pes/hooks.py` HookManager

- **DoD**:
  - `HookManager` 类,支持 `register(plugin) / dispatch(hook_name, context) / dispatch_non_blocking(hook_name, context)`
  - **9 个** hook 名字固定:`before_run / before_phase / before_prompt / after_prompt_turn / after_phase / on_phase_failed / on_output_written / on_run_cancelled / after_run`
  - 调用模式分类:
    - **同步 dispatch**(异常透传):`before_run / before_phase / before_prompt / after_prompt_turn / after_phase / on_output_written`
    - **非阻塞 dispatch**(异常仅 loguru):`on_phase_failed / on_run_cancelled / after_run`
  - `@hookimpl` 装饰器(基于 pluggy 或轻量自实现;MVP 选轻量即可)
  - 契约测试:
    - `test_hook_registration_and_dispatch`
    - `test_sync_dispatch_propagates_exception`
    - `test_nonblocking_dispatch_catches_exception`
    - `test_hook_ordering`(多 plugin 按注册顺序调用)
    - `test_nine_hook_names_registered`(保证 9 个 hook 全部可注册和 dispatch)
- **优先级**:P0
- **依赖**:T0.2
- **契约测试**:`tests/contract/test_hooks.py`
- **估时**:1d

### T0.6 `scrivai/pes/base.py` BasePES 抽象类

- **DoD**:按设计文档 §5.1 伪代码实现:
  - `BasePES.__init__(config, model, workspace, hooks, trajectory_store, runtime_context)`
  - `BasePES.run(task_prompt) -> PESRun`:含 `cancelled` 状态处理(捕获 `KeyboardInterrupt / asyncio.CancelledError` → dispatch `on_run_cancelled` → 重新抛出)
  - `BasePES._run_phase_with_retry(phase, run, task_prompt)`:实现 L2 phase 级重试(按 `max_retries` + `is_retryable`)
  - `BasePES._run_phase(phase, run, task_prompt, attempt_no)`:完整流程(before_phase → build_phase_context → merge → build_phase_prompt → before_prompt → call SDK → parse turns → postprocess_phase_result → validate_phase_outputs → [summarize 阶段 on_output_written] → after_phase)
  - **4 个子类扩展点**(均有默认实现,都是普通 async 方法,子类可选择性覆盖):
    - `build_execution_context(phase, run) -> dict` 默认返回 `{}`(命名强调"执行态局部字段",区别于框架自动字段)
    - `build_phase_prompt(phase, phase_cfg, context, task_prompt) -> str` 默认简单拼接
    - `postprocess_phase_result(phase, result, run)` 默认 no-op
    - `validate_phase_outputs(phase, phase_cfg, result, run)` 默认按 `required_outputs` 校验
  - `BasePES._call_sdk_query(...)`:封装 **L1 传输级重试**(RateLimitError 指数退避 3 次:1s/4s/16s);超限抛 `RateLimitError` 让上层处理
  - `BasePES._list_produced_files(phase)`:按相对路径列出该阶段 `working/` 新增文件
  - 三种失败出口(SDK / postprocess / validate)统一通过 `PhaseError(phase, msg, result=PhaseResult)` 冒泡,带 `error_type / is_retryable`
  - `on_phase_failed` 由 `_run_phase_with_retry` 统一 dispatch,带 `attempt_no / will_retry`
  - `_run_phase_with_retry` 对 `is_retryable=True` 的失败按 `max_retries` 重跑;每次尝试的 `PhaseResult` 都落 TrajectoryStore 新行
  - **本任务用 MockPES(T0.9) 跑测试,真实 SDK 接入在 M1**
  - 契约测试(用 MockPES):
    - `test_three_phase_order`
    - `test_plan_failure_skips_execute_and_summarize`
    - `test_hooks_called_in_correct_order_nine_hooks`(严格顺序 phase 级展开 + `on_output_written` 在 `after_phase` **之前** + `on_run_cancelled` + `after_run` finally 触发)
    - `test_context_layering`(runtime / execution / framework 三层正确合并)
    - `test_required_outputs_enforced`(含结构化规则 `{"path":"findings/","min_files":1,"pattern":"*.json"}`)
    - `test_phase_retry_on_validation_failure`(attempt_no=0 失败 validate,attempt_no=1 成功)
    - `test_phase_no_retry_on_parse_error`(postprocess 失败 → is_retryable=False → 不重试)
    - **`test_cleanup_before_retry`**(attempt_no=0 创建 findings/a.json;attempt_no=1 开始前框架清空 findings/;若 attempt_no=1 不生成任何文件 → required_outputs 校验失败而非"假成功")
    - `test_cancellation_dispatches_on_run_cancelled`(KeyboardInterrupt → status="cancelled" + hook 触发 + `_persist_final_state` 被调一次)
    - `test_on_output_written_only_on_summarize`(只 summarize 且 validate 通过后、after_phase 前触发)
    - `test_extension_points_selective_override`(子类只覆盖 `build_execution_context`,其他沿用默认)
    - **`test_hook_error_maps_to_phase_failure`**(before_phase 同步 hook 抛异常 → PhaseResult.error_type="hook_error", is_retryable=False → 不重试 → run.status="failed")
    - **`test_before_run_hook_error_fails_run`**(before_run hook 抛异常 → run.status="failed", error_type="hook_error";phase 循环不启动;after_run 仍触发)
    - **`test_nonblocking_hook_error_not_propagated`**(after_run / on_phase_failed / on_run_cancelled 抛异常 → 仅 loguru 记录,run.status 不变)
    - **`test_finalize_run_called_on_all_paths`**(success / failed / cancelled / before_run_failed 四条路径都调 `_persist_final_state` 一次)
    - **`test_after_phase_hook_error_on_summarize_marks_run_failed`**(summarize after_phase 异常 → 虽然 output.json 已写,run.status 仍 failed;数据完整性 warning 记 loguru)
- **优先级**:P0
- **依赖**:T0.2, T0.4, T0.5
- **契约测试**:`tests/contract/test_base_pes.py`
- **估时**:4.5d(原 3d + 1.5d:4 扩展点 / L1+L2 重试 / cancel 路径 / 重试前清场 / hook_error 传播 / finalize_run 持久化责任)

### T0.7 `scrivai/trajectory/store.py` TrajectoryStore

- **DoD**:
  - SQLite schema(设计文档 §4.5 完整五表,含新字段):
    - `runs`:含 `provider / sdk_version / skills_is_dirty / error_type`;`status` 含 `cancelled`
    - `phases`:**含 `attempt_no / phase_order / error_type / is_retryable`**;`UNIQUE(run_id, phase_name, attempt_no)`
    - `turns`:不变
    - `tool_calls`:加 `status` 字段
    - `feedback`:**含 `input_summary(NOT NULL) / review_policy_version / source / confidence`**;加 `idx_feedback_source` 索引
  - 建库时执行 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=10000;`
  - 方法:
    - `start_run(run_id, pes_name, model_name, provider, sdk_version, skills_git_hash, agents_git_hash, skills_is_dirty, task_prompt, runtime_context)`
    - `record_phase_start(run_id, phase_name, phase_order, attempt_no) -> phase_id`
    - `record_turn(phase_id, turn_index, role, content_type, data) -> turn_id`
    - `record_tool_call(turn_id, tool_name, tool_input, tool_output, status, duration_ms)`
    - `record_phase_end(phase_id, prompt, response_text, produced_files, usage, error, error_type, is_retryable)`
    - `finalize_run(run_id, status, final_output, workspace_archive_path, error, error_type)`
    - `record_feedback(run_id, input_summary, draft_output, final_output, corrections, review_policy_version, source, confidence, submitted_by)`
    - `get_run(run_id) -> TrajectoryRecord | None`(联查 phases)
    - `list_runs(pes_name=None, status=None, limit=50) -> list[TrajectoryRecord]`
    - `get_feedback_pairs(pes_name=None, min_confidence=None, limit=None) -> list[FeedbackRecord]`
  - **并发模型**:
    - 每线程一连接(`threading.local`);不跨线程共享
    - 事务边界:每个 record_* 独立事务;`record_turn`/`record_tool_call` 允许 batched flush
    - busy 退避:SQLite busy 时框架重试 1 次;仍失败抛 `TrajectoryWriteError`
    - async 场景:`record_*` 内部用 `asyncio.to_thread` 或接 `aiosqlite`
  - 首次打开自动建 schema
  - 默认路径:`~/.scrivai/trajectories.sqlite`;env 回退 `SCRIVAI_TRAJECTORY_DB`
  - 契约测试:
    - `test_schema_init_with_new_fields`
    - `test_full_run_lifecycle_with_attempt_no`(同 phase_name 多次 attempt 都能写)
    - `test_phases_unique_constraint`(同 run_id+phase_name+attempt_no 重复 → IntegrityError)
    - `test_feedback_pair_query_filters_confidence`
    - `test_concurrent_write_safety_two_threads`
    - `test_busy_retry_on_lock`
- **优先级**:P0
- **依赖**:T0.2
- **契约测试**:`tests/contract/test_trajectory_store.py`
- **估时**:2d(原 1.5d + 0.5d 扩 schema 与并发模型)

### T0.8 `scrivai/trajectory/hooks.py` TrajectoryRecorderHook

- **DoD**:
  - `TrajectoryRecorderHook(store)` 插件类
  - 订阅 `before_run / before_phase / before_prompt / after_prompt_turn / after_phase / on_phase_failed / on_output_written / after_run` 全部触点
  - 每个 hook 对应 `TrajectoryStore` 的一个 record 方法
  - `after_prompt_turn` 时解析 turn 里的 tool_use / tool_result → 写 tool_calls 表
  - 额外:`PhaseLogHook`(可选组合 hook),把 prompt / response / turns dump 到 `workspace.logs_dir/<phase>.json`
  - 契约测试:
    - `test_full_run_recorded`(跑一次 MockPES,验证 DB 全表有对应记录)
    - `test_tool_calls_extracted_from_turns`
- **优先级**:P0
- **依赖**:T0.6, T0.7
- **契约测试**:`tests/contract/test_trajectory_hook.py`
- **估时**:1d

### T0.9 `scrivai.testing.mock_pes` MockPES

- **DoD**:
  - `MockPES(BasePES)`:按预录的 trajectory(list of PhaseResult)回放
  - 不依赖 `claude-agent-sdk` 包
  - 支持按 `task_prompt` 关键词选择不同 trajectory
  - 支持人为注入 phase 失败用于测试错误路径
  - 还原完整 turns(供 TrajectoryRecorderHook 测试)
- **优先级**:P0
- **依赖**:T0.6
- **契约测试**:`tests/contract/test_mock_pes.py`
- **估时**:0.8d

### T0.10 `scrivai.testing.tmp_workspace` + `fake_trajectory`

- **DoD**:
  - `TempWorkspaceManager`:用 `tmp_path` 的 WorkspaceManager 变体,测试后自动清理
  - `FakeTrajectoryStore`:内存字典版,满足 TrajectoryStore 公共接口;测试加速用
- **优先级**:P0
- **依赖**:T0.4, T0.7
- **估时**:0.5d

### T0.11 `scrivai/knowledge/` Library 三兄弟

- **DoD**:
  - `base.py`:共通的 `_BaseLibrary` 实现(add/get/list/delete/search 走 qmd)
  - `rules.py`:`RuleLibrary(_BaseLibrary)`,collection 名固定 `"rules"`
  - `cases.py`:同上,collection 名 `"cases"`
  - `templates.py`:同上,collection 名 `"templates"`
  - `factory.py`:
    - `build_qmd_client_from_config(db_path) -> QmdClient`(封装 `qmd.connect`)
    - `build_libraries(qmd_client) -> tuple[RuleLibrary, CaseLibrary, TemplateLibrary]`
  - 元数据完全持久化在 qmd chunk metadata;无内存状态
  - 契约测试:
    - `test_library_crud`(用 FakeQmdClient)
    - `test_entry_id_uniqueness_in_collection`
    - `test_cross_collection_isolation`
- **优先级**:P0
- **依赖**:T0.2,qmd 的 `FakeQmdClient`
- **契约测试**:`tests/contract/test_libraries.py`
- **估时**:1.5d

### T0.12 `scrivai/io/` 工具骨架

- **DoD**:
  - `convert.py`:
    - `docx_to_markdown(path)`:pandoc 子进程
    - `doc_to_markdown(path)`:LibreOffice headless → docx → pandoc
    - `pdf_to_markdown(path, ocr=True)`:docling;不可用抛 NotImplementedError
  - `render.py`:
    - `DocxRenderer(template_path)`:基于 docxtpl
    - `.list_placeholders()`:正则提取 `{{ xxx }}` 占位符
    - `.render(context, output_path)`
  - 所有函数有中文 docstring 说明依赖的外部二进制(pandoc / libreoffice / docling)
- **优先级**:P0
- **依赖**:T0.1
- **契约测试**:`tests/contract/test_io_smoke.py`(smoke 级别,真实内容验证留 M1 T1.5)
- **估时**:1.5d

### T0.13 `scrivai/cli/__main__.py` scrivai-cli

- **DoD**:
  - argparse 路由 `library / io / workspace / trajectory` 四个 group
  - 所有子命令:
    - JSON stdout(`ensure_ascii=False`)
    - error JSON stderr,exit 1
    - env 回退:`SCRIVAI_PROJECT_ROOT, QMD_DB_PATH, SCRIVAI_WORKSPACE_ROOT, SCRIVAI_ARCHIVES_ROOT, SCRIVAI_TRAJECTORY_DB`
  - `pyproject.toml` 注册 `scrivai-cli` entry point
  - **CLI 输出 JSON shape 与对应 Python API `.model_dump(mode="json")` 严格一致**
  - 命令冷启动 P50 < 300ms
  - 契约测试:
    - 每个 group 每个子命令一个 shape 测试
    - env 缺失测试
    - 退出码测试
- **优先级**:P0
- **依赖**:T0.4, T0.7, T0.11, T0.12
- **契约测试**:`tests/contract/test_cli.py`
- **估时**:2d

### T0.14 通用 Skill 草稿(`Scrivai/skills/`)

- **DoD**:
  - `skills/available-tools/SKILL.md`:**只列 Agent 可见的子命令**(设计文档 §4.10.3):
    - `scrivai-cli library {search, get, list}`
    - `scrivai-cli io {docx2md, doc2md, pdf2md, render}`
    - `qmd {search, collection, document}`
    - 每命令含参数、输出 JSON shape、典型错误
    - **严禁**列入 `workspace` / `trajectory` 子命令(信息隔离边界)
  - `skills/search-knowledge/SKILL.md`:讲 library search 的使用时机和调用方式
  - `skills/inspect-document/SKILL.md`:讲如何从 chunk_id 反查原文段落
  - `skills/render-output/SKILL.md`:讲 docxtpl 上下文 schema 约定
  - 每份严格按 Anthropic SKILL.md 格式(YAML frontmatter `name` + `description` + Markdown body)
  - 验证:
    - MockWorkspace 快照复制后,`working/.claude/skills/` 下四个 skill 完整
    - **契约测试**:`grep -E "workspace|trajectory" skills/available-tools/SKILL.md` 零结果(挂在 `tests/contract/test_skill_isolation.py`)
- **优先级**:P0
- **依赖**:T0.4, T0.13
- **估时**:1.2d

### T0.15 通用 Agent Profile YAML(`Scrivai/agents/`)

- **DoD**:
  - `agents/extractor.yaml`:ExtractorPES 默认 PESConfig
  - `agents/auditor.yaml`:AuditorPES 默认 PESConfig
  - `agents/generator.yaml`:GeneratorPES 默认 PESConfig
  - 每份含完整的 plan / execute / summarize 三阶段配置(additional_system_prompt, allowed_tools, max_turns, required_outputs)
  - `default_skills` 默认含 `available-tools`
  - `load_pes_config(yaml_path)` 能加载通过
- **优先级**:P0
- **依赖**:T0.3, T0.14
- **估时**:1d

### T0.16 `scrivai.testing.contract` pytest plugin

- **DoD**:
  - 提供 fixtures:`scrivai_workspace_manager / scrivai_qmd_client / scrivai_libraries / scrivai_trajectory_store`
  - 把 T0.1-T0.15 的契约测试打包成可供下游复用的套件
  - 下游通过 `pytest --pyargs scrivai.testing.contract` 即可跑全套
- **优先级**:P0
- **依赖**:T0.4-T0.15
- **估时**:1d

### T0.17 跑通 qmd 的契约测试(双向验证)

- **DoD**:Scrivai venv 内 `pytest --pyargs qmd.testing.contract` 全绿(用 FakeQmdClient 和真实 SqliteQmdClient 两种)
- **优先级**:P0
- **依赖**:qmd 已完成
- **估时**:0.3d

### T0.18 `SkillsRootResolver` Protocol 预留(M0 只定义,M2 实现)

- **DoD**:
  - `scrivai/models/evolution.py` 定义 `SkillsRootResolver` Protocol:
    - `__enter__() -> Path` 返回 P,保证 `P/.claude/skills/` 可被 EvoSkill 读到
    - `__exit__(*exc)` 清理 `__enter__` 创建的临时资源
    - **职责边界**:Protocol 只负责"准备 skills 根",**不**负责 `os.chdir`(chdir 由 `run_evolution` 在 M2 自己做)
  - `scrivai/evolution/` 目录和 `__init__.py` 存在,但 `trigger.py / runner.py / evaluator.py` 只写"M2 待实现"占位
  - `scrivai.EvolutionTrigger / run_evolution` 可从 `scrivai` 顶层 import(调用会抛 `NotImplementedError("M2 实现")`)
  - 契约测试只验证:
    - `SkillsRootResolver` Protocol 导入并 runtime_checkable
    - import `EvolutionTrigger / run_evolution` 不抛错
    - **Protocol 定义里不涉及 os.chdir 的语义**(docstring grep `chdir` 零结果)
- **优先级**:P0
- **依赖**:T0.2
- **契约测试**:`tests/contract/test_evolution_stubs.py`
- **估时**:0.3d

**M0 系列 DoD 汇总**(拆分为 M0 / M0.25 / M0.5 / M0.75 四个独立可验证子里程碑,详见本章节开头的"里程碑总览"与子里程碑说明):T0.1 - T0.18 全完成;`tests/contract/` 全绿(用 MockPES + FakeQmd);I0 集成节点通过。

---

## M1:真实 Claude SDK + 三个预置 PES(Week 4-6)

### T1.1 真实 Claude Agent SDK 接入

- **DoD**:
  - `BasePES._run_phase` 的 `call SDK` 步骤真实实现,调 `claude_agent_sdk.query()`
  - 构造 `ClaudeAgentOptions`:model / base_url / api_key / fallback_model / cwd / system_prompt / allowed_tools / permission_mode / max_turns / env / setting_sources=["project"] / mcp_servers={}
  - 解析 `AssistantMessage / UserMessage / ResultMessage` 为 `PhaseTurn`
  - 异常捕获 → `PhaseResult.error` → 触发 `on_phase_failed`
  - 每 turn 触发 `after_prompt_turn` hook
  - 契约测试:真 SDK smoke test(需 `ANTHROPIC_API_KEY` env,CI 可 skip)
- **优先级**:P0
- **依赖**:M0
- **估时**:2d

### T1.2 多供应商适配(Claude / GLM / MiniMax)

- **DoD**:
  - `ModelConfig.model + base_url + api_key` 正确传给 SDK
  - 至少跑通 `claude-sonnet-4-6` + `glm-5.1` 各一次 smoke query
  - 输出格式差异记入契约测试备注(不阻断)
- **优先级**:P0
- **依赖**:T1.1
- **估时**:1d

### T1.3 Phase 间文件化契约真实验证

- **DoD**:
  - plan phase 结束后验证 `working/plan.md + plan.json` 存在且 plan.json 可 JSON 解析
  - execute phase 结束后验证 `working/findings/` 下至少一个 `*.json`(具体文件由子类的 handle_phase_response 校验)
  - summarize phase 结束后验证 `working/output.json` 存在且可 JSON 解析
  - 缺失 → 触发 PhaseError
  - 契约测试:刻意写会"忘记创建文件"的 MockPES → 验证 phase 失败
- **优先级**:P0
- **依赖**:T1.1
- **估时**:0.5d

### T1.4 `ExtractorPES` 实现

- **DoD**:
  - `scrivai/agents/extractor.py`
  - 构造参数:`output_schema / extra_skills / skills_override / config_override / plan_prompt_override / execute_prompt_override / summarize_prompt_override / model / workspace / hooks / trajectory_store / runtime_context`
  - 默认 PESConfig 从 `Scrivai/agents/extractor.yaml` 加载
  - `handle_phase_response` 按设计文档 §4.4.1 表格实现:
    - plan:校验 plan.json 含 items_to_extract 列表
    - execute:校验每个 plan item 有对应 findings/<id>.json
    - summarize:读 output.json → `output_schema.model_validate`(失败抛 PhaseError)
  - 契约测试:用 MockPES 回放三阶段 + 真 ExtractorPES 校验逻辑
- **优先级**:P0
- **依赖**:T1.1, T0.15
- **契约测试**:`tests/contract/test_extractor_pes.py`
- **估时**:1.5d

### T1.5 `AuditorPES` 实现

- **DoD**:同 T1.4,但针对 Auditor:
  - 默认 verdict_levels = `["合格","不合格","不适用","需要澄清"]`
  - 构造参数额外:`verdict_levels / evidence_required`
  - `handle_phase_response`:
    - execute:校验 checkpoints 覆盖率(每个 cp_id 至少一个 finding 文件)
    - summarize:校验所有 verdict 在 verdict_levels 内 + evidence 必需性
  - 契约测试同 T1.4 风格
- **优先级**:P0
- **依赖**:T1.4
- **契约测试**:`tests/contract/test_auditor_pes.py`
- **估时**:1.5d

### T1.6 `GeneratorPES` 实现

- **DoD**:同 T1.4,但针对 Generator:
  - 构造参数额外:`template_path`(必传)、`context_schema`、`auto_render`(**默认 `False`**)
  - 4 个策略方法覆盖:
    - `build_execution_context(phase="plan", run)`:解析模板占位符 → 注入 `{"placeholders": [...]}`
    - `postprocess_phase_result(phase="summarize", ...)`:若 `auto_render=True`,读 output.json 作 context → `DocxRenderer.render` → 产 `output/final.docx`
    - `validate_phase_outputs(phase="plan", ...)`:校验 plan.json 覆盖所有占位符
    - `validate_phase_outputs(phase="execute", ...)`:每占位符有 findings/<placeholder>.json
  - 契约测试同 T1.4 风格:
    - `test_auto_render_default_false`(默认不渲染,业务层需显式开启)
    - `test_auto_render_true_produces_docx`(显式 True 时产出 docx)
    - `test_placeholder_coverage_enforced_in_plan`
    - DocxRenderer smoke(真模板 + 真渲染)
- **优先级**:P0
- **依赖**:T1.4, T0.12
- **契约测试**:`tests/contract/test_generator_pes.py`
- **估时**:1.8d

### T1.7 Library 真实接 qmd

- **DoD**:
  - `build_libraries(qmd_client)` 接受真实 `SqliteQmdClient`(from `qmd.connect`)
  - `add` 触发真实分块 + embedding(透传到 qmd)
  - `search` 通过 `qmd.hybrid_search`
  - `get / list / delete` 通过 metadata filters
  - 契约测试:真实 qmd SQLite DB(fixture 级别,<100 chunk)
- **优先级**:P0
- **依赖**:T0.11
- **估时**:1d

### T1.8 IO 工具完善

- **DoD**:
  - `docx_to_markdown` 处理表格 / 公式 / 图片替代文本等边缘情况
  - `pdf_to_markdown` 含表格的扫描件走 OCR
  - `DocxRenderer` 支持循环 / 嵌套(docxtpl 限制内)
  - 契约测试:用 fixture 级 docx / pdf / 模板验证
- **优先级**:P0
- **依赖**:T0.12
- **估时**:2d

### T1.9 通用 Skill 内容打磨

- **DoD**:
  - 每份 SKILL.md 含至少 3 个真实调用示例 + 错误处理提示
  - `available-tools/SKILL.md` 反映 T1.1 后的完整 CLI
- **优先级**:P0
- **依赖**:T1.1
- **估时**:1d

### T1.10 真实 fixture 端到端

- **DoD**:
  - 准备 fixture:`guide_excerpt.md`(10 页)+ `checkpoints_golden.json`(10 条)
  - 用 `ExtractorPES` + 真实 SDK + fixture → 产 output.json(含 10 条 items)
  - 用 `AuditorPES` + 同 fixture → 产 output.json(含 10 条 findings)
  - 用 `GeneratorPES` + `workpaper_template.docx` → 产 `output/final.docx`
  - 归档 tar.gz + TrajectoryStore 完整记录
  - **此测试需 API key,CI skip,本地必须能跑**
  - 输出 Markdown 报告到 `tests/outputs/integration/m1_e2e_<timestamp>.md`(含每个 PES 的 trajectory 摘要)
- **优先级**:P0
- **依赖**:T1.1 - T1.9
- **契约测试**:`tests/integration/test_m1_end_to_end.py`
- **估时**:2d

**M1 DoD 汇总**:I1 通过;契约测试在真 SDK + 真 qmd 下全绿;三个预置 PES 各跑一遍 fixture。

---

## M2:EvoSkill + 并发 + 稳定性(Week 7-8)

### T2.1 `scrivai/evolution/` 数据模型与 Protocol 完善

- **DoD**(M0 T0.18 已预留类型,M2 此处完善和实现):
  - `EvolutionConfig`:`task_name / model / mode / eval_dataset_csv / max_iterations / no_improvement_limit / concurrency / train_ratio / val_ratio / tolerance / selection_strategy / cache_enabled / cache_dir / project_root`(最后一项给 SkillsRootResolver 用)
  - `EvolutionRun`:`best_score_base / best_score_evolved / promoted_branch / candidate_branches / iterations_history`
  - `FeedbackExample`:`question / ground_truth / category / metadata`
  - `Evaluator` Protocol:`(question: str, predicted: str, ground_truth: str) -> float`
  - 字节级匹配设计文档 §4.6
- **优先级**:P0
- **依赖**:M1, T0.18
- **估时**:0.5d

### T2.2 `EvolutionTrigger` 从 trajectory 构建 eval_dataset

- **DoD**:
  - `EvolutionTrigger(store, pes_name, min_feedback_pairs, min_confidence=0.7)`
  - `.has_enough_data() -> bool`(按 `min_feedback_pairs` 和 `min_confidence` 筛后计数)
  - `.build_eval_dataset(output_path, category_fn=None) -> Path`
    - 从 `store.get_feedback_pairs(pes_name, min_confidence)` 拉所有 pairs
    - 对每条 pair 构建 `FeedbackExample`:
      - `question = json.dumps({"task_prompt": rec.run.task_prompt, "input_summary": rec.input_summary}, ensure_ascii=False, sort_keys=True, separators=(",",":"))` (**结构化 JSON,不用魔法分隔符**)
      - `ground_truth = json.dumps(rec.final_output, ensure_ascii=False, sort_keys=True, separators=(",",":"))`
      - `category = category_fn(rec) if category_fn else rec.run.pes_name`
      - `metadata = {"run_id": rec.run_id, "review_policy_version": ..., "source": ..., "confidence": ...}`
    - 去重(同 question+ground_truth 保留最新)
    - 写 CSV(列顺序固定:`question / ground_truth / category`)
  - 契约测试:
    - `test_question_is_valid_json`:`json.loads(row["question"])` 得 `{"task_prompt":..., "input_summary":...}`
    - 模拟 15 条 feedback → build CSV → 验证列 + 行数 + 去重
    - feedback 不足 → `has_enough_data() == False`
    - `min_confidence=0.9` 筛掉 confidence=0.5 的条目
    - **字节级可重复性**:相同输入产出相同 CSV(hash 比对)
    - `test_roundtrip_question`:`task_prompt` 含 `---INPUT---` 等特殊字符也能正确解析
- **优先级**:P0
- **依赖**:T2.1, T0.7
- **契约测试**:`tests/contract/test_evolution_trigger.py`
- **估时**:1d

### T2.2b `SkillsRootResolver` 内置实现(M0 预留的 Protocol 在此落地)

- **DoD**:
  - **Resolver 只管路径,不管 cwd**(与 design §4.6.4 职责边界一致):
    - `DefaultSkillsRootResolver(project_root, skills_subdir="skills")`:建临时目录 `$TMPDIR/scrivai-evo-<ts>/`,在其中建 `.claude/skills → project_root/skills/` symlink;退出时 rmtree 临时目录
    - `CopySkillsRootResolver(project_root, skills_subdir="skills")`:同样建临时目录,但用 `shutil.copytree` 而非 symlink(NFS / Windows 场景)
    - **两个实现都不 `os.chdir`**
  - `run_evolution(config, evaluator, resolver=None)` 流程:
    - 默认 `resolver = DefaultSkillsRootResolver(config.project_root)`
    - `with resolver as skills_root:` 进入上下文拿路径 P
    - `original_cwd = os.getcwd(); os.chdir(P)` ← **chdir 由 run_evolution 做**
    - `try: await _invoke_evoskill_loop(...) finally: os.chdir(original_cwd)`
  - 契约测试:
    - `test_default_resolver_symlink_exists_in_context`
    - `test_default_resolver_cleanup_on_exit`
    - `test_copy_resolver_no_symlinks`(验证临时目录产物不含 symlink)
    - `test_resolver_does_not_chdir`(进入 `__enter__` 前后 os.getcwd() 不变)
    - `test_run_evolution_restores_cwd`(run_evolution 调用前后 cwd 不变)
    - `test_run_evolution_cwd_during_loop`(loop 期间 cwd == resolver 返回的 P)
- **优先级**:P0
- **依赖**:T2.1
- **契约测试**:`tests/contract/test_skills_resolver.py`
- **估时**:1d

### T2.3 `run_evolution` 接通 EvoSkill

- **DoD**:
  - `async def run_evolution(config: EvolutionConfig, evaluator: Evaluator, resolver: SkillsRootResolver | None = None) -> EvolutionRun`
  - 内部:`with resolver or DefaultSkillsRootResolver(config.project_root) as skills_path` → `os.chdir(skills_path.parent.parent)` → 调 EvoSkill 的 `LoopAgents`(参数对齐 T2.1) → finally 恢复 cwd
  - 返回 EvolutionRun 含 `promoted_branch / candidate_branches / iterations_history`
  - 五阶段全部走完(Base / Proposer / Generator / Evaluator / Frontier)
  - 产物只到 git 分支 `evo/<timestamp>-<idx>`,**永不自动写 main**
  - 业务层**不再需要**在项目根建 `.claude/skills → ../skills` 的 git symlink(由 resolver 内部处理)
  - 契约测试:用 mini 评测集(3 条)验证流程能跑出至少 1 个候选分支
- **优先级**:P0
- **依赖**:T2.1, T2.2b
- **契约测试**:`tests/integration/test_run_evolution.py`
- **估时**:2.5d

### T2.4 EvoSkill 在 fixture 上跑通

- **DoD**:
  - 用 M1 积累的 trajectory + 手动编造 10 条 feedback pairs
  - 业务侧提供 IoU `Evaluator`
  - `EvolutionTrigger` → `build_eval_dataset` → `run_evolution`
  - 至少 1 个候选分支;若分数高于 base 给出 `promoted_branch`
  - 输出报告到 `tests/outputs/integration/m2_evolution_<timestamp>.md`
- **优先级**:P0
- **依赖**:T2.3
- **估时**:1.5d

### T2.5 并发压测

- **DoD**:
  - PES execute 阶段允许 Agent 并发跑 tool(SDK 默认)
  - 100 页文书 + 30 checkpoint 端到端 ≤ 10 分钟
  - 失败率 ≤ 5%
  - 归档 + trajectory 全部落盘正确
- **优先级**:P0
- **依赖**:M1
- **估时**:1.5d

### T2.6 TrajectoryStore 查询优化

- **DoD**:
  - 加索引:`runs(pes_name, status)`、`turns(phase_id)`、`tool_calls(tool_name)`、`feedback(run_id)`
  - `list_runs(pes_name=..., limit=50)` P95 < 50ms(10k 条)
  - `get_feedback_pairs(pes_name)` P95 < 200ms(1k 条)
  - 压测脚本放 `tests/perf/`
- **优先级**:P1
- **依赖**:T0.7
- **估时**:0.8d

### T2.7 日志与可观察性

- **DoD**:
  - phase 启动 / 结束打 usage(tokens、duration)
  - 失败时记录原 prompt 前 200 字 + 错误堆栈
  - `workspace/meta.json` 累积 phase 进度
  - 统一走 loguru
- **优先级**:P1
- **依赖**:M1
- **估时**:0.5d

**M2 DoD 汇总**:I2 通过;EvoSkill 跑出候选分支;100 页压测达标。

---

## M3:清理 + 发布(Week 9)

### T3.1 旧目录清理

- **DoD**:
  - 删除所有非新架构的残留目录 / 文件
  - `git grep` 以下符号零结果:
    ```
    LLMClient LLMConfig LLMMessage LLMResponse LLMUsage
    PromptTemplate FewShotTemplate OutputParser PydanticOutputParser
    JsonOutputParser RetryingParser ExtractChain AuditChain GenerateChain
    Project ProjectConfig KnowledgeStore AuditEngine AuditResult
    GenerationEngine GenerationContext MockLLMClient AgentSession
    ```
  - `grep -rE "招标|政府采购|审核点|底稿|投标人" scrivai/` 零结果
  - `grep -rE "from scrivai\.agent\b" scrivai/` 零结果(因为现在是 `scrivai.pes` + `scrivai.agents`)
- **优先级**:P0
- **依赖**:M2
- **估时**:1d

### T3.2 pyproject.toml 0.1.0

- **DoD**:
  - 版本 0.1.0
  - 依赖:`claude-agent-sdk>=X`、`qmd>=0.1.0`、`pydantic>=2`、`pyyaml`、`docxtpl`、`loguru`
  - 系统依赖说明:pandoc、libreoffice(doc→docx)、docling(pdf ocr)
  - CHANGELOG 记录初始版本
- **优先级**:P0
- **依赖**:T3.1
- **估时**:0.3d

### T3.3 README + 示例

- **DoD**:
  - README 反映"Claude Agent 编排框架"定位
  - `examples/` 提供独立 demo:
    - `examples/01_extractor_quickstart.py`:5 分钟上手 ExtractorPES
    - `examples/02_custom_pes.py`:继承 BasePES 自定义
    - `examples/03_evolution_demo.py`:从 trajectory 触发进化
  - 每个 demo 自包含,不依赖 GovDoc
- **优先级**:P1
- **依赖**:T3.1
- **估时**:1.5d

### T3.4 发布到私有 PyPI(可选)

- **DoD**:`pip install scrivai==0.1.0 --index-url <私有源>` 在干净环境安装通过
- **优先级**:P1
- **依赖**:T3.2
- **估时**:0.3d

---

## Deprecation 验收清单(M3 最终)

```bash
cd /home/iomgaa/Projects/Scrivai
bad=""

# 旧架构符号清洁
for sym in LLMClient LLMConfig LLMMessage LLMResponse LLMUsage \
           PromptTemplate FewShotTemplate OutputParser PydanticOutputParser \
           JsonOutputParser RetryingParser ExtractChain AuditChain GenerateChain \
           Project ProjectConfig KnowledgeStore AuditEngine AuditResult \
           GenerationEngine GenerationContext MockLLMClient AgentSession; do
  if git grep -q "\\b$sym\\b" -- 'scrivai/**/*.py'; then
    bad="$bad $sym"
  fi
done
[ -z "$bad" ] && echo "OK: deprecated symbols clean" || { echo "FAIL:$bad"; exit 1; }

# 业务术语泄漏检查
leak=$(grep -rE "招标|政府采购|审核点|底稿|投标人" scrivai/ || true)
[ -z "$leak" ] && echo "OK: business terms clean" || { echo "FAIL: leaked"; exit 1; }

# 包目录不应含 .claude/
[ -d scrivai/.claude ] && { echo "FAIL: scrivai/.claude should not exist"; exit 1; }

# 根目录只允许 .claude/skills 作为 EvoSkill 兼容 symlink(若存在)
if [ -e .claude ]; then
  if [ ! -L .claude/skills ]; then
    echo "FAIL: .claude/skills must be symlink for EvoSkill compat"; exit 1
  fi
fi

echo "All checks passed."
```

---

## 跨项目集成任务

| 任务 | 集成节点 | 说明 |
|---|---|---|
| 消费 qmd 的 `FakeQmdClient` 跑契约 | I0 | M0 必须 |
| 暴露 `MockPES + TempWorkspaceManager + FakeTrajectoryStore + scrivai.testing.contract` 给 GovDoc | I0 | GovDoc 单测必需 |
| Library 固定 collection 名 "rules"/"cases"/"templates" | I0 | 写入契约 |
| `scrivai.ChunkRef is qmd.ChunkRef` re-export 身份一致 | I0 | 契约测试验证 |
| EvoSkill 评测集格式与 GovDoc 的 `Evaluator` 对齐 | I2 | 业务层实现 Evaluator,Scrivai 消费 |
| TrajectoryStore `record_feedback` API 与 GovDoc 专家修订闭环对齐 | I2 | GovDoc Web UI 专家修订后调此 API |

---

## 风险 & 缓解

| 风险 | 缓解 |
|---|---|
| Claude Agent SDK 版本演进破坏 API | 锁定 minor 版本;M0 末跑 SDK smoke 校验 |
| 兼容供应商(GLM/MiniMax)实际行为偏差 | M1 双跑校验;prompt 强制 "以 JSON 格式回复" 约束 |
| Workspace 内容快照磁盘占用增长 | 30 天自动 cleanup;`cleanup_days` 可配 |
| TrajectoryStore 在高频 run 下膨胀 | M2 测试 10k runs 下查询 P95;提供 `scrivai-cli trajectory prune --older-than 90d` |
| EvoSkill Proposer 提议过多低质量修改 | `max_iterations` + `no_improvement_limit` 限制;Evaluator 严格筛 |
| PES 三阶段对短任务过度拆分 | 短任务可设 `max_turns=2`;允许业务自定义子类跳过某 phase |
| 业务术语漏入 Scrivai | pre-commit hook + CI grep |
| docxtpl 不支持某模板结构 | 退路:`python-docx` 手写渲染器,`DocxRenderer` 公共 API 不变 |
| fcntl 锁在某些文件系统(NFS)失败 | M1 在 docker-compose 跑完整 fixture 验证 |
| EvoSkill 候选分支爆炸(每轮 N 个 × M 轮) | `frontier_size` 限 top-K;cache_enabled 跳过已评估分支 |

---

## 日常节奏

- 每天 commit 前:`ruff check . --fix && ruff format . && pytest tests/unit/ tests/contract/`
- 每周五:偏移自检(禁止 scrivai/ 下出现业务术语 + 禁止出现 Scrivai 内部 `.claude/` 目录)
- M0/M1/M2/M3 末:在 `INTEGRATION_ISSUES.md` 汇报交付
