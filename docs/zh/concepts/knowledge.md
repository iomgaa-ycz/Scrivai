<!-- This is a Chinese translation of docs/concepts/knowledge.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 知识检索

Scrivai 提供三种一等库类型，用于向 PES 运行注入领域知识。三者均以 `qmd` 语义检索引擎为底层支撑。

## 库类型

| 类型 | 类 | 用途 |
|---|---|---|
| **规则（Rules）** | `RuleLibrary` | 审核标准、约束条件和合规要求 |
| **案例（Cases）** | `CaseLibrary` | 参考示例（少样本演示、先例） |
| **模板（Templates）** | `TemplateLibrary` | 包含 `{{variable}}` 占位符的文档模板 |

## 通过 `build_libraries` 初始化

推荐使用 `build_libraries` 一次性初始化全部三个库，它从配置字典中读取集合路径：

```python
from scrivai import build_libraries, build_qmd_client_from_config

# Build the qmd client from project config
qmd_client = build_qmd_client_from_config(
    config={"embedding_model": "text-embedding-3-small"}
)

# Build all three libraries
rule_lib, case_lib, template_lib = build_libraries(
    qmd_client=qmd_client,
    rules_path="knowledge/rules/",
    cases_path="knowledge/cases/",
    templates_path="knowledge/templates/",
)
```

## 搜索接口

每个库暴露 `.search(query, top_k)` 方法，返回语义排序后的结果：

```python
# Find the most relevant audit rules for a query
results = rule_lib.search("financial disclosure requirements", top_k=5)
for result in results:
    print(result.chunk_text)
    print(result.score)

# Find reference cases
cases = case_lib.search("contract termination clause", top_k=3)

# Find a matching template
templates = template_lib.search("engineering inspection report", top_k=1)
```

## 向 PES 注入知识

将搜索结果传入 `runtime_context`，PES 即可在系统提示词中使用它们：

```python
rules = rule_lib.search("safety compliance", top_k=5)
result = pes.run(
    runtime_context={
        "document_text": document,
        "applicable_rules": [r.chunk_text for r in rules],
    }
)
```

## 另请参阅

- [API 参考：Knowledge](../../api/knowledge.md)
