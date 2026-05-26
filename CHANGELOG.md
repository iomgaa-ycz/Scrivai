# CHANGELOG

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [0.2.1] — 2026-05-25

### Added — MinerU Local OCR Backend

- **MinerU backend** (`ocr_backend="mineru"`): Local PDF→Markdown pipeline powered by MinerU v3.x — intelligent auto-routing (text extraction for text-based pages, OCR for scanned pages), professional table recognition (RapidTable), layout analysis (LayoutLMv3), and formula recognition
- **MinerU set as default backend**: `SCRIVAI_OCR_BACKEND` env defaults to `"mineru"` (was `"glm"`)
- **Page range support for MinerU**: `start_page` / `end_page` parameters now work with both GLM and MinerU backends
- **GLM-OCR concurrency hard cap**: `max_workers` clamped to 3 with warning log to avoid API rate limiting (HTTP 429)
- Optional dependency group: `pip install scrivai[mineru]`

### Changed

- **Breaking:** Default OCR backend changed from `"glm"` to `"mineru"` — set `SCRIVAI_OCR_BACKEND=glm` to restore previous behavior
- GLM-OCR `max_workers` is now capped at 3 regardless of user input (was uncapped at 12)

## [0.2.0] — 2026-05-25

### Added — Parallel Chunked OCR

- **Parallel chunk processing**: Large PDFs are now split into overlapping chunks and processed in parallel via `ThreadPoolExecutor`, reducing OCR time by 3-7x for 100-300+ page documents
- **Page overlap dedup**: Adjacent chunks overlap by 2 pages (configurable) to preserve cross-page tables and figures; three-tier merge strategy (difflib matching → ratio estimation → direct concat) deduplicates the overlap region
- **Configurable chunking parameters**: `chunk_pages` (default 30), `overlap_pages` (default 2), `max_workers` (default 12) — available as both function parameters and CLI flags
- **Per-chunk retry**: Each chunk retries up to 2 times with exponential backoff on transient failures; all-retries-exhausted aborts the entire conversion
- CLI: `scrivai-cli io convert` gains `--chunk-pages`, `--overlap-pages`, `--max-workers`

### Changed

- **Breaking:** The old serial chunking path (100-page / 50 MB threshold) is replaced by the unified parallel chunking path — all PDFs now go through `_glm_ocr_chunked()`, with small files (≤ 30 pages) degrading to a single chunk with zero overhead
- Internal: `_glm_ocr()` now delegates entirely to `_glm_ocr_chunked()`; old `PdfReader`/`PdfWriter` serial loop removed

## [0.1.9] — 2026-05-24

### Added — Pluggable OCR Backend & GLM-OCR Integration

- **Pluggable OCR backend architecture**: `to_markdown()` now accepts `ocr_backend` parameter to select between multiple OCR providers (`"monkey"` for self-hosted MonkeyOCR, `"glm"` for ZhipuAI GLM-OCR cloud API)
- **GLM-OCR cloud backend** (`ocr_backend="glm"`): ZhipuAI's 0.9B OCR model via `layout_parsing` API — supports PDF / JPG / PNG, returns Markdown with table HTML
- **Auto-chunking for large PDFs**: PDFs exceeding GLM-OCR limits (100 pages / 50 MB) are automatically split via `pypdf`, processed per chunk, and concatenated — users don't need to handle this manually
- **Page range selection**: `start_page` / `end_page` parameters for GLM-OCR backend (1-based)
- CLI: `scrivai-cli io convert` gains `--ocr-backend`, `--glm-api-key`, `--start-page`, `--end-page`
- Environment variables: `SCRIVAI_OCR_BACKEND`, `SCRIVAI_GLM_API_KEY`
- `pypdf>=4.0` added to dependencies

### Changed

