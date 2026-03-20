# Scrivai SDK 设计

> **定位**：工具库，硕士同学基于此构建具体项目  
> **原则**：原子化 · 低封装 · 可组合 · MVP

---

## 1. 模块总览

| 模块 | 核心类/函数 | 说明 |
|------|------------|------|
| LLM | `LLMClient` | litellm 薄封装 |
| 知识库 | `KnowledgeStore` | qmd 封装，统一管理案例/规则 |
| 切片 | `split_by_heading()`, `split_by_clause()` | 入库预处理 |
| 生成 | `GenerationEngine`, `GenerationContext` | 单章生成 + 上下文工具 |
| 审核 | `AuditEngine` | 单/批量审核 |
| 入口 | `Project` | 极简配置加载 |
| 文档预处理 | `DocPipeline`, `OCRAdapter` | PDF → Markdown（旁路工具） |

**不包含**：Orchestrator（用户自己写循环）、Agent 框架（流程确定不需要）、CLI（MVP 阶段不做）

---

## 2. API 详解

### 2.1 LLMClient

```python
client = LLMClient(config)
client.chat(messages)                     # → str
client.chat_with_template(template, vars)  # → str (Jinja2 + LLM)
```

---

### 2.2 KnowledgeStore

**统一知识库**：不区分子库，用 `metadata["type"]` 区分案例/规则。

```python
store = KnowledgeStore(db_path, namespace)

# 入库
store.add(texts=[...], metadatas=[{...}])
store.add_from_directory(path, pattern, metadata)

# 检索
store.search(query, top_k, filters)  # → list[SearchResult]
# filters 示例: {"type": "rule", "status": "active"}

# 管理
store.count(filters)
store.delete(filters)  # filters 必填
```

**SearchResult**: `content`, `metadata`, `score`

**namespace**: 物理隔离，不存在则自动创建

---

### 2.3 切片工具

```python
# 按标题切（案例文档）
split_by_heading(text, level=2)  # → list[Chunk]

# 按条款切（规章制度）
split_by_clause(text, pattern)   # → list[Chunk]
# pattern: 正则，默认匹配 "第X条" / "X.X.X"
# Chunk: text + metadata (含 clause_id, heading, index)
```

---

### 2.4 GenerationEngine

**单章生成**：
```python
gen = GenerationEngine(llm, store=None)  # store 可选
gen.generate_chapter(template, variables)  # → str
# variables: user_inputs, retrieved_cases, previous_summary, glossary
```

**参数说明**：
- `llm`: LLMClient 实例（必传）
- `store`: KnowledgeStore 实例（可选，传 None 时不进行案例检索）

**上下文工具**（独立可用）：
```python
ctx = GenerationContext(llm)
ctx.summarize(text)                    # → str (前文摘要)
ctx.extract_terms(text, existing)      # → dict[str, str] (术语表)
ctx.extract_references(text)           # → list[dict] (交叉引用)
```

**典型用法**：
```python
# 方式一：通过 Project 入口（推荐）
proj = Project("config.yaml")
glossary, summary = {}, ""
for ch in chapters:
    cases = proj.store.search(ch.topic, top_k=3) if proj.store else []
    text = proj.gen.generate_chapter(ch.tpl, {"user_inputs": i, "retrieved_cases": cases, "previous_summary": summary, "glossary": glossary})
    summary = proj.ctx.summarize(text)
    glossary = proj.ctx.extract_terms(text, glossary)

# 方式二：直接实例化各组件
ctx = GenerationContext(llm)
glossary, summary = {}, ""
for ch in chapters:
    cases = store.search(ch.topic, top_k=3)
    text = gen.generate_chapter(ch.tpl, {"user_inputs": i, "retrieved_cases": cases, "previous_summary": summary, "glossary": glossary})
    summary = ctx.summarize(text)
    glossary = ctx.extract_terms(text, glossary)
```

---

### 2.5 AuditEngine

**AuditResult**: `passed`, `severity`, `checkpoint_id`, `chapter_id`, `finding`, `evidence`, `suggestion`

**单要点审核**：
```python
audit = AuditEngine(llm, store)
audit.check_one(doc, checkpoint)  # → AuditResult
# checkpoint: id, description, severity, scope, prompt_template, rule_refs
# scope: "full" | "chapter:ch03"
# rule_refs: [{"source": "X", "clause_id": "Y"} | {"query": "..."}]
```

**批量审核**：
```python
audit.check_many(doc, checkpoints)     # → list[AuditResult]
audit.load_checkpoints(path)          # 从 YAML 加载
```

**四维检查处理**：统一走 `check_one()`，差异在 checkpoint 配置（prompt + rule_refs）

---

### 2.6 Project

极简入口：配置加载 + 组件组装

```python
proj = Project("config.yaml")
proj.llm      # LLMClient
proj.store    # KnowledgeStore | None
proj.gen      # GenerationEngine
proj.ctx      # GenerationContext（独立组件）
proj.audit    # AuditEngine
```

**属性说明**：
| 属性 | 类型 | 说明 |
|------|------|------|
| `llm` | LLMClient | LLM 调用客户端 |
| `store` | KnowledgeStore \| None | 知识库实例（配置中未指定则不初始化） |
| `gen` | GenerationEngine | 章节生成引擎 |
| `ctx` | GenerationContext | 上下文工具（摘要、术语、引用提取） |
| `audit` | AuditEngine | 文档审核引擎 |

---

## 3. 文件结构

