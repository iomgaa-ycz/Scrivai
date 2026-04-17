---
name: available-tools
description: |
  The authoritative reference for all CLI commands available to the agent during
  document audit/generation tasks. Use this whenever you are about to call a
  scrivai-cli or qmd command from Bash, especially in the execute phase. Reading
  this prevents prompt drift, ensures correct flag names, and tells you the exact
  JSON shape to expect back.
---

# Available Tools

This skill is the **command manifest** for the agent. Whenever you are
about to invoke a CLI command from `Bash`, read the relevant section
below to confirm the correct flags and the JSON shape you should expect.

The two command families exposed to the agent are:

1. `scrivai-cli library` — knowledge library lookup (rules / cases / templates)
2. `qmd` — direct semantic search against any qmd collection

The agent **does not** invoke `scrivai-cli workspace` or `scrivai-cli
trajectory` — those are managed by the calling business layer.

---

## scrivai-cli library

All `library` subcommands accept `--type {rules|cases|templates}` to pick the
collection.

### library search

```
scrivai-cli library search --type rules --query "<query>" [--top-k 5] [--filters '{}']
```

Output:
```json
{
  "hits": [
    { "chunk_id": "...", "score": 0.83, "text": "...", "metadata": {} }
  ]
}
```

Error → stderr `{"error": "..."}` + exit 1.

### library get

```
scrivai-cli library get --type rules --entry-id <id>
```

Output:
```json
{ "entry_id": "rule-001", "markdown": "...", "metadata": {} }
```

Returns error if `entry-id` does not exist.

### library list

```
scrivai-cli library list --type rules
```

Output:
```json
{ "entry_ids": ["rule-001", "rule-002"] }
```

---

## qmd

For raw semantic search against any qmd collection (when the library
abstraction is not what you need):

```
qmd search --collection <name> --query "<q>" [--top-k 5] [--rerank]
qmd document get --collection <name> --id <chunk_id>
qmd document list --collection <name>
qmd collection info --name <name>
qmd collection list
```

`qmd document get` returns the full chunk including original markdown and
metadata — useful when you need to see the source context behind a search hit.

---

## Common patterns

- After a `library search` returns a hit, capture its `chunk_id` and use
  `qmd document get` if you need to read the surrounding context before
  using the snippet as evidence.
- Every command writes JSON to stdout on success and JSON to stderr on
  failure. Always check the exit code; a non-zero exit means stderr has
  the structured error.

## Examples

### Example 1 — 审核场景:查围标规则 + 取全文

```bash
scrivai-cli library search --type rules --query "围标串标的认定标准" --top-k 3
# → {"hits": [{"chunk_id": "rule-42::chunk-0", "score": 0.81, "text": "围标的认定…", "metadata": {"title": "招投标法 §32"}}, …]}

qmd document get --collection rules --id rule-42::chunk-0
# → {"id": "rule-42::chunk-0", "markdown": "## 围标的认定\n围标是指…", "metadata": {"title": "招投标法 §32"}, "chunk_count": 1}
```

### Example 2 — 生成场景:带 metadata filter 的搜索

```bash
scrivai-cli library search --type templates --query "验收报告" --filters '{"category": "高压试验"}'
```

Filter 透传到 qmd,只返回 metadata.category == "高压试验" 的 chunk。若不知 metadata key 取值,先跑 `scrivai-cli library list` 抽样。

### Example 3 — 抽取场景:列全部 entry id 预览可用材料

```bash
scrivai-cli library list --type cases
# → {"entry_ids": ["case-2024-001", "case-2024-002", …]}

scrivai-cli library get --type cases --entry-id case-2024-001
# → {"entry_id": "case-2024-001", "markdown": "## 2024 年 XX 变电站审计整改案…", "metadata": {…}}
```

## Errors

所有命令失败时写 JSON 到 stderr + exit 非 0。常见错误与处置:

| 场景 | stderr JSON 片段 | 处置 |
|---|---|---|
| 集合不存在 | `{"error": "collection 'rules' not found"}` | 改 `--type`;不要自行创建 |
| entry id 不存在 | `{"error": "entry 'xxx' not found"}` | 先 `library list` 拿现有 id;或用 search |
| filter JSON 语法错 | `{"error": "invalid --filters: …"}` | 引号用单引号包外层双引号包内层 |
| qmd 未初始化 | `{"error": "qmd not initialized: <db path>"}` | 报错退出;业务层应先建 db |

**重要**:遇到非零 exit,立即读 stderr 的 JSON,不要忽略继续;你的下一步很可能依赖这个失败的命令结果。
