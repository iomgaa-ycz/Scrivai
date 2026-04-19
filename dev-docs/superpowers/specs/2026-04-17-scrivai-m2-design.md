# M2 — Skill Evolution(自研,替代 EvoSkill)设计文档

**日期**:2026-04-17
**分支**:`feat/scrivai-m2-self-evolution`(从 main 拉,等 M1.5c 合并后开始)
**估时**:~7d
**前置依赖**:M1.5c 已合并到 main(trajectory 反查链、workspace copytree、三个预置 PES)

---

## 1. 背景与范围

### 1.1 M2 的原始定位(来自 TD.md L641-765)

原 M2 计划接通开源 **EvoSkill** 五阶段循环,让 Scrivai 基于积累的 `FeedbackRecord` 自动进化 `SKILL.md`。核心任务 T2.2/T2.2b/T2.3:
- `EvolutionTrigger.build_eval_dataset()` → CSV
- `SkillsRootResolver` 两个内置实现(处理 EvoSkill 硬编码 `<cwd>/.claude/skills/` 的问题)
- `run_evolution()` 调 EvoSkill `LoopAgents`

### 1.2 为什么放弃 EvoSkill(2026-04-17 决策)

重读 EvoSkill 源码(`Reference/EvoSkill/src/`)后确认 8 条根本性不兼容:

| # | 冲突 | EvoSkill 预设 | Scrivai 现实 |
|---|---|---|---|
| 1 | 数据形态 | 静态 CSV benchmark + train/val split | 专家增量反馈,`draft_output` vs `final_output` |
| 2 | 进化粒度 | 整个 program(system prompt + 所有 skills) | 要按 PES × 单个 SKILL.md 精细化 |
| 3 | cwd 耦合 | 硬编码 `<cwd>/.claude/skills/` | 我们 skills 在 `skills/`,sandbox 已 copytree 到 `.claude/skills/`;再加一层 EvoSkill 的就是 sandbox 套 sandbox |
| 4 | 版本策略 | 强制 git 分支 `program/iter-*` | 污染主仓;无法进 `evolution.db` 查询 |
| 5 | 评分接口 | `(q, pred, gt) -> float` | 业务评估器只看最终答案,这一条反而契合 |
| 6 | 依赖 | Py 3.12+ + dspy/GEPA + 独立 base_agent | 我们 3.11 + 已有 `BasePES`/`llm_client`,会变两套 agent loop |
| 7 | Proposer 输入 | 只看 failure 样本 | 我们有完整 trajectory 不用浪费 |
| 8 | 触发节奏 | 一次性 benchmark 十几条 | 专家边审边积累 |

### 1.3 M2 新范围

**做**:
- 自研 `scrivai/evolution/` 模块,覆盖 trigger → proposer → evaluator → runner → promote 全链路
- 独立 `~/.scrivai/evolution.db` 持久化版本 DAG
- Evaluator 通过 **准备临时 project_root** 的方式 replay 真实 `ExtractorPES/AuditorPES/GeneratorPES`
- Python SDK 暴露 `scrivai.evolution.promote(version_id)` 供专家手动上线
- 模拟反馈数据 fixture(造 30 条)用于集成测试
- 删 M0 预留的 `SkillsRootResolver` / 旧 `EvolutionConfig` / `FeedbackExample`

**不做**:
- 不做 CLI(promote 走 Python SDK;TD.md `scrivai-cli trajectory build-eval-dataset` 弃)
- 不做自动触发(只留显式 `run_evolution()`;架构预留 hook 给 M3)
- 不做并发压测 & observability(挪到 M3)
- 不搞 "category 分层采样"(per-(PES, skill) 粒度已足够)
- 不搞跨机 skills 快照缓存(MVP 用 shutil.copytree)

### 1.4 成功标准

1. `run_evolution(pes_name="extractor", skill_name="available-tools", ...)` 跑完:
   - baseline_score + 至少 1 个候选 version 入 `evolution.db`
   - 候选若高于 baseline 填入 `best_version_id`
   - LLM 调用数 ≤ 硬上限 500
2. `promote(version_id)` 原子覆盖 `skills/<skill_name>/`,自动备份
3. `FeedbackRecord` → 对应 `TrajectoryRecord.phase_records` 的反查链可工作
4. 模拟反馈 fixture 可重跑,幂等
5. 集成测试在真 GLM-5.1 下绿(≤ 100 LLM calls)
6. 删完 M0 预留后 `scrivai.EvolutionConfig / FeedbackExample / SkillsRootResolver / Evaluator` 不再可 import

---

## 2. 关键决策记录

brainstorm 锁定的 15 个决策点。理由栏引用 `docs/design.md §4.6` 或 `TD.md M2`。

