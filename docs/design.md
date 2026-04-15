# Scrivai 设计文档

**日期**: 2026-04-15
**项目**: Scrivai
**本项目在系统中的定位**: 文档审核 / 生成的 **Claude Agent 编排框架**

> 本文档是 Scrivai 在 GovDoc 三项目体系中的设计。顶层计划见 `/home/iomgaa/Projects/GOVDOC_PROGRAM_PLAN.md`。
> 范式更新（2026-04-15）：从 LLMClient + Chain 切换为 Claude Agent SDK + Workspace + PES + Skill。

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

```python
# scrivai.agent
from pathlib import Path
from typing import Any, Literal, Protocol
from datetime import datetime
from pydantic import BaseModel

class ModelConfig(BaseModel):
    model: str                          # "claude-sonnet-4-6" / "glm-5.1" / "minimax-2.7"
    base_url: str | None = None
    api_key: str | None = None
    fallback_model: str | None = None

class PhaseConfig(BaseModel):
    name: Literal["plan", "execute", "summarize"]
    max_turns: int
    allowed_tools: list[str]            # ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"]
    permission_mode: Literal["bypassPermissions", "acceptEdits", "ask"] = "bypassPermissions"
    additional_system_prompt: str = ""

class AgentProfile(BaseModel):
    name: str
    display_name: str
    prompt_text: str                    # base system prompt
    phases: dict[str, PhaseConfig]      # 必含 "plan", "execute", "summarize"
    skills_required: list[str] = []     # skill 名称列表（用于校验 workspace 中是否存在）

class WorkspaceSpec(BaseModel):
    run_id: str
    project_root: Path                  # 业务项目根（必须含 skills/、agents/）
    data_inputs: dict[str, Path]        # 名字 → 源路径（symlink 到 workspace/data/）
    extra_env: dict[str, str] = {}

class WorkspaceHandle(BaseModel):
    run_id: str
    root: Path
    working_dir: Path                   # = root / "working"
    data_dir: Path                      # = root / "data"
    output_dir: Path                    # = root / "output"
    logs_dir: Path                      # = root / "logs"
    meta_path: Path                     # = root / "meta.json"

class WorkspaceManager(Protocol):
    def create(self, spec: WorkspaceSpec) -> WorkspaceHandle: ...
    def archive(self, handle: WorkspaceHandle, *, success: bool) -> Path: ...
    def cleanup_old(self, days: int = 30) -> int: ...

class PhaseResult(BaseModel):
    phase: Literal["plan", "execute", "summarize"]
    text: str
    turns: list[dict]                   # 完整 trajectory（含 tool_calls + tool_results）
    usage: dict
    error: str | None = None

class AgentRunResult(BaseModel):
    run_id: str
    workspace_archive_path: Path | None
    workspace_failed_path: Path | None
    phases: list[PhaseResult]
    final_output: str                   # = phases[-1].text
    success: bool
    total_usage: dict

class AgentSession(Protocol):
    async def run(
        self,
        *,
        agent: AgentProfile,
        model: ModelConfig,
        workspace: WorkspaceHandle,
        task_prompt: str,
        phase_inputs: dict[str, dict] = {},
    ) -> AgentRunResult: ...

def build_agent_session() -> AgentSession: ...
def build_workspace_manager(workspaces_root: Path | None = None,
                            archives_root: Path | None = None) -> WorkspaceManager: ...
```

### 4.2 Knowledge 层（Python API + CLI 包装）

```python
# scrivai.knowledge
from pydantic import BaseModel
from typing import Protocol
from qmd import QmdClient, SearchResult

class LibraryEntry(BaseModel):
    entry_id: str
    title: str
    source_path: str
    markdown_path: str
    metadata: dict = {}

class Library(Protocol):
    collection_name: str
    def add(self, entry_id: str, markdown: str, metadata: dict | None = None,
            *, source_path: str | None = None, title: str | None = None) -> LibraryEntry: ...
    def get(self, entry_id: str) -> LibraryEntry: ...
    def list(self, filters: dict | None = None) -> list[LibraryEntry]: ...
    def delete(self, entry_id: str) -> None: ...
    def search(self, query: str, *, top_k: int = 5,
               filters: dict | None = None) -> list[SearchResult]: ...

class RuleLibrary(Library): ...
class CaseLibrary(Library): ...
class TemplateLibrary(Library): ...

def build_libraries(qmd_client: QmdClient) -> tuple[RuleLibrary, CaseLibrary, TemplateLibrary]: ...
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

Scrivai 提供三个**通用 skill**，作为业务层 skill 的"基类"。业务层可在自己的 skills/ 里**同名覆盖**或**追加新 skill**。

```
Scrivai/skills/
├── search-knowledge/
│   ├── SKILL.md
│   └── (assets/)
├── inspect-document/
│   └── SKILL.md
└── render-output/
    └── SKILL.md
