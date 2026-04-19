# Graph Report - .  (2026-04-18)

## Corpus Check
- 181 files · ~134,729 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1264 nodes · 3780 edges · 50 communities detected
- Extraction: 33% EXTRACTED · 67% INFERRED · 0% AMBIGUOUS · INFERRED: 2534 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `WorkspaceHandle` - 131 edges
2. `PhaseResult` - 111 edges
3. `PESConfig` - 107 edges
4. `ModelConfig` - 103 edges
5. `PESRun` - 91 edges
6. `WorkspaceSnapshot` - 90 edges
7. `PhaseConfig` - 90 edges
8. `RunHookContext` - 84 edges
9. `TrajectoryStore` - 83 edges
10. `PhaseHookContext` - 80 edges

## Surprising Connections (you probably didn't know these)
- `T0.3 契约测试:scrivai.pes.config.load_pes_config。` --uses--> `PESConfigError`  [INFERRED]
  tests/contract/test_pes_config.py → scrivai/exceptions.py
- `fixture 提供的合法 extractor YAML → 返回 PESConfig 实例。` --uses--> `PESConfigError`  [INFERRED]
  tests/contract/test_pes_config.py → scrivai/exceptions.py
- `缺失环境变量 → PESConfigError(不让模板字符串原样传下去)。` --uses--> `PESConfigError`  [INFERRED]
  tests/contract/test_pes_config.py → scrivai/exceptions.py
- `缺少必需字段 name → PESConfigError(包装 pydantic ValidationError)。` --uses--> `PESConfigError`  [INFERRED]
  tests/contract/test_pes_config.py → scrivai/exceptions.py
- `非法 YAML → PESConfigError。` --uses--> `PESConfigError`  [INFERRED]
  tests/contract/test_pes_config.py → scrivai/exceptions.py

## Hyperedges (group relationships)
- **M0 地基层 4 任务协同** — td_t02_models, td_t03_pes_config, td_t18_skills_root_resolver, td_milestone_m0 [EXTRACTED 1.00]
- **M0.25 基础设施三件套(Workspace/Hook/Trajectory)** — td_t04_workspace, td_t05_hooks, td_t07_trajectory_store, td_t10_testing_helpers [EXTRACTED 1.00]
- **M1 三个预置 PES 共用 BasePES 模式** — td_t14_extractor, td_t15_auditor, td_t16_generator, design_basepes, spec_m15_decision_2_runtime_context [EXTRACTED 1.00]
- **M1 E2E PES Pipeline (Extractor→Auditor→Generator)** — concept_extractor_pes, concept_auditor_pes, concept_generator_pes [EXTRACTED 1.00]
- **M1 E2E fixture triplet (guide + checkpoints + template)** — m1_e2e_substation_guide, m1_e2e_checkpoints_golden, m1_e2e_workpaper_template_docx [EXTRACTED 1.00]
- **Doc Pipeline E2E test suite (regex/clean/validation)** — test_pipeline_regex_only, test_pipeline_clean_only, test_pipeline_validation_warnings [INFERRED 0.85]
- **Multichapter Flow Test Suite** — test_multichapter_coherence, test_summary_propagation, test_glossary_propagation [EXTRACTED 0.95]
- **Project SDK Test Suite** — test_sdk_full_flow, test_sdk_with_knowledge [EXTRACTED 0.95]
- **Context Propagation Modules** — module_summary, module_glossary, module_multichapter_flow [INFERRED 0.80]
- **Preprocessing/Extraction Prompt Family** — prompt_clean, prompt_extract_references, prompt_extract_terms [INFERRED 0.75]
- **Three Demo PES Agents (Auditor/Generator/Extractor)** — agent_auditor_pes, agent_generator_pes, agent_extractor_pes [EXTRACTED 0.90]
- **Self-Audit Iterative Cycle (test + demo)** — test_generate_audit_revise, test_max_revisions, example_02_generate_with_revision [INFERRED 0.80]

## Communities

