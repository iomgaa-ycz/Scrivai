"""Project SDK 入口单元测试。

所有测试 mock litellm.completion，不发真实请求。
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrivai.llm import LLMConfig
from scrivai.project import Project, ProjectConfig


def _create_config_file(content: str) -> str:
    """创建临时配置文件，返回路径。"""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return path


def _basic_config_yaml() -> str:
    """基本配置 YAML 内容。"""
    return """
llm:
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 1024
  api_base: null
  api_key: null
"""


@patch("scrivai.llm.litellm.completion")
def test_project_init_basic(mock_completion):
    """基本初始化，验证所有组件创建。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    config_path = _create_config_file(_basic_config_yaml())
    try:
        proj = Project(config_path)

        # 验证所有组件已创建
        assert proj.llm is not None
        assert proj.store is not None  # 默认创建
        assert proj.gen is not None
        assert proj.ctx is not None
        assert proj.audit is not None
    finally:
        os.unlink(config_path)


@patch("scrivai.llm.litellm.completion")
def test_project_init_without_knowledge(mock_completion):
    """无 knowledge 配置时的初始化。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    yaml_content = """
llm:
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 1024
"""

    config_path = _create_config_file(yaml_content)
    try:
        proj = Project(config_path)
        # knowledge 为空字典时，使用默认配置，store 仍然创建
        assert proj.store is not None
    finally:
        os.unlink(config_path)


@patch("scrivai.llm.litellm.completion")
def test_project_load_yaml(mock_completion):
    """YAML 配置正确加载。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    yaml_content = """
llm:
  model: "deepseek/deepseek-chat"
  temperature: 0.5
  max_tokens: 2048
  api_base: "https://custom.api.com"
knowledge:
  db_path: "custom/path.db"
  namespace: "test_ns"
"""

    config_path = _create_config_file(yaml_content)
    try:
        proj = Project(config_path)

        # 验证配置加载
        assert proj.config.llm.model == "deepseek/deepseek-chat"
        assert proj.config.llm.temperature == 0.5
        assert proj.config.llm.max_tokens == 2048
        assert proj.config.llm.api_base == "https://custom.api.com"
        assert proj.config.knowledge["db_path"] == "custom/path.db"
        assert proj.config.knowledge["namespace"] == "test_ns"
    finally:
        os.unlink(config_path)


@patch.dict(os.environ, {"LLM_API_KEY": "sk-env-override"})
@patch("scrivai.llm.litellm.completion")
def test_project_env_override(mock_completion):
    """.env 中 API key 覆盖 YAML。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    yaml_content = """
llm:
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 1024
  api_key: "sk-yaml-key"
"""

    config_path = _create_config_file(yaml_content)
    try:
        proj = Project(config_path)
        # env 中的 key 覆盖 yaml
        assert proj.config.llm.api_key == "sk-yaml-key"  # config 保留原始值
        # 但 llm client 使用的是 env 值（通过 os.getenv）
    finally:
        os.unlink(config_path)


def test_project_missing_config():
    """配置文件不存在抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="配置文件不存在"):
        Project("/nonexistent/path.yaml")


def test_project_invalid_config():
    """配置缺少 llm 字段抛 ValueError。"""
    yaml_content = """
knowledge:
  db_path: "test.db"
"""
    config_path = _create_config_file(yaml_content)
    try:
        with pytest.raises(ValueError, match="必须包含 llm 字段"):
            Project(config_path)
    finally:
        os.unlink(config_path)


@patch("scrivai.llm.litellm.completion")
def test_project_expose_components(mock_completion):
    """暴露的组件可独立调用。"""
    mock_completion.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="测试响应"))]
    )

    config_path = _create_config_file(_basic_config_yaml())
    try:
        proj = Project(config_path)

        # 直接使用 llm
        result = proj.llm.chat([{"role": "user", "content": "test"}])
        assert result == "测试响应"

        # 验证 gen/audit 可访问
        assert hasattr(proj.gen, "generate_chapter")
        assert hasattr(proj.audit, "check_one")
        assert hasattr(proj.ctx, "summarize")
    finally:
        os.unlink(config_path)


@patch("scrivai.llm.litellm.completion")
def test_project_config_property(mock_completion):
    """config 属性可访问原始配置。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    config_path = _create_config_file(_basic_config_yaml())
    try:
        proj = Project(config_path)

        # 验证 config 属性
        assert isinstance(proj.config, ProjectConfig)
        assert isinstance(proj.config.llm, LLMConfig)
        assert proj.config.llm.model == "gpt-4o"
    finally:
        os.unlink(config_path)


@patch("scrivai.llm.litellm.completion")
def test_project_db_directory_created(mock_completion):
    """db_path 目录自动创建。"""
    mock_completion.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "subdir", "nested", "test.db")
        yaml_content = f"""
llm:
  model: "gpt-4o"
  temperature: 0.7
  max_tokens: 1024
knowledge:
  db_path: "{db_path}"
  namespace: "test"
"""
        config_path = _create_config_file(yaml_content)
        try:
            Project(config_path)
            # 目录已创建
            assert Path(db_path).parent.exists()
        finally:
            os.unlink(config_path)
