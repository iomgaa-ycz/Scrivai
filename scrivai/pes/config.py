"""PESConfig YAML loader.

Supports:
- ${ENV_VAR} environment variable interpolation (string level)
- pydantic schema validation (failures wrapped as PESConfigError)
- YAML syntax errors wrapped as PESConfigError
- Missing file wrapped as PESConfigError
"""

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
    """Recursively replace ${ENV_VAR} placeholders in dict / list / str with environment values.

    Raises PESConfigError when an environment variable is missing (naming the missing variable).
    """
    if isinstance(node, str):

        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in os.environ:
                raise PESConfigError(f"environment variable not set: {var_name} (referenced in PESConfig YAML)")
            return os.environ[var_name]

        return ENV_VAR_PATTERN.sub(_replace, node)
    if isinstance(node, dict):
        return {k: _interpolate_env_vars(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_interpolate_env_vars(v) for v in node]
    return node


def load_pes_config(yaml_path: Path) -> PESConfig:
    """Load a PESConfig YAML file and return the parsed PESConfig.

    Raises:
        PESConfigError: File not found, YAML syntax error, missing environment variable,
            or pydantic validation failure.
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise PESConfigError(f"PESConfig YAML file not found: {yaml_path}")

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PESConfigError(f"PESConfig YAML syntax error ({yaml_path}): {e}") from e

    if not isinstance(raw, dict):
        raise PESConfigError(
            f"PESConfig YAML top level must be a mapping, got {type(raw).__name__}: {yaml_path}"
        )

    interpolated = _interpolate_env_vars(raw)

    # Inject each phases dict key as the name field of the corresponding PhaseConfig
    if isinstance(interpolated.get("phases"), dict):
        for phase_name, phase_cfg in interpolated["phases"].items():
            if isinstance(phase_cfg, dict) and "name" not in phase_cfg:
                phase_cfg["name"] = phase_name

    try:
        return PESConfig.model_validate(interpolated)
    except ValidationError as e:
        raise PESConfigError(f"PESConfig schema validation failed ({yaml_path}): {e}") from e