### Community 0 - "M2 Evolution Engine"
Cohesion: 0.04
Nodes (97): BudgetExceededError, LLMCallBudget, LLMCallBudget — 进化期间 LLM 调用预算守卫。, 追踪并限制单次 run_evolution 的 LLM 调用总数。, 尝试消耗 n 次调用;若消耗后超预算抛 BudgetExceededError。, CandidateEvaluator, _prepare_temp_project_root(), CandidateEvaluator — 用候选 SKILL.md 重跑真实 PES,打分。  参考 docs/superpowers/specs/2026-0 (+89 more)

### Community 1 - "PES Config & Workspace Models"
Cohesion: 0.1
Nodes (120): _NullHookManager, _BaseLibrary — 三个 Library 的共通基类。  直接代理 qmd Collection 的 add_document / get_docum, 构建本阶段的 execution_context。默认返回空 dict。, 渲染本阶段 prompt。默认拼接 config.prompt_text + phase prompt + task + context。, 响应后处理。默认 no-op。异常 → response_parse_error(不可重试)。, 校验必需产物。默认按 required_outputs 逐条校验。          异常 → output_validation_error(可重试)。, 调 LLMClient,翻译异常为 _SDKError(error_type=...)。          - _MaxTurnsError → _SDKErr, 包裹 phase 级重试;on_phase_failed 在此统一 dispatch。 (+112 more)

### Community 2 - "Core PES Run Models"
Cohesion: 0.05
Nodes (105): AuditOutput, Finding, main(), _require_env(), AuditorPES, AuditorPES — 对照 data/checkpoints.json 审核(M1.5a T1.5)。  runtime_context 业务字段: - o, execute 阶段:data/checkpoints.json 的 cp_id 与 findings 对齐。, 对照 data/checkpoints.json 审核文档合规性。      阶段契约:     - plan     → working/plan.md + (+97 more)

### Community 3 - "Trajectory Storage"
Cohesion: 0.04
Nodes (77): TrajectoryStore 写入失败(SQLite busy 超过重试预算)。M0.25 T0.7 实现。, TrajectoryWriteError, FakeTrajectoryStore, FakeTrajectoryStore — 测试用的 :memory: SQLite TrajectoryStore。  行为与 prod Trajectory, _main(), M3a Example 03 专用 feedback seeder(4 条,extractor)。  与 tests/fixtures/m2_evolution, 清 demo-extractor-* 旧行并 seed 4 条新 feedback(幂等)。      参数:         db_path: traject, seed() (+69 more)

