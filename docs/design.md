# Scrivai 设计文档

> **版本**: v3（2026-04-15）
> **v2→v3 变更**（基于 Codex review + EvoSkill spike + docxtpl 探针）：
> 1. pydantic/Protocol 集中在本项目 `scrivai/models/` 目录（单一真相）；design.md 不再内嵌代码。qmd 的类型通过 `from qmd import ...` 直接用，Scrivai re-export 以便 GovDoc 统一从 `scrivai` 拿
> 2. **PES 阶段契约改为"强制文件化产物"**：plan→`working/plan.md`+`plan.json`；execute→`working/findings/<id>.json`；summarize→`working/output.json`。phase 间交互通过文件不靠 text
> 3. **Workspace 从 symlink 改为内容快照**（`shutil.copytree`）+ 记录 skills/agents 的 git commit hash 到 `meta.json`；归档含完整可复现集；失败保留 resolve 所有 symlink
> 4. **并发锁**：`WorkspaceManager.create` 加 `fcntl` 文件锁 + `WorkspaceSpec.force` 字段控制 run_id 冲突
> 5. **Summarize 阶段 `allowed_tools` 收紧**至 `["Bash", "Read", "Write"]`（移除 Glob/Edit 避免发散）
> 6. **新增 `build_qmd_client_from_config`** 工厂（业务层不再直接 `qmd.connect`）
> 7. **新增通用 skill** `available-tools/SKILL.md`（CLI 命令 manifest）
> 8. **EvolutionConfig 对齐 EvoSkill 真实 API**（spike 发现：scorer 签名 `(q,pred,gt)->float`；CSV dataset；硬编码 `.claude/skills/` 路径）
> 9. **DocxRenderer 模板制作约束**：docxtpl 要求模板手工 Word 制作，不能程序化生成（详见 §4.3）

**日期**: 2026-04-15（v3 更新）
**项目**: Scrivai
**本项目在系统中的定位**: 文档审核 / 生成的 **Claude Agent 编排框架**

> 本文档是 Scrivai 在 GovDoc 三项目体系中的设计。顶层计划见 `/home/iomgaa/Projects/GOVDOC_PROGRAM_PLAN.md`。
> 范式更新（2026-04-15）：从 LLMClient + Chain 切换为 Claude Agent SDK + Workspace + PES + Skill。

### 配套附录（本文档的附录，权威性低于本文）

| 文件 | 职责 | 对应本文章节 |
|---|---|---|
| [`architecture.md`](architecture.md) | **附录 A**：10 个模块的职责 / 对外出口 / 依赖拓扑 / 测试策略 | §5 内部架构 |
| [`sdk_design.md`](sdk_design.md) | **附录 B**：Claude Agent SDK 集成（`ClaudeAgentOptions` 字段、`allowed_tools` 矩阵、CLI+Bash vs MCP 决策、hook / 错误处理） | §5.1 AgentSession |

附录与本文冲突时以本文为准。附录变更必须同步更新本文对应章节（见各附录末节的"变更纪律"）。

---

## 1. 定位

Scrivai 是文档审核 / 生成场景下的 **Agent 编排框架**——围绕 Claude Agent SDK 提供 **AgentSession、WorkspaceManager、PES 三阶段执行器、通用 Skill 包、CLI 工具集** 五大能力。

| 维度 | 要点 |
|---|---|
| **知道什么** | Agent SDK 的调用方式、workspace 沙箱化、PES 流程、通用知识库（Library）、文档 I/O、CLI 工具规范、Skill 装入约定、EvoSkill 进化机制 |
| **不知道什么** | 业务领域（招标 / 政府采购 / 医疗 / ...）；具体 prompt 文本（除"通用 skill"外）；具体业务 schema |
| **依赖** | qmd-py（向量数据库）、claude-agent-sdk |
| **被谁用** | GovDoc-Auditor 及未来任何"文档审核/生成"应用 |
| **禁止事项** | 源码出现 `招标 / 政府采购 / 审核点 / 底稿 / 投标人` 等业务术语 |

**核心范式**：Agent 是编排者，Python 提供工具（CLI）和沙箱（Workspace）；Scrivai 是这套范式的"通用底盘"，业务层只需写自己的 prompt + skill + CLI。

## 2. 系统关系

