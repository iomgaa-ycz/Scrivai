"""LLM 客户端模块。

提供 LLMClient 作为 litellm 的薄封装，支持直接对话和 Jinja2 模板渲染。
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import jinja2
import litellm

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM 配置。

    Attributes:
        model: litellm 模型标识，如 "gpt-4o", "deepseek/deepseek-chat"
        temperature: 生成温度
        max_tokens: 最大生成 token 数
        api_base: 自定义 API 端点（可选）
        api_key: API 密钥（可选，也可通过环境变量设置）
    """

    model: str
    temperature: float
    max_tokens: int
    api_base: Optional[str]
    api_key: Optional[str]


class LLMClient:
    """LLM 客户端，封装 litellm 调用和 Jinja2 模板渲染。

    Args:
        config: LLM 配置对象
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def chat(self, messages: list[dict]) -> str:
        """发送消息列表到 LLM，返回生成文本。

        Args:
            messages: OpenAI 格式消息列表，如 [{"role": "user", "content": "..."}]

        Returns:
            LLM 生成的文本内容
        """
        kwargs: dict = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if self._config.api_base:
            kwargs["api_base"] = self._config.api_base
        if self._config.api_key:
            kwargs["api_key"] = self._config.api_key

        logger.debug("LLM 调用: model=%s, messages=%d条", self._config.model, len(messages))
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        logger.debug("LLM 响应: %d字符", len(content) if content else 0)
        return content

    def chat_with_template(self, template: str, variables: dict) -> str:
        """渲染 Jinja2 模板后发送到 LLM。

        Args:
            template: Jinja2 模板字符串，或模板文件路径
            variables: 模板变量字典

        Returns:
            LLM 生成的文本内容
        """
        # Phase 1: 加载模板内容
        if os.path.isfile(template):
            with open(template, encoding="utf-8") as f:
                tpl_str = f.read()
        else:
            tpl_str = template

        # Phase 2: 渲染模板
        rendered = jinja2.Template(tpl_str).render(**variables)

        # Phase 3: 调用 LLM
        messages = [{"role": "user", "content": rendered}]
        return self.chat(messages)
