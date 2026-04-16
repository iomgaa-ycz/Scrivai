# 附录 A：Scrivai 模块拆分

> **版本**: v3（2026-04-15）
> **定位**: 本文是 `docs/design.md` 的附录，专责补充 **模块级职责与边界**。权威信息以 `design.md` 为准；若本文与 `design.md` 冲突，以 `design.md` 为准。
> **对应章节**: `design.md §5 内部架构`

## A.1 为什么要这份附录

`design.md §5` 给出了目录树和两个核心模块（`AgentSession` / `WorkspaceManager`）的实现要点。本附录补充：

1. **10 个模块的统一总表**：每个模块的职责边界、对外出口、内部依赖
2. **模块依赖拓扑**：谁能 import 谁、反向依赖是否被禁止
3. **分模块测试策略**：单元 / 契约 / 集成测试的归属

目的是让"新加一个功能应该落在哪个模块"这类问题有确定答案。

## A.2 模块总表

| # | 路径 | 职责 | 公开出口（`scrivai/__init__.py` 可见） |
|---|---|---|---|
| 1 | `scrivai/models/` | pydantic + Protocol（单一真相） | `ModelConfig, PhaseConfig, AgentProfile, WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle, WorkspaceManager, PhaseResult, AgentRunResult, AgentSession, LibraryEntry, Library, EvolutionConfig, Evaluator` + re-export `ChunkRef/SearchResult/CollectionInfo/Collection/QmdClient` |
| 2 | `scrivai/agent/` | **PES 引擎**：session + profile + runner + 消息解析 | `build_agent_session()`（内部用 `_AgentSession`） |
| 3 | `scrivai/workspace/` | Workspace 生命周期（snapshot + fcntl lock + archive） | `build_workspace_manager()` |
| 4 | `scrivai/llm/` | Claude Agent SDK 客户端工厂 + `ClaudeAgentOptions` 构造 | 不对外暴露；仅被 `agent/session.py` 使用 |
| 5 | `scrivai/prompts/` | PromptManager（j2+md 模板装载 / system prompt 组装） | `PromptManager`（轻量，无状态） |
| 6 | `scrivai/knowledge/` | Library 实现（Rule/Case/Template + factory） | `RuleLibrary, CaseLibrary, TemplateLibrary, build_qmd_client_from_config` |
| 7 | `scrivai/io/` | 旁路工具：docx/pdf→md、DocxRenderer | `docx_to_markdown, pdf_to_markdown, DocxRenderer` |
| 8 | `scrivai/evolution/` | **进化引擎**：EvoSkill adapter | `EvolutionRunner, EvolutionConfig`（见 `design.md §4.8`） |
| 9 | `scrivai/cli/` | `scrivai-cli` 子命令（library/io/workspace） | 非 Python API；通过 console_scripts 暴露二进制 |
| 10 | `scrivai/testing/` | MockAgentSession + FakeQmdClient + contract plugin | `MockAgentSession, FakeQmdClient, contract`（pytest plugin） |

**源 skills / agents**（不在 `scrivai/` 包内、但属于 Scrivai 仓库）：
- `skills/search-knowledge/SKILL.md`
- `skills/inspect-document/SKILL.md`
- `skills/render-output/SKILL.md`
- `skills/available-tools/SKILL.md`
- `agents/extractor.yaml` / `auditor.yaml` / `generator.yaml`

运行时由 `WorkspaceManager.create` 以内容快照方式复制到 workspace 的 `working/.claude/`（见 `design.md §5.3`）。

## A.3 依赖拓扑

允许的 import 方向（上游 → 下游）：

```
          ┌─────────────┐
          │   models    │  ← 被所有模块依赖；自身仅依赖 pydantic + qmd 类型
          └──────┬──────┘
                 │
      ┌──────────┼──────────┬─────────┬──────────┐
      ▼          ▼          ▼         ▼          ▼
  ┌───────┐  ┌───────┐  ┌───────┐ ┌───────┐  ┌───────┐
  │prompts│  │  llm  │  │ knowl │ │  io   │  │testing│
  └───┬───┘  └───┬───┘  └───┬───┘ └───┬───┘  └───┬───┘
      │          │          │         │          │
      └──────────┴────┬─────┴─────────┘          │
                     ▼                           │
              ┌──────────────┐                   │
              │    agent     │ ◀─── workspace ◀──┘（被 agent 注入）
              └──────┬───────┘       (独立模块)
                     │
                     ▼
              ┌──────────────┐
              │  evolution   │（调 agent 产出 trajectory 给 EvoSkill）
              └──────────────┘

  cli 独立层：聚合 knowledge / io / workspace 为 subcommand，不被 agent 直接 import
```

**禁止的反向依赖**：
- `models` 禁止 import 任何其它 scrivai 子模块
- `prompts / llm / knowledge / io` 不能 import `agent`（防止循环）
- `knowledge` 不能 import `cli`（cli 是 knowledge 的 Bash 封装，反向依赖会形成环）
- `testing` 只能被 tests 目录 import，不能出现在生产代码里

## A.4 分模块详表

### A.4.1 `models/` — 契约单一真相

- **文件**: `agent.py` / `workspace.py` / `evolution.py` / `knowledge.py` / `__init__.py`
- **依赖**: 仅 `pydantic`, `qmd`（re-export 用）
- **禁止**: 任何运行时行为（IO / 网络 / 文件系统）
- **测试**: schema 兼容性快照测试（pydantic `.model_json_schema()`）