### Community 4 - "Workspace Sandbox"
Cohesion: 0.04
Nodes (65): scrivai.testing.contract — pytest plugin 提供下游可复用的 fixtures。  下游通过 `pytest --pyar, tmp_path 锚定的 LocalWorkspaceManager。, tmp_path 锚定的 qmd client。, tmp_path 锚定的 TrajectoryStore。, scrivai_qmd_client(), scrivai_trajectory_store(), scrivai_workspace_manager(), WorkspaceManager 错误(run_id 冲突 / fcntl 失败等)。M0.25 T0.4 实现。 (+57 more)

### Community 5 - "LLM Client Layer"
Cohesion: 0.05
Nodes (60): _build_minimal_source_proj(), _ExtractOut, main(), _make_pes_factory(), _overlap_score(), 简单 evaluator:对 items 集合算 Jaccard。      参数:         question: 问题文本(本例未使用)。, 返回 (pes_name, workspace) -> ExtractorPES 的工厂函数。      工厂必须用 ws.project_root(Candi, ExtractorPES 输出 schema(items 列表)。 (+52 more)

### Community 6 - "BasePES Engine"
Cohesion: 0.05
Nodes (31): _BaseLibrary, BasePES, RuleLibrary / CaseLibrary / TemplateLibrary 的共通实现。      子类只需在 __init__ 中传入 colle, 写入 qmd chunk;entry_id 在 collection 内必须唯一。          重复抛 ValueError;qmd 的 add_docu, 按 document_id 取;不存在返回 None。, 删除 collection 内的 entry;不存在不报错(qmd 行为)。, 透传 qmd hybrid_search。, _utcnow() (+23 more)

### Community 7 - "Milestone Planning Docs"
Cohesion: 0.05
Nodes (61): BasePES 三阶段执行引擎, 9 Hook 触点系统, PESRun pydantic 模型, PhaseResult pydantic 模型, qmd-py 上游契约, qmd re-export 不是强契约 (rationale), RuleLibrary/CaseLibrary/TemplateLibrary, ExtractorPES/AuditorPES/GeneratorPES (+53 more)

### Community 8 - "M1 E2E Test Fixtures"
Cohesion: 0.08
Nodes (32): 案例 3: 110kV 城东输电线路工程, 案例 2: 220kV 产业园区变电站土建工程, 案例 1: 500kV 电白变电站主变安装工程, AuditorPES, 断路器动作试验 (circuit_breaker_operation), 互感器校验 (ct_pt_calibration), ExtractorPES, GeneratorPES (+24 more)

### Community 9 - "Pre-built Agents & SDK Tests"
Cohesion: 0.08
Nodes (33): AuditorPES (Document Auditor Agent), ExtractorPES (Information Extractor Agent), GeneratorPES (Document Generator Agent), Concept: M2 Skill Evolution, Concept: Generate + Self-Audit Iterative Revision, Configuration: .env (ANTHROPIC_BASE_URL/AUTH_TOKEN/SCRIVAI_DEFAULT_MODEL), Demo 01: AuditorPES Single-Doc Audit, Demo 02: GeneratorPES Template Generation with Revision (+25 more)

### Community 10 - "BasePES Tests"
Cohesion: 0.18
Nodes (20): HookRecorder, _make_config(), _make_workspace(), _run(), test_after_phase_hook_error_on_summarize_marks_run_failed(), test_before_run_hook_error_fails_run(), test_cancellation_dispatches_on_run_cancelled(), test_cleanup_before_retry() (+12 more)

### Community 11 - "IO Smoke Tests"
Cohesion: 0.07
Nodes (27): M0.75 T0.12 contract tests for IO tools(smoke 级别)。  参考 docs/superpowers/specs/20, 用 python-docx 造一个含 docxtpl 占位符的 .docx 模板。      docxtpl 占位符语法是 {{ var }};python-d, list_placeholders 返回去重排序的占位符名列表。, render 写出 docx,文件存在且非空。, 模板不存在 → FileNotFoundError。, 渲染异常时不留半成品文件。      docxtpl 在缺 context key 时默认渲染为空字符串(不抛错),     所以这里用 invalid out, pandoc 把含表格的 docx 转 markdown,保留表格结构(内容 + 表格语法)。, 用 python-docx 程序化造一份简单 docx fixture。 (+19 more)

### Community 12 - "CLI Tests"
Cohesion: 0.12
Nodes (23): _parse_error_json(), populated_store(), M0.75 T0.13 contract tests for scrivai-cli。  参考 docs/superpowers/specs/2026-04-1, 没有 --db-path 也没有 QMD_DB_PATH env → stderr JSON + exit 1。, CLI docx2md 写出 markdown 文件。, CLI render 用 docxtpl 模板 + JSON context → 写 docx。, 从 stderr 提取最后一条 JSON 错误对象,容忍前面的 warning/log。, 造一个含一次完整 run 的 trajectory db。 (+15 more)

### Community 13 - "Knowledge Libraries (qmd)"
Cohesion: 0.12
Nodes (13): _BaseLibrary, CaseLibrary, CaseLibrary — 历史定稿(经专家审核的优质样本),collection 名固定 'cases'。, 案例知识库,固定 collection 'cases'。, build_qmd_client_from_config(), Knowledge factory — 构建 QmdClient 与三个 Library。, 封装 qmd.connect;统一 ~ 展开。, RuleLibrary — 法规 / 指引 / 标准的 markdown 分块,collection 名固定 'rules'。 (+5 more)

### Community 14 - "Knowledge Library Tests"
Cohesion: 0.1
Nodes (17): M0.75 T0.11 contract tests for Knowledge Libraries.  参考 docs/superpowers/specs/2, contract plugin 提供的 trajectory store fixture 应即用即测。, hybrid_search 的 filters 参数:透传 qmd;只返回匹配 metadata 的 chunk。      规格参考 docs/design., add → get → list → delete → get returns None。, 同 entry_id 在同一 collection 内 add 两次 → ValueError。, rules 和 cases 各 add 同 entry_id → 互不影响。, add 几条 → search 返回 list[SearchResult](非空)。, contract plugin 提供的 scrivai_libraries fixture 应即用即测。 (+9 more)

### Community 15 - "Models & Hooks Contract Tests"
Cohesion: 0.11
Nodes (9): test_exceptions_importable(), test_failure_hook_context_extra_fields(), test_knowledge_module_importable(), test_nine_hook_contexts_exist(), test_pes_module_importable(), test_phase_related_hook_contexts_have_attempt_no(), test_phase_result_round_trip(), test_trajectory_module_importable() (+1 more)

### Community 16 - "Generator PES Tests"
Cohesion: 0.24
Nodes (15): _phase_result(), _run(), template_path(), test_build_execution_context_non_plan_empty(), test_build_execution_context_plan_parses_placeholders(), test_build_execution_context_requires_template_path(), test_generator_smoke_with_real_glm(), test_postprocess_auto_render_true_produces_docx() (+7 more)

### Community 17 - "Hook Manager Tests"
Cohesion: 0.19
Nodes (13): M0.25 T0.5 contract tests for HookManager.  References: - docs/design.md §4.3 -, 多 plugin 注册:assert pluggy 实际调用顺序(LIFO,后注册先调)。      若 BasePES (M0.5) 需要 FIFO,届时给, 构造一个最小合法 PESRun 给所有 context 测试用。, HookManager 必须注册全部 9 个 hookspec,缺一个就抛错。, 注册 plugin → dispatch 触发其方法,context 透传无失真。, dispatch 同步分发:plugin 抛异常,直接冒泡,不被吞。, dispatch_non_blocking:plugin 抛异常,只 loguru 记一次,不冒泡。, _sample_run() (+5 more)

### Community 18 - "Evolution Store Tests"
Cohesion: 0.24
Nodes (10): _mk_version(), test_create_and_get_run(), test_finalize_run_updates_fields(), test_get_baseline_creates_from_source_when_absent(), test_get_baseline_returns_existing_root_when_no_promoted(), test_list_versions_by_pes_skill(), test_list_versions_filter_status(), test_mark_promoted() (+2 more)

### Community 19 - "PES Config Tests"
Cohesion: 0.15
Nodes (11): T0.3 契约测试:scrivai.pes.config.load_pes_config。, fixture 提供的合法 extractor YAML → 返回 PESConfig 实例。, 缺失环境变量 → PESConfigError(不让模板字符串原样传下去)。, 缺少必需字段 name → PESConfigError(包装 pydantic ValidationError)。, 非法 YAML → PESConfigError。, 文件不存在 → PESConfigError。, test_env_var_missing_raises_pes_config_error(), test_file_not_found_raises_pes_config_error() (+3 more)

### Community 20 - "qmd Re-export Tests"
Cohesion: 0.17
Nodes (7): qmd re-export 身份相等契约测试。  scrivai.ChunkRef 应当与 qmd.ChunkRef 是同一个对象(身份相等,非副本)。, 从 scrivai.models.knowledge 导入的 ChunkRef 与 qmd.ChunkRef 身份相等。, 从 scrivai.models 聚合层导入的 ChunkRef 也身份相等。, scrivai.ChunkRef is qmd.ChunkRef(顶层 re-export 身份相等)。, test_chunk_ref_identity_from_models_aggregate(), test_chunk_ref_identity_from_models_knowledge(), test_chunk_ref_identity_from_scrivai_top_level()

### Community 21 - "Hook Implementation"
Cohesion: 0.2
Nodes (2): after_phase(), on_phase_failed()

### Community 22 - "CLI Library Subcommand"
Cohesion: 0.33
Nodes (9): cmd_get(), cmd_list(), cmd_search(), _entry_to_json(), _pick_library(), scrivai-cli library group — search / get / list。, SearchResult 透传所有公开属性(qmd 提供 model_dump 或 dict)。, _resolve_qmd_db() (+1 more)

### Community 23 - "Docx Rendering"
Cohesion: 0.2
Nodes (5): DocxRenderer, DocxRenderer — docxtpl 模板渲染。  约束(docxtpl 限制): 1. 模板必须由 Word/LibreOffice 手工制作(jin, 基于 docxtpl 的 docx 模板渲染器。, 正则扫描模板内全部 {{ var }} 占位符;返回去重排序的 var 名列表。, 渲染模板并写到 output_path;失败不留半成品。          每次 render 重新加载模板(DocxTemplate.render 是一次性消

### Community 24 - "qmd Contract Tests"
Cohesion: 0.2
Nodes (9): M0.75 T0.17 双向契约:验证 qmd 接口未变,scrivai re-export 身份相等。  参考 docs/superpowers/specs/, qmd 顶层必须导出 ChunkRef / SearchResult / CollectionInfo / connect / QmdClient。, scrivai.ChunkRef is qmd.ChunkRef(re-export 身份相等)。, qmd Collection 必须提供:add_document / get_document / list_documents /     delete_do, qmd 基本 CRUD 走通(冒烟,确保升级后契约未变)。, test_qmd_basic_crud_works(), test_qmd_collection_methods_signature(), test_qmd_top_level_symbols_present() (+1 more)

### Community 25 - "CLI Trajectory Subcommand"
Cohesion: 0.33
Nodes (6): cmd_get_run(), cmd_list(), cmd_record_feedback(), scrivai-cli trajectory group — record-feedback / list / get-run / build-eval-dat, _read_json(), _resolve_db()

### Community 26 - "CLI IO Subcommand"
Cohesion: 0.36
Nodes (5): cmd_doc2md(), cmd_docx2md(), cmd_pdf2md(), scrivai-cli io group — docx2md / doc2md / pdf2md / render。, _write_or_echo()

### Community 27 - "Format Conversion (pandoc)"
Cohesion: 0.29
Nodes (7): doc_to_markdown(), docx_to_markdown(), pdf_to_markdown(), 文档格式转换 — pandoc / LibreOffice / MonkeyOCR HTTP。  外部依赖: - pandoc 二进制(docx → markd, pandoc docx → markdown(UTF-8)。      参数:         path: .docx 文件路径     返回:, LibreOffice headless 把 .doc 转成 .docx,再调 docx_to_markdown。      LibreOffice 也能识别, MonkeyOCR HTTP 服务把 PDF 转 markdown。      流程(参考 Reference/smart-construction-ai/cr

### Community 28 - "Evolution Trigger Tests"
Cohesion: 0.5
Nodes (6): _mk_feedback(), _mk_trajectory(), test_collect_failures_failure_threshold(), test_collect_failures_split_deterministic(), test_has_enough_data(), test_trajectory_summary_truncation()

### Community 29 - "Skill Isolation Tests"
Cohesion: 0.25
Nodes (5): M0.75 T0.14 contract test:available-tools/SKILL.md 不能含 workspace/trajectory/io。, Agent 可见命令清单严禁出现 workspace/trajectory/io 子命令(信息隔离边界)。      检查具体的 CLI 子命令名,而不是单词本, 每份 SKILL.md 必须有合法 YAML frontmatter,含 name 和 description。, test_available_tools_does_not_list_workspace_or_trajectory(), test_skill_md_has_required_frontmatter()

### Community 30 - "Evolution Evaluator Tests"
Cohesion: 0.57
Nodes (6): _fake_workspace_create(), _mk_sample(), _mk_version(), test_evaluate_isolated_sample_failure(), test_evaluate_prepares_temp_project_root(), test_evaluate_propagates_budget_exceeded()

### Community 31 - "CLI Entry Point"
Cohesion: 0.43
Nodes (6): build_parser(), _emit_err(), _emit_ok(), main(), scrivai-cli main entry — argparse 路由到 4 个 group。, 失败输出 JSON 到 stderr;exit code 1。

### Community 32 - "Pytest Conftest"
Cohesion: 0.29
Nodes (5): M0 契约测试共享 fixtures。  T0.16(M0.75)将把这里的 fixture "毕业"为 scrivai.testing.contract py, 生成一份合法的 extractor PESConfig YAML 写到 tmp,返回 Path。, 合法 PhaseResult dict,用于 model_dump/model_validate 回环。, sample_pes_config_yaml(), sample_phase_result_dict()

### Community 33 - "MockPES Tests"
Cohesion: 0.67
Nodes (6): _make_config(), _make_workspace(), test_default_outcome_when_not_specified(), test_happy_path_three_phases(), test_injected_failure_triggers_retry(), test_produced_files_created_in_workspace()

### Community 34 - "Evolution Proposer Tests"
Cohesion: 0.48
Nodes (5): _fake_llm_response(), _mk_failure(), test_propose_budget_consumed(), test_propose_parses_n_proposals(), test_propose_prompt_contains_required_elements()

### Community 35 - "PES Config Loader"
Cohesion: 0.4
Nodes (5): _interpolate_env_vars(), load_pes_config(), PESConfig YAML 加载器。  支持: - ${ENV_VAR} 环境变量插值(字符串级) - pydantic schema 校验(失败包装为 PE, 递归把 dict / list / str 中的 ${ENV_VAR} 替换成环境变量值。      缺失环境变量 → PESConfigError(明确报哪个, 加载 PESConfig YAML 并返回解析后的 PESConfig。      异常:       PESConfigError — 文件不存在 / YAM

### Community 36 - "Phase Log Hook"
Cohesion: 0.47
Nodes (3): after_phase(), on_phase_failed(), PhaseLogHook

### Community 37 - "Trajectory Recorder Hook Tests"
Cohesion: 0.73
Nodes (5): _make_config(), _make_turn(), _make_workspace(), test_full_run_recorded(), test_tool_calls_extracted_from_turns()

### Community 38 - "Generate-with-Revision Example"
Cohesion: 0.47
Nodes (5): _cli(), GeneratorOutput, main(), _require_env(), Section

### Community 39 - "M2 Evolution Design Rationale"
Cohesion: 0.33
Nodes (6): M2 自研 Evolution Plan, M2 自研 Evolution Spec, 决策 Q1: 进化粒度 = (PES × skill) 复合键 (rationale), 决策 R2: LLM 调用硬上限 500 (rationale), 决策 X1: 临时 project_root replay (rationale), M2 Skill Evolution 自研

### Community 40 - "Version Health Test"
Cohesion: 0.4
Nodes (3): scrivai.__version__ 健康度(M3a Task 3)。, __version__ 必须与 pyproject.toml [project].version 一致。, test_version_matches_pyproject()

### Community 41 - "Evolution Budget Tests"
Cohesion: 0.4
Nodes (0): 

### Community 42 - "Evolution Promote Tests"
Cohesion: 0.6
Nodes (3): _mk_version(), test_promote_no_backup(), test_promote_writes_snapshot_and_backs_up()

### Community 43 - "Agent YAML Profile Tests"
Cohesion: 0.5
Nodes (3): M0.75 T0.15 contract tests:agents/*.yaml 都能被 load_pes_config 加载。  参考 docs/superp, load_pes_config 加载三份 YAML 全部通过且字段完整。, test_load_pes_config()

### Community 44 - "Example DocxTpl Builder"
Cohesion: 0.5
Nodes (3): build_template(), 构造 docxtpl 最小模板到 OUT_PATH。  单独抽出来是为了避免在 examples/data/ 入库二进制 .docx。, 构造含 3 个占位符的 docxtpl 模板。      参数:         out_path: 输出 .docx 路径,父目录会自动创建。      返回

### Community 45 - "Doc Pipeline E2E Tests"
Cohesion: 0.67
Nodes (4): Doc Pipeline (regex + LLM cleanup module under test), test_pipeline_clean_only (Doc Pipeline E2E), test_pipeline_regex_only (Doc Pipeline E2E), test_pipeline_validation_warnings (Doc Pipeline E2E)

### Community 46 - "Evolution DB Schema"
Cohesion: 1.0
Nodes (1): evolution.db SQL schema(3 表)。  参考 docs/superpowers/specs/2026-04-17-scrivai-m2-d

### Community 47 - "M3a Release Plan"
Cohesion: 1.0
Nodes (2): M3a 最小可用发版 Plan, M3 清理 + 发布

### Community 48 - "TD Document"
Cohesion: 1.0
Nodes (1): Scrivai 任务分解 (TD.md)

### Community 49 - "Design Document"
Cohesion: 1.0
Nodes (1): Scrivai 设计文档 (design.md)

## Knowledge Gaps
- **163 isolated node(s):** `evolution.db SQL schema(3 表)。  参考 docs/superpowers/specs/2026-04-17-scrivai-m2-d`, `Workspace 沙箱相关 pydantic + WorkspaceManager Protocol。  参考 docs/design.md §4.1 / §`, `workspace 快照元信息(写入 meta.json)。`, `对一个已创建 workspace 的引用,业务层与 PES 都通过此对象操作。`, `WorkspaceManager Protocol(M0.25 实现)。` (+158 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Evolution DB Schema`** (2 nodes): `schema.py`, `evolution.db SQL schema(3 表)。  参考 docs/superpowers/specs/2026-04-17-scrivai-m2-d`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `M3a Release Plan`** (2 nodes): `M3a 最小可用发版 Plan`, `M3 清理 + 发布`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `TD Document`** (1 nodes): `Scrivai 任务分解 (TD.md)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Design Document`** (1 nodes): `Scrivai 设计文档 (design.md)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `M2 evolution fixtures。` connect `M2 Evolution Engine` to `PES Config & Workspace Models`, `Core PES Run Models`, `Trajectory Storage`, `Workspace Sandbox`, `Phase Log Hook`, `BasePES Engine`, `Knowledge Libraries (qmd)`, `Docx Rendering`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Why does `WorkspaceHandle` connect `PES Config & Workspace Models` to `M2 Evolution Engine`, `Core PES Run Models`, `Workspace Sandbox`, `Phase Log Hook`, `BasePES Engine`, `BasePES Tests`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `TrajectoryStore` connect `Trajectory Storage` to `M2 Evolution Engine`, `PES Config & Workspace Models`, `LLM Client Layer`, `BasePES Engine`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 128 inferred relationships involving `WorkspaceHandle` (e.g. with `M2 evolution fixtures。` and `PhaseOutcome`) actually correct?**
  _`WorkspaceHandle` has 128 INFERRED edges - model-reasoned connections that need verification._
- **Are the 109 inferred relationships involving `PhaseResult` (e.g. with `ScrivaiError` and `PESConfigError`) actually correct?**
  _`PhaseResult` has 109 INFERRED edges - model-reasoned connections that need verification._
- **Are the 104 inferred relationships involving `PESConfig` (e.g. with `M2 evolution fixtures。` and `PhaseOutcome`) actually correct?**
  _`PESConfig` has 104 INFERRED edges - model-reasoned connections that need verification._
- **Are the 100 inferred relationships involving `ModelConfig` (e.g. with `M2 evolution fixtures。` and `PhaseOutcome`) actually correct?**
  _`ModelConfig` has 100 INFERRED edges - model-reasoned connections that need verification._