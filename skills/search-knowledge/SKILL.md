---
name: search-knowledge
description: |
  Use when you need to find supporting evidence from the rules/cases/templates
  knowledge bases — laws, regulations, historical reviewed documents, or
  templates. Trigger this any time you are about to assert a verdict, cite a
  rule, or back a finding with evidence. Skipping this step almost always leads
  to ungrounded outputs and missing chunk_ids in the final report.
---

# Search Knowledge

When you are reasoning about a task — judging whether a clause is compliant,
deciding which template fits, or finding precedent — pull supporting material
from the knowledge libraries before you write the conclusion.

## When to use

- About to write a verdict, judgement, or assertion that should be backed
  by a rule or precedent
- About to compose text that should match an existing case or template
- The current document references a regulation you have not yet looked up

## How

```bash
scrivai-cli library search --type rules --query "<focused query>" --top-k 5
```

Pick the `--type` that matches what you need:

- `rules` — laws, regulations, technical standards
- `cases` — historical reviewed documents (gold-standard examples)
- `templates` — boilerplate / structural templates

## Why this matters

Two reasons:

1. **Grounded output** — every claim should trace back to a source chunk
   so a reviewer can verify it.
2. **Better recall on first attempt** — phrasing the same query 2–3
   different ways increases the chance of finding the actual relevant
   material. Don't accept zero hits as the final answer; rephrase.

## After getting hits

Each hit comes with a `chunk_id`. **Always include the `chunk_id` when
you cite the snippet** — downstream tools and human reviewers use it to
re-locate the source. If you need the chunk's surrounding context, use
the `inspect-document` skill.

## Examples

### Example 1 — 多次重写 query 提高召回

```bash
scrivai-cli library search --type rules --query "断路器分合闸时间" --top-k 3
scrivai-cli library search --type rules --query "断路器分闸时间 合闸时间 同期性" --top-k 3
scrivai-cli library search --type rules --query "高压开关机械特性试验" --top-k 3
```

同一意图的 3 种表述;聚合 chunk_id 去重,命中率显著高于单次 query。

### Example 2 — 先 rules 后 cases 的两段式调用

```bash
# 1) 从 rules 找适用条款
scrivai-cli library search --type rules --query "避雷器阻性电流 ≤25%" --top-k 3
# 2) 从 cases 找曾经如何落地这个条款的先例
scrivai-cli library search --type cases --query "避雷器阻性电流 整改" --top-k 3
```

### Example 3 — filter 收窄到特定文档

```bash
scrivai-cli library search --type templates --query "工作底稿" --top-k 5 --filters '{"doc_type": "workpaper"}'
```

当你已知想要的模板类别,加 `--filters` 避免被同字面量的其它文档稀释。

## Errors

| 场景 | stderr JSON | 处置 |
|---|---|---|
| top-k 过大 | (不报错,但响应慢) | 本项目建议 3-5;超过 10 极少有增益 |
| 返回 `hits: []` | (exit 0,空列表) | **不要把零命中当作"不存在"写入 verdict**。重写 query 再试;3 次仍 0 才可写「需要澄清」 |
| filter key 不存在 | 通常 (exit 0,空列表) | 先跑 `qmd collection info --name <c>` 看 metadata schema |

**关键原则**:搜索返回的每条 hit 都带 `chunk_id`。**你引用的每一句话都必须挂 `chunk_id`**,没 chunk_id 的结论视作 ungrounded,会被下游 pipeline 拒收。
