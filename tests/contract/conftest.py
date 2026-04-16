"""M0 契约测试共享 fixtures。

T0.16(M0.75)将把这里的 fixture "毕业"为 scrivai.testing.contract pytest plugin
供下游(GovDoc 等)直接复用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest


@pytest.fixture
def sample_pes_config_yaml(tmp_path: Path) -> Path:
    """生成一份合法的 extractor PESConfig YAML 写到 tmp,返回 Path。"""
    yaml_text = """\
name: extractor
display_name: 通用条目抽取
prompt_text: |
  You are a structured information extractor.
default_skills:
  - available-tools
phases:
  plan:
    additional_system_prompt: "draft an extraction strategy."
    allowed_tools: [Bash, Read, Write]
    max_turns: 6
    max_retries: 1
    permission_mode: default
    required_outputs: [plan.md, plan.json]
  execute:
    additional_system_prompt: "execute plan.json."
    allowed_tools: [Bash, Read, Write]
    max_turns: 30
    max_retries: 1
    permission_mode: default
    required_outputs:
      - {path: "findings/", min_files: 1, pattern: "*.json"}
  summarize:
    additional_system_prompt: "aggregate."
    allowed_tools: [Bash, Read, Write]
    max_turns: 4
    max_retries: 1
    permission_mode: default
    required_outputs: [output.json]
"""
    p = tmp_path / "extractor.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    return p


@pytest.fixture
def sample_phase_result_dict() -> dict[str, Any]:
    """合法 PhaseResult dict,用于 model_dump/model_validate 回环。"""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "phase": "plan",
        "attempt_no": 0,
        "prompt": "you are a planner.",
        "response_text": "{}",
        "turns": [],
        "produced_files": ["plan.md", "plan.json"],
        "usage": {"input_tokens": 100, "output_tokens": 200},
        "started_at": now,
        "ended_at": now,
        "error": None,
        "error_type": None,
        "is_retryable": False,
    }


@pytest.fixture
def env_var_set(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str], None]:
    """提供一个可设置环境变量并自动恢复的辅助。"""

    def _set(key: str, value: str) -> None:
        monkeypatch.setenv(key, value)

    return _set