| # | 决策 | 依据 |
|---|---|---|
| Q1 | 进化粒度 = **(PES × skill) 复合键** | 细粒度可溯源;"Extractor 的 search-knowledge" 独立演化 |
| Q2 | 版本存储 = **SQLite DAG**(独立 `~/.scrivai/evolution.db`) | 不污染主仓;能 SQL 查 lineage |
| Q3 | 触发 = **显式 `run_evolution()`** | MVP 可控;M3 再加自动 hook |
| Q4 | Evaluator 签名 = `(question, predicted, ground_truth) -> float` | 专家只标最终答案;中间过程不是标注对象 |
| Q5 | Proposer 输入 = **失败样本 + trajectory + 当前 SKILL.md + 历史被拒 proposals** | 充分利用 trajectory;避免重复犯错 |
| Q6 | 版本存储 = **同时存 content_snapshot(全量) + content_diff(unified diff) + change_summary** | 新版可独立使用 + 能看清新旧差异(参考 OpenSpace `SkillLineage`) |
| Q7 | Base agent = **重跑真实 ExtractorPES/AuditorPES/GeneratorPES** | 评分真实反映业务效果 |
| Q8 | 评测数据来源 = **直接查 `trajectory.db`**,不 dump CSV | 不用 EvoSkill 了,CSV 中间层多余 |
| Q9 | 技术栈 = Py 3.11 + 复用 `scrivai.pes.llm_client`,零 EvoSkill / git / dspy 依赖 | 统一栈 |
| Q10 | 模块拆分 = `models / store / trigger / proposer / evaluator / runner / budget`(7 文件) | 职责单一,便于单测 |
| R1 | 数据库 = **独立 `evolution.db`** | trajectory 管"发生什么",evolution 管"手册怎么演进",分离清楚 |
| R2 | **LLM 调用硬上限 500** | 防失控;超限抛 `BudgetExceededError` |
| R3 | Promote = **Python SDK `scrivai.evolution.promote()`**,非 CLI | 业务方控制 |
| R4 | M0 预留(`SkillsRootResolver / EvolutionConfig / FeedbackExample / Evaluator`)**直接删** | MVP 原则,不搞向后兼容 |
| R5 | 启动燃料 = **自造 mock feedback**(无真实标注) | 用户无标注;fixture 脚本可重跑 |

### 2.1 额外实现决策(不需用户拍板,架构师定)

| # | 决策 | 理由 |
|---|---|---|
| X1 | Evaluator replay 走 "**临时 project_root**" 方案(非 hook 注入 prompt) | 跟真实业务流一致;保真 |
| X2 | 临时 project_root 用 `shutil.copytree(source) + overwrite target skill` | 简单可靠;MVP 不做硬链优化 |
| X3 | Proposer 每次调 LLM 返回 N=3 候选(可配) | 单次 prompt 产多候选节省 call |
| X4 | Frontier 逻辑内嵌 runner.py,不独立模块 | 代码不足百行,无独立必要 |
| X5 | Proposer prompt 走 JSON 模式;LLM 返回 `{"proposals": [...]}` | 结构化,避免正则切分 |
| X6 | 不做 `selection_strategy`(贪心 top-1 父选择) | MVP;M3 按需加 `round_robin / pareto` |
| X7 | 进化期间**不写主仓 `skills/`**,只写 `~/.scrivai/evolution.db` + `/tmp/scrivai-eval-*/`(临时) | 零污染 |
| X8 | `FailureSample` 冗余存 `trajectory_context`(phase_records 摘要),避免 Proposer 再次查 DB | 单向数据流 |
| X9 | `promote()` 默认备份到 `skills/<name>/.backup/evo-<ts>/` | 可回退 |
| X10 | M2 MVP integration test 仅验 `ExtractorPES`(`data_inputs={}`);`AuditorPES/GeneratorPES` 的 `data_inputs` 复原延到 M3 | 减少 fixture 复杂度 |

---

## 3. 系统架构

### 3.1 目录结构(M2 产物)

```
scrivai/evolution/
├── __init__.py              MODIFY:重写 public API 导出
├── models.py                NEW:pydantic 模型(FailureSample/SkillVersion/...)
├── schema.py                NEW:SQL schema 常量字符串
├── store.py                 NEW:SkillVersionStore(evolution.db CRUD)
├── trigger.py               REWRITE:从 trajectory 拉 feedback + 打分分 train/holdout
├── proposer.py              NEW:LLM 生成 N 个候选 SKILL.md 内容
├── evaluator.py             REWRITE:CandidateEvaluator(replay PES)
├── runner.py                REWRITE:run_evolution 总编排 + 内嵌 Frontier
├── budget.py                NEW:LLMCallBudget(limit=500)
└── promote.py               NEW:promote(version_id) SDK 函数

scrivai/models/evolution.py  REWRITE:删旧 5 类,重写 6 类(见 §4.1)

scrivai/__init__.py          MODIFY:重写 evolution 相关 re-exports

tests/contract/
├── test_evolution_models.py       NEW
├── test_evolution_store.py        NEW
├── test_evolution_trigger.py      NEW
├── test_evolution_proposer.py     NEW
├── test_evolution_evaluator.py    NEW
├── test_evolution_budget.py       NEW
└── test_evolution_promote.py      NEW

tests/integration/
└── test_m2_evolution_cycle.py     NEW:真 GLM E2E,≤ 100 LLM calls

tests/fixtures/m2_evolution/
├── __init__.py                      NEW
├── seed_feedback.py                 NEW:造 30 条 mock feedback(每 PES 10)
└── README.md                        NEW

docs/
├── design.md                        MODIFY:§4.6 全面重写(新架构)
└── TD.md                            MODIFY:M2 章节整体重切
```

