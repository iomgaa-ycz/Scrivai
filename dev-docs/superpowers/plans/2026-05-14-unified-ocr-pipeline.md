# Issue #9: 统一 OCR 转换管线

> 对应 GitHub Issue: #9 — DOC 文件转换乱码：建议统一走 PDF + OCR 路径

## 1. 背景

当前 `scrivai/io/convert.py` 有三条独立转换路径：

| 函数 | 路径 | 问题 |
|------|------|------|
| `docx_to_markdown` | pandoc 直转 | 表格/图片/复杂排版丢失 |
| `doc_to_markdown` | LibreOffice → docx → pandoc | 实测产出编码乱码 + 结构丢失 |
| `pdf_to_markdown` | MonkeyOCR HTTP | 可用，但仅限 PDF |

下游项目 GovDoc-Editor 处理招标文书时频繁遇到 `.doc` 格式文件，乱码直接影响审查准确性。

## 2. 方案

统一为单一入口 `to_markdown()`，所有格式走 MonkeyOCR 管线：

```
.doc / .docx → LibreOffice headless → PDF ─┐
                                            ├→ MonkeyOCR HTTP → Markdown
.pdf ───────────────────────────────────────┘
```

MonkeyOCR 不可达时，`.doc/.docx` 可降级到 pandoc 路径（`.pdf` 无 fallback）。

### 被否决的方案

- **方案 B: 纯修复 pandoc 链路** — 只能解决编码问题，表格/图片损失无法改善，治标不治本
- **方案 C: MinerU 替代 MonkeyOCR** — 需要 GPU + 重 Python 依赖，部署复杂度远高于已有 Docker 容器

## 3. `convert.py` 内部结构

```
convert.py
├── _DEFAULT_OCR_URL          # os.environ.get("SCRIVAI_OCR_BASE_URL", "http://100.81.95.44:7861")
├── _to_pdf(path) -> Path     # LibreOffice headless: doc/docx → PDF (临时目录)
├── _ocr_to_markdown(pdf_path, base_url, timeout) -> str   # MonkeyOCR HTTP 调用
├── _pandoc_to_markdown(docx_path) -> str                   # pandoc 直转 (fallback 专用)
└── to_markdown(path, *, ocr_base_url, timeout, fallback) -> str  # 唯一公开入口
```

### 路由表

| 后缀 | 主路径 | fallback (`fallback=True`) |
|------|--------|---------------------------|
| `.pdf` | MonkeyOCR | 无（直接报错） |
| `.doc` / `.docx` | LibreOffice → PDF → MonkeyOCR | LibreOffice → docx → pandoc |
| 其他 | raise IOError | — |

### fallback 规则

- 仅在 MonkeyOCR **网络不可达/超时** 时触发
- OCR 返回业务错误（如解析失败）不触发 fallback
- fallback 对 `.doc` 需再走一次 LibreOffice（转 docx 而非 pdf），然后 pandoc
- fallback 触发时记录 `logging.warning`

### 配置优先级

```
函数参数 ocr_base_url > 环境变量 SCRIVAI_OCR_BASE_URL > 硬编码默认值
```

## 4. 公开 API 变更

### 删除

- `docx_to_markdown()`
- `doc_to_markdown()`
- `pdf_to_markdown()`
- CLI 子命令 `docx2md` / `doc2md` / `pdf2md`

### 新增

- `to_markdown(path, *, ocr_base_url, timeout, fallback)` — 唯一入口
- CLI 子命令 `convert`：`scrivai-cli io convert --input <file> [--output <file>] [--ocr-base-url <url>] [--timeout <sec>] [--no-fallback]`

### 导出

```python
# scrivai/io/__init__.py
from scrivai.io.convert import to_markdown
from scrivai.io.render import DocxRenderer

__all__ = ["to_markdown", "DocxRenderer"]
```

`scrivai/__init__.py` 同步更新导入和 `__all__`。

## 5. 测试

使用 `real_data/` 真实文件：

| 用例 | 文件 | 说明 | skip 条件 |
|------|------|------|-----------|
| `test_to_markdown_doc` | `real_data/...整治工作指引.doc` | .doc OCR 主路径 | MonkeyOCR 不可达 / LibreOffice 缺失 |
| `test_to_markdown_docx` | `real_data/...设备采购.docx` | .docx OCR 主路径 | MonkeyOCR 不可达 / LibreOffice 缺失 |
| `test_to_markdown_pdf` | `real_data/...归档资料.pdf` | .pdf OCR 直转 | MonkeyOCR 不可达 |
| `test_to_markdown_fallback` | 程序化 fixture | mock OCR 不可达，降级 pandoc | pandoc 缺失 |
| `test_to_markdown_unsupported` | 任意 `.xls` | 不支持格式报错 | 无 |
| DocxRenderer 测试 | 保持不动 | — | — |

## 6. 涉及文件

| 文件 | 操作 |
|------|------|
| `scrivai/io/convert.py` | 重写 |
| `scrivai/io/__init__.py` | 更新导出 |
| `scrivai/__init__.py` | 更新导入和 `__all__` |
| `scrivai/cli/io_cmd.py` | 删除旧子命令，新增 `convert` |
| `tests/contract/test_io_smoke.py` | 重写转换相关测试 |
