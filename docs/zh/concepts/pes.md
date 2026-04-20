<!-- This is a Chinese translation of docs/concepts/pes.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# PES 引擎

**PES**（Plan–Execute–Summarize）是 Scrivai 的核心抽象。每次与 LLM 的交互都被封装在一个三阶段流水线中，并强制执行文件契约。

## 三阶段

| 阶段 | 用途 | 文件契约 |
|---|---|---|
| **计划（Plan）** | 读取输入，生成逐步计划 | `working/plan.md` + `working/plan.json` |
| **执行（Execute）** | 按计划执行，为每个条目生成发现结果 | `working/findings/<id>.json` |
| **摘要（Summarize）** | 将所有发现结果合并为单一结构化输出 | `working/output.json` |

阶段结果存储在 `PESRun.phase_results["plan"]`、`phase_results["execute"]` 和 `phase_results["summarize"]` 中。

## 配置

PES 行为由 YAML 配置文件定义，通过 `load_pes_config()` 加载：

```yaml
name: auditor
display_name: Auditor — Compliance Audit
prompt_text: |
  You are a compliance audit agent. ...
default_skills:
  - available-tools
phases:
  plan:
    allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    max_turns: 10
    max_retries: 1
    required_outputs: [plan.md, plan.json]
  execute:
    allowed_tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    max_turns: 25
    max_retries: 1
    required_outputs:
      - {path: "findings", min_files: 1, pattern: "*.json"}
  summarize:
    allowed_tools: ["Bash", "Read", "Write"]
    max_turns: 10
    max_retries: 1
    required_outputs: [output.json]
```

关键字段：

- `prompt_text` — 发送给 Agent SDK 的基础系统提示词
- `phases` — 包含三个 `PhaseConfig` 条目（plan/execute/summarize）的字典
- `external_cli_tools` — Agent 被允许执行的 Bash 命令（提示词级别约束）

## 提示词管理

自 v0.1.7 起，阶段特定的指令由 **Jinja2 模板**通过 `PromptManager` 管理。每个内置 PES 拥有 3 个模板（`{name}_{phase}.j2`），精确控制 Agent 看到的内容：

```
scrivai/pes/prompts/
├── prompt_spec.yaml          # Variable contracts per template
├── templates/                # Jinja2 templates
│   ├── auditor_plan.j2
│   ├── auditor_execute.j2
│   └── ...
└── fragments/                # Shared rules injected into all templates
    └── workspace_rules.md
```

模板仅引用它们需要的变量（例如 `{{ workspace.working_dir }}`）。内部路径如 `output_dir` 不会暴露给 Agent。

## 内置 PES 实现

### ExtractorPES

从文档中提取结构化数据。

| `runtime_context` 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `output_schema` | `type[BaseModel]` | 是 | 用于输出验证的 Pydantic 模型 |

文件契约：plan 阶段 → 包含 `items_to_extract` 列表的 `plan.json`；execute 阶段 → 每个条目对应 `findings/<id>.json`；summarize 阶段 → 根据 `output_schema` 验证的 `output.json`。

### AuditorPES

按照检查点清单审核文档。

| `runtime_context` 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `output_schema` | `type[BaseModel]` | 是 | 用于审核输出的 Pydantic 模型 |
| `verdict_levels` | `list[str]` | 否 | 默认值：`["合格", "不合格", "不适用", "需要澄清"]` |
| `evidence_required` | `bool` | 否 | 默认值：`True` |

前提条件：运行前需将 `data/checkpoints.json` 放入工作区。

### GeneratorPES

使用 LLM 收集的内容填充 docxtpl 模板。

| `runtime_context` 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `template_path` | `Path` | 是 | docxtpl `.docx` 模板的路径 |
| `context_schema` | `type[BaseModel]` | 是 | 用于模板上下文的 Pydantic 模型 |
| `auto_render` | `bool` | 否 | 若为 True，渲染 `output/final.docx` |

## 通过子类化创建自定义 PES

要创建自定义 PES，继承 `BasePES` 并重写扩展点：

```python
from pathlib import Path
from pydantic import BaseModel
from scrivai import (
    BasePES, ModelConfig, WorkspaceSpec,
    build_workspace_manager, load_pes_config,
)

class MyOutput(BaseModel):
    summary: str

class MyPES(BasePES):
    """Custom PES with additional execution context."""

    async def build_execution_context(self, phase, run):
        if phase == "plan":
            return {"custom_field": "injected into template context"}
        return {}

# 1. Create workspace
ws_mgr = build_workspace_manager()
spec = WorkspaceSpec(
    run_id="my-run-001",
    project_root=Path("/path/to/project"),
    data_inputs={"source.md": Path("/path/to/source.md")},
    extra_env={"MY_DB_PATH": "/data/my.db"},  # passed to Agent subprocess
)
ws = ws_mgr.create(spec)

# 2. Load config and run
config = load_pes_config(Path("my_pes.yaml"))
model = ModelConfig(model="claude-sonnet-4-20250514")
pes = MyPES(config=config, model=model, workspace=ws,
            runtime_context={"output_schema": MyOutput})
run = await pes.run("Process source.md and produce a summary")

print(run.status)        # "completed"
print(run.final_output)  # {"summary": "..."}
```

扩展点（按需重写）：

| 方法 | 用途 | 默认行为 |
|---|---|---|
| `build_execution_context()` | 向模板上下文注入额外变量 | 返回 `{}` |
| `build_phase_prompt()` | 完全控制提示词组装 | 委托给 `PromptManager` |
| `postprocess_phase_result()` | 在每个阶段后验证/转换 LLM 输出 | 无操作 |
| `validate_phase_outputs()` | 检查文件契约输出是否存在 | 验证 `required_outputs` |

## 另请参阅

- [API 参考：PES](../../api/pes.md)
- [模型：PESConfig、PhaseConfig、PESRun](../../api/models.md)
- [概念：工作区](workspace.md)
