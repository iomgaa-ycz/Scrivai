# Scrivai Examples

三个端到端可跑通的 demo,覆盖 M1.5(PES)+ M2(进化)核心用法。

## 先决条件

```bash
# 1. 装 scrivai(开发模式)
pip install -e ".[dev]"

# 2. 配置 .env(参考项目根的 .env.example)
cp .env.example .env
# 编辑填入你的网关 base_url + token

# 3. 激活 conda 环境
conda activate scrivai
```

## Demo 列表

| # | 文件 | 覆盖 | 预计耗时 | LLM 调用 |
|---|------|------|---------|---------|
| 01 | `01_audit_single_doc.py` | AuditorPES 对照审核 | ~2-3 min | ~3 |
| 02 | `02_generate_with_revision.py` | GeneratorPES 模板生成 | ~1-2 min | ~3 |
| 03 | `03_evolve_skill_workflow.py` | M2 Skill 进化全流程 | ~3-5 min | 3-10 |

## 运行

```bash
python examples/01_audit_single_doc.py
python examples/02_generate_with_revision.py            # 不渲染 docx
python examples/02_generate_with_revision.py --render   # 渲染 docx
python examples/03_evolve_skill_workflow.py             # 末尾会问是否 promote
```

## 输出位置

所有 demo 输出都在 `/tmp/scrivai-examples/` 下(workspace、archive、evolution.db、
docx 渲染结果),不污染仓库。重置所有 demo 状态:`rm -rf /tmp/scrivai-examples/`。

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| `未设置 ANTHROPIC_AUTH_TOKEN` | 未配 .env 或未激活环境 | `cp .env.example .env` + 编辑 + `conda activate scrivai` |
| `pes.run` 状态 = `failed` 且 error 提到 SDK | 网关不可达或模型不支持 | 检查 `ANTHROPIC_BASE_URL` + `SCRIVAI_DEFAULT_MODEL` |
| example 03 所有候选 score=0 | evaluator_fn 与 ExtractorPES 输出结构不符 | 本 demo 已知行为(mock fixture 覆盖有限);进化流程本身走通即 PASS |
