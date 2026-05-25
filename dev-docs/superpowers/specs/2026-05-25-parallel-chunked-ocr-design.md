# GLM OCR 并行分块处理设计

> 日期: 2026-05-25
> 状态: draft
> 范围: `scrivai/io/convert.py`, `scrivai/cli/io_cmd.py`, `tests/contract/test_io_smoke.py`
> 前置: `2026-05-23-ocr-backend-refactor-design.md`（已实现）

## 1. 目标

大型 PDF（300+ 页）通过 GLM OCR 转 Markdown 需要 30 分钟以上。将 PDF 分块并行处理以大幅缩短耗时，同时通过页面重叠 + 智能合并解决跨页表格/图表的内容丢失问题。

**约束**:
- 工程/政府文档为主：大量表格、图表、跨页元素
- 内容不能丢失，格式可以不完美（如跨页表格拆成两段可接受）
- MVP 原则：方案简单可靠优先

## 2. 决策记录

| 决策 | 选项 | 结论 |
|------|------|------|
| 分块策略 | 页面重叠 / 预检测智能边界 / LLM 后处理 | **页面重叠**（简单可靠，业界验证） |
| 重叠页数 | 1 页 / 2 页 | **2 页**（覆盖跨 3 页表格，6% 额外开销可接受） |
| 并行方式 | ThreadPool / ProcessPool / asyncio | **ThreadPoolExecutor**（I/O 密集型，线程足够） |
| 小文件/大文件分流 | 分流两条路径 / 统一路径 | **统一路径**（≤chunk_pages 退化为 1 chunk，代码更简洁） |
| 去重合并 | difflib 精确匹配 / 比例估算 / 直接拼接 | **三级降级**（见 §3.3） |

**否决理由**:
- 预检测智能边界：pypdf 对扫描件提取文本能力差，启发式不可靠
- LLM 后处理合并：额外 LLM 调用增加成本和时间，MVP 阶段过度工程化
- ProcessPool：每个 chunk 只是 HTTP 调用，进程间序列化开销不值得
- 小/大文件分流：增加代码分支，小文件走统一路径自动退化为单 chunk

## 3. 架构设计

### 3.1 流程总览

```
to_markdown(path)
  └─ _glm_ocr(pdf_path)
       └─ _glm_ocr_chunked(pdf_path, ...)
            ├─ Phase 1: 分块（chunk_pages=30, overlap_pages=2）
            │    ≤30 页 → 1 chunk, 无重叠
            │    >30 页 → N chunks, 边界各重叠 2 页
            ├─ Phase 2: ThreadPoolExecutor(max_workers=12) 并行调用 _glm_ocr_single()
            │    每个 chunk 失败重试 2 次，仍失败则整体抛异常
            ├─ Phase 3: _merge_chunks() 三级去重合并
            └─ 返回完整 Markdown
```

### 3.2 分块策略

```
示例：100 页文档，chunk_pages=30, overlap_pages=2

Chunk 0: 页  1 – 30
Chunk 1: 页 29 – 58    ← 与 chunk 0 重叠页 29-30
Chunk 2: 页 57 – 86    ← 与 chunk 1 重叠页 57-58
Chunk 3: 页 85 – 100   ← 与 chunk 2 重叠页 85-86
```

每个 chunk 的页范围计算：
```python
stride = chunk_pages - overlap_pages      # 28
chunk_start = first_idx + i * stride
chunk_end = min(chunk_start + chunk_pages - 1, last_idx)
```

当 `chunk_start > last_idx` 时停止生成 chunk。

### 3.3 三级去重合并

对相邻两个 chunk 的 Markdown 输出，按优先级依次尝试：

**第一级：归一化 difflib 精确匹配（覆盖 ~90%+ 情况）**
1. 将两份 Markdown 按行 split
2. 归一化：strip 空白、去空行、统一全角/半角标点
3. `difflib.SequenceMatcher` 在 prev 尾部和 next 头部查找最长公共行序列
4. 在公共序列中点切割：取 `prev[:中点]` + `next[中点:]`

**第二级：比例估算 + 段落边界（覆盖 ~9%）**
1. `overlap_ratio = overlap_pages / chunk_pages`
2. `est_cut = int(len(prev_md) * (1 - overlap_ratio))`
3. 在 `est_cut` 附近找最近的段落边界（`\n\n`）
4. 取 `prev[:段落边界]` + `next`（next 保留全部，接受微量重叠）

**第三级：直接拼接（极端 fallback，<1%）**
- 比例估算总能执行，此层实际不会触发
- 保留作为防御性兜底

### 3.4 错误处理

- 单 chunk 失败：重试 `chunk_retries`（默认 2）次，指数退避
- 重试后仍失败：取消所有进行中的 future，抛出异常终止整个转换
- 日志：每个 chunk 的开始/完成/重试/失败均有 INFO/WARNING 级别日志

