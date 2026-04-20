"""契约测试:external_cli_tools 白名单机制。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from scrivai.models.pes import PESConfig, PhaseConfig
from scrivai.models.workspace import WorkspaceHandle, WorkspaceSnapshot
from scrivai.testing.mock_pes import MockPES, PhaseOutcome


def _phase(name: str) -> PhaseConfig:
    return PhaseConfig(name=name, allowed_tools=["Bash", "Read"], required_outputs=[])


def _three_phases() -> dict:
    return {
        "plan": _phase("plan"),
        "execute": _phase("execute"),
        "summarize": _phase("summarize"),
    }


def test_pes_config_accepts_external_cli_tools() -> None:
    """PESConfig 应接受 external_cli_tools 字段。"""
    cfg = PESConfig(
        name="auditor",
        prompt_text="system prompt",
        phases=_three_phases(),
        external_cli_tools=["qmd search --collection tender_001"],
    )
    assert cfg.external_cli_tools == [
        "qmd search --collection tender_001",
    ]


def test_pes_config_external_cli_tools_defaults_empty() -> None:
    """不传 external_cli_tools 时默认空列表。"""
    cfg = PESConfig(
        name="auditor",
        prompt_text="system prompt",
        phases=_three_phases(),
    )
    assert cfg.external_cli_tools == []


class TestYamlLoading:
    """YAML 中的 external_cli_tools 字段可被正确加载。"""

    def test_load_with_external_cli_tools(self, tmp_path: Path) -> None:
        yaml_text = """\
name: auditor
prompt_text: "system"
external_cli_tools:
  - "qmd search --collection tender_001"
  - "qmd document get --collection tender_001"
phases:
  plan:
    allowed_tools: [Bash, Read]
    required_outputs: [plan.json]
  execute:
    allowed_tools: [Bash, Read, Write, Grep]
    required_outputs:
      - path: "findings/"
        min_files: 1
        pattern: "*.json"
  summarize:
    allowed_tools: [Bash, Read, Write]
    required_outputs: [output.json]
"""
        p = tmp_path / "auditor.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        from scrivai.pes.config import load_pes_config

        cfg = load_pes_config(p)
        assert cfg.external_cli_tools == [
            "qmd search --collection tender_001",
            "qmd document get --collection tender_001",
        ]

    def test_load_without_external_cli_tools(self, tmp_path: Path) -> None:
        yaml_text = """\
name: auditor
prompt_text: "system"
phases:
  plan:
    allowed_tools: [Bash, Read]
    required_outputs: []
  execute:
    allowed_tools: [Bash, Read]
    required_outputs: []
  summarize:
    allowed_tools: [Bash, Read, Write]
    required_outputs: []
"""
        p = tmp_path / "auditor.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        from scrivai.pes.config import load_pes_config

        cfg = load_pes_config(p)
        assert cfg.external_cli_tools == []


# ---------------------------------------------------------------------------
# Task 2: _resolve_cli_tools merges config + runtime_context
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path) -> WorkspaceHandle:
    root = tmp_path / "ws" / "run-1"
    for d in ("working", "data", "output", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return WorkspaceHandle(
        run_id="run-1",
        root_dir=root,
        working_dir=root / "working",
        data_dir=root / "data",
        output_dir=root / "output",
        logs_dir=root / "logs",
        snapshot=WorkspaceSnapshot(
            run_id="run-1",
            project_root=tmp_path,
            snapshot_at=datetime.now(timezone.utc),
        ),
    )


def _make_config_with_cli_tools(tools: list[str]) -> PESConfig:
    return PESConfig(
        name="auditor",
        prompt_text="system prompt",
        phases={
            "plan": _phase("plan"),
            "execute": _phase("execute"),
            "summarize": _phase("summarize"),
        },
        external_cli_tools=tools,
    )


def _make_pes(
    tmp_path: Path,
    config_tools: list[str],
    runtime_tools: list[str] | None = None,
) -> MockPES:
    rt: dict[str, Any] = {}
    if runtime_tools is not None:
        rt["external_cli_tools"] = runtime_tools
    return MockPES(
        config=_make_config_with_cli_tools(config_tools),
        workspace=_make_workspace(tmp_path),
        runtime_context=rt,
        phase_outcomes={
            "plan": [PhaseOutcome(response_text="ok")],
            "execute": [PhaseOutcome(response_text="ok")],
            "summarize": [PhaseOutcome(response_text="ok")],
        },
    )


class TestResolveCliTools:
    """_resolve_cli_tools should merge config and runtime_context, deduplicated."""

    def test_config_only(self, tmp_path: Path) -> None:
        pes = _make_pes(tmp_path, config_tools=["qmd search --collection rules"])
        result = pes._resolve_cli_tools()
        assert result == ["qmd search --collection rules"]

    def test_runtime_only(self, tmp_path: Path) -> None:
        pes = _make_pes(
            tmp_path,
            config_tools=[],
            runtime_tools=["qmd search --collection tender_001"],
        )
        result = pes._resolve_cli_tools()
        assert result == ["qmd search --collection tender_001"]

    def test_merge_dedup(self, tmp_path: Path) -> None:
        pes = _make_pes(
            tmp_path,
            config_tools=["qmd search --collection rules"],
            runtime_tools=[
                "qmd search --collection rules",
                "qmd search --collection tender_001",
            ],
        )
        result = pes._resolve_cli_tools()
        assert "qmd search --collection rules" in result
        assert "qmd search --collection tender_001" in result
        assert len(result) == 2

    def test_empty_when_none(self, tmp_path: Path) -> None:
        pes = _make_pes(tmp_path, config_tools=[])
        result = pes._resolve_cli_tools()
        assert result == []


# ---------------------------------------------------------------------------
# Task 3: build_phase_prompt injects whitelist
# ---------------------------------------------------------------------------


class TestPromptInjection:
    """external_cli_tools 非空时，build_phase_prompt 应注入工具白名单段落。"""

    @pytest.mark.asyncio
    async def test_tools_injected_into_prompt(self, tmp_path: Path) -> None:
        pes = _make_pes(tmp_path, config_tools=["qmd search --collection tender_001"])
        prompt = await pes.build_phase_prompt(
            phase="execute",
            phase_cfg=pes.config.phases["execute"],
            context={},
            task_prompt="审核招标文书",
        )
        assert "qmd search --collection tender_001" in prompt
        assert "ALLOWED EXTERNAL CLI" in prompt

    @pytest.mark.asyncio
    async def test_no_injection_when_empty(self, tmp_path: Path) -> None:
        pes = _make_pes(tmp_path, config_tools=[])
        prompt = await pes.build_phase_prompt(
            phase="execute",
            phase_cfg=pes.config.phases["execute"],
            context={},
            task_prompt="审核招标文书",
        )
        assert "ALLOWED EXTERNAL CLI" not in prompt