```
GovDoc-Auditor（业务）
   │
   │ ① Python 调用 Scrivai 启动 Agent
   │    AgentSession.run(agent=..., model=..., workspace=..., task_prompt=...)
   ▼
┌────────────────────────────────────────────────┐
│ Scrivai                                        │
│  ┌───────────────────────────────────────┐    │
│  │ AgentSession (调 Claude Agent SDK)     │    │
│  │   plan → execute → summarize           │    │
│  └────────┬──────────────────────────────┘    │
│           │ 创建/管理                          │
│  ┌────────▼──────────────────────────────┐    │
│  │ WorkspaceManager                       │    │
│  │   ~/.govdoc/workspaces/<run_id>/       │    │
│  │     working/.claude/skills/  (symlink) │    │
│  │     data/  (symlink 业务输入)           │    │
│  │     output/  logs/  meta.json          │    │
│  └───────────────────────────────────────┘    │
│  ┌───────────────────────────────────────┐    │
│  │ scrivai-cli (Bash 工具调用入口)         │    │
│  │   library {search, get, list}          │    │
│  │   io {docx2md, pdf2md, render, ...}    │    │
│  │   workspace {create, archive, cleanup} │    │
│  └────────┬──────────────────────────────┘    │
│           │ 内部依赖                           │
│  ┌────────▼──────────────────────────────┐    │
│  │ knowledge.{Rule|Case|Template}Library  │    │
│  │ io.{docx_to_markdown, DocxRenderer...} │    │
│  └───────────────────────────────────────┘    │
└────────────┬───────────────────────────────────┘
             │ Python API + CLI
             ▼
        qmd-py（向量数据库 + qmd CLI）
```

## 3. 上游契约：qmd-py（canonical from PLAN §4.1）

```python
from qmd import (
    ChunkRef, SearchResult, CollectionInfo,
    Collection, QmdClient, connect,
)
```

CLI（agent 通过 Bash 调用）：

```bash
qmd search --collection <name> --query <q> [--top-k 5] [--rerank]
qmd document {get,add,delete,list}
qmd collection {info,list}
```

Scrivai 对 qmd 的使用模式：
- Library 实现内部 `import qmd`（直接调）
- Agent 通过 Bash 调 `qmd search ...`（不直接 import）

**固定 collection 约定**：
- `RuleLibrary` → `"rules"`
- `CaseLibrary` → `"cases"`
- `TemplateLibrary` → `"templates"`
- 临时 collection 命名约定：`run_<run_id>_<purpose>`（如 `run_a1b2c3_tender`）

## 4. 对外契约（canonical from PLAN §4.2）

### 4.1 Agent 与 Workspace 核心模型

**单一真相**：`Scrivai/scrivai/models/agent.py`（+ `workspace.py`）；从 `scrivai/__init__.py` 导出。

```python
# 所有 pydantic/Protocol 从 scrivai 直接导入
from scrivai import (
    ModelConfig, PhaseConfig, AgentProfile,
    WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle, WorkspaceManager,
    PhaseResult, AgentRunResult, AgentSession,
    # 工厂函数
    build_agent_session, build_workspace_manager,
    build_qmd_client_from_config,   # v3 新增：业务层不再直接 import qmd
)
# qmd 类型：Scrivai re-export 方便下游一站式 import
from scrivai import ChunkRef, SearchResult, CollectionInfo  # 实际来自 qmd，Scrivai 转发
```

**v3 关键字段说明**（详见 contracts 源码）：
- `WorkspaceSpec.force: bool`（v3 新增）：run_id 冲突时，`True` 覆盖原 workspace，`False` 抛 `WorkspaceError`
- `WorkspaceSnapshot`（v3 新增）：记录快照时的 `skills_git_hash / agents_git_hash / snapshot_at`，写入 workspace 的 `meta.json`
- `WorkspaceHandle.snapshot: WorkspaceSnapshot`（v3 新增）
- `PhaseResult.produced_files: list[str]`（v3 新增）：该 phase 写入 workspace 的文件清单（相对 `working_dir`）
- `AgentRunResult.final_output_path: Path | None`（v3 新增）：summarize 产出的 `working/output.json` 绝对路径；业务层**应优先读此文件**，`final_output` 字符串字段保留向后兼容

### 4.1.1 PES 流程语义（v3 文件化契约）

`AgentSession.run` 顺序执行 plan → execute → summarize 三个 phase。**v3 变更**：三 phase 通过 workspace 内的约定文件交互，**不再依赖** `phase.text` 字符串拼接——避免 plan 阶段的工具调用 / 内部状态在 text 摘要中丢失。

**Plan**
- `query()` 无状态调用，输入：`task_prompt + phase_inputs.get("plan", {})`
- **必需产物**：`working/plan.md`（人类可读策略）+ `working/plan.json`（机器可读执行清单，结构由业务 agent 定义）
- system_prompt **强制要求**："你必须在结束前用 Write 工具写入 `working/plan.md` 和 `working/plan.json`"
- `PhaseResult.produced_files` 必含 `"plan.md"` 和 `"plan.json"`；缺失则 phase 失败（`error="required output file missing: ..."`）