### 3.2 数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│ 输入:trajectory.db 中已有 FeedbackRecord(pes_name, draft, final)    │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
              ┌──────────────────────────┐
              │  EvolutionTrigger        │
              │  .collect_failures()     │
              │  - get_feedback_pairs()  │
              │  - evaluator_fn 打分     │
              │  - get_run() 取 phase_records
              │  - split train/holdout   │
              └──────────────────────────┘
                           │ list[FailureSample]
                           ▼
       ┌────────────────────────────────────────┐
       │ for iter in max_iterations:            │
       │                                        │
       │   ┌──────────────────────────────┐     │
       │   │ Proposer.propose(N=3)        │     │
       │   │ 输入:当前 SKILL.md +         │     │
       │   │      train failures +        │     │
       │   │      rejected history        │     │
       │   │ 输出:list[EvolutionProposal] │     │
       │   └────────┬─────────────────────┘     │
       │            │ LLM calls: +1             │
       │            ▼                           │
       │   ┌──────────────────────────────┐     │
       │   │ for proposal in proposals:   │     │
       │   │   SkillVersion 入 DB         │     │
       │   │   ┌──────────────────────┐   │     │
       │   │   │ CandidateEvaluator   │   │     │
       │   │   │ .evaluate(version)   │   │     │
       │   │   │ - 建临时 project_root │   │     │
       │   │   │ - 对每条 holdout:    │   │     │
       │   │   │   workspace.create  │   │     │
       │   │   │   pes.run           │   │     │
       │   │   │   evaluator_fn 打分 │   │     │
       │   │   │ - 聚合 EvolutionScore│   │     │
       │   │   └──────────────────────┘   │     │
       │   │   LLM calls: +3×|holdout|    │     │
       │   │   Frontier.update(top_K)     │     │
       │   └──────────────────────────────┘     │
       │                                        │
       │   if budget 耗尽 或 no_improvement 超限:│
       │      break                             │
       └────────────────────────────────────────┘
                           │
                           ▼
              ┌──────────────────────────┐
              │ 返回 EvolutionRunRecord  │
              │ - best_version_id        │
              │ - candidate_version_ids  │
              │ - iterations_history     │
              └──────────────────────────┘
                           │
              (用户人工审查 + 调 promote)
                           ▼
              ┌──────────────────────────┐
              │ promote(version_id)      │
              │ - 读 content_snapshot    │
              │ - 备份 skills/<name>/    │
              │ - 覆盖 skills/<name>/    │
              │ - 标记 promoted_at       │
              └──────────────────────────┘
