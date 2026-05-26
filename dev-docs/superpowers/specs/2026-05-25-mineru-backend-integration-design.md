# MinerU 后端集成设计

> 日期: 2026-05-25
> 状态: approved

## 1. 背景

GLM-OCR 云端 API 存在并发限制（约 5 QPS），处理大文件（1335 页）时 48 个 chunk 并行请求频繁触发 429 限流。需要引入本地 PDF 解析方案减少 API 依赖。

MinerU（mineru v3.x）是一个成熟的本地 PDF→Markdown 流水线，具备智能分流（文字型/扫描型自动判断）、版面分析、表格识别、公式识别等能力，完全本地运行，无 API 费用。

## 2. 方案

将 MinerU 作为第三个 OCR 后端集成到 `scrivai/io/convert.py`，与 Monkey OCR、GLM OCR 并列。MinerU 设为默认后端。

### 2.1 三后端并行

```python
_BACKENDS = {"monkey": _monkey_ocr, "glm": _glm_ocr, "mineru": _mineru_ocr}
```

默认后端从 `"glm"` 改为 `"mineru"`（`SCRIVAI_OCR_BACKEND` env 覆盖）。

### 2.2 GLM-OCR 并发硬限

```python
_GLM_MAX_WORKERS = 3
```

`_glm_ocr_chunked()` 入口处 clamp：

```python
if max_workers > _GLM_MAX_WORKERS:
    logger.warning("GLM-OCR max_workers %d 超过限制, 已降至 %d", max_workers, _GLM_MAX_WORKERS)
    max_workers = _GLM_MAX_WORKERS
```

函数签名的 `max_workers` 默认值不变（12），由运行时 clamp。

### 2.3 `_mineru_ocr()` 实现

```python
def _mineru_ocr(
    pdf_path: Path,
    *,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
```

流程：

1. **页面切割**（可选）：若指定 `start_page/end_page`，用 pypdf 切出子 PDF bytes；否则 `pdf_path.read_bytes()`
2. **调用 MinerU**：
   ```python
   from mineru.cli.common import do_parse

   do_parse(
       output_dir=tmp_dir,
       pdf_file_names=[stem],
       pdf_bytes_list=[pdf_bytes],
       p_lang_list=["ch"],
       backend="pipeline",
       parse_method="auto",
       f_dump_md=True,
       f_dump_middle_json=False,
       f_dump_model_output=False,
       f_draw_layout_bbox=False,
       f_draw_span_bbox=False,
       f_dump_orig_pdf=False,
       f_dump_content_list=False,
   )
   ```
3. **读取结果**：从 `<tmp_dir>/<stem>/auto/<stem>.md` 读取 Markdown
4. **清理**：`tempfile.TemporaryDirectory` 自动清理

若已用 pypdf 切出子 PDF，则不传 `start_page_id/end_page_id`，避免双重切割。

### 2.4 `to_markdown()` 签名变更

- 默认后端改为 `"mineru"`
- `start_page` / `end_page` 从 GLM-only 提升为通用参数（MinerU 也支持）
- 不新增 MinerU 专属参数（`parse_method`、`backend` 硬编码在 `_mineru_ocr` 内部）
- 现有 GLM/Monkey 专属参数保留不变

### 2.5 错误处理

| 场景 | 处理 |
|------|------|
| mineru 未安装 | import 失败 → `IOError("mineru 未安装，请运行 pip install 'mineru[all]'")` |
| 模型未下载 | 自动触发下载，`logger.info` 记录；下载失败 → `IOError` |
| PDF 解析失败 | 包装为 `IOError` |

pandoc fallback 逻辑（`.docx/.doc` OCR 不可达时降级）对三个后端通用，无需修改。

### 2.6 CLI 变更

`--ocr-backend` help 更新为 `"OCR backend: monkey | glm | mineru (default: mineru)"`。

## 3. 文件变更清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `scrivai/io/convert.py` | MODIFY | 新增 `_mineru_ocr()`；`_BACKENDS` 加 `"mineru"`；`_GLM_MAX_WORKERS=3` + clamp；默认后端改 `"mineru"` |
| `scrivai/cli/io_cmd.py` | MODIFY | `--ocr-backend` / `--max-workers` help 文本更新 |
| `tests/unit/test_mineru_ocr.py` | NEW | MinerU 后端单元测试（mock `do_parse`） |
| `tests/unit/test_glm_chunked.py` | MODIFY | 补充 max_workers clamp 测试 |

## 4. 不做的事

- 不新增 MinerU 配置项（无 API key / env）
- 不修改 MinerU 内部的 OCR 行为（由 `parse_method="auto"` 自行决定）
- 不改动 Monkey / GLM 后端的现有逻辑（除 GLM clamp）

## 5. 被否决的方案

- **docling**：对该 PDF 中文输出乱码（字体编码问题），不可用
- **pypdf 纯文字提取 + GLM 兜底**：表格质量差，无版面分析能力
- **MinerU v1.x (magic-pdf)**：旧版，模型较老，未来可能停止维护