**Execute**
- `query()` 无状态调用
- system_prompt **明确指示**："读 `working/plan.md` 和 `working/plan.json` 作为起点；按清单逐项执行"
- **必需产物**：`working/findings/<item_id>.json`——plan.json 指定的每个 item 一个文件
- agent 自主用 Bash 调 CLI 检索、读文件、写 findings
- `PhaseResult.produced_files` 至少含一个 `findings/*.json`

**Summarize**
- `query()` 无状态调用
- system_prompt 指示："读 `working/findings/*.json`（用 Bash `ls working/findings/`），聚合成 `working/output.json`"
- **必需产物**：`working/output.json`——**唯一**最终结构化输出，结构由业务层 task_prompt 明确约束
- `allowed_tools` **收紧**到 `["Bash", "Read", "Write"]`（无 Edit/Glob/Grep，避免发散重检索）
- `AgentRunResult.final_output_path = workspace.working_dir / "output.json"`

**错误处理**：每 phase 结束后 Scrivai 校验 `produced_files` 完整性；任一必需文件缺失 → 中断后续 phase，`success=False`。

### 4.2 Knowledge 层（Python API + CLI 包装）

**单一真相**：`Scrivai/scrivai/models/knowledge.py` + `Scrivai/scrivai/knowledge/*.py`

```python
from scrivai import (
    LibraryEntry, Library,               # pydantic + Protocol
    RuleLibrary, CaseLibrary, TemplateLibrary,  # 具体实现，对应固定 collection 名
    build_libraries,                     # 工厂
)
```

**持久化策略**：LibraryEntry 元数据完全持久化在 qmd chunk metadata；不维护内存状态。

### 4.3 IO 工具

```python
# scrivai.io
from pathlib import Path
def docx_to_markdown(path: str | Path) -> str: ...
def doc_to_markdown(path: str | Path) -> str: ...        # libreoffice → docx → pandoc
def pdf_to_markdown(path: str | Path, *, ocr: bool = True) -> str: ...

class DocxRenderer:
    def __init__(self, template_path: str | Path): ...
    def render(self, context: dict, output_path: str | Path) -> None: ...
    def list_placeholders(self) -> list[str]: ...
```

**v3 模板制作约束**（依 2026-04-15 docxtpl 探针；详见 `INTEGRATION_ISSUES.md` ISSUE-002）：

1. **模板必须由 Word/LibreOffice 手工制作**——不能用 python-docx 程序化生成。程序化生成容易把 jinja 标签（`{%tr for %}`）拆到多个 XML `<w:r>` 中导致 docxtpl 解析失败
2. **单 cell 内不支持嵌套 `{% for %}`**——用 jinja2 过滤器（如 `{{ items | join('; ') }}`）扁平化
3. **避免表中表（nested tables）**——docxtpl 不自动展开子表
4. **退路**：若 docxtpl 不够用，直接 `python-docx` 手写渲染器；`DocxRenderer` 公共 API 不变，仅换底层实现。记入风险登记，M1 不做

### 4.4 CLI 命令规范

入口：`scrivai-cli <group> <subcommand> [args]`，等价 `python -m scrivai.cli <group> <subcommand>`

**通用约定**：
- JSON 到 stdout（`json.dumps(..., ensure_ascii=False)`）
- 错误 JSON 到 stderr，exit 1
- 环境变量回退：`SCRIVAI_PROJECT_ROOT`、`QMD_DB_PATH`、`SCRIVAI_WORKSPACE_ROOT`、`SCRIVAI_ARCHIVES_ROOT`

**必备命令**：

```bash
# library 组（agent 高频用）
scrivai-cli library search --type rules|cases|templates --query <q> [--top-k 5] [--filters '{}']
scrivai-cli library get    --type rules|cases|templates --entry-id <id>
scrivai-cli library list   --type rules|cases|templates [--filters '{}']

# io 组（管道触发用，agent 也可用）
scrivai-cli io docx2md --input <path> [--output <path>]
scrivai-cli io doc2md  --input <path> [--output <path>]
scrivai-cli io pdf2md  --input <path> [--output <path>] [--ocr]
scrivai-cli io render  --template <path> --context-json <path> --output <path>

# workspace 组（业务层用，**不**给 agent 用）
scrivai-cli workspace create   --run-id <id> --project-root <path> --data <name>=<path> [--data ...] [--env KEY=VAL ...]
scrivai-cli workspace archive  --run-id <id> [--success|--failed]
scrivai-cli workspace cleanup  --days 30
```

CLI 子命令的 JSON 输出 schema 在契约测试中和对应 Python API `.model_dump()` 比对。

### 4.5 不变量（契约测试覆盖）