```

### 3.3 与 EvoSkill / OpenSpace 对比(精简)

| 维度 | EvoSkill | OpenSpace | **Scrivai M2** |
|---|---|---|---|
| 进化类型 | skill_only / prompt_only | FIX / DERIVED / CAPTURED | **FIX only**(M2 MVP) |
| 版本存储 | git 分支 | SQLite DAG | **SQLite DAG**(借鉴 OpenSpace) |
| 触发 | CLI benchmark | 后处理 / 工具降级 / 周期 | **显式 SDK 调用** |
| Base agent | 内置通用 | 用户 agent | **真实业务 PES**(独有) |
| 评分 | `multi_tolerance / LLM judge` | 指标驱动 | **用户 `Evaluator` 函数** |
| 内容差异 | 整段 rewrite | diff | **snapshot + diff 双存**(Q6) |
| 依赖 | dspy/GEPA + git | SQLite + litellm | **零新依赖** |

---

## 4. 数据模型

### 4.1 pydantic 模型(`scrivai/models/evolution.py`,全面重写)

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- trigger 产物 ---

class FailureSample(BaseModel):
    """单条失败样本(来自 trajectory.feedback)。"""
    model_config = ConfigDict(extra="forbid")

    feedback_id: int
    run_id: str
    task_prompt: str                        # 复自 TrajectoryRecord.task_prompt
    question: str                           # 复自 FeedbackRecord.input_summary
    draft_output_str: str                   # json.dumps(draft_output, sort_keys, ensure_ascii=False)
    ground_truth_str: str                   # json.dumps(final_output, ...)
    baseline_score: float                   # evaluator_fn(question, draft_output_str, ground_truth_str)
    confidence: float
    trajectory_summary: dict[str, str]      # {"plan": "<=800字截断", "execute": "...", "summarize": "..."}
    data_inputs: dict[str, Path] = Field(default_factory=dict)
                                            # workspace.data_inputs 快照(M2 MVP 可留空)


# --- 版本 DAG ---

SkillVersionStatus = Literal["draft", "evaluated", "promoted", "rejected"]

class SkillVersion(BaseModel):
    """版本 DAG 中的一个节点。"""
    model_config = ConfigDict(extra="forbid")

    version_id: str                         # "extractor:available-tools:2026-04-17T12:00:00Z:abc123"
    pes_name: str
    skill_name: str
    parent_version_id: Optional[str]        # None = baseline
    content_snapshot: dict[str, str]        # {relative_path: file_content} 全目录快照
    content_diff: str                       # unified diff(baseline 无父则为空字符串)
    change_summary: str                     # LLM 生成的 1-2 句改动描述
    status: SkillVersionStatus = "draft"
    created_at: datetime
    promoted_at: Optional[datetime] = None
    created_by: str                         # "human" | model id,例 "glm-5.1"


# --- Proposer 产物 ---

class EvolutionProposal(BaseModel):
    """Proposer 单次返回的候选方案(未入库,未打分)。"""
    model_config = ConfigDict(extra="forbid")

    new_content_snapshot: dict[str, str]    # 至少包含 SKILL.md
    change_summary: str
    reasoning: str                          # LLM 输出的分析,存档在 SkillVersion 外的日志


# --- Evaluator 产物 ---

class EvolutionScore(BaseModel):
    """候选版本在 hold-out 上的评分结果。"""
    model_config = ConfigDict(extra="forbid")

    version_id: str
    score: float                            # 0.0-1.0,hold-out 所有样本算术平均
    per_sample_scores: list[float]
    hold_out_size: int
    llm_calls_consumed: int                 # 本次 evaluate 消耗的 LLM calls(3 × hold_out_size)
    evaluated_at: datetime


# --- Runner 产物 ---

class EvolutionRunRecord(BaseModel):
    """一次 run_evolution 调用的完整记录。"""
    model_config = ConfigDict(extra="forbid")

    evo_run_id: str
    pes_name: str
    skill_name: str
    config_snapshot: dict[str, Any]         # EvolutionRunConfig.model_dump()
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: Literal["running", "completed", "failed", "budget_exceeded"] = "running"
    baseline_version_id: str
    baseline_score: float
    best_version_id: Optional[str] = None   # score 超过 baseline 才填
    best_score: Optional[float] = None
    candidate_version_ids: list[str] = Field(default_factory=list)
    llm_calls_used: int = 0
    iterations_history: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


# --- Runner 输入配置 ---

class EvolutionRunConfig(BaseModel):
    """run_evolution 输入配置。"""
    model_config = ConfigDict(extra="forbid")

    pes_name: str
    skill_name: str
    max_iterations: int = 5
    n_proposals_per_iter: int = 3
    frontier_size: int = 3
    no_improvement_limit: int = 2
    max_llm_calls: int = 500
    hold_out_ratio: float = Field(default=0.3, ge=0.1, le=0.5)
    min_confidence: float = 0.7
    failure_threshold: float = 0.5
    proposer_model: str = "glm-5.1"
    random_seed: int = 42                   # train/holdout 分割可重复
```

**废弃类型**(`scrivai/models/evolution.py` 重写时删除):
- `FeedbackExample`(被 `FailureSample` 取代)
- `EvolutionConfig`(被 `EvolutionRunConfig` 取代;字段不兼容)
- `EvolutionRun`(被 `EvolutionRunRecord` 取代;字段不兼容)
- `Evaluator` Protocol(下放为 type alias `EvaluatorFn = Callable[[str, str, str], float]`)
- `SkillsRootResolver` Protocol(整个移除,不需要)

### 4.2 evolution.db schema(`scrivai/evolution/schema.py`)

```sql
-- 技能版本表(DAG 节点)
CREATE TABLE IF NOT EXISTS skill_versions (
    version_id              TEXT PRIMARY KEY,
    pes_name                TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    parent_version_id       TEXT,
    content_snapshot_json   TEXT NOT NULL,      -- dict[relpath, content]
    content_diff            TEXT NOT NULL,      -- unified diff
    change_summary          TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK(status IN
                            ('draft','evaluated','promoted','rejected')),
    created_at              TEXT NOT NULL,      -- ISO UTC
    promoted_at             TEXT,
    created_by              TEXT NOT NULL,
    FOREIGN KEY(parent_version_id) REFERENCES skill_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_skill_versions_pes_skill
    ON skill_versions(pes_name, skill_name);
CREATE INDEX IF NOT EXISTS idx_skill_versions_parent
    ON skill_versions(parent_version_id);

-- 每次 run_evolution 的元信息
CREATE TABLE IF NOT EXISTS evolution_runs (
    evo_run_id              TEXT PRIMARY KEY,
    pes_name                TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    config_snapshot_json    TEXT NOT NULL,
    started_at              TEXT NOT NULL,
    completed_at            TEXT,
    status                  TEXT NOT NULL CHECK(status IN
                            ('running','completed','failed','budget_exceeded')),
    baseline_version_id     TEXT NOT NULL,
    baseline_score          REAL NOT NULL,
    best_version_id         TEXT,
    best_score              REAL,
    llm_calls_used          INTEGER NOT NULL DEFAULT 0,
    candidate_version_ids_json TEXT NOT NULL,   -- JSON array
    iterations_history_json TEXT NOT NULL,
    error                   TEXT,
    FOREIGN KEY(baseline_version_id) REFERENCES skill_versions(version_id),
    FOREIGN KEY(best_version_id) REFERENCES skill_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_pes_skill
    ON evolution_runs(pes_name, skill_name);

-- 每个候选 version 的 hold-out 评分
CREATE TABLE IF NOT EXISTS evolution_scores (
    score_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id              TEXT NOT NULL,
    evo_run_id              TEXT NOT NULL,
    score                   REAL NOT NULL,
    per_sample_scores_json  TEXT NOT NULL,      -- JSON array of floats
    hold_out_size           INTEGER NOT NULL,
    llm_calls_consumed      INTEGER NOT NULL,
    evaluated_at            TEXT NOT NULL,
    FOREIGN KEY(version_id) REFERENCES skill_versions(version_id),
    FOREIGN KEY(evo_run_id) REFERENCES evolution_runs(evo_run_id)
);
CREATE INDEX IF NOT EXISTS idx_evolution_scores_version
    ON evolution_scores(version_id);
```

