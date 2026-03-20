"""AuditEngine 单元测试。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scrivai.audit.engine import AuditEngine, AuditResult
from scrivai.knowledge.store import KnowledgeStore, SearchResult
from scrivai.llm import LLMClient

# === Fixtures ===


@pytest.fixture
def mock_llm() -> LLMClient:
    """创建 Mock LLM 客户端。"""
    return MagicMock(spec=LLMClient)


@pytest.fixture
def mock_store() -> KnowledgeStore:
    """创建 Mock 知识库。"""
    return MagicMock(spec=KnowledgeStore)


@pytest.fixture
def engine(mock_llm: LLMClient) -> AuditEngine:
    """创建 AuditEngine 实例（无知识库）。"""
    return AuditEngine(llm=mock_llm, store=None)


@pytest.fixture
def engine_with_store(mock_llm: LLMClient, mock_store: KnowledgeStore) -> AuditEngine:
    """创建 AuditEngine 实例（有知识库）。"""
    return AuditEngine(llm=mock_llm, store=mock_store)


# === AuditResult 测试 ===


def test_result_dataclass() -> None:
    """验证 AuditResult 数据类正确性。"""
    result = AuditResult(
        passed=True,
        severity="error",
        checkpoint_id="struct_completeness",
        chapter_id="ch03",
        finding="结构完整",
        evidence="第3章包含所有必需小节",
        suggestion="",
    )
    assert result.passed is True
    assert result.severity == "error"
    assert result.checkpoint_id == "struct_completeness"
    assert result.chapter_id == "ch03"
    assert result.finding == "结构完整"
    assert result.evidence == "第3章包含所有必需小节"
    assert result.suggestion == ""


# === AuditEngine 初始化测试 ===


def test_engine_init(mock_llm: LLMClient, mock_store: KnowledgeStore) -> None:
    """验证正确初始化。"""
    engine = AuditEngine(llm=mock_llm, store=mock_store)
    assert engine._llm is mock_llm
    assert engine._store is mock_store


def test_engine_init_without_store(mock_llm: LLMClient) -> None:
    """无 store 时也能初始化。"""
    engine = AuditEngine(llm=mock_llm, store=None)
    assert engine._llm is mock_llm
    assert engine._store is None


# === check_one 测试 ===


def test_check_one_basic(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """基本 check_one 流程。"""
    # Setup
    document = "## 第一章 概述\n\n这是测试文档。"
    checkpoint = {
        "id": "test_checkpoint",
        "description": "测试审核",
        "severity": "warning",
        "scope": "full",
    }
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": True,
            "finding": "文档符合要求",
            "evidence": "无问题",
            "suggestion": "",
        }
    )

    # Execute
    result = engine.check_one(document, checkpoint)

    # Verify
    assert result.passed is True
    assert result.checkpoint_id == "test_checkpoint"
    assert result.severity == "warning"
    assert result.chapter_id is None
    mock_llm.chat.assert_called_once()


def test_check_one_with_rules(
    engine_with_store: AuditEngine,
    mock_llm: MagicMock,
    mock_store: MagicMock,
) -> None:
    """带 rule_refs 的审核。"""
    # Setup
    document = "## 测试文档\n\n变压器安装应符合规范。"
    checkpoint = {
        "id": "semantic_check",
        "description": "语义合规检查",
        "severity": "error",
        "scope": "full",
        "rule_refs": [
            {"query": "变压器安装要求"},
        ],
    }
    mock_store.search.return_value = [
        SearchResult(
            content="变压器安装前应进行外观检查",
            metadata={"source": "GB50150", "type": "rule"},
            score=0.9,
        ),
    ]
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": True,
            "finding": "符合要求",
            "evidence": "文档已说明安装规范",
            "suggestion": "",
        }
    )

    # Execute
    result = engine_with_store.check_one(document, checkpoint)

    # Verify
    assert result.passed is True
    mock_store.search.assert_called_once()
    # 验证 prompt 中包含规则内容
    call_args = mock_llm.chat.call_args
    prompt = call_args[0][0][0]["content"]
    assert "GB50150" in prompt


def test_check_one_scope_chapter(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """scope='chapter:ch03' 章节截取。"""
    # Setup - 使用包含 chapter_id 的标题
    document = """## ch01 概述

