"""LLMClient 单元测试。

所有测试 mock litellm.completion，不发真实请求。
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

from scrivai.llm import LLMClient, LLMConfig


def _make_config(**overrides) -> LLMConfig:
    """构造测试用 LLMConfig。"""
    defaults = {
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 1024,
        "api_base": None,
        "api_key": None,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _mock_response(content: str) -> MagicMock:
    """构造 litellm 模拟响应。"""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


@patch("scrivai.llm.litellm.completion")
def test_chat_basic(mock_completion):
    """验证消息格式正确传递、返回值正确提取。"""
    mock_completion.return_value = _mock_response("你好世界")
    client = LLMClient(_make_config())

    messages = [{"role": "user", "content": "你好"}]
    result = client.chat(messages)

    assert result == "你好世界"
    call_kwargs = mock_completion.call_args[1]
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["messages"] == messages
    assert call_kwargs["temperature"] == 0.7
    assert call_kwargs["max_tokens"] == 1024


@patch("scrivai.llm.litellm.completion")
def test_chat_with_template_string(mock_completion):
    """模板字符串渲染 + LLM 调用。"""
    mock_completion.return_value = _mock_response("回答")
    client = LLMClient(_make_config())

    result = client.chat_with_template("请分析：{{ topic }}", {"topic": "AI"})

    assert result == "回答"
    sent_content = mock_completion.call_args[1]["messages"][0]["content"]
    assert sent_content == "请分析：AI"


@patch("scrivai.llm.litellm.completion")
def test_chat_with_template_file(mock_completion):
    """从文件路径加载模板 + 渲染 + LLM 调用。"""
    mock_completion.return_value = _mock_response("文件模板回答")
    client = LLMClient(_make_config())

    with tempfile.NamedTemporaryFile(mode="w", suffix=".j2", delete=False, encoding="utf-8") as f:
        f.write("项目名称：{{ name }}")
        tmp_path = f.name

    try:
        result = client.chat_with_template(tmp_path, {"name": "Scrivai"})
        assert result == "文件模板回答"
        sent_content = mock_completion.call_args[1]["messages"][0]["content"]
        assert sent_content == "项目名称：Scrivai"
    finally:
        os.unlink(tmp_path)


@patch("scrivai.llm.litellm.completion")
def test_chat_with_template_variables(mock_completion):
    """复杂变量（dict/list/中文）注入正确。"""
    mock_completion.return_value = _mock_response("ok")
    client = LLMClient(_make_config())

    variables = {
        "items": ["变电站", "输电线路"],
        "meta": {"author": "张三", "version": 2},
    }
    template = "项目：{% for i in items %}{{ i }} {% endfor %}作者：{{ meta.author }}"
    result = client.chat_with_template(template, variables)

    assert result == "ok"
    sent = mock_completion.call_args[1]["messages"][0]["content"]
    assert "变电站" in sent
    assert "输电线路" in sent
    assert "张三" in sent


@patch("scrivai.llm.litellm.completion")
def test_config_api_key_passthrough(mock_completion):
    """api_key 正确传递给 litellm。"""
    mock_completion.return_value = _mock_response("ok")
    client = LLMClient(_make_config(api_key="sk-test-123"))

    client.chat([{"role": "user", "content": "test"}])

    assert mock_completion.call_args[1]["api_key"] == "sk-test-123"


@patch("scrivai.llm.litellm.completion")
def test_config_api_base(mock_completion):
    """自定义 api_base 正确传递。"""
    mock_completion.return_value = _mock_response("ok")
    client = LLMClient(_make_config(api_base="https://custom.api.com/v1"))

    client.chat([{"role": "user", "content": "test"}])

    assert mock_completion.call_args[1]["api_base"] == "https://custom.api.com/v1"
