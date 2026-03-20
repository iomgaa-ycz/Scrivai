"""共享测试 fixtures 和配置。

提供真实 LLM 调用测试所需的 fixtures 和 skip 条件。
"""

import os

import pytest
from dotenv import load_dotenv

from scrivai.llm import LLMClient, LLMConfig

# 加载 .env 文件
load_dotenv()


def has_real_api() -> bool:
    """检查是否有可用的真实 API 配置。"""
    return all(os.getenv(k) for k in ["API_KEY", "MODEL_NAME", "BASE_URL"])


# 跳过条件：无 API 配置时跳过
skip_if_no_api = pytest.mark.skipif(
    not has_real_api(),
    reason="需要设置 API_KEY, MODEL_NAME, BASE_URL 环境变量",
)


@pytest.fixture
def real_llm_client() -> LLMClient:
    """创建真实 LLM 客户端（使用 .env 配置）。

    使用低温度和小 max_tokens 确保稳定性和控制成本。
    支持 Claude 协议（anthropic/ 前缀）。
    """
    model_name = os.getenv("MODEL_NAME", "claude-3-5-sonnet-20241022")
    # 为 Claude 协议添加前缀
    if not model_name.startswith("anthropic/"):
        model_name = f"anthropic/{model_name}"

    config = LLMConfig(
        model=model_name,
        temperature=0.3,
        max_tokens=256,
        api_base=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
    )
    return LLMClient(config)


@pytest.fixture
def real_llm_client_long() -> LLMClient:
    """创建支持长响应的真实 LLM 客户端。

    用于需要更长输出的测试（如摘要生成）。
    支持 Claude 协议（anthropic/ 前缀）。
    """
    model_name = os.getenv("MODEL_NAME", "claude-3-5-sonnet-20241022")
    # 为 Claude 协议添加前缀
    if not model_name.startswith("anthropic/"):
        model_name = f"anthropic/{model_name}"

    config = LLMConfig(
        model=model_name,
        temperature=0.3,
        max_tokens=512,
        api_base=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
    )
    return LLMClient(config)
