# M0 执行设计 — Scrivai v3 地基层

**日期**: 2026-04-16
**里程碑**: M0(地基层,`feat/scrivai-m0-foundation` 分支)
**参考**:
- `docs/design.md` §4.1 / §4.5 / §4.6(权威契约)
- `docs/TD.md` §M0(任务清单,T0.2 / T0.3 / T0.18 + legacy 清理)
- `CLAUDE.md` §3 SOP(Phase 1 规划 → 等待 → Phase 2 执行)

---

## 1. 摘要

在重命名后的 `feat/scrivai-m0-foundation` 分支上,分 **3 个粗粒度 commit** 完成 M0 地基层:**legacy 清理 + 所有 pydantic / Protocol 模型 + PESConfig YAML 加载器 + Evolution 占位**。目标:`scrivai/models/` 在 `mypy --strict` 下通过,4 个契约测试集全绿,为 M0.25 基础设施层提供稳定契约。

**估时**: 3.3d(对齐 TD.md §M0 估算)

---

## 2. 已决策点(Q1-Q5)

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| Q1 | 分支策略 | **(b) 重命名** `feat/v3-p0-cleanup` → `feat/scrivai-m0-foundation` | docs 打磨与代码契约强耦合,同分支同 PR 审阅上下文最完整 |
| Q2 | pyproject 清理幅度 | **(b) 中等** — 删 `litellm` + `jinja2`,加 `pydantic>=2`,保留 `python-dotenv` | 清晰删除永不回头的 deps;`python-dotenv` 留给 M1 API key 决策时再议 |
| Q3 | `scrivai/exceptions.py` 范围 | **(b) 前置声明** 5 类异常骨架 | 集中可见;后续里程碑只补行为,避免搬家重构 |
| Q4 | conftest.py 重写方式 | **(b) 整体重写** — `tests/conftest.py` 保留 `load_dotenv`;新建 `tests/contract/conftest.py` | 契约 fixtures 集中,未来 T0.16 `scrivai.testing.contract` pytest plugin 可直接"毕业" |
| Q5 | commit 分片 | **(a) 粗粒度** — 3 个 commit | PR diff 整洁;每个 commit 在 M0 DoD 下可独立跑测试验证 |

---

## 3. 拟议变更

### 3.1 Commit 1 `docs: finalize v3 spec`

| 文件 | 动作 | 说明 |
|---|---|---|
| `CLAUDE.md` | `[MODIFY]` | 工作树已改,直接 add |
| `README.md` | `[MODIFY]` | 同上 |
| `docs/design.md` | `[MODIFY]` | 同上 |
| `docs/architecture.md` | `[DELETE]` | 已被 design.md 取代 |
| `docs/sdk_design.md` | `[DELETE]` | 同上 |

本 commit 仅含 docs 改动。

### 3.2 Commit 2 `refactor: clean legacy v2 code for v3 foundation`

#### 3.2.1 删除 legacy 源码

```
scrivai/audit/              [DELETE] 整个目录
scrivai/generation/         [DELETE] 整个目录
scrivai/knowledge/          [DELETE] 整个目录(含 store.py + __init__.py)
scrivai/llm.py              [DELETE]
scrivai/project.py          [DELETE]
scrivai/chunkers.py         [DELETE]
scrivai/utils/              [DELETE] 整个目录(doc_pipeline.py / office_tools.py 等)
```

#### 3.2.2 删除 legacy 测试

```
tests/unit/test_audit.py                              [DELETE]
tests/unit/test_audit_real.py                         [DELETE]
tests/unit/test_chunkers.py                           [DELETE]
tests/unit/test_doc_pipeline.py                       [DELETE]
tests/unit/test_doc_pipeline_real.py                  [DELETE]
tests/unit/test_generation.py                         [DELETE]
tests/unit/test_generation_real.py                    [DELETE]
tests/unit/test_knowledge.py                          [DELETE]
tests/unit/test_llm.py                                [DELETE]
tests/unit/test_llm_real.py                           [DELETE]
tests/unit/test_office_tools.py                       [DELETE]
tests/unit/test_project.py                            [DELETE]
tests/unit/test_project_real.py                       [DELETE]
tests/integration/test_audit_flow.py                  [DELETE]
tests/integration/test_generation_audit_cycle.py      [DELETE]
tests/integration/test_generation_flow.py             [DELETE]
tests/integration/test_multichapter_flow.py           [DELETE]
tests/integration/test_project_sdk_flow.py            [DELETE]
tests/e2e/test_doc_pipeline_e2e.py                    [DELETE]
```

