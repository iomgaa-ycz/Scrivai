# IO samples fixtures

本目录的 `.docx` 二进制 fixture 由 `scripts/` 下的一次性构造脚本生成,入 git(~70 KB 合计)。

| 文件 | 生成脚本 | 用途 |
|---|---|---|
| `table_sample.docx` | `scripts/make_table_sample.py` | 验证 `docx_to_markdown` 保留表格结构(pandoc 输出) |
| `loop_template.docx` | `scripts/make_loop_template.py` | 验证 `DocxRenderer` 支持 docxtpl `{% for %}` 循环模板 |

## 重新生成

若 fixture 损坏或需更新,删掉重跑脚本:

```bash
rm tests/fixtures/io_samples/*.docx
conda run -n scrivai python scripts/make_table_sample.py
conda run -n scrivai python scripts/make_loop_template.py
```

## 为什么 `loop_template.docx` 需要 XML 后处理

docxtpl 的 `{% for %}` jinja 标签要求整个标签在同一 `<w:r>` 内。python-docx 写入字符串时可能因 auto-formatting 把字符拆到多 run,导致 docxtpl 解析失败。脚本采取 **占位字符串 + XML 字符串替换** 的社区规避方案:先写 `__TAG_FOR__` 等唯一占位,保存后解压 docx,对 `word/document.xml` 做 replace,再重新打包。
