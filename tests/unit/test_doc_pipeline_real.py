"""MarkdownCleaner LLM 清洗真实调用测试。

使用真实 LLM API 验证清洗功能。
"""

from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api
from utils.doc_pipeline import MarkdownCleaner


@skip_if_no_api
class TestMarkdownCleanerReal:
    """MarkdownCleaner LLM 清洗真实调用测试类。"""

    def test_real_llm_clean_basic(self, real_llm_client_long: LLMClient) -> None:
        """验证基本 LLM 清洗（水印、表格格式）。"""
        cleaner = MarkdownCleaner(llm=real_llm_client_long, chunk_size=1000)

        text = """
## 概述

CHINA SOUTHERN POWER GRID CO., LTD.

本项目为变电站工程。

| 参数 | 值 |
|------|-----|
| 电压 | 110kV |
| 容量 | 120MVA |
"""
        result = cleaner.clean(text)

        # 验证：返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 10
        # 水印应被移除（正则清洗阶段）
        assert "CHINA SOUTHERN POWER GRID" not in result

    def test_real_llm_clean_chunking(self, real_llm_client_long: LLMClient) -> None:
        """验证长文本分块清洗。"""
        cleaner = MarkdownCleaner(llm=real_llm_client_long, chunk_size=500)

        # 创建一个较长的文本以触发分块
        sections = []
        for i in range(5):
            sections.append(f"""
## 第{i + 1}节

这是第{i + 1}节的内容。包含一些技术描述和说明文字。
项目名称为XX变电站工程，建设地点在XX省XX市。
""")
        text = "\n".join(sections)

        result = cleaner.clean(text)

        # 验证：返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 50

    def test_real_llm_clean_post_process(self, real_llm_client_long: LLMClient) -> None:
        """验证后处理（移除对话性前缀）。"""
        cleaner = MarkdownCleaner(llm=real_llm_client_long, chunk_size=1000)

        text = """
## 技术参数

本工程主要技术参数如下：
- 电压等级：110kV
- 主变压器容量：2×120MVA
"""
        result = cleaner.clean(text)

        # 验证：返回非空字符串，不包含对话性前缀
        assert isinstance(result, str)
        assert len(result) > 10
        # 后处理应移除常见前缀
        assert not result.startswith("好的")
        assert not result.startswith("以下是")
        assert not result.startswith("当然")