### A.4.2 `agent/` — PES 引擎

- **文件**: `session.py` / `profile.py` / `runner.py` / `messages.py`
- **核心类型**: `_AgentSession`（内部） + `PESRunner`（编排 plan→execute→summarize）
- **依赖**: `models, prompts, llm, workspace`（通过注入）
- **测试**: `testing/mock_agent.py` 支持契约测试；集成测试用真 SDK

### A.4.3 `workspace/` — 沙箱生命周期

- **文件**: `manager.py` / `snapshot.py` / `lock.py` / `archive.py`
- **关键不变量**（见 `design.md §5.2`）：
  - `create()` 先拿 fcntl 独占锁再创建目录
  - skills/agents 走 `shutil.copytree(symlinks=False)` 内容快照
  - `meta.json` 记录 `skills_git_hash`、`agents_git_hash`
  - `WorkspaceSpec.force=True` 才允许覆盖已存在的 `run_id`
- **测试**: 并发锁契约测试（两个进程同时 create 同一 run_id） + 快照完整性测试

### A.4.4 `llm/` — Claude Agent SDK 适配层

- **文件**: `sdk_client.py`（构造 `ClaudeAgentOptions`） / `tools_policy.py`（PES allowed_tools 矩阵）
- **细节见附录 B `sdk_design.md`**
- **依赖**: `claude_agent_sdk`, `models`
- **测试**: 字段构造单元测试；不跑真 SDK

### A.4.5 `prompts/` — PromptManager

- **文件**: `manager.py` / `loader.py`
- **职责**: 装载 `templates/prompts/*.j2 + *.md`，组装 `system_prompt`（agent.prompt_text + phase.additional_system_prompt + 上阶段结果引用），**无状态**
- **替代**: 旧 `GenerationContext`（v2 遗留）被彻底删除；`summarize/extract_terms/extract_references` 功能不再以 Python 函数存在，而是成为 agent prompt 的一部分
- **测试**: 模板渲染单元测试 + 变量缺失检测

### A.4.6 `knowledge/` — Library

- **文件**: `base.py` / `rules.py` / `cases.py` / `templates.py` / `factory.py`
- **职责**: 在 qmd 上封装固定 collection 约定（`rules` / `cases` / `templates`）；业务层不直接调 `qmd.connect`，用 `build_qmd_client_from_config(cfg)`
- **依赖**: `qmd`, `models`
- **测试**: 契约测试（`FakeQmdClient`） + 集成测试（真 qmd）

### A.4.7 `io/` — 文档旁路工具

- **文件**: `convert.py`（docx/pdf → md）/ `render.py`（`DocxRenderer`，docxtpl 封装）/ `markdown.py`
- **约束**: `DocxRenderer` 的模板必须手工 Word 制作（见 `design.md §4.3` 与 `INTEGRATION_ISSUES.md ISSUE-002`）
- **测试**: 单元（小 docx fixture） + 契约（程序化生成模板应报错）

### A.4.8 `evolution/` — 进化引擎

- **文件**: `config.py` / `runner.py` / `proposer.py`（可选） / `generator.py` / `frontier.py`
- **职责**: 桥接 EvoSkill：封装 CSV dataset + scorer `(question, predicted, ground_truth) -> float` + LoopConfig
- **依赖**: `evoskill`（外部包）, `agent`（跑 trajectory）, `models`
- **限制**: 仅 M2+ 启用；M0/M1 不编译、不测试
- **测试**: adapter 单元测试（mock evoskill）

### A.4.9 `cli/` — Bash 工具入口

- **文件**: `__main__.py`（路由） / `library.py` / `io.py` / `workspace.py`
- **职责**: 把 `knowledge / io / workspace` 的 Python API 封成 `scrivai-cli <group> <cmd>`，以 JSON 输出 stdout
- **规范**: 所有命令退出码 0=成功 / 1=业务错误 / 2=参数错误；stderr 走 logging，stdout 只放 JSON
- **测试**: 每个子命令一个契约测试（argparse 解析 + JSON schema 校验）

### A.4.10 `testing/` — 测试支持

- **文件**: `mock_agent.py` / `tmp_workspace.py` / `fake_qmd.py` / `contract.py`（pytest plugin）
- **职责**: 下游项目（GovDoc-Auditor）也能 `import scrivai.testing` 跑契约测试
- **依赖**: `pytest`, `models`
- **约束**: 生产代码不能 import

## A.5 和 design.md 的章节映射

| 本附录章节 | 对应 design.md 章节 |
|---|---|
| A.2 模块总表 | §5 内部架构（目录树） |
| A.3 依赖拓扑 | — 新增（design.md 未正式描述） |
| A.4.2 agent 详述 | §4.1 / §4.1.1 / §5.1 |
| A.4.3 workspace 详述 | §5.2 / §5.3 |
| A.4.4 llm + PES allowed_tools | 附录 B `sdk_design.md` |
| A.4.6 knowledge | §4.2 |
| A.4.7 io | §4.3 |
| A.4.9 cli | §4.4 |
| A.4.8 evolution | §4.8 |
| A.4.10 testing | §4.5（契约测试覆盖面） |

## A.6 变更纪律

新增 / 删除 / 合并模块 → 先走 `GOVDOC_PROGRAM_PLAN.md §8 变更流程`，更新 `design.md §5` 目录树与本附录 A.2 表格；两处同步改动。

**禁止**：只改本附录不动 `design.md`（会导致附录反客为主）。
