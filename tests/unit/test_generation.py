"""GenerationEngine 和 GenerationContext 单元测试。"""

import logging
from unittest.mock import MagicMock

import pytest

from core.generation import GenerationContext, GenerationEngine
from core.knowledge.store import KnowledgeStore, SearchResult
from core.llm import LLMClient

# =============================================================================
# GenerationEngine 测试
# =============================================================================


class TestGenerationEngine:
    """GenerationEngine 测试类。"""

    def test_engine_init(self) -> None:
        """验证正确初始化。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_store = MagicMock(spec=KnowledgeStore)

        engine = GenerationEngine(llm=mock_llm, store=mock_store)

        assert engine._llm is mock_llm
        assert engine._store is mock_store

    def test_engine_init_without_store(self) -> None:
        """验证无 store 时也能初始化。"""
        mock_llm = MagicMock(spec=LLMClient)

        engine = GenerationEngine(llm=mock_llm)

        assert engine._llm is mock_llm
        assert engine._store is None

    def test_engine_generate_chapter_basic(self) -> None:
        """基本模板渲染 + LLM 调用。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat_with_template.return_value = "生成的章节内容"

        engine = GenerationEngine(llm=mock_llm)
        result = engine.generate_chapter(
            template="模板内容: {{ title }}",
            variables={"title": "测试标题"},
        )

        assert result == "生成的章节内容"
        mock_llm.chat_with_template.assert_called_once_with(
            "模板内容: {{ title }}",
            {"title": "测试标题"},
        )

    def test_engine_generate_chapter_with_complex_vars(self) -> None:
        """复杂变量注入。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat_with_template.return_value = "生成的章节"

        engine = GenerationEngine(llm=mock_llm)
        variables = {
            "user_inputs": {"工程名称": "XX变电站", "电压等级": "110kV"},
            "retrieved_cases": [
                SearchResult(content="案例1", metadata={"type": "case"}, score=0.9)
            ],
            "previous_summary": "前文摘要",
            "glossary": {"术语1": "定义1"},
        }

        result = engine.generate_chapter(template="模板", variables=variables)

        assert result == "生成的章节"
        mock_llm.chat_with_template.assert_called_once_with("模板", variables)

    def test_engine_generate_chapter_from_file(self, tmp_path) -> None:
        """从文件路径加载模板。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat_with_template.return_value = "文件模板生成结果"

        template_file = tmp_path / "chapter.j2"
        template_file.write_text("章节模板: {{ name }}", encoding="utf-8")

        engine = GenerationEngine(llm=mock_llm)
        result = engine.generate_chapter(
            template=str(template_file),
            variables={"name": "测试"},
        )

        assert result == "文件模板生成结果"
        mock_llm.chat_with_template.assert_called_once()

    def test_engine_retrieve_cases(self) -> None:
        """retrieve_cases 调用 KnowledgeStore。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_store = MagicMock(spec=KnowledgeStore)
        mock_store.search.return_value = [
            SearchResult(content="案例1", metadata={"id": "1"}, score=0.9),
            SearchResult(content="案例2", metadata={"id": "2"}, score=0.8),
        ]

        engine = GenerationEngine(llm=mock_llm, store=mock_store)
        results = engine.retrieve_cases(query="测试查询", top_k=3, filters={"type": "case"})

        assert len(results) == 2
        assert results[0].content == "案例1"
        mock_store.search.assert_called_once_with(
            "测试查询",
            top_k=3,
            filters={"type": "case"},
        )

    def test_engine_retrieve_cases_no_store(self) -> None:
        """未配置 store 时抛异常。"""
        mock_llm = MagicMock(spec=LLMClient)
        engine = GenerationEngine(llm=mock_llm)

        with pytest.raises(RuntimeError, match="未配置 KnowledgeStore"):
            engine.retrieve_cases(query="测试")


# =============================================================================
# GenerationContext 测试
# =============================================================================


class TestGenerationContext:
    """GenerationContext 测试类。"""

    def test_context_init(self) -> None:
        """验证正确初始化。"""
        mock_llm = MagicMock(spec=LLMClient)
        ctx = GenerationContext(llm=mock_llm)

        assert ctx._llm is mock_llm

    def test_context_summarize(self) -> None:
        """summarize 调用 LLM 并返回摘要。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = "这是摘要内容"

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.summarize("这是一段需要摘要的长文本...")

        assert result == "这是摘要内容"
        mock_llm.chat.assert_called_once()
        # 验证传入的 prompt 包含模板内容
        call_args = mock_llm.chat.call_args
        prompt = call_args[0][0][0]["content"]
        assert "摘要" in prompt or "200" in prompt

    def test_context_summarize_strips_whitespace(self) -> None:
        """去除首尾空白。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = "  \n摘要内容  \n"

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.summarize("文本")

        assert result == "摘要内容"

    def test_context_extract_terms_basic(self) -> None:
        """解析 JSON 并合并术语表。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '{"术语A": "定义A", "术语B": "定义B"}'

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_terms("文本", {"已有术语": "已有定义"})

        assert "已有术语" in result
        assert "术语A" in result
        assert result["术语A"] == "定义A"

    def test_context_extract_terms_from_code_block(self) -> None:
        """从 ```json 代码块提取。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '```json\n{"新术语": "新定义"}\n```'

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_terms("文本", {})

        assert result == {"新术语": "新定义"}

    def test_context_extract_terms_invalid_json(self, caplog) -> None:
        """无效 JSON 返回原术语表 + 日志。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = "这不是有效的 JSON"

        ctx = GenerationContext(llm=mock_llm)
        with caplog.at_level(logging.WARNING):
            result = ctx.extract_terms("文本", {"已有": "定义"})

        assert result == {"已有": "定义"}
        assert "JSON 解析失败" in caplog.text

    def test_context_extract_terms_non_dict_response(self, caplog) -> None:
        """返回非 dict 时返回原表 + 日志。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '["术语1", "术语2"]'  # 返回 list 而非 dict

        ctx = GenerationContext(llm=mock_llm)
        with caplog.at_level(logging.WARNING):
            result = ctx.extract_terms("文本", {"已有": "定义"})

        assert result == {"已有": "定义"}
        assert "非 dict" in caplog.text

    def test_context_extract_terms_overwrites(self) -> None:
        """新术语覆盖旧定义。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '{"术语A": "新定义"}'

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_terms("文本", {"术语A": "旧定义"})

        assert result["术语A"] == "新定义"

    def test_context_extract_references_basic(self) -> None:
        """解析引用列表。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '[{"source": "ch03", "target": "第2章", "type": "section"}]'

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_references("文本")

        assert len(result) == 1
        assert result[0]["source"] == "ch03"
        assert result[0]["target"] == "第2章"
        assert result[0]["type"] == "section"

    def test_context_extract_references_multiple(self) -> None:
        """提取多个引用。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = """[
            {"source": "ch03", "target": "第2章", "type": "section"},
            {"source": "ch03", "target": "表3-1", "type": "table"},
            {"source": "ch03", "target": "图2-1", "type": "figure"}
        ]"""

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_references("文本")

        assert len(result) == 3
        types = {r["type"] for r in result}
        assert types == {"section", "table", "figure"}

    def test_context_extract_references_empty(self) -> None:
        """无引用时返回空列表。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = "[]"

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_references("文本")

        assert result == []

    def test_context_extract_references_invalid_json(self, caplog) -> None:
        """无效 JSON 返回空列表 + 日志。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = "无效 JSON"

        ctx = GenerationContext(llm=mock_llm)
        with caplog.at_level(logging.WARNING):
            result = ctx.extract_references("文本")

        assert result == []
        assert "JSON 解析失败" in caplog.text

    def test_context_extract_references_filters_invalid(self) -> None:
        """过滤无效引用项。"""
        mock_llm = MagicMock(spec=LLMClient)
        # 包含无效项：缺少 target 和 type
        mock_llm.chat.return_value = """[
            {"source": "ch03", "target": "第2章", "type": "section"},
            {"source": "ch03"},
            {"target": "表3-1"},
            "not a dict"
        ]"""

        ctx = GenerationContext(llm=mock_llm)
        result = ctx.extract_references("文本")

        # 只有第一项有效
        assert len(result) == 1
        assert result[0]["target"] == "第2章"

    def test_context_extract_references_non_list(self, caplog) -> None:
        """返回非 list 时返回空列表 + 日志。"""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.chat.return_value = '{"target": "第2章", "type": "section"}'  # dict 而非 list

        ctx = GenerationContext(llm=mock_llm)
        with caplog.at_level(logging.WARNING):
            result = ctx.extract_references("文本")

        assert result == []
        assert "非 list" in caplog.text