```

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
    allowed_tools: ["Bash", "Read", "Write", "Glob"]
    additional_system_prompt: |
      Read all working/findings/*.md, compile into a single JSON object
      matching the schema given in task_prompt. Write to working/output.json
      and respond with the JSON content as your final message.

skills_required:
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

class Evaluator(Protocol):
    def evaluate(self, run_result: AgentRunResult, golden: dict) -> float: ...

class EvolutionConfig(BaseModel):
    project_root: Path
    skills_dir: Path                    # 默认 project_root / "skills"
    eval_dataset_path: Path             # JSON: list[{"task": ..., "golden": ...}]
    base_branch: str = "main"
    frontier_size: int = 5
    proposer_model: ModelConfig

class EvolutionRun(BaseModel):
    started_at: datetime
    base_skill_hash: str
    candidates: list[dict]              # [{"branch": "evo/...", "score": 0.87, "diff": "..."}]
    promoted_branch: str | None         # 最高分超过 base 的候选分支名（建议人工 PR 合并）

def run_evolution(config: EvolutionConfig, evaluator: Evaluator) -> EvolutionRun: ...
```

**进化机制（5 阶段，参考 EvoSkill 论文）**：
1. **Base run**：当前 main 上的 skill 跑 eval_dataset，记录每条任务的 trajectory + score
2. **Proposer**：proposer_model 分析失败/低分 trajectory，提议对哪些 SKILL.md 做什么修改
3. **Generator**：把每个提议生成具体的 SKILL.md 修改，写到 git 分支 `evo/<timestamp>-<idx>`
4. **Evaluator**：每个分支跑评测集 → 业务层提供的 `Evaluator.evaluate` 打分
5. **Frontier**：留 top-N 分支；若最高分 > base 则在 `promoted_branch` 给出建议合并的分支名

**安全性**：进化产物**永远不直接覆盖 main**；只到 git 分支。人工审核 + PR + 跑回归测试后才合并到 main。

## 5. 内部架构

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
│   ├── design.md
│   └── TD.md
└── pyproject.toml
```

### 5.1 AgentSession 实现要点

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

### 5.2 WorkspaceManager 实现要点

```python
# scrivai/agent/workspace.py（伪代码）
class _WorkspaceManager:
    def create(self, spec):
        root = self.workspaces_root / spec.run_id
        working = root / "working"
        data = root / "data"
        output = root / "output"
        logs = root / "logs"

        for d in (working, data, output, logs):
            d.mkdir(parents=True, exist_ok=True)

        # symlink skills 和 agents 到 working/.claude/
        claude_dir = working / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / "skills").symlink_to(spec.project_root / "skills",
                                           target_is_directory=True)
        if (spec.project_root / "agents").exists():
            (claude_dir / "agents").symlink_to(spec.project_root / "agents",
                                               target_is_directory=True)

        # symlink data_inputs
        for name, src in spec.data_inputs.items():
            (data / name).symlink_to(src.resolve())

        # 写 meta.json
        meta = {
            "run_id": spec.run_id,
            "created_at": datetime.utcnow().isoformat(),
            "project_root": str(spec.project_root.resolve()),
            "data_inputs": {k: str(v) for k, v in spec.data_inputs.items()},
            "extra_env": spec.extra_env,
        }
        (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

        return WorkspaceHandle(...)

    def archive(self, handle, *, success):
        if success:
            archive_path = self.archives_root / f"{handle.run_id}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(handle.output_dir, arcname="output")
                tar.add(handle.logs_dir, arcname="logs")
                tar.add(handle.meta_path, arcname="meta.json")
            shutil.rmtree(handle.root)
            return archive_path
        else:
            (handle.root / ".failed").write_text(datetime.utcnow().isoformat())
            return handle.root

    def cleanup_old(self, days=30):
        cutoff = time.time() - days * 86400
        count = 0
        for p in self.archives_root.glob("*.tar.gz"):
            if p.stat().st_mtime < cutoff:
                p.unlink(); count += 1
        for p in self.workspaces_root.glob("*/.failed"):
            ws = p.parent
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(ws); count += 1
        return count
```

### 5.3 Skills/Agents 装入：Symlink 而非 Copy

**理由**：业务侧的 skills/ 是"长期沉淀的资产"，会被 EvoSkill 不断进化；workspace 用 symlink 让每次运行自动看到最新版本，进化成果可累计。EvoSkill 的进化候选写到 git 分支（不直接改 main 上的文件），所以不会污染运行中的 workspace（运行中读的是 main 分支的文件）。

注意事项：
- `WorkspaceManager.create` 必须用绝对路径 symlink（`src.resolve()`），避免 cwd 变化导致悬空
- Windows 上 symlink 受限 → MVP 只支持 Linux/macOS

## 6. 与 GovDoc / qmd 的协调点

### 6.1 GovDoc 怎么用 Scrivai

```python
# 业务层（GovDoc-Auditor）伪代码
from scrivai.agent import (
    build_agent_session, build_workspace_manager,
    AgentProfile, ModelConfig, WorkspaceSpec,
)
from scrivai.agent.profile import load_agent_profile

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
