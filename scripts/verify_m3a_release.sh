#!/usr/bin/env bash
# M3a 发版前 deprecation 验收脚本。
# 参考 docs/TD.md M3 "Deprecation 验收清单"。
# 使用: bash scripts/verify_m3a_release.sh
# 退出码: 0 = 全部通过;非 0 = 有残留,stderr 打印明细

set -u  # 未定义变量视为错误(-e 会在 grep 无匹配时过早退出)
cd "$(dirname "$0")/.."

fail=0

# 1. 老架构符号(M0 前原型 + M0 占位)必须 0 命中
OLD_SYMBOLS=(
  "LLMConfig" "LLMMessage" "LLMUsage"
  "PromptTemplate" "FewShotTemplate" "OutputParser" "PydanticOutputParser"
  "JsonOutputParser" "RetryingParser" "ExtractChain" "AuditChain" "GenerateChain"
  "ProjectConfig" "KnowledgeStore" "AuditEngine" "AuditResult"
  "GenerationEngine" "GenerationContext" "MockLLMClient" "AgentSession"
  "FeedbackExample" "EvolutionConfig" "SkillsRootResolver"
)
# 豁免说明:
# - "Project\b"    不扫 — 历史名称,当前无同名顶层类(EvolutionProposal 等非同源)
# - "LLMClient\b"  不扫 — scrivai.pes.llm_client.LLMClient 是当前 SDK 封装
# - "LLMResponse\b" 不扫 — scrivai.pes.llm_client.LLMResponse 是当前 SDK 返回数据类(名称复用)
# - "EvolutionRun\b" 不扫 — EvolutionRunRecord / EvolutionRunConfig 是合法前缀

for sym in "${OLD_SYMBOLS[@]}"; do
  hits=$(git grep -l "\\b${sym}\\b" -- 'scrivai/**/*.py' 2>/dev/null | grep -v '^Reference/' || true)
  if [ -n "$hits" ]; then
    echo "FAIL: ${sym} 残留:" >&2
    echo "$hits" >&2
    fail=1
  fi
done

# 2. 业务术语泄漏(scrivai 是通用库,不应含 GovDoc 场景词)
leak=$(git grep -E "招标|政府采购|审核点|底稿|投标人" -- 'scrivai/**/*.py' 2>/dev/null | grep -v 'Reference/' || true)
if [ -n "$leak" ]; then
  echo "FAIL: 业务术语泄漏到 scrivai/:" >&2
  echo "$leak" >&2
  fail=1
fi

# 3. 包目录不应含 .claude/(那是用户工作区目录)
if [ -d scrivai/.claude ]; then
  echo "FAIL: scrivai/.claude 目录不应存在" >&2
  fail=1
fi

# 4. litellm 依赖已移除(pyproject.toml 不应再出现)
if grep -q "litellm" pyproject.toml 2>/dev/null; then
  echo "FAIL: pyproject.toml 仍引用 litellm" >&2
  fail=1
fi

# 5. 核心路径必须可 import
python - <<'PY' || fail=1
import sys
try:
    import scrivai
    from scrivai import (
        ExtractorPES, AuditorPES, GeneratorPES,
        BasePES, ModelConfig,
        run_evolution, promote, SkillVersionStore,
    )
    # LLMClient 不在顶层 __all__,从子模块导入验证
    from scrivai.pes.llm_client import LLMClient
    _ = LLMClient  # silence unused warning
    print(f"OK: scrivai core imports clean (symbols={len(scrivai.__all__)})")
except Exception as e:
    print(f"FAIL: scrivai import broken: {e}", file=sys.stderr)
    sys.exit(1)
PY

if [ $fail -ne 0 ]; then
  echo "" >&2
  echo "=== M3a 发版验收 FAIL ===" >&2
  exit 1
fi
echo "=== M3a 发版验收 PASS ==="