1. `WorkspaceManager.create` 产出的 `WorkspaceHandle` 目录结构完整：`working/`、`data/`、`output/`、`logs/`、`meta.json` 全在；`working/.claude/skills/` 是指向 `project_root/skills/` 的 symlink；`working/.claude/agents/` 同理；`data_inputs` 全部 symlink 到 `data_dir/`
2. `WorkspaceManager.archive(success=True)` 把 `output + logs + meta` 打包 `tar.gz` 到 `archives_root/<run_id>.tar.gz` 并删除原 workspace；返回归档路径
3. `WorkspaceManager.archive(success=False)` 不动 workspace，写一个 `.failed` 标记，返回 `workspace.root`
4. `WorkspaceManager.cleanup_old` 同时清 archives 和 failed workspace（30 天内修改的不动）
5. `AgentSession.run` 严格按 plan → execute → summarize 顺序；plan 失败则 execute 不跑；执行/汇总失败保留已完成 phase 的 PhaseResult
6. PES 之间的 context 传递：execute 的 system_prompt 拼接 = `agent.prompt_text + agent.phases["execute"].additional_system_prompt + plan.text`；summarize 同理拼 execute.text
7. `AgentRunResult.success = all(p.error is None for p in phases)`
8. Library 的 `entry_id` 全局唯一（每 collection 内）
9. `DocxRenderer.render` 成功即产出完整文件；失败不留半成品
10. 所有 CLI 命令在缺失必备 env var 时给出明确的 stderr JSON `{"error": "missing env var: ..."}`

### 4.6 通用 Skill 包（Scrivai/skills/）

Scrivai 提供四个**通用 skill**（v3 新增 `available-tools`），作为业务层 skill 的"基类"。业务层可在自己的 skills/ 里**同名覆盖**或**追加新 skill**。

```
Scrivai/skills/
├── search-knowledge/
│   ├── SKILL.md
│   └── (assets/)
├── inspect-document/
│   └── SKILL.md
├── render-output/
│   └── SKILL.md
└── available-tools/               ← v3 新增：CLI 命令 manifest
    └── SKILL.md
```

**`available-tools/SKILL.md`** 的作用：枚举 `scrivai-cli / qmd / govdoc-cli` 所有子命令的参数、输出 JSON shape、典型错误。agent 在任何 phase 都可 `Read .claude/skills/available-tools/SKILL.md` 作为**权威命令参考**——避免 prompt 漂移导致 agent 瞎调命令。业务 agent 的 `skills_required` 默认应含此 skill。

**SKILL.md 标准格式**（Anthropic skill 约定）：

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
- 需要回溯定位原文出处

## How to use
Invoke via Bash:

```bash
scrivai-cli library search --type <rules|cases|templates> --query "<query>" --top-k 5
```

## Output
JSON list of `SearchResult`:
```json
[
  {
    "ref": {"chunk_id": "...", "document_id": "...", "collection": "rules",
            "position": 12, "char_start": 1024, "char_end": 1200},
    "text": "...",
    "score": 0.87
  }
]
```

## Tips
- 同一查询可换 2-3 个表述提高召回
- 结果不足时 top-k 调到 10
- 引用证据时必须带 `chunk_id` 便于回溯
```

### 4.7 通用 Agent Profile 包（Scrivai/agents/）

```
Scrivai/agents/
├── extractor.yaml    # 用于"信息抽取"
├── auditor.yaml      # 用于"对照审核"
└── generator.yaml    # 用于"按模板生成"
```

YAML 字段严格匹配 §4.1 `AgentProfile`。**业务层不一定要用这些**——可在自己 `agents/` 写更具体的 agent profile（如 `gov-auditor.yaml`），用业务 prompt 覆盖。

YAML 示例（`Scrivai/agents/auditor.yaml`）：

```yaml
name: auditor
display_name: 通用对照审核 Agent
prompt_text: |
  You are a meticulous compliance auditor. You audit a document against
  a set of checkpoints. For each checkpoint:
  1. Use search-knowledge skill to find relevant evidence in the document.
  2. Cite chunk_ids in your verdict.
  3. Output structured JSON in summarize phase.

  You may use these CLI tools via Bash:
  - scrivai-cli library search ...
  - qmd search ...
  - scrivai-cli io docx2md ...