保留空目录与 `__init__.py`(`tests/unit/`,`tests/integration/`,`tests/e2e/`)作为占位。

#### 3.2.3 清空与改写

**`scrivai/__init__.py`** `[MODIFY]`(本 commit 末态,Commit 3 再补回 re-exports):

```python
"""Scrivai v3 — Claude Agent 编排框架(地基层 M0,待 M0.75 冻结对外契约)。"""
```

**`tests/conftest.py`** `[MODIFY]` 重写为最小化:

```python
"""Scrivai 测试根配置——加载 .env(保留为 M1 API key 留接口)。"""
from dotenv import load_dotenv

load_dotenv()
```

#### 3.2.4 `pyproject.toml` `[MODIFY]`

```toml
[project]
version = "0.2.0a0"                            # 跳到 0.2 标识 v3 不兼容
dependencies = [
    "pydantic>=2.6",                            # [ADD] T0.2 必需
    "pyyaml>=6.0",                              # 保留
    "python-dotenv>=1.0",                       # 保留(M1 决策)
    "qmd>=0.1.0",                               # 保留
    # 删除: litellm, jinja2
]
[project.optional-dependencies]
dev = [
    "ruff>=0.4",
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "mypy>=1.10",                               # [ADD] M0 DoD 跑 mypy --strict
]

[tool.mypy]
plugins = ["pydantic.mypy"]                     # [ADD] 规避 pydantic v2 Field 假阳性
strict = true
files = ["scrivai/models"]
```

#### 3.2.5 Commit 2 末态 DoD

- `git grep -E "LLMClient|AuditEngine|GenerationEngine|ProjectConfig|KnowledgeStore" -- scrivai/ tests/` 零结果
- `pytest tests/ -v` 通过(收集到 0 个测试,无 import 报错)
- `pip install -e ".[dev]"` 成功

### 3.3 Commit 3 `feat: add M0 models + config + evolution stubs + contract tests`

本 commit 是 M0 主要工作,按 T0.2 → T0.18 → T0.3 顺序实现(models 先,evolution stubs 次之,因其依赖 `scrivai.models.evolution`;pes.config 最后)。

#### 3.3.1 `scrivai/exceptions.py` `[NEW]`

```python
"""Scrivai 异常层级——M0 前置声明,后续里程碑只补行为。"""


class ScrivaiError(Exception):
    """所有 Scrivai 异常的根基类。"""


class PESConfigError(ScrivaiError):
    """PESConfig YAML 加载 / schema 校验失败。M0 T0.3 实现。"""


class WorkspaceError(ScrivaiError):
    """WorkspaceManager 错误(run_id 冲突 / fcntl 失败等)。M0.25 T0.4 实现。"""


class TrajectoryWriteError(ScrivaiError):
    """TrajectoryStore 写入失败(SQLite busy 超过重试预算)。M0.25 T0.7 实现。"""


class PhaseError(ScrivaiError):
    """BasePES phase 级失败统一出口。携带 result / error_type / is_retryable。M0.5 T0.6 实现。"""


class RateLimitError(ScrivaiError):
    """Claude SDK 速率限制;用于 L1 传输级重试。M0.5 T0.6 实现。"""
```

#### 3.3.2 `scrivai/models/` 子模块 `[NEW]` — T0.2

| 文件 | 导出 |
|---|---|
| `scrivai/models/__init__.py` | 聚合所有 pydantic + Protocol 符号 |
| `scrivai/models/pes.py` | `ModelConfig, PhaseConfig, PESConfig, PhaseTurn, PhaseResult, PESRun` + **9 个 HookContext**:`HookContext, RunHookContext, PhaseHookContext, PromptHookContext, PromptTurnHookContext, FailureHookContext, OutputHookContext, CancelHookContext` |
| `scrivai/models/workspace.py` | `WorkspaceSpec, WorkspaceSnapshot, WorkspaceHandle` + `WorkspaceManager` Protocol |
| `scrivai/models/knowledge.py` | `LibraryEntry` + `Library` Protocol + `from qmd import ChunkRef, SearchResult, CollectionInfo` re-export |
| `scrivai/models/trajectory.py` | `TrajectoryRecord, PhaseRecord, FeedbackRecord` |
| `scrivai/models/evolution.py` | `EvolutionConfig, EvolutionRun, FeedbackExample` + `Evaluator, SkillsRootResolver` Protocol |

