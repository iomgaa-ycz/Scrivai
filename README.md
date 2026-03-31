# Scrivai

**可配置的通用文档生成与审核框架**

[![PyPI version](https://img.shields.io/pypi/v/scrivai.svg)](https://pypi.org/project/scrivai/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 概述

Scrivai 是一个 Python SDK，面向长文档自动化生成与审核场景。核心设计理念：

- **库优先**：作为工具库交付，用户 `import scrivai` 直接使用
- **原子化**：每个组件独立可用，不强制组合
- **可配置**：通过 YAML 配置文件接入不同项目，无需修改框架代码
- **MVP**：聚焦核心功能，避免过度工程

### 核心能力

| 能力 | 描述 |
|------|------|
| **文档生成** | 基于用户输入 + 历史案例库，按章节模板生成长文档，保障全文连贯 |
| **文档审核** | 基于规章制度/标准，逐要点审核文档合规性，输出结构化报告 |
| **知识检索** | 基于 qmd 的语义检索，统一管理案例/规则/模板 |
| **文档预处理** | PDF → Markdown 的 OCR 转换与清洗（旁路工具） |
| **Office 预处理** | Word → PDF 转换（可选旁路工具，依赖本机 LibreOffice） |



## 系统架构

```
┌─────────────────────────────┐
│      Project (入口)         │  ← 极简配置加载 + 组件组装
│   .llm / .store / .gen /    │
│   .ctx / .audit             │
└──────────────┬──────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
┌───────┴────┐  ┌────┴────────┐
│  生成引擎  │  │   审核引擎    │
│ Generation │  │    Audit     │
└───────┬────┘  └────┬────────┘
        │             │
┌───────┴───┐   ┌────┴───────┐
│ 上下文工具 │   │            │
│   Context │   │            │
└───────┬───┘   └────────────┘
        │
┌───────┴─────────────────────┐
│         LLM 调用层           │  ← litellm（支持多 Provider）
│        LLM Client           │
└──────────────┬──────────────┘
               │
┌──────────────┴──────────────┐
│         知识库               │  ← qmd 语义检索
│    Knowledge Store          │
└─────────────────────────────┘
```

## 安装

### 环境要求

- Python >= 3.11

### 从 PyPI 安装（推荐）

```bash
pip install scrivai
```

### 从源码安装（开发）

```bash
# 克隆仓库
git clone https://github.com/iomgaa/scrivai.git
cd scrivai

# 安装
pip install -e .

# 开发依赖
pip install -e ".[dev]"
```

### 配置 API Key

创建 `.env` 文件：

```bash
LLM_API_KEY=your_api_key_here
```

## 快速开始

### 1. 创建项目配置

```yaml
# my-project.yaml
llm:
  model: "deepseek/deepseek-chat"
  temperature: 0.7
  max_tokens: 4096

knowledge:
  db_path: "data/my-project.db"
  namespace: "my-project"
```

### 2. 使用 SDK

```python
import scrivai

# 初始化项目
project = scrivai.Project("my-project.yaml")

# === 文档生成 ===
# 准备模板和变量
template = """
## 工程概况

请根据以下信息撰写本章：

### 用户输入
{{ user_inputs | tojson }}

### 相关历史案例
{% for case in retrieved_cases %}
--- 案例 {{ loop.index }} ---
{{ case.content }}
{% endfor %}

### 前文摘要
{{ previous_summary }}

### 术语表
{{ glossary | tojson }}
"""

# 检索案例
cases = project.gen.retrieve_cases("变电站施工方案概况", top_k=3)

# 生成章节
chapter = project.gen.generate_chapter(template, {
    "user_inputs": {"工程名称": "XX变电站", "地点": "广东省"},
    "retrieved_cases": cases,
    "previous_summary": "",
    "glossary": {}
})

# === 长文档生成（多章节连贯）===
glossary, summary = {}, ""
for ch in chapters:
    cases = project.store.search(ch["topic"], top_k=3) if project.store else []
    text = project.gen.generate_chapter(ch["template"], {
        "user_inputs": inputs,
        "retrieved_cases": cases,
        "previous_summary": summary,
        "glossary": glossary
    })
    summary = project.ctx.summarize(text)
    glossary = project.ctx.extract_terms(text, glossary)

# === 文档审核 ===
# 定义审核要点
checkpoints = [
    {
        "id": "CP001",
        "description": "检查工程概况章节完整性",
        "severity": "error",
        "scope": "chapter:工程概况",
        "prompt_template": "检查该章节是否包含工程名称、地点、规模等必要信息",
        "rule_refs": [{"query": "施工方案编制要求"}]
    }
]

# 执行审核
results = project.audit.check_many(document_text, checkpoints)
for r in results:
    print(f"[{'✓' if r.passed else '✗'}] {r.checkpoint_id}: {r.finding}")
```

## 核心 API

### Project

统一入口，配置加载 + 组件组装。

```python
project = scrivai.Project("config.yaml")

project.llm      # LLMClient — LLM 调用客户端
project.store    # KnowledgeStore | None — 知识库实例
project.gen      # GenerationEngine — 章节生成引擎
project.ctx      # GenerationContext — 上下文工具
project.audit    # AuditEngine — 文档审核引擎
```

### GenerationEngine

单章生成（原子操作），多章编排由调用方负责。

```python
# 生成章节
text = project.gen.generate_chapter(template, variables)

# 检索案例（便捷方法）
cases = project.gen.retrieve_cases(query, top_k=5, filters={"type": "case"})
```

**模板变量**：

| 变量 | 类型 | 说明 |
|------|------|------|
| `user_inputs` | dict | 用户输入的变量 |
| `retrieved_cases` | list[SearchResult] | RAG 检索结果 |
| `previous_summary` | str | 前文摘要 |
| `glossary` | dict[str, str] | 术语表 |

### GenerationContext

上下文工具，保障长文档连贯性。

```python
# 生成前文摘要（压缩上下文）
summary = project.ctx.summarize(text)

# 提取术语并合并到术语表
glossary = project.ctx.extract_terms(text, existing_glossary)

# 提取交叉引用
refs = project.ctx.extract_references(text)
```

### AuditEngine

四维审核：结构合规、引用有效性、语义合规、内部一致性。

```python
# 单要点审核
result = project.audit.check_one(document, checkpoint)

# 批量审核
results = project.audit.check_many(document, checkpoints)

# 从 YAML 加载审核要点
checkpoints = project.audit.load_checkpoints("checkpoints.yaml")
```

**AuditResult**：

```python
@dataclass
class AuditResult:
    passed: bool              # 是否通过
    severity: str             # "error" | "warning" | "info"
    checkpoint_id: str        # 审核要点标识
    chapter_id: str | None    # 章节标识
    finding: str              # 审核发现
    evidence: str             # 支撑证据
    suggestion: str           # 修改建议
```

**Checkpoint 配置**：

```yaml
checkpoints:
  - id: "CP001"
    description: "检查工程概况完整性"
    severity: "error"
    scope: "chapter:工程概况"    # "full" | "chapter:xxx"
    prompt_template: "检查是否包含工程名称、地点、规模"
    rule_refs:                   # 支撑条文
      - source: "GB50150"
        clause_id: "3.2.1"
      - query: "施工方案编制要求"  # 语义查询
```

### KnowledgeStore

基于 qmd 的统一知识库，通过 `metadata["type"]` 区分案例/规则。

```python
# 入库
store.add(
    texts=["案例内容..."],
    metadatas=[{"type": "case", "source": "doc.pdf"}]
)

# 批量导入
store.add_from_directory(
    path="cases/",
    pattern="*.md",
    metadata={"type": "case"}
)

# 语义检索
results = store.search(query, top_k=5, filters={"type": "rule"})

# 统计与删除
count = store.count(filters={"type": "case"})
deleted = store.delete(filters={"source": "old_doc.pdf"})
```

### DocPipeline（旁路工具）

PDF → Markdown 转换与清洗。

```python
from utils.doc_pipeline import DoclingAdapter, MonkeyOCRAdapter, MarkdownCleaner, DocPipeline

# Docling（本地，无需服务）
pipeline = DocPipeline(DoclingAdapter(), MarkdownCleaner())
result = pipeline.run("document.pdf")

# MonkeyOCR + LLM 清洗
pipeline = DocPipeline(
    MonkeyOCRAdapter("http://localhost:8080"),
    MarkdownCleaner(llm=project.llm)
)
result = pipeline.run("document.pdf")

# 结果
print(result.raw_md)       # OCR 原始输出
print(result.cleaned_md)   # 清洗后输出
print(result.warnings)     # 验证警告
```
## Office 预处理工具

Scrivai 提供可选的 Office 文档预处理工具，供调用方在 PDF pipeline 前自行组合使用。

### Word → PDF

依赖本机安装 [LibreOffice](https://www.libreoffice.org/)（不作为 Python 包依赖）。

```bash
# Ubuntu/Debian
sudo apt install libreoffice

# macOS
brew install --cask libreoffice

# Windows
# 从 https://www.libreoffice.org/ 下载安装后，将 soffice.exe 所在目录加入 PATH，
# 或调用时通过 libreoffice_cmd 参数显式传入绝对路径。
```

最小调用示例：

```python
from scrivai.utils import convert_word_to_pdf_via_libreoffice

pdf_path = convert_word_to_pdf_via_libreoffice(
    input_path="documents/report.docx",
    output_path="output/report.pdf",
)
# 返回 Path 对象；传入 DocPipeline 时请用 str(pdf_path)
```

支持 `.doc` 和 `.docx` 输入；`output_path` 父目录不存在时自动创建。
若 LibreOffice 未安装或命令不在 PATH 中，抛出 `RuntimeError` 并给出明确提示。

### Word → Markdown（via Pandoc）

依赖本机安装 [Pandoc](https://pandoc.org/)（不作为 Python 包依赖），仅支持 `.docx` 输入。

```python
from scrivai.utils import convert_docx_to_markdown_via_pandoc

md_path = convert_docx_to_markdown_via_pandoc(
    input_path="documents/report.docx",
    output_path="output/report.md",
)
```
## 配置参考

### 完整配置示例

```yaml
# LLM 配置（必须）
llm:
  model: "deepseek/deepseek-chat"  # litellm 模型标识
  temperature: 0.7
  max_tokens: 4096
  api_base: null                   # 自定义 API 端点（可选）
  # api_key 从 .env 读取（LLM_API_KEY）

# 知识库配置（可选，设为 null 禁用）
knowledge:
  db_path: "data/scrivai.db"
  namespace: "default"

# 生成引擎配置（可选）
generation:
  templates_dir: "templates/chapters"

# 审核引擎配置（可选）
audit:
  checkpoints_path: "config/checkpoints.yaml"
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | API 密钥（优先） |
| `API_KEY` | API 密钥（备选） |

## 开发指南

### 代码质量

```bash
# Lint
ruff check . --fix

# Format
ruff format .

# 类型检查（可选）
mypy scrivai/
```

### 测试

```bash
# 单元测试
pytest tests/unit/ -v

# 集成测试（需要 API key）
pytest tests/integration/ -v

# E2E 测试
pytest tests/e2e/ -v

# 覆盖率
pytest tests/ --cov=scrivai --cov-report=term-missing
```

### 测试组织

```
tests/
├── unit/          # 单元测试（使用 mock）
├── integration/   # 集成测试（真实 API 调用）
└── e2e/           # 端到端测试
```

## 项目结构

```
Scrivai/
├── scrivai/                 # 核心模块
│   ├── __init__.py          # 统一导出
│   ├── llm.py               # LLMClient（litellm 薄封装）
│   ├── project.py           # Project 入口
│   ├── chunkers.py          # 文本切片工具
│   ├── knowledge/           # 知识库
│   │   ├── __init__.py
│   │   └── store.py         # KnowledgeStore（qmd 封装）
│   ├── generation/          # 生成引擎
│   │   ├── __init__.py
│   │   ├── engine.py        # GenerationEngine
│   │   └── context.py       # GenerationContext
│   └── audit/               # 审核引擎
│       ├── __init__.py
│       └── engine.py        # AuditEngine, AuditResult
├── utils/                   # 工具模块
│   └── doc_pipeline.py      # OCR + 清洗管道
├── templates/
│   └── prompts/             # Prompt 模板（j2 + md 分离）
│       ├── base.j2
│       ├── summarize.j2 / summarize.md
│       ├── extract_terms.j2 / extract_terms.md
│       ├── extract_references.j2 / extract_references.md
│       ├── audit.j2 / audit.md
│       └── clean.j2 / clean.md
├── examples/                # 示例配置
├── tests/                   # 测试
├── docs/                    # 文档
│   ├── architecture.md      # 架构设计
│   └── sdk_design.md        # SDK 详细设计
├── CLAUDE.md                # 开发规范
├── REVIEW_GUIDE.md          # 代码审查指南
├── pyproject.toml
└── README.md
```

## 文档

| 文档 | 说明 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统架构详解 |
| [docs/sdk_design.md](docs/sdk_design.md) | SDK API 详细设计 |
| [CLAUDE.md](CLAUDE.md) | 开发规范与 SOP |
| [REVIEW_GUIDE.md](REVIEW_GUIDE.md) | 代码审查指南 |

## 设计原则

### 不包含的内容

- **Orchestrator**：`GenerationEngine` + `AuditEngine` 原子接口已够用，用户自己写循环
- **Agent 框架**：流程确定，代码控制即可，不需要 LLM 自主决策
- **CLI**：MVP 阶段不做，SDK 做扎实后 CLI 是 thin wrapper

### 连贯性保障机制

长文档（8-10章）生成时，通过以下机制保证连贯：

1. **术语表**：每章生成后提取术语，合并到全局字典，后续章节注入
2. **前文摘要**：每章生成后压缩上下文为摘要，后续章节携带
3. **交叉引用追踪**：记录跨章节引用，后续章节引用时强制一致

## 许可证

MIT License
