"""T0.3 契约测试:scrivai.pes.config.load_pes_config。"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_load_minimal_extractor_yaml(sample_pes_config_yaml: Path) -> None:
    """fixture 提供的合法 extractor YAML → 返回 PESConfig 实例。"""
    from scrivai.pes.config import load_pes_config

    cfg = load_pes_config(sample_pes_config_yaml)
    assert cfg.name == "extractor"
    assert "plan" in cfg.phases
    assert "execute" in cfg.phases
    assert "summarize" in cfg.phases
    assert cfg.phases["execute"].required_outputs[0]["path"] == "findings/"


def test_env_var_interpolation(tmp_path: Path, env_var_set) -> None:
    """${ENV_VAR} 替换。"""
    env_var_set("SCRIVAI_TEST_PROMPT", "this is from env")
    yaml_text = """\
name: extractor
prompt_text: "${SCRIVAI_TEST_PROMPT}"
phases:
  plan:
    allowed_tools: [Bash]
    required_outputs: [plan.md]
"""
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    from scrivai.pes.config import load_pes_config

    cfg = load_pes_config(p)
    assert cfg.prompt_text == "this is from env"


def test_env_var_missing_raises_pes_config_error(tmp_path: Path) -> None:
    """缺失环境变量 → PESConfigError(不让模板字符串原样传下去)。"""
    yaml_text = """\
name: extractor
prompt_text: "${SCRIVAI_DEFINITELY_NOT_SET_XYZ}"
phases:
  plan:
    allowed_tools: [Bash]
    required_outputs: [plan.md]
"""
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    from scrivai.exceptions import PESConfigError
    from scrivai.pes.config import load_pes_config

    with pytest.raises(PESConfigError, match="SCRIVAI_DEFINITELY_NOT_SET_XYZ"):
        load_pes_config(p)


def test_schema_validation_error_maps_to_pes_config_error(tmp_path: Path) -> None:
    """缺少必需字段 name → PESConfigError(包装 pydantic ValidationError)。"""
    yaml_text = """\
prompt_text: "no name field"
phases:
  plan:
    allowed_tools: [Bash]
    required_outputs: [plan.md]
"""
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml_text, encoding="utf-8")

    from scrivai.exceptions import PESConfigError
    from scrivai.pes.config import load_pes_config

    with pytest.raises(PESConfigError):
        load_pes_config(p)


def test_yaml_syntax_error_maps_to_pes_config_error(tmp_path: Path) -> None:
    """非法 YAML → PESConfigError。"""
    p = tmp_path / "bad.yaml"
    p.write_text("name: extractor\n  bad indent: : :", encoding="utf-8")

    from scrivai.exceptions import PESConfigError
    from scrivai.pes.config import load_pes_config

    with pytest.raises(PESConfigError):
        load_pes_config(p)


def test_file_not_found_raises_pes_config_error(tmp_path: Path) -> None:
    """文件不存在 → PESConfigError。"""
    from scrivai.exceptions import PESConfigError
    from scrivai.pes.config import load_pes_config

    with pytest.raises(PESConfigError):
        load_pes_config(tmp_path / "does_not_exist.yaml")