### 3.5 日志与进度

```
INFO  PDF 分块: 300 页 → 11 chunks (chunk_pages=30, overlap=2, workers=12)
INFO  Chunk 0/11 (页 1-30, 2.1MB) 开始处理
INFO  Chunk 0/11 完成 (12.3s)
WARN  Chunk 3/11 失败, 重试 1/2: TimeoutError(...)
INFO  全部 11 chunks 完成, 开始合并 (总耗时 45.2s)
INFO  合并完成, 输出 Markdown 共 128,456 字符
```

## 4. 接口变更

### 4.1 `to_markdown()` 新增参数

```python
def to_markdown(
    path: str | Path,
    *,
    # --- 已有参数 ---
    ocr_backend: str | None = None,
    glm_api_key: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    ocr_base_url: str | None = None,
    upload_rate: int | None = None,
    timeout: int = 300,
    fallback: bool = True,
    # --- 新增参数 ---
    chunk_pages: int = 30,         # 每 chunk 页数
    overlap_pages: int = 2,        # 重叠页数
    max_workers: int = 12,         # 并行线程数
) -> str:
```

新参数仅对 GLM 后端生效；MonkeyOCR 后端忽略。

### 4.2 `_glm_ocr()` 签名变更

```python
def _glm_ocr(
    pdf_path: Path,
    *,
    api_key: str,
    timeout: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
    # --- 新增 ---
    chunk_pages: int = 30,
    overlap_pages: int = 2,
    max_workers: int = 12,
) -> str:
```

删除小文件直调分支，统一调用 `_glm_ocr_chunked()`。

### 4.3 新增内部函数

| 函数 | 签名 | 职责 |
|------|------|------|
| `_glm_ocr_chunked()` | `(pdf_path, *, api_key, timeout, start_page, end_page, chunk_pages, overlap_pages, max_workers) -> str` | 分块 + 并行调用 + 合并 |
| `_merge_chunks()` | `(chunks_md: list[str], overlap_pages: int, chunk_pages: int) -> str` | 顺序合并所有 chunk |
| `_merge_two()` | `(prev_md: str, next_md: str, overlap_pages: int, chunk_pages: int) -> str` | 合并相邻两个 chunk |
| `_find_overlap_boundary()` | `(prev_lines: list[str], next_lines: list[str]) -> tuple[int, int] \| None` | difflib 归一化匹配，返回切割位置 |

## 5. CLI 变更

`scrivai-cli io convert` 新增参数：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `--chunk-pages` | int | 30 | GLM 分块页数 |
| `--overlap-pages` | int | 2 | 分块重叠页数 |
| `--max-workers` | int | 12 | 并行线程数 |

## 6. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scrivai/io/convert.py` | [MODIFY] | 删除小文件分支，新增 `_glm_ocr_chunked` / `_merge_chunks` / `_merge_two` / `_find_overlap_boundary`，`to_markdown` 新增参数透传 |
| `scrivai/cli/io_cmd.py` | [MODIFY] | 新增 `--chunk-pages` / `--overlap-pages` / `--max-workers` CLI 参数 |
| `tests/contract/test_io_smoke.py` | [MODIFY] | 新增合并逻辑单元测试 |

## 7. 测试

### 7.1 单元测试（不需要 GLM API）

| 测试 | 说明 |
|------|------|
| `test_merge_two_with_overlap` | 构造有重叠内容的两段 Markdown，验证 difflib 合并正确去重 |
| `test_merge_two_fallback_ratio` | 构造无匹配内容的两段 Markdown，验证比例估算切割 |
| `test_merge_chunks_single` | 单 chunk 直接返回，不调合并 |
| `test_merge_chunks_multi` | 3+ chunks 顺序合并 |
| `test_chunk_range_calculation` | 验证 chunk 页范围计算（含边界情况：总页数不整除、小于 chunk_pages） |

### 7.2 集成测试（需要 GLM API）

| 测试 | 说明 |
|------|------|
| `test_glm_chunked_small_pdf` | ≤30 页 PDF，验证退化为单 chunk |
| `test_glm_chunked_large_pdf` | >30 页 PDF，验证并行 + 合并输出完整 |

## 8. 性能预期

| 文档大小 | 当前耗时 | 预期耗时 | 加速比 |
|----------|---------|---------|--------|
| 30 页 | ~3 min | ~3 min | 1x（单 chunk） |
| 100 页 | ~10 min | ~3 min | ~3x |
| 300 页 | ~30 min | ~5 min | ~6x |
| 500 页 | ~50 min | ~7 min | ~7x |

> 加速比受 GLM API 并发限制影响，实际值需验证。max_workers=12 可能超过 API 限流阈值，届时可调低。