**默认 DB 路径**:`~/.scrivai/evolution.db`(由 `SkillVersionStore()` 无参构造时 expand);测试用 `SkillVersionStore(db_path=tmp_path/"evo.db")` 覆盖。

---

## 5. API 契约

### 5.1 EvolutionTrigger

```python
class EvolutionTrigger:
    def __init__(
        self,
        trajectory_store: TrajectoryStore,
        pes_name: str,
        skill_name: str,
        evaluator_fn: Callable[[str, str, str], float],
        min_confidence: float = 0.7,
        failure_threshold: float = 0.5,
    ) -> None: ...

    def has_enough_data(self, min_samples: int = 10) -> bool:
        """符合 min_confidence 的 feedback 条数 >= min_samples。"""

    def collect_failures(
        self,
        hold_out_ratio: float = 0.3,
        random_seed: int = 42,
    ) -> tuple[list[FailureSample], list[FailureSample]]:
        """返回 (train_failures, hold_out_samples)。

        - train_failures: baseline_score < failure_threshold 的样本(Proposer 用)
        - hold_out_samples: 从所有满足 min_confidence 的样本随机抽,**不限是否失败**
          (Evaluator replay 用;含成功样本是为了防过拟合到失败)
        """
```

### 5.2 Proposer

```python
class Proposer:
    def __init__(
        self,
        llm_client: LLMClient,
        model: str = "glm-5.1",
    ) -> None: ...

    def propose(
        self,
        current_skill_snapshot: dict[str, str],   # 当前 SKILL.md 目录快照
        failures: list[FailureSample],
        rejected_proposals: list[EvolutionProposal],   # 之前打分低的,避免重复
        n: int = 3,
        budget: LLMCallBudget | None = None,
    ) -> list[EvolutionProposal]:
        """单次 LLM 调用产出 N 个候选 SKILL.md 内容。

        budget 非空时自动 consume(1),超额抛 BudgetExceededError。
        """
```

### 5.3 CandidateEvaluator

```python
class CandidateEvaluator:
    def __init__(
        self,
        workspace_mgr: WorkspaceManager,
        pes_factory: Callable[[str, WorkspaceHandle], BasePES],
        evaluator_fn: Callable[[str, str, str], float],
        source_project_root: Path,             # 业务方 skills/agents 的根
        budget: LLMCallBudget,
    ) -> None: ...

    async def evaluate(
        self,
        version: SkillVersion,
        hold_out: list[FailureSample],
    ) -> EvolutionScore:
        """对候选 version 在 hold_out 上打分。

        每条 sample 消耗 3 LLM calls(plan+execute+summarize)。
        """
```

### 5.4 run_evolution(总编排)

```python
async def run_evolution(
    config: EvolutionRunConfig,
    trajectory_store: TrajectoryStore,
    workspace_mgr: WorkspaceManager,
    pes_factory: Callable[[str, WorkspaceHandle], BasePES],
    evaluator_fn: Callable[[str, str, str], float],
    source_project_root: Path,
    llm_client: LLMClient,
    version_store: SkillVersionStore | None = None,  # 默认 ~/.scrivai/evolution.db
) -> EvolutionRunRecord:
    """执行一次完整进化循环。"""
```

### 5.5 Promote(Python SDK)

```python
def promote(
    version_id: str,
    source_project_root: Path,
    version_store: SkillVersionStore | None = None,
    backup: bool = True,
) -> Path:
    """把 version 的 content_snapshot 写入 source_project_root/skills/<skill_name>/。

    - backup=True 时把当前内容备份到 skills/<skill_name>/.backup/evo-<ts>/
    - 更新 SkillVersion.status = 'promoted' + promoted_at = now()
    - 返回备份目录路径(未备份返回新 skill 目录路径)
    """
```

### 5.6 LLMCallBudget

```python
class BudgetExceededError(Exception): ...

class LLMCallBudget:
    def __init__(self, limit: int = 500) -> None: ...

    def consume(self, n: int = 1) -> None:
        """>= limit 时抛 BudgetExceededError。"""

    @property
    def remaining(self) -> int: ...
    @property
    def used(self) -> int: ...
    @property
    def is_exhausted(self) -> bool: ...
```

### 5.7 SkillVersionStore