phases:
  plan:
    name: plan
    max_turns: 6
    allowed_tools: ["Bash", "Read", "Glob", "Grep", "Skill", "Write"]
    additional_system_prompt: |
      In this phase, draft a retrieval+audit strategy. Output:
      - which queries to run for each checkpoint
      - which sections of the document to focus on
      Save plan to working/plan.md
  execute:
    name: execute
    max_turns: 30
    allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"]
    additional_system_prompt: |
      Execute the plan from working/plan.md. For each checkpoint:
      - run searches
      - read evidence
      - write per-checkpoint findings to working/findings/<id>.md
  summarize:
    name: summarize
    max_turns: 4
    allowed_tools: ["Bash", "Read", "Write"]   # v3：收紧，无 Glob/Edit
    additional_system_prompt: |
      Read all working/findings/*.json (use `ls working/findings/` via Bash),
      compile into a single JSON object matching the schema given in task_prompt.
      Write to working/output.json and respond with the JSON content as your
      final message.

skills_required:
  - available-tools       # v3：默认必含
  - search-knowledge
  - inspect-document
```

### 4.8 EvoSkill 集成

```python
# scrivai.evolution
from pathlib import Path
from datetime import datetime
from typing import Protocol
from pydantic import BaseModel
from scrivai.agent import AgentRunResult, ModelConfig

**单一真相**：`Scrivai/scrivai/models/evolution.py` + `Scrivai/scrivai/evolution/*.py`
**对齐依据**：2026-04-15 EvoSkill spike（详见 `INTEGRATION_ISSUES.md` ISSUE-001 / ISSUE-003）

```python
from scrivai import Evaluator, EvolutionConfig, EvolutionRun, run_evolution

# Evaluator 签名（对齐 EvoSkill scorer 协议）：
#   def __call__(question: str, predicted: str, ground_truth: str) -> float
```

**v3 关键变更（依 spike 发现）**：
- `Evaluator` 签名从 `(run_result, golden) -> float` 改为 **EvoSkill 原生** `(question, predicted, ground_truth) -> float`——业务层从 `AgentRunResult.final_output_path` 读 predicted，从 golden 序列化 ground_truth
- `EvolutionConfig.eval_dataset_path` 改为 `eval_dataset_csv`——EvoSkill 要求 CSV 格式（`question / ground_truth / category` 三列必需）
- 新增字段：`task_name / model / mode / max_iterations / no_improvement_limit / concurrency / train_ratio / val_ratio / tolerance / selection_strategy / cache_enabled / cache_dir`
- 删除字段：`skills_dir`（EvoSkill **硬编码** `cwd/.claude/skills/`）、`base_branch`（EvoSkill 隐式 `main`）、`proposer_model`（EvoSkill 用 `LoopAgents` 内部管理）

**⚠️ 集成准备：Skills 路径兼容**

EvoSkill 硬编码读写 `project_root/.claude/skills/`。但本项目 v3 设计规定 skills 源位于 `project_root/skills/`（非 `.claude/`）。**M2 接入 EvoSkill 前业务层必须选一方案**：

| 方案 | 做法 | 推荐度 |
|---|---|---|
| **A**（推荐） | 在业务项目根建 git 追踪的 symlink `<project>/.claude/skills -> ../skills`——EvoSkill 透过 symlink 读写，实际落在 `skills/`；git diff 显示在 `.claude/skills/` 但真实改动在 `skills/` | ⭐ 推荐 |
| B | 把源 skills 迁到 `.claude/skills/`——与 EvoSkill 原生兼容，但违背"不放 .claude/"指示 | 不推荐 |
| C | 推迟 EvoSkill 到 M3，M2 手写 skill 迭代 | 下策 |

**进化机制（5 阶段，参考 EvoSkill 论文）**：
1. **Base run**：当前 main 上的 skill 跑 eval_dataset，记录每条任务的 trajectory + score
2. **Proposer**：用 `model` 参数指定的模型分析失败 trajectory，提议修改
3. **Generator**：生成具体 SKILL.md 修改，写到 git 分支 `evo/<timestamp>-<idx>`
4. **Evaluator**：每分支跑评测集 → `Evaluator(question, predicted, ground_truth)` 打分
5. **Frontier**：留 top-N 分支；最高分超过 base 时填入 `promoted_branch`

**安全性**：进化产物**永不直接覆盖 main**；只到 git 分支。人工审核 + PR + 跑回归测试后才合并 main。

## 5. 内部架构

> 模块级职责与依赖拓扑详见附录 A [`architecture.md`](architecture.md)；本节给出顶层目录结构与两个关键模块（AgentSession / WorkspaceManager）的实现要点。

```
Scrivai/
├── scrivai/
│   ├── __init__.py        ← public API only（见 §4 出口）
│   ├── agent/
│   │   ├── session.py     ← AgentSession 实现（封装 query()）
│   │   ├── profile.py     ← AgentProfile + YAML 加载
│   │   ├── workspace.py   ← WorkspaceManager 实现
│   │   ├── runner.py      ← PESRunner（plan→execute→summarize）
│   │   └── messages.py    ← 解析 Claude SDK 的 Message
│   ├── cli/
│   │   ├── __main__.py    ← scrivai-cli 路由
│   │   ├── library.py
│   │   ├── io.py
│   │   └── workspace.py
│   ├── knowledge/
│   │   ├── base.py
│   │   ├── rules.py
│   │   ├── cases.py
│   │   ├── templates.py
│   │   └── factory.py
│   ├── io/
│   │   ├── convert.py
│   │   ├── render.py
│   │   └── markdown.py
│   ├── evolution/
│   │   ├── config.py
│   │   ├── runner.py
│   │   ├── proposer.py
│   │   ├── generator.py
│   │   └── frontier.py
│   ├── testing/
│   │   ├── mock_agent.py  ← MockAgentSession（按 trajectory 回放）
│   │   ├── tmp_workspace.py
│   │   └── contract.py    ← pytest plugin
│   └── exceptions.py
├── skills/                 ← 通用 skill（不放 .claude/）
│   ├── search-knowledge/SKILL.md
│   ├── inspect-document/SKILL.md
│   └── render-output/SKILL.md
├── agents/                 ← 通用 agent profile
│   ├── extractor.yaml
│   ├── auditor.yaml
│   └── generator.yaml
├── tests/
│   ├── unit/
│   ├── contract/          ← 用 MockAgentSession + FakeQmdClient
│   ├── integration/       ← 真实 SDK + 真实 qmd
│   └── fixtures/
├── docs/
│   ├── design.md          ← 本文（权威）
│   ├── architecture.md    ← 附录 A：模块拆分
│   ├── sdk_design.md      ← 附录 B：Claude Agent SDK 集成
│   └── TD.md
└── pyproject.toml
```

### 5.1 AgentSession 实现要点

> `ClaudeAgentOptions` 字段在 PES 三阶段的差异、`allowed_tools` 矩阵、CLI+Bash vs MCP 的决策记录详见附录 B [`sdk_design.md`](sdk_design.md)。

```python
# scrivai/agent/session.py（伪代码）
from claude_agent_sdk import query, ClaudeAgentOptions

class _AgentSession:
    async def run(self, *, agent, model, workspace, task_prompt, phase_inputs={}):
        phases = []
        prev_text = ""
        for phase_name in ("plan", "execute", "summarize"):
            phase_cfg = agent.phases[phase_name]
            sys_prompt = "\n\n".join([
                agent.prompt_text,
                phase_cfg.additional_system_prompt,
                f"Previous phase output:\n{prev_text}" if prev_text else "",
            ]).strip()

            options = ClaudeAgentOptions(
                model=model.model,
                base_url=model.base_url,
                api_key=model.api_key,
                fallback_model=model.fallback_model,
                cwd=str(workspace.working_dir),
                system_prompt=sys_prompt,
                allowed_tools=phase_cfg.allowed_tools,
                permission_mode=phase_cfg.permission_mode,
                max_turns=phase_cfg.max_turns,
                env={
                    "SCRIVAI_PROJECT_ROOT": str(spec_project_root),
                    "QMD_DB_PATH": os.environ["QMD_DB_PATH"],
                    "GOVDOC_RUN_ID": workspace.run_id,
                    **phase_inputs.get(phase_name, {}),
                },
                setting_sources=["project"],
            )

            phase_prompt = self._build_phase_prompt(phase_name, task_prompt, prev_text, phase_inputs)

            turns = []
            text = ""
            usage = {}
            error = None
            try:
                async for msg in query(prompt=phase_prompt, options=options):
                    self._record(msg, turns)
                    if isinstance(msg, ResultMessage):
                        text = msg.result
                        usage = msg.usage
                        break
            except Exception as e:
                error = str(e)

            phase_result = PhaseResult(phase=phase_name, text=text, turns=turns,
                                       usage=usage, error=error)
            phases.append(phase_result)
            self._dump_phase_log(workspace, phase_result)
            if error:
                break
            prev_text = text

        success = all(p.error is None for p in phases)
        # archive 由调用方决定时机；这里只组装结果
        return AgentRunResult(...)
```

### 5.2 WorkspaceManager 实现要点（v3 快照 + 锁）

```python
# scrivai/agent/workspace.py
import fcntl, shutil, subprocess, json, tarfile, time
from datetime import datetime, timezone
from pathlib import Path

class _WorkspaceManager:
    def __init__(self, workspaces_root, archives_root):
        self.workspaces_root = Path(workspaces_root)
        self.archives_root = Path(archives_root)
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.archives_root.mkdir(parents=True, exist_ok=True)

    def _git_hash(self, path: Path) -> str | None:
        try:
            r = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    def create(self, spec):
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
                    raise WorkspaceError(
                        f"workspace already exists: {root}; set WorkspaceSpec.force=True to overwrite"
                    )
                shutil.rmtree(root)

            working = root / "working"; data = root / "data"
            output = root / "output"; logs = root / "logs"
            for d in (working, data, output, logs):
                d.mkdir(parents=True, exist_ok=True)

            # 内容快照（v3：不再 symlink）
            claude_dir = working / ".claude"
            claude_dir.mkdir(exist_ok=True)
            src_skills = spec.project_root / "skills"
            if src_skills.exists():
                shutil.copytree(src_skills, claude_dir / "skills", symlinks=False)
            src_agents = spec.project_root / "agents"
            if src_agents.exists():
                shutil.copytree(src_agents, claude_dir / "agents", symlinks=False)

            # data_inputs 也复制（跨机归档可用）
            for name, src in spec.data_inputs.items():
                dst = data / name
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=False)
                else:
                    shutil.copy2(src, dst)

            # snapshot 元信息
            snapshot = WorkspaceSnapshot(
                skills_git_hash=self._git_hash(spec.project_root),
                agents_git_hash=self._git_hash(spec.project_root),
                snapshot_at=datetime.now(timezone.utc).isoformat(),
            )
            meta = {
                "run_id": spec.run_id,
                "created_at": snapshot.snapshot_at,
                "project_root": str(spec.project_root.resolve()),
                "data_inputs": {k: str(v) for k, v in spec.data_inputs.items()},
                "extra_env": spec.extra_env,
                "snapshot": snapshot.model_dump(),
            }
            (root / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2)
            )

            return WorkspaceHandle(
                run_id=spec.run_id, root=root, working_dir=working,
                data_dir=data, output_dir=output, logs_dir=logs,
                meta_path=root / "meta.json", snapshot=snapshot,
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            try: lock_path.unlink()
            except FileNotFoundError: pass

    def archive(self, handle, *, success):
        if success:
            archive_path = self.archives_root / f"{handle.run_id}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                # 完整可复现集：skills 快照 + data + output + logs + meta
                tar.add(handle.working_dir / ".claude", arcname="snapshot/.claude")
                tar.add(handle.data_dir, arcname="snapshot/data")
                tar.add(handle.output_dir, arcname="output")
                tar.add(handle.logs_dir, arcname="logs")
                tar.add(handle.meta_path, arcname="meta.json")
            shutil.rmtree(handle.root)
            return archive_path
        else:
            (handle.root / ".failed").write_text(
                datetime.now(timezone.utc).isoformat()
            )
            return handle.root

    def cleanup_old(self, days=30):
        cutoff = time.time() - days * 86400
        count = 0
        for p in self.archives_root.glob("*.tar.gz"):
            if p.stat().st_mtime < cutoff:
                p.unlink(); count += 1
        for failed_marker in self.workspaces_root.glob("*/.failed"):
            ws = failed_marker.parent
            if failed_marker.stat().st_mtime < cutoff:
                shutil.rmtree(ws); count += 1
        return count