```
core/
├── llm.py              # LLMClient
├── knowledge/          # 知识库子包
│   ├── __init__.py     # 导出 KnowledgeStore, SearchResult
│   └── store.py        # KnowledgeStore 实现
├── chunkers.py         # split_by_heading, split_by_clause
├── generation/
│   ├── __init__.py     # 导出 GenerationEngine, GenerationContext
│   ├── engine.py       # GenerationEngine
│   └── context.py      # GenerationContext
├── audit/
│   ├── __init__.py     # 导出 AuditEngine, AuditResult
│   └── engine.py       # AuditEngine, AuditResult
└── project.py          # Project
utils/
├── __init__.py
└── doc_pipeline.py     # OCRAdapter, MonkeyOCRAdapter, DoclingAdapter,
                        # MarkdownCleaner, DocPipeline, DocPipelineResult
templates/
└── prompts/            # Prompt 模板（j2 + md 分离）
    ├── base.j2         # 基础骨架
    ├── summarize.j2 / summarize.md
    ├── extract_terms.j2 / extract_terms.md
    ├── extract_references.j2 / extract_references.md
    ├── audit.j2 / audit.md
    └── clean.j2 / clean.md
```

---

## 4. Doc Pipeline（文档预处理）

**定位**：旁路工具，独立于主引擎，用于将 PDF 转换为 Markdown 后入库。

### 4.1 OCRAdapter

抽象基类，统一两种 OCR 后端接口。两个实现均只接受 PDF，传入非 PDF 文件时抛 `ValueError`。

```python
class OCRAdapter(ABC):
    def to_markdown(self, file_path: str) -> str
    # 输入：本地 PDF 文件路径
    # 输出：原始 Markdown（未清洗）
    # 非 PDF 文件抛 ValueError

class MonkeyOCRAdapter(OCRAdapter):
    def __init__(self, base_url: str, timeout: int = 120)
    def to_markdown(self, file_path: str) -> str
    # 实现：POST /parse 上传 PDF → 下载 ZIP → 提取 .md

class DoclingAdapter(OCRAdapter):
    def __init__(self)
    def to_markdown(self, file_path: str) -> str
    # 实现：DocumentConverter().convert(path) → document.export_to_markdown()
```

### 4.2 MarkdownCleaner

两阶段清洗，LLM 阶段可选。

```python
class MarkdownCleaner:
    def __init__(self, llm: Optional[LLMClient] = None)
    # llm 来自 core/llm.py，传 None 则跳过 LLM 清洗阶段

    def clean(self, text: str) -> str
    # Phase 1（正则）：水印、异常表格分隔行、残留 HTML 标签、LaTeX 符号 → Unicode
    # Phase 2（LLM）：分块 → 语义清洗 → 后处理；llm=None 时跳过
```

### 4.3 DocPipeline

组合 adapter + cleaner，对外暴露单一入口。

```python
@dataclass
class DocPipelineResult:
    raw_md: str          # OCR 原始输出
    cleaned_md: str      # 清洗后输出
    warnings: list[str]  # 验证警告（字数损失、幻觉短语、表格结构），空列表表示无问题
    # 调用方自行决定如何处理 warnings，Pipeline 本身不抛异常

class DocPipeline:
    def __init__(self, adapter: OCRAdapter, cleaner: MarkdownCleaner)
    def run(self, file_path: str) -> DocPipelineResult
```

### 4.4 典型用法

```python
from scrivai.llm import LLMClient
from utils.doc_pipeline import DoclingAdapter, MonkeyOCRAdapter, MarkdownCleaner, DocPipeline

# Docling（本地，无需服务）
pipeline = DocPipeline(DoclingAdapter(), MarkdownCleaner())
result = pipeline.run("path/to/doc.pdf")

# MonkeyOCR + LLM 清洗
llm = LLMClient(config)
pipeline = DocPipeline(MonkeyOCRAdapter("http://localhost:8080"), MarkdownCleaner(llm=llm))
result = pipeline.run("path/to/doc.pdf")

# 清洗后入库
if not result.warnings:
    store.add(texts=[result.cleaned_md], metadatas=[{"source": "doc.pdf", "type": "case"}])
```

---

## 5. 模板加载机制

SDK 内部使用 **j2 + md 分离模式** 管理 prompt 模板。

### 5.1 模板结构

每个 prompt 由两个文件组成：
- **`.j2` 文件**：Jinja2 骨架模板，包含 `{{ prompt_content }}` 变量
- **`.md` 文件**：实际的 prompt 指令内容

```
templates/prompts/
├── base.j2              # 基础骨架
├── summarize.j2         # 摘要骨架
├── summarize.md         # 摘要指令
└── ...
```

### 5.2 加载函数

```python
def _load_template(name: str) -> str:
    """加载 prompt 模板，将 .md 内容注入 .j2 骨架"""
    # 1. 读取 templates/prompts/{name}.j2
    # 2. 读取 templates/prompts/{name}.md
    # 3. 将 md 内容注入 j2 的 {{ prompt_content }} 变量
    # 4. 返回完整 prompt
```

### 5.3 使用示例

```python
# 内部调用（用户通常不需要直接使用）
from scrivai.llm import _load_template

prompt = _load_template("summarize")  # 加载 summarize.j2 + summarize.md
```

---

## 6. qmd 依赖

SDK 依赖 qmd 提供以下能力（如 qmd 尚未实现，需补充）：

| 能力 | 说明 |
|------|------|
| metadata 列 | documents 表加 `metadata TEXT` 存 JSON |
| 入库传 metadata | `index_document()` 接受 metadata 参数 |
| 过滤检索 | `search(filters)` 转为 `json_extract()` 条件 |
| 非文件入库 | 直接接收文本+元数据，不依赖磁盘文件 |