```python
class SkillVersionStore:
    def __init__(self, db_path: Path | None = None) -> None: ...

    # skill_versions
    def save_version(self, version: SkillVersion) -> None: ...
    def get_version(self, version_id: str) -> SkillVersion: ...
    def list_versions(
        self, pes_name: str, skill_name: str, status: str | None = None
    ) -> list[SkillVersion]: ...
    def get_baseline(
        self, pes_name: str, skill_name: str, source_project_root: Path
    ) -> SkillVersion:
        """没有 baseline 就从 source_project_root/skills/<skill_name>/ 生成一个。"""
    def update_version_status(
        self, version_id: str, status: SkillVersionStatus
    ) -> None: ...
    def mark_promoted(self, version_id: str) -> None: ...

    # evolution_runs
    def create_run(self, record: EvolutionRunRecord) -> None: ...
    def finalize_run(self, record: EvolutionRunRecord) -> None: ...
    def get_run(self, evo_run_id: str) -> EvolutionRunRecord: ...

    # evolution_scores
    def record_score(self, score: EvolutionScore, evo_run_id: str) -> None: ...
    def get_scores_for_version(self, version_id: str) -> list[EvolutionScore]: ...
```

---

## 6. 关键实现要点

### 6.1 临时 project_root(Evaluator replay 的核心机制)

```
CandidateEvaluator.evaluate(version, hold_out):

   1. 准备临时目录:
      temp_root = Path(tempfile.mkdtemp(prefix=f"scrivai-eval-{version_id}-"))

   2. 完整复制 source_project_root 内容到 temp_root:
      shutil.copytree(source_project_root, temp_root, dirs_exist_ok=True)

   3. 覆盖 target skill:
      target_dir = temp_root / "skills" / version.skill_name
      shutil.rmtree(target_dir)
      target_dir.mkdir()
      for relpath, content in version.content_snapshot.items():
          (target_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
          (target_dir / relpath).write_text(content, encoding="utf-8")

   4. 对每条 sample:
      workspace = workspace_mgr.create(WorkspaceSpec(
          run_id=f"eval-{version_id}-{idx}",
          project_root=temp_root,         ← 关键:用临时 root
          data_inputs=sample.data_inputs,
          force=True,
      ))
      pes = pes_factory(version.pes_name, workspace)
      result = await pes.run(sample.task_prompt)
      predicted = json.dumps(result.final_output, sort_keys=True, ensure_ascii=False)
      score = evaluator_fn(sample.question, predicted, sample.ground_truth_str)
      budget.consume(3)
      workspace_mgr.archive(workspace, success=True)   # 可选:评估完归档

   5. 清理临时目录:shutil.rmtree(temp_root, ignore_errors=True)
```

**不变量**:
- 评估期间**不触碰** `source_project_root/skills/`
- 临时目录命名含 version_id,**易追溯失败调试**
- `workspace_mgr.archive` 留痕,便于人工复盘某个候选的 PES 跑法

### 6.2 Proposer prompt 结构

```text
系统:你是 SKILL.md 修订专家。你的工作是提出 N 个改进版 SKILL.md 候选,
      每个候选必须是完整 SKILL.md 内容(不是 diff)。

用户:
## 进化目标
- PES: {pes_name}
- Skill: {skill_name}

## 当前 SKILL.md 全文
```
{current_content}
```

## 失败样本(共 {len(failures)} 条,展示前 {K} 条)
### 样本 1
- 输入:{question}
- 期望:{ground_truth_str}(截断 800 字)
- 当前 Agent 输出:{draft_output_str}(截断 800 字)
- 得分:{baseline_score}
- 执行过程摘要:
  - plan: {trajectory_summary.plan}(截断 500 字)
  - execute: {trajectory_summary.execute}(截断 500 字)
  - summarize: {trajectory_summary.summarize}(截断 500 字)
### 样本 2 ...

## 历史被拒候选(共 {len(rejected)} 条,展示前 3 条 change_summary)
- "简化工具选择流程" - 得分 0.42(低于 baseline 0.55)
- "添加 few-shot 示例" - 得分 0.48
- ...

## 要求
请提出 {N} 个不同方向的改进方案。每个方案要:
1. 针对失败样本的具体问题
2. 不重复已被拒的方向
3. 完整替换 SKILL.md 内容(可保留大部分原文)

以 JSON 格式返回:
```json
{
  "proposals": [
    {
      "change_summary": "一句话概括改动方向",
      "reasoning": "为什么这个改动能解决失败样本",
      "new_content": {
        "SKILL.md": "<完整新内容>"
      }
    },
    ...
  ]
}
```
```

**硬约束**:
- K(展示样本数)默认 = 5(避免 prompt 爆炸)
- 截断保留首尾各一半(中间省略号)
- 返回非合法 JSON 或 proposals 少于 N → 抛 `ProposerError`,runner 记为 `no_improvement_count += 1`

### 6.3 Frontier 策略(内嵌 runner.py)

```python
@dataclass
class Frontier:
    """贪心 top-K 前沿。"""
    size: int
    members: list[tuple[str, float]] = field(default_factory=list)   # (version_id, score)

    def consider(self, version_id: str, score: float) -> bool:
        """若可加入前沿返回 True(已满且 score 低于最低则拒绝)。"""
        if len(self.members) < self.size:
            self.members.append((version_id, score))
            self.members.sort(key=lambda x: -x[1])
            return True
        lowest = self.members[-1][1]
        if score > lowest:
            self.members[-1] = (version_id, score)
            self.members.sort(key=lambda x: -x[1])
            return True
        return False

    def top(self) -> tuple[str, float] | None:
        return self.members[0] if self.members else None
```

