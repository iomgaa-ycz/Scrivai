"""LLMClient 真实调用测试。

使用真实 LLM API 进行测试，验证实际功能。
"""

import os
import tempfile

from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


@skip_if_no_api
class TestLLMClientReal:
    """LLMClient 真实调用测试类。"""

    def test_real_chat_basic(self, real_llm_client: LLMClient) -> None:
        """验证基本对话功能。"""
        messages = [{"role": "user", "content": "你好，请回复'测试成功'"}]
        result = real_llm_client.chat(messages)

        # 验证：返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 0

    def test_real_chat_with_template(self, real_llm_client: LLMClient) -> None:
        """验证模板渲染 + 调用。"""
        template = "请用一句话解释：{{ topic }}"
        result = real_llm_client.chat_with_template(template, {"topic": "Python"})

        # 验证：返回非空字符串，应包含 Python 相关内容
        assert isinstance(result, str)
        assert len(result) > 10

    def test_real_chat_with_template_file(self, real_llm_client: LLMClient) -> None:
        """验证从模板文件加载 + 渲染 + 调用。"""
        # 创建临时模板文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".j2", delete=False, encoding="utf-8"
        ) as f:
            f.write("项目名称：{{ name }}，版本：{{ version }}")
            tmp_path = f.name

        try:
            result = real_llm_client.chat_with_template(
                tmp_path, {"name": "Scrivai", "version": "1.0"}
            )
            # 验证：返回非空字符串
            assert isinstance(result, str)
            assert len(result) > 0
        finally:
            os.unlink(tmp_path)

    def test_real_chinese_content(self, real_llm_client: LLMClient) -> None:
        """验证中文内容处理。"""
        messages = [{"role": "user", "content": "请用中文回答：1+1等于几？只回答数字。"}]
        result = real_llm_client.chat(messages)

        # 验证：返回包含数字的中文响应
        assert isinstance(result, str)
        assert len(result) > 0
        # 宽松匹配：响应中应包含 2 或 "二"
        assert "2" in result or "二" in result

    def test_real_long_response(self, real_llm_client_long: LLMClient) -> None:
        """验证长响应截断（max_tokens 限制生效）。"""
        # 创建一个可能产生长回复的请求
        messages = [
            {
                "role": "user",
                "content": "请写一个关于机器学习的简短介绍，不超过100字。",
            }
        ]
        result = real_llm_client_long.chat(messages)

        # 验证：返回内容不应过长（max_tokens=512 限制）
        assert isinstance(result, str)
        assert len(result) > 10
        # 粗略检查：512 tokens 约 1500 中文字符
        assert len(result) < 2000
