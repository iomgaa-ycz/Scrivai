# CHANGELOG

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [0.2.0] — 2026-04-18

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
- `python -m build` 成功生成 wheel(`dist/scrivai-0.2.0-py3-none-any.whl`,82.8KB,仅 SPDX/license classifier deprecation warning 无 ERROR)
- 干净 venv(Python 3.11.15)从 wheel 装 `[dev]` extras 全部依赖 OK,`scrivai==0.2.0, symbols=63` import 冒烟通过
- 3 examples 全部跑通(scrivai conda env):
    - `01_audit_single_doc.py` → `status=completed`,3 findings(2 合格 / 1 需要澄清),verdict 合法
    - `02_generate_with_revision.py` → `status=completed`,3 placeholder 全部填充
    - `03_evolve_skill_workflow.py` → `status=completed`,evo_run 无增益跳过 promote(符合 demo 预期)

## [0.1.3] — 2026-04-17 之前

M0-M1.5c 各阶段交付,详见 `docs/TD.md` 里程碑记录。
