"""契约测试:external_cli_tools 白名单机制。"""

from __future__ import annotations

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