**关键字段对齐**(严格对应 `docs/design.md` §4.1):

- `PESRun.status: Literal["running", "completed", "failed", "cancelled"]` + `provider / sdk_version / skills_is_dirty / error_type`
- `PhaseResult.attempt_no: int`,`error_type: str | None`,`is_retryable: bool`;`error_type` 值域 `Literal["sdk_rate_limit", "sdk_other", "max_turns_exceeded", "response_parse_error", "output_validation_error", "cancelled", "hook_error", None]`(M0 定义值域,不校验语义)
- `PhaseHookContext / PromptHookContext / PromptTurnHookContext / FailureHookContext` **全部**含 `attempt_no`;`FailureHookContext` 额外 `will_retry: bool, error_type: str`
- `PhaseConfig.required_outputs: list[str | RequiredOutputRule]`,其中 `RequiredOutputRule = dict`(通过 pydantic `Union` + `discriminator` 或宽松 `Any` dict,M0 取宽松 dict;结构校验延至 M0.5 `validate_phase_outputs`)
- `SkillsRootResolver.__enter__() -> Path`;`__exit__(exc_type, exc_val, exc_tb) -> None`;docstring 明确"不负责 chdir"

**所有字段**配中文 docstring。pydantic 模型开启 `ConfigDict(extra="forbid", frozen=False)`(可变以便 `phase_results` 就地填充)。

#### 3.3.3 `scrivai/pes/config.py` `[NEW]` — T0.3

```python
"""PESConfig YAML 加载器。"""
from pathlib import Path
import os
import re
import yaml
from pydantic import ValidationError

from scrivai.exceptions import PESConfigError
from scrivai.models.pes import PESConfig

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def load_pes_config(yaml_path: Path) -> PESConfig:
    """加载 PESConfig YAML。

    - 支持 `${ENV_VAR}` 环境变量插值(字符串级别递归)
    - 找不到环境变量时抛 PESConfigError
    - YAML 语法错误抛 PESConfigError
    - pydantic schema 校验失败抛 PESConfigError(包装原 ValidationError)

    M0 只实现"加载用户 YAML";内置默认 YAML(对齐 M0.75 T0.15)此时不存在,
    覆盖规则"用户 YAML > 内置默认"在 T0.15 补。
    """
    ...
```

**`scrivai/pes/__init__.py`**:

```python
"""Scrivai PES(Planning-Execute-Summarize)执行引擎。M0 仅含 config 加载器。"""
from scrivai.pes.config import load_pes_config

__all__ = ["load_pes_config"]
```

#### 3.3.4 `scrivai/evolution/` 占位 `[NEW]` — T0.18

```python
# scrivai/evolution/__init__.py
"""Scrivai Evolution — Skill 进化。M0 仅占位,真实实现在 M2。"""
from scrivai.evolution.trigger import EvolutionTrigger
from scrivai.evolution.runner import run_evolution

__all__ = ["EvolutionTrigger", "run_evolution"]


# scrivai/evolution/trigger.py
class EvolutionTrigger:
    """从 TrajectoryStore 构建进化评测集(M2 实现)。"""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("M2 实现")

    def has_enough_data(self):
        raise NotImplementedError("M2 实现")

    def build_eval_dataset(self, *args, **kwargs):
        raise NotImplementedError("M2 实现")


# scrivai/evolution/runner.py
async def run_evolution(*args, **kwargs):
    """EvoSkill 五阶段进化(M2 实现)。"""
    raise NotImplementedError("M2 实现")


# scrivai/evolution/evaluator.py(空占位,M2 实现内置 Evaluator 示例)
"""Evaluator 内置实现(M2)。"""
```

#### 3.3.5 `scrivai/__init__.py` `[MODIFY]` — M0 最终状态

