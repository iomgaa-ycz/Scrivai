---
name: inspect-document
description: |
  Use when you have a chunk_id (typically from a library search hit) and need to
  read the original document context around it — the full markdown of the chunk,
  surrounding metadata, or the parent document. Trigger this any time you want
  to verify whether a search hit is actually on-topic before citing it.
---

# Inspect Document

When a search returns a chunk_id and the snippet alone is not enough
context to judge relevance, fetch the full chunk to see the surrounding text.

## When to use

- A `library search` hit looks promising but the snippet is truncated
- You need to verify a quote is faithful to the source before citing it
- You want to see the chunk's metadata (e.g. which document / section it
  came from) before using it as evidence

## How

```bash
qmd document get --collection <name> --id <chunk_id>
```

Returns:
```json
{ "id": "...", "markdown": "...full chunk text...", "metadata": {...}, "chunk_count": 1 }
```

The `metadata` typically includes the source document name, section, or
other locator the original ingestion pipeline put there.

## Why this matters

A search hit's snippet may be truncated or surrounded by qualifiers that
flip its meaning. Always fetch the full chunk before using a snippet as
the basis for a verdict — especially "negative" findings ("rule X
prohibits Y") where context can invert the conclusion.

## Examples

### Example 1 — 验证搜索命中的原文

```bash
# 先 search 拿 chunk_id
scrivai-cli library search --type rules --query "保护定值" --top-k 3
# → [{"chunk_id": "rule-88::chunk-2", "text": "保护定值修改必须双人…"}]

# 再 get 全文
qmd document get --collection rules --id rule-88::chunk-2
# → {"id": "rule-88::chunk-2", "markdown": "## 保护定值管理\n保护定值修改必须双人签字…\n见 §4.3。", "metadata": {"doc": "国网保护管理办法"}}
```

### Example 2 — 元数据驱动定位原文

```bash
qmd document get --collection cases --id case-2025-014::chunk-0 | jq -r '.metadata.source_file'
# → "2025 年度 110kV XX 变电站春检总结.docx"
```

`metadata.source_file` / `metadata.section` 是本项目 ingest pipeline 常见字段(具体 key 取决于建库时写入);未知 schema 时先用 `qmd collection info` 看结构。

### Example 3 — 批量拉全文做 cross-reference

```bash
for id in rule-42::chunk-0 rule-42::chunk-1 rule-42::chunk-2; do
  qmd document get --collection rules --id "$id" | jq -c '{id, text_preview: .markdown[0:80]}'
done
```

## Errors

| 场景 | stderr JSON | 处置 |
|---|---|---|
| chunk_id 不存在 | `{"error": "chunk 'xxx' not found in rules"}` | 先 `qmd search` / `library search` 确认 id 还在;可能是 ingest 重建后 id 变了 |
| collection 名错 | `{"error": "collection 'xxx' not found"}` | 常见笔误:`rule` vs `rules` — 本项目统一用复数 |
| 返回值为空 markdown | (无错,但 `markdown` 字段 ="") | 通常是 ingest 时原文丢失,跳过此 chunk 换下一个 |

**重要**:`chunk_count` 字段告诉你这份 chunk 原属于的父文档被切成几块;若 = 1 说明父文档本就短。
