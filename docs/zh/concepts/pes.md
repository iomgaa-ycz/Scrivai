<!-- This is a Chinese translation of docs/concepts/pes.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# PES 引擎

**PES**（Plan–Execute–Summarize）是 Scrivai 的核心抽象。每次与 LLM 的交互都被封装在一个 PES 中，强制执行确定性的三阶段生命周期。

## 三阶段

| 阶段 | 用途 | 输出 |
|---|---|---|
| **计划（Plan）** | LLM 读取系统提示词和运行时上下文，生成逐步计划。 | 包含计划文本的 `PhaseResult` |
| **执行（Execute）** | LLM 按计划执行，可选地在多轮对话中使用工具。 | 包含所有轮次的 `PhaseResult` |
| **摘要（Summarize）** | LLM 将执行轨迹提炼为简洁、结构化的最终输出。 | 包含结构化输出的 `PhaseResult` |

三个阶段分别对应 `PESRun.phases[0]`、`phases[1]` 和 `phases[2]`。

## 文件契约

每个预置 PES 规定了它从 `runtime_context` 中读取哪些键，以及向 `output` 写入什么内容。这些契约在运行时强制执行。

### ExtractorPES

从文档中提取结构化字段。

| `runtime_context` 键 | 类型 | 说明 |
|---|---|---|
| `document_text` | `str` | 待提取的原始文本 |
| `extraction_schema` | `dict` | 字段名到期望类型的映射 |

输出：与 `extraction_schema` 匹配的 `dict`。

### AuditorPES

按照一组规则审核文档，输出发现结果。

| `runtime_context` 键 | 类型 | 说明 |
|---|---|---|
| `document_text` | `str` | 待审核的文档 |
| `rules` | `list[str]` | 以纯文本形式表示的审核标准 |

输出：包含 `findings`（列表）和 `verdict`（字符串）键的 `dict`。

### GeneratorPES

根据模板和输入变量生成文档。

| `runtime_context` 键 | 类型 | 说明 |
|---|---|---|
| `template` | `str` | 包含 `{{variable}}` 占位符的 Markdown 模板 |
| `inputs` | `dict` | 替换到模板中的值 |

输出：渲染后的文档字符串（`str`）。

## 自定义 PES

要创建自定义 PES，继承 `BasePES` 并实现 `_build_plan_prompt` 和 `_parse_output`：

```python
from scrivai.pes.base import BasePES
from scrivai import PESConfig, ModelConfig, PhaseConfig

class TranslatorPES(BasePES):
    """Translate a document from one language to another."""

    def _build_plan_prompt(self, runtime_context: dict) -> str:
        src = runtime_context["source_language"]
        tgt = runtime_context["target_language"]
        return f"Translate the following text from {src} to {tgt}."

    def _parse_output(self, raw: str) -> str:
        return raw.strip()


config = PESConfig(
    name="translator",
    model=ModelConfig(model="claude-sonnet-4-20250514"),
    phases=[
        PhaseConfig(name="plan"),
        PhaseConfig(name="execute"),
        PhaseConfig(name="summarize"),
    ],
)

pes = TranslatorPES(config=config)
result = pes.run(
    runtime_context={
        "document_text": "Hello, world!",
        "source_language": "English",
        "target_language": "Spanish",
    }
)
print(result.output)  # 'Hola, mundo!'
```

## 另请参阅

- [API 参考：PES](../api/pes.md)
- [模型：PESConfig、PhaseConfig、PESRun](../api/models.md)