父选择策略(MVP)**= 贪心**:每轮总是取 `frontier.top()` 作 parent。

### 6.4 预算追踪

- `LLMCallBudget(500)` 在 `run_evolution` 开头创建
- 注入 `Proposer.propose(budget=...)` 和 `CandidateEvaluator(budget=...)`
- 每次 Proposer 调 LLM consume(1)
- 每次 Evaluator 的一条 sample consume(3)(plan+execute+summarize 各一)
- runner 每轮末检查 `budget.is_exhausted`,真则 break + status = `"budget_exceeded"`

---

## 7. 测试策略

### 7.1 合约测试(每模块一份,总 ~7 文件)

| 文件 | 验证点 |
|---|---|
| `test_evolution_models.py` | pydantic 字段完整 / 序列化 roundtrip / status Literal 约束 |
| `test_evolution_store.py` | SQL schema 可建 / save-get-list roundtrip / lineage 父子链 / status 更新 |
| `test_evolution_trigger.py` | mock store + evaluator_fn → 确认 train/holdout split / failures 筛选 / trajectory_summary 截断 |
| `test_evolution_proposer.py` | mock llm_client → prompt 包含 4 要素(current/failures/rejected/格式) / JSON parse 失败抛 ProposerError |
| `test_evolution_evaluator.py` | mock pes_factory → 验证临时 project_root 结构(target skill 被换,其余完整) / budget 消耗 |
| `test_evolution_budget.py` | consume → 超限抛 / 计数准确 |
| `test_evolution_promote.py` | tmp skills dir + version_snapshot → 写入正确 + 备份存在 + status = promoted |

### 7.2 集成测试

`tests/integration/test_m2_evolution_cycle.py`:
- `@pytest.mark.skipif(not os.getenv("ANTHROPIC_AUTH_TOKEN"))`
- fixture:调用 `seed_feedback.py` 造 mock feedback 到 tmp trajectory.db
- 配置:`EvolutionRunConfig(pes="extractor", skill="available-tools", max_iterations=2, n_proposals=2, max_llm_calls=100)`
- `evaluator_fn = 简单字符串相似度`(如 IoU on keys)
- 断言:
  1. `evolution.db` 有 ≥3 个 `SkillVersion`(1 baseline + ≥2 candidate)
  2. `EvolutionRunRecord.status in {"completed", "budget_exceeded"}`
  3. 至少 1 个 candidate 有 `EvolutionScore`
  4. 输出 Markdown 报告到 `tests/outputs/integration/m2_evolution_<ts>.md`

### 7.3 Mock feedback fixture(`tests/fixtures/m2_evolution/seed_feedback.py`)

**幂等脚本**,每次跑前清空目标 db。

数据结构:每个 PES(Extractor/Auditor/Generator)造 10 条,共 30 条。

每条包含:
- `run_id = f"mock-{pes}-{idx}"`
- `task_prompt`(基于 M1.5c fixture 的变电站主题变体)
- `input_summary`
- `draft_output`(含故意的小瑕疵,如字段缺失 / 表述错误)
- `final_output`(专家修正版,JSON 结构对齐)
- `confidence = random.uniform(0.7, 1.0)`
- 部分样本额外 `start_run/finalize_run + record_phase_end` 写入 phases 表,便于 trigger 的 trajectory_summary 测试
  - 10 条中 3 条含真实 phase_records(固定 id 方便测试)
  - 其余 7 条只有 runs+feedback 两表内容,`trajectory_summary` 为 `{}`

**生成原则**:
1. 每条 pair 的 `draft_output` 与 `final_output` 差异具有可解释的"改进方向"(避免随机噪声)
2. 差异类型分布:字段遗漏 4 条 / 表述错误 3 条 / 结构问题 3 条(每 PES)
3. `input_summary` 是真实可读中文(不是 lorem),LLM Proposer 能理解

---

## 8. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 临时 project_root 建立失败(磁盘/权限) | 中 | Evaluator 捕获 → version.status="rejected" + 记入 history |
| Evaluator 跑 PES 超时或失败(SDK 错误) | 高 | per-sample 独立 try/except;失败样本 score=0;整体 ≥80% 成功视为通过 |
| Proposer 产出非合法 JSON | 中 | 抛 ProposerError → iteration 记 no_improvement;超限 3 次 → `status="failed"` |
| `max_llm_calls=500` 被穿透 | 低 | `LLMCallBudget.consume` 在每次 call 前检查,会早停 |
| 临时目录遗留(异常路径) | 低 | `try/finally` shutil.rmtree;runner 退出前再扫 `/tmp/scrivai-eval-*` 清理 |
| Workspace `force=True` 在并行 evaluate 冲突 | 中 | run_id 含 version_id + idx,天然不碰;MVP 不做并行 evaluate |
| mock feedback 与真实分布差太远 | 高 | integration test 只作 smoke,真实数据集成留 M3;design 文档标明 |
| 主仓 skills 在进化中被其他进程修改 | 低 | MVP 单进程,不处理;需要时可加 fcntl 锁(同 workspace) |
| `promote` 时备份目录过多 | 低 | `.backup/evo-<ts>/` 旁放 README;业务方周期清理;不自动删 |
| `evaluator_fn` 评分不稳定(同输入不同输出) | 中 | 评分器是业务方实现,文档明确要求确定性;测试时用 string IoU 等稳定函数 |