```

### 5.3 Skills/Agents 装入：Snapshot 而非 Symlink（v3 变更）

**v2 做法（已废弃）**：symlink `project_root/skills → workspace/.claude/skills`
**v3 做法**：`shutil.copytree(symlinks=False)` 内容快照 + 记录 `skills_git_hash / agents_git_hash` 到 `meta.json`

**为什么改**：
- symlink 下，运行中若 main 分支被改（如合并 EvoSkill 候选）会**立刻污染**正在跑的 run
- symlink 归档后指向源路径，跨机失效，**无法复盘**
- 快照让每次运行获得瞬间的**不可变**依赖集

**代价**：
- 磁盘：每次快照 ~几 MB（skills + agents），可接受
- 创建速度：仍 P95 < 300ms

**好处**：
- 运行对源变更**免疫**
- 归档可跨机复盘
- EvoSkill 合并 main 分支**不污染**运行中的 run
- `meta.json.snapshot` 可追溯使用的是哪个 git hash 的 skill

## 6. 与 GovDoc / qmd 的协调点

### 6.1 GovDoc 怎么用 Scrivai

```python
# 业务层（GovDoc-Auditor）伪代码 — v3
from scrivai import (
    ModelConfig, WorkspaceSpec,   # pydantic（从 Scrivai 统一导入）
    build_agent_session, build_workspace_manager,
    build_qmd_client_from_config,   # v3：业务层不直接 import qmd
    build_libraries,
    load_agent_profile,             # from scrivai.agent.profile re-export
)

