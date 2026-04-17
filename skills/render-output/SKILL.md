---
name: render-output
description: |
  Use when you are constructing a context dictionary that will eventually be
  fed to docxtpl to render a final .docx report. Triggers any time the task is
  about template-driven document generation, especially in the summarize phase
  of a GeneratorPES, or whenever you see {{ placeholder }} markers in a template
  and need to know how to fill them.
---

# Render Output

When the task is to fill a docxtpl template with structured content, the
schema of the context dict is the contract between you (the agent) and
the template. Get this right or the renderer will silently produce empty
fields.

## When to use

- The task is to fill a template (`.docx` with `{{ ... }}` markers)
- You see `placeholders` keys in the phase context — those are the
  template variables you must supply
- You are writing `output.json` whose contents will be passed to a
  renderer downstream

## docxtpl context conventions

A typical template context looks like:

```json
{
  "project_name": "X变电站升级改造",
  "author": "张三",
  "sections": [
    { "title": "概述", "body": "..." },
    { "title": "范围", "body": "..." }
  ]
}
```

Rules:

- Top-level keys map to `{{ key }}` placeholders in the template
- Lists map to `{% for item in items %}...{% endfor %}` loops; each item
  is a dict whose keys are then accessed inside the loop body
- Plain strings are inserted as text — markdown formatting in them is
  **not** interpreted by docxtpl

## Why this matters

docxtpl silently renders missing keys as empty strings — there is no
"key not found" error at render time. The only way to catch a mismatch
is to verify your context dict covers exactly the placeholders the
template advertises (run `scrivai-cli io render` outside of an agent run
if you want to test interactively).

## Tips

- If the template has a placeholder you do not have data for, write
  `null` or `""` rather than omitting the key — makes the gap visible
  in the rendered output instead of producing an empty section that
  looks intentional
- Avoid putting complex markdown (headings, tables) inside placeholder
  values; build the structure in the template, not the data

## Examples

### Example 1 — 最简占位符填充(plan.json 阶段)

假设 template 含 `{{ project_name }}` 和 `{{ report_date }}`:

```json
{
  "fills": [
    {"placeholder": "project_name", "source": "data/guide.md '# Project' 一节"},
    {"placeholder": "report_date",  "source": "任务生成日期"}
  ]
}
```

### Example 2 — 循环块的 context 形状(execute.findings/*.json)

若 template 含 `{% for item in items %}{{ item.name }}{% endfor %}`:

```json
{
  "placeholder": "items",
  "content": [
    {"name": "alpha", "verdict": "合格"},
    {"name": "beta",  "verdict": "不合格"}
  ],
  "source_refs": [{"chunk_id": "case-2025-014::chunk-0", "quote": "…"}]
}
```

`content` 是 list,docxtpl 会迭代渲染每一项。

### Example 3 — 多段式 output.json(summarize 阶段)

```json
{
  "context": {
    "project_name": "XX 220kV 变电站大修",
    "report_date": "2026-04-17",
    "audit_summary": "共 10 项,合格 7、不合格 2、需要澄清 1。…"
  },
  "sections": [
    {"placeholder": "project_name",  "content": "XX 220kV 变电站大修",
     "source_refs": [{"chunk_id": "doc-guide::chunk-0", "quote": "项目名称:XX 220kV 变电站大修"}]}
  ]
}
```

## Errors

docxtpl **不会**为缺失 key 报错 — 渲染为空字符串。因此框架在 `summarize` 后会:

| 校验失败 | 现象 | 处置 |
|---|---|---|
| `context_schema.model_validate` 失败 | summarize 抛 `response_parse_error` | 补齐 pydantic schema 要求的字段,再写 output.json |
| 占位符覆盖率 < 100% | execute 抛 `output_validation_error` | 漏 placeholder 的 findings 文件必须补上 |
| 循环占位符 content 类型错 | docxtpl 渲染结果空 | 循环占位符的 `content` 必须是 list,不是 str |

**绝不**用 Python 的 `None` 做占位符值 — 会被 docxtpl 渲染成字符串 `"None"`,肉眼不易察觉。用 `""` 或具体 sentinel 字符串。
