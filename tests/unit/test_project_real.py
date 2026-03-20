"""Project 真实调用测试。

使用真实 LLM API 验证 SDK 入口功能。
"""

import os
import tempfile

import yaml

from scrivai.project import Project
from tests.conftest import skip_if_no_api


def _get_model_name() -> str:
    """获取带有 anthropic/ 前缀的模型名称。

    litellm 需要此前缀来识别 Claude 协议 API。
    """
    model_name = os.getenv("MODEL_NAME", "claude-3-5-sonnet-20241022")
    if not model_name.startswith("anthropic/"):
        model_name = f"anthropic/{model_name}"
    return model_name


def _get_api_base() -> str:
    """获取 API 基础 URL。

    Claude 协议不需要 /v1 后缀。
    """
    return os.getenv("BASE_URL", "")


@skip_if_no_api
class TestProjectReal:
    """Project 真实调用测试类。"""

    def test_real_project_init(self) -> None:
        """验证真实初始化（使用 .env）。"""
        # 创建临时配置文件
        config = {
            "llm": {
                "model": _get_model_name(),
                "temperature": 0.3,
                "max_tokens": 256,
                "api_base": _get_api_base(),
                "api_key": os.getenv("API_KEY"),
            },
            "knowledge": None,  # 禁用知识库以加快测试
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(config, f)
            tmp_path = f.name

        try:
            project = Project(tmp_path)

            # 验证：组件正确初始化
            assert project.llm is not None
            assert project.gen is not None
            assert project.ctx is not None
            assert project.audit is not None
            # knowledge 设为 None
            assert project.store is None
        finally:
            os.unlink(tmp_path)

    def test_real_project_llm_chat(self) -> None:
        """验证通过 Project.llm 发起对话。"""
        config = {
            "llm": {
                "model": _get_model_name(),
                "temperature": 0.3,
                "max_tokens": 128,
                "api_base": _get_api_base(),
                "api_key": os.getenv("API_KEY"),
            },
            "knowledge": None,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(config, f)
            tmp_path = f.name

        try:
            project = Project(tmp_path)
            result = project.llm.chat([{"role": "user", "content": "你好"}])

            # 验证：返回非空字符串
            assert isinstance(result, str)
            assert len(result) > 0
        finally:
            os.unlink(tmp_path)

    def test_real_project_context_summarize(self) -> None:
        """验证通过 Project.ctx 生成摘要。"""
        config = {
            "llm": {
                "model": _get_model_name(),
                "temperature": 0.3,
                "max_tokens": 256,
                "api_base": os.getenv("BASE_URL"),
                "api_key": os.getenv("API_KEY"),
            },
            "knowledge": None,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(config, f)
            tmp_path = f.name

        try:
            project = Project(tmp_path)
            text = "本项目为XX变电站建设工程，投资5000万元。"
            result = project.ctx.summarize(text)

            # 验证：返回非空字符串摘要
            assert isinstance(result, str)
            assert len(result) > 5
        finally:
            os.unlink(tmp_path)

    def test_real_project_audit_check(self) -> None:
        """验证通过 Project.audit 审核。"""
        config = {
            "llm": {
                "model": _get_model_name(),
                "temperature": 0.3,
                "max_tokens": 256,
                "api_base": os.getenv("BASE_URL"),
                "api_key": os.getenv("API_KEY"),
            },
            "knowledge": None,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(config, f)
            tmp_path = f.name

        try:
            project = Project(tmp_path)
            document = "## 概述\n\n本项目为XX工程。"
            checkpoint = {
                "id": "test_cp",
                "description": "测试审核",
                "prompt_template": "检查是否有内容",
                "severity": "info",
            }
            result = project.audit.check_one(document, checkpoint)

            # 验证：返回 AuditResult
            assert result.checkpoint_id == "test_cp"
            assert isinstance(result.passed, bool)
        finally:
            os.unlink(tmp_path)