qmd = build_qmd_client_from_config(cfg.qmd.db_path)   # ← 不再 qmd.connect
rules, cases, templates = build_libraries(qmd)

# 业务 agent 在 GovDoc/agents/gov-auditor.yaml
agent = load_agent_profile(Path("GovDoc-Auditor/agents/gov-auditor.yaml"))
model = ModelConfig(model="claude-sonnet-4-6", api_key=os.environ["ANTHROPIC_API_KEY"])

ws_mgr = build_workspace_manager()
workspace = ws_mgr.create(WorkspaceSpec(
    run_id=audit_run.id,
    project_root=Path("GovDoc-Auditor"),  # ← 含业务 skills/ 和 agents/
    data_inputs={
        "tender.md": Path("/data/storage/tender_<id>.md"),
        "checkpoints.json": Path("/data/storage/checkpoints_<id>.json"),
    },
    extra_env={"GOVDOC_DB_PATH": "/data/app.sqlite"},
))

session = build_agent_session()
result = await session.run(
    agent=agent,
    model=model,
    workspace=workspace,
    task_prompt="审核 tender.md 中的资格要求和评分办法，针对 checkpoints.json 中的所有审核点。"
                "summarize 阶段输出符合 GovFinding 列表的 JSON。",
)

# 业务层归档
ws_mgr.archive(workspace, success=result.success)
# result.final_output 是 summarize 阶段的 JSON，业务层解析并落 app.sqlite
```

注意：业务的 `gov-auditor.yaml` 完整地继承了 `Scrivai/agents/auditor.yaml` 的字段语义（同 schema），但 prompt_text 是业务专用的。Scrivai 不强制业务层用通用 agent，业务可以自由覆盖。

### 6.2 GovDoc 不应做的

- 不直接 `import claude_agent_sdk`（通过 Scrivai.agent）
- 不直接管理 workspace 目录（通过 Scrivai.WorkspaceManager）
- 不修改 Scrivai 源码塞业务 prompt
- 不跨过 AgentSession 直接调底层 SDK

### 6.3 变更流程

如需新增 PhaseConfig 字段、新通用 skill、新 CLI 命令——走 PLAN §8 流程。

## 7. 硬切换：Deprecation Target

旧 API 在 M0 末删除，无过渡：

| 旧符号 | 处理 |
|---|---|
| `scrivai.LLMClient / LLMConfig / LLMMessage / LLMResponse / LLMUsage` | 整体删除 |
| `scrivai.PromptTemplate / FewShotTemplate` | 删除（system prompt 拼接由 PESRunner 做） |
| `scrivai.OutputParser / JsonOutputParser / PydanticOutputParser / RetryingParser` | 删除（结构化输出靠 summarize 阶段的 prompt 约束 + 业务层 schema 校验） |
| `scrivai.ExtractChain / AuditChain / GenerateChain` 及其 Input/Output | 删除（替换为 AgentSession + 业务 agent） |
| `scrivai.Project / ProjectConfig / KnowledgeStore / AuditEngine / GenerationEngine / GenerationContext` | 删除（旧版本残留） |
| `scrivai.testing.MockLLMClient` | 改为 `MockAgentSession` |

M3 验收：

```bash
cd /home/iomgaa/Projects/Scrivai
for sym in LLMClient LLMConfig LLMMessage LLMResponse PromptTemplate FewShotTemplate \
           OutputParser PydanticOutputParser JsonOutputParser RetryingParser \
           ExtractChain AuditChain GenerateChain Project ProjectConfig \
           KnowledgeStore AuditEngine GenerationEngine; do
  if git grep -q "\\b$sym\\b" -- 'scrivai/**/*.py'; then
    echo "FAIL: $sym still present"; exit 1
  fi