这是第一章内容。

## ch03 变压器安装

这是第三章内容，包含变压器安装的具体要求。

## ch05 验收

这是第四章内容。
"""
    checkpoint = {
        "id": "chapter_check",
        "description": "章节检查",
        "severity": "info",
        "scope": "chapter:ch03",
    }
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": True,
            "finding": "章节内容符合要求",
            "evidence": "第三章内容完整",
            "suggestion": "",
        }
    )

    # Execute
    result = engine.check_one(document, checkpoint)

    # Verify
    assert result.chapter_id == "ch03"
    # 验证 prompt 中只包含第三章内容
    call_args = mock_llm.chat.call_args
    prompt = call_args[0][0][0]["content"]
    assert "变压器安装" in prompt
    assert "ch01" not in prompt
    assert "ch05" not in prompt


def test_check_one_json_from_code_block(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """从 ```json 提取结果。"""
    # Setup
    document = "测试文档"
    checkpoint = {"id": "test", "severity": "warning", "scope": "full"}
    mock_llm.chat.return_value = """根据审核结果：

```json
{
  "passed": false,
  "finding": "发现问题",
  "evidence": "第3段",
  "suggestion": "需要修改"
}
```
"""

    # Execute
    result = engine.check_one(document, checkpoint)

    # Verify
    assert result.passed is False
    assert result.finding == "发现问题"
    assert result.evidence == "第3段"
    assert result.suggestion == "需要修改"


def test_check_one_invalid_json(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """JSON 解析失败返回默认值。"""
    # Setup
    document = "测试文档"
    checkpoint = {"id": "test", "severity": "error", "scope": "full"}
    mock_llm.chat.return_value = "这不是有效的 JSON 响应"

    # Execute
    result = engine.check_one(document, checkpoint)

    # Verify
    assert result.passed is False
    assert result.finding == "无法解析审核结果"
    assert "请人工复核" in result.suggestion


# === check_many 测试 ===


def test_check_many(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """批量审核正确调用。"""
    # Setup
    document = "测试文档"
    checkpoints = [
        {"id": "cp1", "severity": "error", "scope": "full"},
        {"id": "cp2", "severity": "warning", "scope": "full"},
    ]
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": True,
            "finding": "OK",
            "evidence": "",
            "suggestion": "",
        }
    )

    # Execute
    results = engine.check_many(document, checkpoints)

    # Verify
    assert len(results) == 2
    assert results[0].checkpoint_id == "cp1"
    assert results[1].checkpoint_id == "cp2"
    assert mock_llm.chat.call_count == 2


# === load_checkpoints 测试 ===


def test_load_checkpoints(engine: AuditEngine) -> None:
    """从 YAML 加载配置。"""
    # Setup
    yaml_content = """
checkpoints:
  - id: struct_check
    description: 结构检查
    severity: error
    scope: full
  - id: ref_check
    description: 引用检查
    severity: warning
    scope: full
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()

        # Execute
        checkpoints = engine.load_checkpoints(f.name)

    # Verify
    assert len(checkpoints) == 2
    assert checkpoints[0]["id"] == "struct_check"
    assert checkpoints[1]["id"] == "ref_check"

    # Cleanup
    Path(f.name).unlink()


# === 规则检索测试 ===


def test_retrieve_rules_semantic(
    engine_with_store: AuditEngine,
    mock_store: MagicMock,
) -> None:
    """语义查询规则。"""
    # Setup
    mock_store.search.return_value = [
        SearchResult(
            content="变压器应水平安装",
            metadata={"source": "GB50150", "type": "rule"},
            score=0.9,
        ),
    ]
    rule_refs = [{"query": "变压器安装要求"}]

    # Execute
    rules_text = engine_with_store._retrieve_rules(rule_refs)

    # Verify
    assert "GB50150" in rules_text
    assert "变压器应水平安装" in rules_text
    mock_store.search.assert_called_with(
        "变压器安装要求",
        top_k=3,
        filters={"type": "rule"},
    )


def test_retrieve_rules_exact(
    engine_with_store: AuditEngine,
    mock_store: MagicMock,
) -> None:
    """精确引用规则。"""
    # Setup
    mock_store.search.return_value = [
        SearchResult(
            content="设备安装前应进行检查",
            metadata={"source": "GB50150", "clause_id": "3.2.1", "type": "rule"},
            score=0.95,
        ),
    ]
    rule_refs = [{"source": "GB50150", "clause_id": "3.2.1"}]

    # Execute
    rules_text = engine_with_store._retrieve_rules(rule_refs)

    # Verify
    assert "GB50150 3.2.1" in rules_text
    mock_store.search.assert_called_with(
        "",
        top_k=1,
        filters={"type": "rule", "source": "GB50150", "clause_id": "3.2.1"},
    )


def test_retrieve_rules_no_store(engine: AuditEngine) -> None:
    """无 store 时返回空规则。"""
    # Setup
    rule_refs = [{"query": "测试查询"}]

    # Execute
    rules_text = engine._retrieve_rules(rule_refs)

    # Verify
    assert rules_text == ""


# === 章节提取测试 ===


def test_extract_chapter(engine: AuditEngine) -> None:
    """章节提取逻辑。"""
    # Setup
    document = """## ch01 概述

第一章内容。

## ch03 变压器

这是第三章的具体内容。

## ch05 验收

验收内容。
"""

    # Execute
    chapter_text = engine._extract_chapter(document, "ch03")

    # Verify
    assert "变压器" in chapter_text
    assert "ch01" not in chapter_text
    assert "ch05" not in chapter_text


def test_extract_chapter_not_found(engine: AuditEngine) -> None:
    """章节不存在时返回全文。"""
    # Setup
    document = "## 第一章\n内容"

    # Execute
    chapter_text = engine._extract_chapter(document, "ch99")

    # Verify
    assert chapter_text == document


# === 边界情况测试 ===


def test_check_one_empty_document(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """空文档也能处理。"""
    # Setup
    checkpoint = {"id": "test", "severity": "warning", "scope": "full"}
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": True,
            "finding": "空文档",
            "evidence": "",
            "suggestion": "",
        }
    )

    # Execute
    result = engine.check_one("", checkpoint)

    # Verify
    assert result.passed is True


def test_check_one_missing_optional_fields(engine: AuditEngine, mock_llm: MagicMock) -> None:
    """checkpoint 缺少可选字段时使用默认值。"""
    # Setup
    checkpoint = {"id": "minimal"}  # 只有 id，其他都用默认值
    mock_llm.chat.return_value = json.dumps(
        {
            "passed": False,
            "finding": "测试",
            "evidence": "证据",
            "suggestion": "建议",
        }
    )

    # Execute
    result = engine.check_one("文档", checkpoint)

    # Verify
    assert result.severity == "warning"  # 默认值
    assert result.chapter_id is None  # scope 默认 full


def test_parse_json_response_plain_json(engine: AuditEngine) -> None:
    """纯 JSON 响应（无代码块）也能解析。"""
    # Setup
    response = '{"passed": true, "finding": "OK", "evidence": "", "suggestion": ""}'

    # Execute
    data = engine._parse_json_response(response, {})

    # Verify
    assert data["passed"] is True


def test_parse_json_response_with_json_prefix(engine: AuditEngine) -> None:
    """带 ```json 前缀的代码块也能解析。"""
    # Setup
    response = """```json
{"passed": false, "finding": "问题", "evidence": "位置", "suggestion": "修复"}
```"""

    # Execute
    data = engine._parse_json_response(response, {})

    # Verify
    assert data["passed"] is False
    assert data["finding"] == "问题"