- **Breaking:** MonkeyOCR no longer has a built-in default URL — you must set `SCRIVAI_OCR_BASE_URL` env or pass `ocr_base_url` parameter when using `ocr_backend="monkey"`
- **Breaking:** Default OCR backend changed from implicit MonkeyOCR to `"glm"` (configurable via `SCRIVAI_OCR_BACKEND` env)
- All OCR-related environment variables are now read at call time (not at module import time) — users can set `os.environ` in code before calling `to_markdown()`
- Internal: `_ocr_to_markdown()` renamed to `_monkey_ocr()`, `_BACKENDS` registry dict for dispatch

## [0.1.8] — 2026-05-14

### Changed — Unified OCR Pipeline (Issue #9)

- **Breaking:** `docx_to_markdown()` / `doc_to_markdown()` / `pdf_to_markdown()` removed — replaced by single `to_markdown(path)` entry point
- All document formats (`.doc` / `.docx` / `.pdf`) now route through MonkeyOCR pipeline: doc/docx → LibreOffice headless → PDF → MonkeyOCR HTTP → Markdown
- Pandoc fallback for `.doc` / `.docx` when MonkeyOCR is unreachable (`fallback=True` by default)
- Upload rate limiting (default 500 KB/s) via `requests-toolbelt` streaming — prevents Tailscale / home-broadband upload stalls on large files
- OCR service URL configurable via `SCRIVAI_OCR_BASE_URL` env var or `ocr_base_url` parameter
- Upload rate configurable via `SCRIVAI_OCR_UPLOAD_RATE` env var or `upload_rate` parameter
- CLI: `scrivai-cli io docx2md` / `doc2md` / `pdf2md` merged into `scrivai-cli io convert`
- `PhaseConfig.max_turns` default raised from 10 to 16

### Removed

- `docx_to_markdown()`, `doc_to_markdown()`, `pdf_to_markdown()` — use `to_markdown()` instead
- CLI subcommands `docx2md`, `doc2md`, `pdf2md` — use `convert` instead

## [0.1.7] — 2026-04-20

### Added — Jinja2 Prompt Management + Issue #8 Fix