done
echo "OK: all deprecated symbols removed"
```

另外 `grep -rE "(招标|政府采购|审核点|底稿|投标人)" scrivai/` 必须零结果。

## 8. 配置（YAML）

业务层传给 Scrivai 的 `scrivai.yaml`（示例）：

```yaml
model:
  model: claude-sonnet-4-6
  base_url: https://api.anthropic.com   # 或 GLM/MiniMax 的兼容端点
  api_key: ${ANTHROPIC_API_KEY}
  fallback_model: claude-haiku-4-5

qmd:
  db_path: ./data/qmd.sqlite

workspace:
  workspaces_root: ~/.govdoc/workspaces
  archives_root: ~/.govdoc/archives
  cleanup_days: 30

evolution:
  enabled: false       # M2 才打开
  proposer_model: claude-sonnet-4-6
  frontier_size: 5
```

## 9. 非目标（YAGNI）

- 流式输出（SDK 的中间消息可用于日志，但对外不暴露 stream API）
- 多 agent 互相调用（MVP 单 agent + PES）
- 跨进程任务调度（业务层用 FastAPI BackgroundTasks 即可）
- prompt 版本管理（EvoSkill 的 git 分支已是事实版本管理）
- 多模态 prompt
- Windows 支持
- 自动合并 EvoSkill 候选到 main（必须人工 PR）

## 10. 性能目标（M2）

- PES 三阶段端到端（含 LLM 调用）：审核 10 个 checkpoint × 100 页文书 ≤ 10 分钟
- WorkspaceManager.create P95 < 100ms
- WorkspaceManager.archive P95 < 5s（含 tar.gz）
- scrivai-cli 命令冷启动 P50 < 300ms

---

详细任务分解见 `TD.md`。