```python
"""Scrivai v3 — Claude Agent 编排框架(M0 地基层)。完整 Public API 在 M0.75 冻结。"""
from qmd import ChunkRef, SearchResult, CollectionInfo
from scrivai.evolution import EvolutionTrigger, run_evolution

__all__ = [
    "ChunkRef",
    "SearchResult",
    "CollectionInfo",
    "EvolutionTrigger",
    "run_evolution",
]
```

#### 3.3.6 契约测试 `[NEW]`

```
tests/contract/__init__.py                                    [NEW] 空
tests/contract/conftest.py                                    [NEW] 共享 fixtures
tests/contract/test_models.py                                 [NEW] T0.2 契约
tests/contract/test_reexport.py                               [NEW] qmd 身份相等
tests/contract/test_pes_config.py                             [NEW] T0.3 契约
tests/contract/test_evolution_stubs.py                        [NEW] T0.18 契约
```

**`tests/contract/conftest.py`** fixtures:

- `sample_pes_config_yaml(tmp_path)` — 写一个合法的 extractor PESConfig YAML 到 tmp
- `sample_phase_result_dict()` — 返回合法 PhaseResult dict(用于 model_dump/model_validate 回环)
- `qmd_chunk_ref_factory()` — 造 ChunkRef 实例

**测试清单**(T0.2 / T0.3 / T0.18 各自 DoD 映射):

| 测试文件 | 测试函数 | 验证点 |
|---|---|---|
| `test_models.py` | `test_all_pydantic_classes_importable` | 从 `scrivai.models.{pes,workspace,knowledge,trajectory,evolution}` 导入所有类不抛错 |
| `test_models.py` | `test_nine_hook_contexts_exist_with_attempt_no` | 9 个 HookContext 全部可构造;4 个带 `attempt_no`;`FailureHookContext` 含 `will_retry`+`error_type` |
| `test_models.py` | `test_pes_run_status_literal` | PESRun.status 只接受 4 值,其他抛 ValidationError |
| `test_models.py` | `test_phase_result_error_type_roundtrip` | `model_dump()` → `model_validate()` 往返稳定(含 attempt_no/error_type/is_retryable) |
| `test_models.py` | `test_required_outputs_mixed_types` | PhaseConfig.required_outputs 同时接受 `"plan.md"` 和 `{"path":"findings/","min_files":1,"pattern":"*.json"}` |
| `test_models.py` | `test_protocols_runtime_checkable` | `Library / WorkspaceManager / Evaluator / SkillsRootResolver` 全部 `@runtime_checkable`,对 stub 类 `isinstance` 生效 |
| `test_reexport.py` | `test_chunk_ref_identity_from_scrivai` | `import scrivai, qmd; assert scrivai.ChunkRef is qmd.ChunkRef` |
| `test_reexport.py` | `test_chunk_ref_identity_from_models` | `from scrivai.models.knowledge import ChunkRef; assert ChunkRef is qmd.ChunkRef` |
| `test_pes_config.py` | `test_load_minimal_extractor_yaml` | 完整 extractor YAML → `load_pes_config` 返回 PESConfig 实例 |
| `test_pes_config.py` | `test_env_var_interpolation` | `${TEST_ENV_VAR}` 被替换;缺失时抛 PESConfigError |
| `test_pes_config.py` | `test_schema_validation_error_maps_to_pes_config_error` | 缺少 `name` 字段 → PESConfigError(不是 pydantic ValidationError 冒泡) |
| `test_pes_config.py` | `test_yaml_syntax_error_maps_to_pes_config_error` | 非法 YAML → PESConfigError |
| `test_evolution_stubs.py` | `test_stub_classes_importable_from_top_level` | `from scrivai import EvolutionTrigger, run_evolution` 不抛错 |
| `test_evolution_stubs.py` | `test_stub_methods_raise_not_implemented_m2` | `EvolutionTrigger()` 与 `await run_evolution()` 抛 `NotImplementedError("M2 实现")` |
| `test_evolution_stubs.py` | `test_skills_root_resolver_protocol_runtime_checkable` | 构造满足 `__enter__/__exit__` 的假类,`isinstance(fake, SkillsRootResolver)` 为 True |
| `test_evolution_stubs.py` | `test_skills_root_resolver_docstring_no_chdir` | Protocol 类与 `__enter__/__exit__` docstring 中不含 `chdir` 字串 |

