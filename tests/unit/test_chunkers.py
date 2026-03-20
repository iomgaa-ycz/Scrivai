"""切片工具单元测试。"""

from scrivai.chunkers import split_by_clause, split_by_heading


class TestSplitByHeading:
    """split_by_heading 测试组。"""

    def test_basic_split(self):
        """基本切分：按 ## 标题分割。"""
        text = """## 第一章 总则

这是第一章内容。

## 第二章 细则

这是第二章内容。"""
        chunks = split_by_heading(text, level=2)

        assert len(chunks) == 2
        assert chunks[0].metadata["heading"] == "第一章 总则"
        assert chunks[1].metadata["heading"] == "第二章 细则"
        assert "第一章内容" in chunks[0].text
        assert "第二章内容" in chunks[1].text

    def test_preserve_heading_context(self):
        """标题上下文保留：标题前的内容独立成片。"""
        text = """前置内容
应该被保留。

## 标题一

内容一。"""
        chunks = split_by_heading(text, level=2)

        assert len(chunks) == 2
        assert chunks[0].metadata["heading"] is None
        assert "前置内容" in chunks[0].text
        assert chunks[1].metadata["heading"] == "标题一"

    def test_empty_text(self):
        """空文本返回空列表。"""
        assert split_by_heading("", level=2) == []
        assert split_by_heading("   \n  ", level=2) == []

    def test_no_heading(self):
        """无标题文本：整段作为一个切片。"""
        text = "纯文本内容，没有标题。"
        chunks = split_by_heading(text, level=2)

        assert len(chunks) == 1
        assert chunks[0].metadata["heading"] is None
        assert chunks[0].text == text

    def test_custom_level(self):
        """自定义标题层级。"""
        text = """### 子标题

内容。"""
        chunks = split_by_heading(text, level=3)

        assert len(chunks) == 1
        assert chunks[0].metadata["heading"] == "子标题"


class TestSplitByClause:
    """split_by_clause 测试组。"""

    def test_default_pattern_chinese(self):
        """默认 pattern：中文条款（第X条）。"""
        text = """第一条 总则内容。

第二条 细则内容。

第三条 附则内容。"""
        chunks = split_by_clause(text)

        assert len(chunks) == 3
        assert chunks[0].metadata["clause_id"] == "第一条"
        assert chunks[1].metadata["clause_id"] == "第二条"
        assert chunks[2].metadata["clause_id"] == "第三条"

    def test_default_pattern_numeric(self):
        """默认 pattern：数字条款（1.1 格式）。"""
        text = """1.1 第一条内容。

1.2 第二条内容。"""
        chunks = split_by_clause(text)

        assert len(chunks) == 2
        assert chunks[0].metadata["clause_id"] == "1.1"
        assert chunks[1].metadata["clause_id"] == "1.2"

    def test_custom_pattern(self):
        """自定义 pattern。"""
        text = """ARTICLE 1: First
ARTICLE 2: Second"""
        chunks = split_by_clause(text, pattern=r"ARTICLE \d+")

        assert len(chunks) == 2
        assert chunks[0].metadata["clause_id"] == "ARTICLE 1"
        assert chunks[1].metadata["clause_id"] == "ARTICLE 2"

    def test_no_match(self):
        """无匹配：整段作为一个切片。"""
        text = "普通文本，没有条款编号。"
        chunks = split_by_clause(text)

        assert len(chunks) == 1
        assert chunks[0].metadata["clause_id"] is None

    def test_empty_text(self):
        """空文本返回空列表。"""
        assert split_by_clause("") == []
        assert split_by_clause("   \n  ") == []

    def test_content_before_first_clause(self):
        """条款前内容独立成片。"""
        text = """前言内容。

第一条 正式条款。"""
        chunks = split_by_clause(text)

        assert len(chunks) == 2
        assert chunks[0].metadata["clause_id"] is None
        assert "前言" in chunks[0].text
        assert chunks[1].metadata["clause_id"] == "第一条"
