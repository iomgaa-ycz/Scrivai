"""PES configuration YAML loader with environment variable interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scrivai.exceptions import PESConfigError
from scrivai.models.pes import PESConfig

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _interpolate_env_vars(node: Any) -> Any:
    """递归把 dict / list / str 中的 ${ENV_VAR} 替换成环境变量值。

    缺失环境变量 → PESConfigError(明确报哪个变量缺)。
    """
    if isinstance(node, str):

        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in os.environ:
                raise PESConfigError(f"环境变量未设置:{var_name}(在 PESConfig YAML 中引用)")
            return os.environ[var_name]

        return ENV_VAR_PATTERN.sub(_replace, node)
    if isinstance(node, dict):
        return {k: _interpolate_env_vars(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_interpolate_env_vars(v) for v in node]
    return node


def load_pes_config(yaml_path: Path) -> PESConfig:
    """Load and validate a PES configuration from a YAML file.

    The YAML file defines phase configurations, prompt text, default skills,
    and other PES settings. Environment variable interpolation is supported
    using ``${VAR_NAME}`` syntax.

    Args:
        yaml_path: Path to the YAML configuration file.

    Returns:
        A validated ``PESConfig`` instance.

    Raises:
        PESConfigError: If the file doesn't exist, contains invalid YAML,
            references missing environment variables, or fails Pydantic
            validation.

    Example:
        >>> from pathlib import Path
        >>> from scrivai import load_pes_config
        >>> config = load_pes_config(Path("scrivai/agents/extractor.yaml"))
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise PESConfigError(f"PESConfig YAML 文件不存在:{yaml_path}")

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PESConfigError(f"PESConfig YAML 语法错误({yaml_path}):{e}") from e

    if not isinstance(raw, dict):
        raise PESConfigError(
            f"PESConfig YAML 顶层必须是 mapping,得到 {type(raw).__name__}:{yaml_path}"
        )

    interpolated = _interpolate_env_vars(raw)

    # 将 phases dict 的 key 注入为每个 PhaseConfig 的 name 字段
    if isinstance(interpolated.get("phases"), dict):
        for phase_name, phase_cfg in interpolated["phases"].items():
            if isinstance(phase_cfg, dict) and "name" not in phase_cfg:
                phase_cfg["name"] = phase_name

    try:
        return PESConfig.model_validate(interpolated)
    except ValidationError as e:
        raise PESConfigError(f"PESConfig schema 校验失败({yaml_path}):{e}") from e
