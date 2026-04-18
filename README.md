# Scrivai

**Claude Agent SDK 文档编排框架 — 审核 / 生成 / 自我进化**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 是什么

Scrivai 是一个 Python 库,把 Claude Agent SDK 包成三阶段(plan → execute → summarize)
执行引擎 **PES**(Plan-Execute-Summarize),加上轨迹存储、Skill 自我进化、知识检索等
周边能力,面向长文档生成 + 审核场景。

**设计定位:** 通用库。业务方(如政府文书、技术报告等)通过继承 `BasePES` 或复用三个
预置 PES(`ExtractorPES / AuditorPES / GeneratorPES`)快速拼装流程,不强加业务结构。

## 核心能力

| 能力 | API | 说明 |
|------|-----|------|
| **三阶段执行引擎** | `BasePES` | plan / execute / summarize 强契约,每阶段有 file-contract 输出 |
| **文档抽取** | `ExtractorPES` | 结构化条目抽取(JSON schema 校验) |
| **文档审核** | `AuditorPES` | 对照 checkpoint 列表做逐条 verdict |
| **文档生成** | `GeneratorPES` | docxtpl 模板填充 + 可选 docx 渲染 |
| **轨迹存储** | `TrajectoryStore` | SQLite 记录每次 run / phase / feedback,支持进化查询 |
| **Skill 自进化** | `run_evolution / promote` | 自研进化循环:Proposer LLM 生成候选 → 真实 PES 重跑评估 → 专家 SDK 原子 promote |
| **知识检索** | `CaseLibrary / RuleLibrary / TemplateLibrary` | 基于 [qmd](https://pypi.org/project/qmd/) 的语义检索 |
| **IO 适配** | `DocxRenderer / doc_to_markdown / pdf_to_markdown` | 办公格式互转 |

## 安装

```bash
# 从源码(MVP 阶段,尚未发布 PyPI)
git clone https://github.com/iomgaa-ycz/Scrivai
cd Scrivai
conda create -n scrivai python=3.11 -y
conda activate scrivai
pip install -e ".[dev]"
```

### 配置网关

项目默认走私有网关 + GLM-5.1(通过 Claude Agent SDK 标准 env):

```bash
cp .env.example .env
# 编辑 .env,填入:
#   ANTHROPIC_BASE_URL=https://your-gateway.example.com
#   ANTHROPIC_AUTH_TOKEN=sk-...
#   SCRIVAI_DEFAULT_MODEL=glm-5.1
#   SCRIVAI_DEFAULT_PROVIDER=glm
```

多供应商切换(Claude / GLM / MiniMax)通过 `ModelConfig(base_url + model + api_key)` 在
代码层覆盖 env 即可。

## 快速开始(5 分钟)

三个 demo 端到端跑通,参考 [`examples/`](examples/):

```bash
python examples/01_audit_single_doc.py       # ~2-3 min — AuditorPES
python examples/02_generate_with_revision.py # ~1-2 min — GeneratorPES
python examples/03_evolve_skill_workflow.py  # ~3-5 min — Skill 进化
```

或最小代码:

```python
import asyncio
from pathlib import Path
from pydantic import BaseModel
from scrivai import (
    ExtractorPES,
    ModelConfig,
    WorkspaceSpec,
    build_workspace_manager,
    load_pes_config,
)


class Output(BaseModel):
    items: list[str]


async def main():
    ws_mgr = build_workspace_manager()
    ws = ws_mgr.create(WorkspaceSpec(run_id="demo", project_root=Path.cwd(), force=True))
    config = load_pes_config(Path("scrivai/agents/extractor.yaml"))

    pes = ExtractorPES(
        config=config,
        model=ModelConfig(model="glm-5.1", provider="glm"),
        workspace=ws,
        runtime_context={"output_schema": Output},
    )
    run = await pes.run("从 data/source.md 抽取主要条目")
    print(run.final_output)


asyncio.run(main())
```

## 核心概念

### PES(Plan-Execute-Summarize)

所有 Agent 执行单元都遵守三阶段:

```
┌──────┐      ┌────────┐      ┌───────────┐
│ plan │ ───▶ │execute │ ───▶ │ summarize │
└──────┘      └────────┘      └───────────┘
    │             │                 │
    ▼             ▼                 ▼
plan.json    findings/*.json    output.json
```

每阶段的 `required_outputs`(YAML 里定义)是 file-contract,框架在阶段结束自动校验;
校验失败自动触发阶段内重试(`max_retries`)。

### 三个预置 PES

| PES | runtime_context 必填 | output 约定 |
|-----|---------------------|-------------|
| `ExtractorPES` | `output_schema: type[BaseModel]` | `working/output.json` 符合 schema |
| `AuditorPES` | `output_schema`;`data/checkpoints.json` 预置 | `findings/` + `output.json`;每 cp 一 verdict |
| `GeneratorPES` | `template_path, context_schema`;`auto_render` 可选 | `output.json.context` 可喂给 docxtpl |

### 自研 Skill 进化(M2 新增)

```
┌─────────────────┐
│ TrajectoryStore │ ← feedback(草稿 vs 终稿)
└────────┬────────┘
         ▼
┌─────────────────┐   ┌──────────────┐
│ EvolutionTrigger│──▶│   Proposer   │ ← LLM N 候选
└─────────────────┘   └──────┬───────┘
                             ▼
                      ┌──────────────────┐
                      │CandidateEvaluator│ ← 真实 PES 重跑 hold_out
                      └──────┬───────────┘
                             ▼
                      ┌──────────────────┐
                      │ SkillVersionStore│ ← DAG + 评分
                      └──────┬───────────┘
                             ▼
                      专家 SDK 调用
                      promote(version_id)
                             ▼
                      skills/<skill>/ 原子替换
                      + backup
```

关键决策:
- **不自动 promote** — 专家审 diff + 跑业务回归后显式 `promote(version_id)` 才落地
- **业务层显式触发** `run_evolution()` — 不做后台定时
- **独立 `evolution.db`** — 和 `trajectory.db` 分离,查询清晰

见 [`examples/03_evolve_skill_workflow.py`](examples/03_evolve_skill_workflow.py) 端到端
demo 与 [`docs/design.md`](docs/design.md) §4.6 架构文档。

## 已知限制

v0.2.0 不包含:

- **并发隔离** — 同一 skill 不应被两个业务方同时跑 `run_evolution`(无文件锁)
- **观测指标** — LLM usage / duration / failure 未做 prometheus/otel 导出
- **自动触发** — `run_evolution` 需业务方显式调用;`promote` 需专家显式调用
- **DERIVED / CAPTURED 进化类型** — M2 仅实现 FIX 类型(针对失败样本改 SKILL.md);衍生新 skill / 从对话捕获 skill 未实现

上述均规划在未来版本(M3b+)。

## 项目结构

```
Scrivai/
├── scrivai/                 # 核心库
│   ├── pes/                 # BasePES + LLMClient + config 加载
│   ├── agents/              # 三个预置 PES + 对应 YAML
│   ├── evolution/           # M2 自研进化系统
│   ├── trajectory/          # TrajectoryStore + hook
│   ├── workspace/           # WorkspaceManager 沙箱
│   ├── knowledge/           # qmd 封装(Case / Rule / Template)
│   ├── io/                  # docx/pdf/md 互转
│   ├── models/              # pydantic 数据模型
│   └── testing/             # 测试工具(MockPES / FakeTrajectoryStore)
├── examples/                # 3 个端到端 demo
├── tests/                   # unit / contract / integration / e2e
├── docs/
│   ├── design.md            # 设计文档(权威)
│   ├── TD.md                # 任务分解与里程碑
│   └── superpowers/         # 规格与 plan
├── CLAUDE.md                # 代码规范与 SOP
├── CHANGELOG.md             # 发版记录
└── pyproject.toml
```

## 开发

```bash
# lint + format
ruff check . --fix
ruff format .

# 测试
conda run -n scrivai pytest tests/unit/ -v          # 纯 mock
conda run -n scrivai pytest tests/contract/ -v      # API 契约
conda run -n scrivai pytest tests/integration/ -v   # 真 API key

# 发版前 deprecation gate
bash scripts/verify_m3a_release.sh
```

pytest 陷阱:必须用 conda env 内的 pytest(shell 的 pytest 是 base conda),见
`CLAUDE.md`。

## 文档索引

| 文档 | 用途 |
|------|------|
| [`docs/design.md`](docs/design.md) | 完整架构 / 契约 / 模块依赖(权威) |
| [`docs/TD.md`](docs/TD.md) | M0-M3 任务分解与里程碑 |
| [`CLAUDE.md`](CLAUDE.md) | 开发 SOP / 代码规范 |
| [`CHANGELOG.md`](CHANGELOG.md) | 发版记录 |
| [`examples/README.md`](examples/README.md) | 三个 demo 的运行指引 |

## License

MIT
