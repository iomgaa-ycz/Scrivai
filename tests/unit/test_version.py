"""scrivai.__version__ 健康度(M3a Task 3)。"""

from __future__ import annotations


def test_version_exists_and_is_str():
    import scrivai

    assert hasattr(scrivai, "__version__"), "scrivai 必须导出 __version__"
    assert isinstance(scrivai.__version__, str)
    # semver 基本形态校验
    parts = scrivai.__version__.split(".")
    assert len(parts) >= 3
    assert all(p.split("-")[0].isdigit() for p in parts[:3]), (
        f"非 semver 格式: {scrivai.__version__}"
    )


def test_version_matches_pyproject():
    """__version__ 必须与 pyproject.toml [project].version 一致。"""
    import re
    from pathlib import Path

    import scrivai

    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m, "pyproject.toml 未找到 version 字段"
    assert scrivai.__version__ == m.group(1), (
        f"scrivai.__version__={scrivai.__version__} 不匹配 pyproject {m.group(1)}"
    )