- `scrivai.PromptManager` — Jinja2 template-based prompt assembly with YAML contract validation (replaces `json.dumps` approach)
- 9 built-in prompt templates (`{auditor,extractor,generator}_{plan,execute,summarize}.j2`) + shared `workspace_rules.md` fragment
- `prompt_spec.yaml` — declares required context variables per PES/phase
- `WorkspaceHandle.extra_env` — environment variables now flow through to Agent SDK subprocess (fixes issue #8)
- `PESConfig.external_cli_tools` — Bash command whitelist injected into Agent prompts
- `jinja2>=3.1` as explicit dependency

### Changed

- `BasePES.build_phase_prompt()` now delegates to `PromptManager` instead of `json.dumps(context)` — Agent only sees explicitly templated variables
- `BasePES._call_sdk_query()` passes `extra_env` to `LLMClient.execute_task()` and uses only `config.prompt_text` as `system_prompt` (fixes duplication bug)
- `BasePES.__init__()` accepts optional `prompt_manager` parameter for dependency injection
- `_workspace_payload()` no longer exposes `output_dir` to Agent (fixes path ambiguity from issue #8)
- `relaxed_json_loads` removed from public API (`__all__`)

### Removed

- `PhaseConfig.additional_system_prompt` — content migrated to Jinja2 templates

## [0.1.6] — 2026-04-19

### Changed — Documentation System Redesign

- All docstrings rewritten to English (Google style) per `CONTRIBUTING.md`
- MkDocs Material site skeleton with API reference (auto-generated from docstrings)
- Chinese translation skeleton (`docs/zh/`)
- README rewritten in English; `README.zh-CN.md` added
- License migrated from MIT to Apache 2.0
- Internal dev docs moved to `dev-docs/`

### Fixed

- LLM client: manual assistant turn counting to prevent infinite loops
- Auditor: verdict dict compatibility + evidence multi-field tolerance
- Auditor: auto-repair malformed JSON in findings/
- IO: MonkeyOCR bypass system proxy + timeout 120→300s

### Added

- `TrajectoryStore.delete_run()` — cascade delete for run cleanup
- `CONTRIBUTING.md` with documentation standards

## [0.1.5] — 2026-04-17

### Added — Relaxed JSON Repair

- `scrivai.relaxed_json_loads()` — 5-stage fault-tolerant JSON parser (strip envelope → normalize quotes → remove trailing commas → escape inner quotes → strict fallback)
- `PESConfig.strict_json` field — when True, skips repair and uses strict `json.loads`
- `ScrivaiJSONRepairError` exception with dual inheritance

### Changed

- `Proposer` JSON parsing switched to balanced-bracket scanning + Chinese quote normalization
- PES layer uses `relaxed_json_loads` for all JSON file reads

## [0.1.4] — 2026-04-18

### Added — M2 自研 Skill 进化系统

- `scrivai.run_evolution(config, ...)` — 自研进化循环(替代原计划的 EvoSkill 集成)
- `scrivai.promote(version_id, source_project_root)` — Python SDK 方式把评估通过的 SkillVersion 原子写回 `skills/`
- `scrivai.SkillVersionStore` — 独立 SQLite(`evolution.db`)存 skill 版本 DAG + 评分历史
- `scrivai.Proposer` — LLM 基于失败样本生成 N 候选
- `scrivai.CandidateEvaluator` — 在 hold_out 集跑真实 PES 评估候选
- `scrivai.EvolutionTrigger` — 从 `TrajectoryStore.feedback` 收集失败样本 + 分 train/holdout
- `scrivai.LLMCallBudget` — 进化循环预算守卫(默认上限 500 次调用)
- pydantic 模型:`FailureSample / SkillVersion / EvolutionProposal / EvolutionScore / EvolutionRunRecord / EvolutionRunConfig`
- 3 个 examples:`01_audit_single_doc.py` / `02_generate_with_revision.py` / `03_evolve_skill_workflow.py`
- `scripts/verify_m3a_release.sh` — 发版前 deprecation 扫描一键 gate

### Changed

- `Proposer` JSON 解析改为平衡括号扫描 + 中文引号/尾逗号正规化 + 失败后一次严格化重试,修复 GLM 偶发非法 JSON 导致进化循环中断
- `scrivai.__version__` 现在从 `importlib.metadata` 读取,与 pyproject `version` 字段单一真相
- README 完整重写,反映当前 PES 架构 + M2 进化系统(原 README 描述的是 M0 前原型,已完全不适用)

### Removed

- M0 占位符 `FeedbackExample / EvolutionConfig / EvolutionRun / Evaluator / SkillsRootResolver` — 被 M2 实际类替代,MVP 原则不做向后兼容

### Known Limitations

- 并发隔离未做:两个业务方不应同时对同一 skill 跑 `run_evolution`(未加文件锁)
- 无观测指标:LLM usage / duration / failure 等未上报
- 无自动触发:business 层须显式调 `run_evolution()`,专家须显式调 `promote()`
- `DERIVED / CAPTURED` 进化类型未实现(M2 仅实现 `FIX` 类型)

### Verification

- `scripts/verify_m3a_release.sh` 全通过(deprecation 扫描 + core imports 干净,symbols=63)
- `python -m build` 成功生成 wheel(`dist/scrivai-0.1.4-py3-none-any.whl`,82.8KB,仅 SPDX/license classifier deprecation warning 无 ERROR)
- 干净 venv(Python 3.11.15)从 wheel 装 `[dev]` extras 全部依赖 OK,`scrivai==0.1.4, symbols=63` import 冒烟通过
- 3 examples 全部跑通(scrivai conda env):
    - `01_audit_single_doc.py` → `status=completed`,3 findings(2 合格 / 1 需要澄清),verdict 合法
    - `02_generate_with_revision.py` → `status=completed`,3 placeholder 全部填充
    - `03_evolve_skill_workflow.py` → `status=completed`,evo_run 无增益跳过 promote(符合 demo 预期)

## [0.1.3] — 2026-04-17 之前

M0-M1.5c 各阶段交付,详见 `docs/TD.md` 里程碑记录。