---

## 4. 验证计划

**本地 DoD 检查命令**(M0 合入 main 前必须全绿):

```bash
conda activate scrivai
pip install -e ".[dev]"

# 1. legacy 清理完整性
git grep -E "LLMClient|AuditEngine|GenerationEngine|ProjectConfig|KnowledgeStore" -- scrivai/ tests/
# 期望:零输出

# 2. 静态类型检查(严格模式 + pydantic plugin)
mypy --strict scrivai/models/
# 期望:Success

# 3. 契约测试
pytest tests/contract/test_models.py \
       tests/contract/test_reexport.py \
       tests/contract/test_pes_config.py \
       tests/contract/test_evolution_stubs.py -v
# 期望:全绿

# 4. 顶层 import 全可用
python - <<'PY'
from scrivai.models.pes import (
    PESRun, PESConfig, PhaseConfig, PhaseResult, PhaseTurn, ModelConfig,
    HookContext, RunHookContext, PhaseHookContext, PromptHookContext,
    PromptTurnHookContext, FailureHookContext, OutputHookContext, CancelHookContext,
)
from scrivai.models.evolution import (
    SkillsRootResolver, EvolutionConfig, EvolutionRun, FeedbackExample, Evaluator,
)
import scrivai
from scrivai import EvolutionTrigger, run_evolution, ChunkRef, SearchResult, CollectionInfo
import qmd
assert scrivai.ChunkRef is qmd.ChunkRef
print("OK")
PY

# 5. Stub 行为
python -c "import asyncio; from scrivai import run_evolution; asyncio.run(run_evolution())" 2>&1 | grep "M2 实现"
# 期望:含 "M2 实现"

# 6. Ruff 格式 + lint
ruff check . --fix && ruff format .
# 期望:no issues
```

---

## 5. 风险识别

| # | 风险 | 缓解 |
|---|---|---|
| 1 | `qmd>=0.1.0` 不在 conda 环境 | 先 `pip list | grep qmd` 核实;缺则 `pip install qmd` |
| 2 | pydantic v2 与 Path/datetime/Literal 序列化 | 契约测试 `test_phase_result_error_type_roundtrip` 用真实时间戳+路径走回环 |
| 3 | `@runtime_checkable` Protocol 结构性匹配陷阱 | 造 stub 类时方法签名齐全;测试明确验证 `isinstance` 行为 |
| 4 | `mypy --strict` 对 pydantic v2 `Field(default_factory=...)` 误报 | pyproject.toml 已加 `[tool.mypy] plugins = ["pydantic.mypy"]` |
| 5 | 分支已重命名但远端仍指旧名 | 不影响本地工作;PR 推送时会自动建立新 upstream |
| 6 | `tests/contract/conftest.py` fixtures 与 T0.16 plugin 冲突 | 设计为纯 fixture(非 plugin-level hook),T0.16 升级时 fixture 可直接迁移到 plugin |

---

## 6. 估时分布

- **Commit 1** (docs): 工作树已就绪,约 0.1d
- **Commit 2** (cleanup + deps + conftest): 0.3d
- **Commit 3** (models + config + evolution + tests):
  - `exceptions.py`: 0.2d
  - `scrivai/models/`(5 子模块 + `__init__.py`): 2.0d
  - `scrivai/pes/config.py` + `scrivai/pes/__init__.py`: 0.5d
  - `scrivai/evolution/` 占位: 0.3d
  - `scrivai/__init__.py` 最终态: 0.1d
  - 4 个契约测试文件 + `tests/contract/conftest.py`: 0.8d
  - 调试回环 + mypy + ruff 打磨: 0.3d

**合计**: ≈3.3d

---

## 7. 后续里程碑预告(仅供参考,M0 不涉及)

- **M0.25**: WorkspaceManager + HookManager + TrajectoryStore 实现(6d)
- **M0.5**: BasePES + MockPES + TrajectoryRecorderHook(6.3d)
- **M0.75**: Knowledge Library + IO + CLI + 通用 Skills/Agents + I0 集成(9d)
- **M1**: 真实 Claude SDK 接入 + 三个预置 PES(~2 周)
- **M2**: EvoSkill + 并发压测(~2 周)
- **M3**: 清理 + 发布(1 周)