---

## 9. 与现有模块的边界

| 模块 | M2 是否改动 | 关系 |
|---|---|---|
| `scrivai/pes/*` | ❌ | 完全依赖,不改 |
| `scrivai/workspace/*` | ❌ | 完全依赖,不改 |
| `scrivai/trajectory/*` | ❌ | 只读(`get_feedback_pairs / get_run`) |
| `scrivai/agents/*`(三预置 PES) | ❌ | 完全依赖,不改 |
| `skills/*` | ❌ | 进化期间**不写入**;仅 `promote` 显式调用时写 |
| `scrivai/models/evolution.py` | ✅ 全面重写 | 旧 5 类全删 |
| `scrivai/evolution/*` | ✅ 全面重写 | 重写 `trigger/evaluator/runner`,新增 `models/schema/store/proposer/budget/promote` |
| `scrivai/__init__.py` | ✅ | 修改 re-exports(删 SkillsRootResolver 等 4 项;新增 promote/SkillVersion 等) |
| `docs/design.md §4.6` | ✅ | 整节重写,反映新架构 |
| `docs/TD.md M2` | ✅ | 章节重切,T2.1-T2.7 重新映射 |

**新增 public API**(`scrivai/__init__.py` 导出):

```python
from scrivai.evolution import (
    EvolutionTrigger,
    Proposer,
    CandidateEvaluator,
    LLMCallBudget,
    run_evolution,
    promote,
    SkillVersionStore,
)
from scrivai.models.evolution import (
    FailureSample,
    SkillVersion,
    EvolutionProposal,
    EvolutionScore,
    EvolutionRunRecord,
    EvolutionRunConfig,
)
```

**废弃 public API**(从 `scrivai/__init__.py` 移除):
- `FeedbackExample`(替换为 `FailureSample`)
- `EvolutionConfig`(替换为 `EvolutionRunConfig`)
- `EvolutionRun`(替换为 `EvolutionRunRecord`)
- `Evaluator`(替换为 `Callable[[str, str, str], float]`;不再是 Protocol)
- `SkillsRootResolver`(彻底删除)

---

## 10. Deprecation 清单

合入 main 前必须通过:

```bash
# 1. 旧符号在 scrivai 顶层不可 import
for sym in FeedbackExample EvolutionConfig EvolutionRun SkillsRootResolver; do
  python -c "from scrivai import $sym" 2>&1 | grep -q ImportError \
    || { echo "FAIL: $sym 还能 import"; exit 1; }
done

# 2. 旧 Protocol/类在 scrivai.models.evolution 不存在
for sym in FeedbackExample EvolutionConfig EvolutionRun SkillsRootResolver; do
  python -c "from scrivai.models.evolution import $sym" 2>&1 | grep -q ImportError \
    || { echo "FAIL: $sym 还在 models"; exit 1; }
done

# 3. 旧单测已删
[ -f tests/contract/test_skills_resolver.py ] \
  && { echo "FAIL: test_skills_resolver.py 未删"; exit 1; } || true

# 4. evolution 模块 grep 无 EvoSkill / SkillsRootResolver 残留
if git grep -q -i "evoskill\|skillsrootresolver" scrivai/; then
  echo "FAIL: 仍有 evoskill/resolver 残留"; exit 1
fi

echo "Deprecation checks passed."
```

同时 `docs/design.md §4.6` 和 `docs/TD.md M2` 必须同步更新(见 Task 11 of plan)。

---

## 11. 后续演进路线(M3 及以后)

M2 刻意留白的扩展点:

| 扩展 | 何时做 | 实现思路 |
|---|---|---|
| DERIVED 进化类型(多父合成) | M3 | `EvolutionProposal.parent_version_ids: list[str]`;Proposer 额外模式 |
| CAPTURED 进化类型(从成功任务抽新 skill) | M3 | 新增 `CapturePES` 分析成功 trajectory |
| 自动触发(`on_run_finalized` hook) | M3 | `EvolutionScheduler` 观察 feedback 计数 + 质量指标 |
| 跨机 evolution.db 复制 | M3 | 走 qmd 的 sync 通道 |
| LLM judge 型 evaluator | M3 | 内置 `LLMJudgeEvaluator(rubric)` |
| 并发 evaluate 多候选 | M3 | `asyncio.gather` + workspace 独立 run_id 已保证隔离 |
| 版本 prune / GC | M3 | `scrivai.evolution.prune(older_than_days=30, keep_promoted=True)` |

以上不在 M2 范围。

---

## 12. 变更日志

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-04-17 | 本文初稿 | M2 从 EvoSkill 改自研 |
