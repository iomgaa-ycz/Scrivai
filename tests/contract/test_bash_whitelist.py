"""契约测试:external_cli_tools 白名单机制。"""

from __future__ import annotations

from pathlib import Path

from scrivai.models.pes import PESConfig, PhaseConfig


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
