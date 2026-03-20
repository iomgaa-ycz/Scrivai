"""生成引擎端到端流程集成测试。

使用真实 LLM API 验证完整生成流程。
"""

import pytest

from scrivai.generation.context import GenerationContext
from scrivai.generation.engine import GenerationEngine
from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


@skip_if_no_api
class TestGenerationFlow:
    """生成引擎端到端流程测试类。"""

    def test_generation_flow_with_context(self, real_llm_client_long: LLMClient) -> None:
        """验证完整生成流程：摘要 → 术语 → 引用 → 章节。"""
        engine = GenerationEngine(real_llm_client_long)
        ctx = GenerationContext(real_llm_client_long)

        # Phase 1: 生成第一章
        chapter1 = engine.generate_chapter(
            "请用简短的段落介绍{{ project }}的基本情况，包括投资金额和建设周期。",
            {"project": "XX变电站工程"},
        )
        assert len(chapter1) > 10

        # Phase 2: 生成摘要
        summary = ctx.summarize(chapter1)
        assert len(summary) > 5

        # Phase 3: 提取术语
        terms = ctx.extract_terms(chapter1, {})
        assert isinstance(terms, dict)

        # Phase 4: 生成第二章（使用摘要和术语）
        chapter2 = engine.generate_chapter(
            """
前文摘要：{{ summary }}

请基于前文内容，简述{{ project }}的技术方案。
""",
            {"project": "XX变电站工程", "summary": summary},
        )
        assert len(chapter2) > 10

    def test_generation_flow_retrieve_and_generate(self, real_llm_client_long: LLMClient) -> None:
        """验证检索 + 生成（mock qmd）。

        由于 qmd 需要 mock，这里验证 GenerationEngine 的检索接口
        在无知识库时正确抛出异常。
        """
        # 不配置知识库的引擎
        engine = GenerationEngine(real_llm_client_long, store=None)

        # 生成章节（无需检索）
        result = engine.generate_chapter(
            "请写一段关于{{ topic }}的简短介绍。",
            {"topic": "电力工程"},
        )
        assert len(result) > 10

        # 尝试检索应抛出异常（无知识库）
        with pytest.raises(RuntimeError, match="未配置 KnowledgeStore"):
            engine.retrieve_cases("变压器安装")
