"""relaxed_json_loads 单元测试。"""

from __future__ import annotations

import json
import timeit

import pytest

from scrivai.exceptions import ScrivaiError, ScrivaiJSONRepairError


class TestScrivaiJSONRepairError:
    """ScrivaiJSONRepairError 异常类测试。"""

    def test_inherits_scrivai_error(self) -> None:
        err = ScrivaiJSONRepairError(
            msg="test error",
            doc='{"bad}',
            pos=5,
            original_text='{"bad}',
            repaired_text='{"bad}',
            stages_applied=["strip_envelope"],
        )
        assert isinstance(err, ScrivaiError)

    def test_inherits_json_decode_error(self) -> None:
        err = ScrivaiJSONRepairError(
            msg="test error",
            doc='{"bad}',
            pos=5,
            original_text='{"bad}',
            repaired_text='{"bad}',
            stages_applied=["strip_envelope"],
        )
        assert isinstance(err, json.JSONDecodeError)

    def test_attributes(self) -> None:
        err = ScrivaiJSONRepairError(
            msg="parse failed",
            doc='{"bad}',
            pos=5,
            original_text="original",
            repaired_text="repaired",
            stages_applied=["strip_envelope", "normalize_quotes"],
        )
        assert err.original_text == "original"
        assert err.repaired_text == "repaired"
        assert err.stages_applied == ["strip_envelope", "normalize_quotes"]
        assert err.doc == '{"bad}'
        assert err.pos == 5


from scrivai.utils.json_repair import RepairReport, relaxed_json_loads


class TestRelaxedJsonLoadsStrictMode:
    """strict=True 模式测试。"""

    def test_strict_valid_json(self) -> None:
        result = relaxed_json_loads('{"a": 1, "b": 2}', strict=True)
        assert result == {"a": 1, "b": 2}

    def test_strict_invalid_json_raises_json_decode_error(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            relaxed_json_loads('{"a": 1,}', strict=True)

    def test_strict_does_not_raise_scrivai_error(self) -> None:
        with pytest.raises(json.JSONDecodeError) as exc_info:
            relaxed_json_loads('{"a": 1,}', strict=True)
        assert not isinstance(exc_info.value, ScrivaiJSONRepairError)


class TestRelaxedJsonLoadsStage0:
    """Stage-0 快路径:合法 JSON 直通。"""

    def test_valid_object(self) -> None:
        result = relaxed_json_loads('{"a": 1, "b": 2}')
        assert result == {"a": 1, "b": 2}

    def test_valid_array(self) -> None:
        result = relaxed_json_loads('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_valid_json_with_report(self) -> None:
        result, report = relaxed_json_loads(
            '{"a": 1}', return_repair_report=True
        )
        assert result == {"a": 1}
        assert isinstance(report, RepairReport)
        assert report.stages_applied == []
        assert report.original == '{"a": 1}'
        assert report.final == '{"a": 1}'


class TestStage1StripEnvelope:
    """Stage-1: 剥壳(围栏 / 注释 / 空白)。"""

    def test_markdown_fence_json(self) -> None:
        text = '```json\n{"a": 1}\n```'
        assert relaxed_json_loads(text) == {"a": 1}

    def test_markdown_fence_no_lang(self) -> None:
        text = '```\n{"a": 1}\n```'
        assert relaxed_json_loads(text) == {"a": 1}

    def test_markdown_fence_with_whitespace(self) -> None:
        text = '  \n```json\n{"a": 1}\n```\n  '
        assert relaxed_json_loads(text) == {"a": 1}

    def test_line_comment(self) -> None:
        text = '{\n  "a": 1, // this is a comment\n  "b": 2\n}'
        assert relaxed_json_loads(text) == {"a": 1, "b": 2}

    def test_block_comment(self) -> None:
        text = '{\n  /* comment */\n  "a": 1\n}'
        assert relaxed_json_loads(text) == {"a": 1}

    def test_line_comment_inside_string_preserved(self) -> None:
        text = '{"url": "https://example.com"}'
        assert relaxed_json_loads(text) == {"url": "https://example.com"}

    def test_fence_with_report(self) -> None:
        text = '```json\n{"a": 1}\n```'
        result, report = relaxed_json_loads(text, return_repair_report=True)
        assert result == {"a": 1}
        assert "strip_envelope" in report.stages_applied


class TestStage2NormalizeQuotes:
    """Stage-2: 中文/全角引号 → 半角(仅语法位置)。"""

    def test_chinese_double_quotes(self) -> None:
        text = '{\u201ca\u201d: \u201c值\u201d, \u201cb\u201d: \u201c文本\u201d}'
        result = relaxed_json_loads(text)
        assert result == {"a": "值", "b": "文本"}

    def test_chinese_single_quotes_in_syntax(self) -> None:
        text = "{\u2018a\u2019: \u2018val\u2019}"
        result = relaxed_json_loads(text)
        assert result == {"a": "val"}

    def test_fullwidth_comma(self) -> None:
        text = '{"a": 1\uff0c "b": 2}'
        result = relaxed_json_loads(text)
        assert result == {"a": 1, "b": 2}

    def test_chinese_quotes_inside_string_preserved(self) -> None:
        text = '{"text": "他说\u201c你好\u201d"}'
        result = relaxed_json_loads(text)
        assert result["text"] == "他说\u201c你好\u201d"

    def test_fullwidth_comma_inside_string_preserved(self) -> None:
        text = '{"text": "A\uff0cB\uff0cC"}'
        result = relaxed_json_loads(text)
        assert result["text"] == "A\uff0cB\uff0cC"


class TestStage3RemoveTrailingCommas:
    """Stage-3: 删除对象/数组尾逗号。"""

    def test_object_trailing_comma(self) -> None:
        assert relaxed_json_loads('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}

    def test_array_trailing_comma(self) -> None:
        assert relaxed_json_loads('[1, 2, 3,]') == [1, 2, 3]

    def test_nested_trailing_commas(self) -> None:
        assert relaxed_json_loads('{"a": [1, 2,], "b": {"c": 3,},}') == {
            "a": [1, 2],
            "b": {"c": 3},
        }

    def test_comma_inside_string_preserved(self) -> None:
        result = relaxed_json_loads('{"a": "含,逗号的值,",}')
        assert result == {"a": "含,逗号的值,"}

    def test_trailing_comma_with_whitespace(self) -> None:
        text = '{"a": 1 ,  \n}'
        assert relaxed_json_loads(text) == {"a": 1}


class TestStage4EscapeInnerQuotes:
    """Stage-4: 字符串值内未转义引号 → 转义。"""

    def test_single_bare_quote(self) -> None:
        text = '{"quote": "他说"yes"了"}'
        result = relaxed_json_loads(text)
        assert result == {"quote": '他说"yes"了'}

    def test_multiple_bare_quotes(self) -> None:
        text = '{"q": "他说"yes"和"no"了"}'
        result = relaxed_json_loads(text)
        assert result == {"q": '他说"yes"和"no"了'}

    def test_already_escaped_quotes_unchanged(self) -> None:
        text = r'{"q": "已转义\"引号\""}'
        result = relaxed_json_loads(text)
        assert result == {"q": '已转义"引号"'}

    def test_bare_quote_in_array(self) -> None:
        text = '["他说"yes"了"]'
        result = relaxed_json_loads(text)
        assert result == ['他说"yes"了']


class TestCombinedCases:
    """多阶段组合修复。"""

    def test_ticket_case8_combined(self) -> None:
        """工单用例 8: 尾逗号 + 中文引号 + 裸引号组合。"""
        text = '{\u201cname\u201d: \u201c张三\u201d, \u201cquote\u201d: \u201c他说"yes"了\u201d,}'
        result = relaxed_json_loads(text)
        assert result["name"] == "张三"
        assert result["quote"] == '他说"yes"了'

    def test_fence_plus_trailing_comma(self) -> None:
        text = '```json\n{"a": 1, "b": 2,}\n```'
        assert relaxed_json_loads(text) == {"a": 1, "b": 2}

    def test_fence_plus_chinese_quotes(self) -> None:
        text = '```json\n{\u201ca\u201d: 1}\n```'
        assert relaxed_json_loads(text) == {"a": 1}

    def test_comments_plus_trailing_comma(self) -> None:
        text = '{\n  "a": 1, // comment\n  "b": 2,\n}'
        assert relaxed_json_loads(text) == {"a": 1, "b": 2}


class TestErrorHandling:
    """全部失败时的异常行为。"""

    def test_unfixable_raises_repair_error(self) -> None:
        with pytest.raises(ScrivaiJSONRepairError) as exc_info:
            relaxed_json_loads("{totally broken json content")
        err = exc_info.value
        assert err.original_text == "{totally broken json content"
        assert len(err.stages_applied) == 4
        assert isinstance(err, ScrivaiError)
        assert isinstance(err, json.JSONDecodeError)

    def test_non_json_start_fails(self) -> None:
        with pytest.raises((json.JSONDecodeError, ScrivaiJSONRepairError)):
            relaxed_json_loads("hello world")

    def test_error_message_contains_stages(self) -> None:
        with pytest.raises(ScrivaiJSONRepairError) as exc_info:
            relaxed_json_loads("{bad")
        assert "strip_envelope" in str(exc_info.value)


class TestPerformance:
    """Stage-0 快路径性能约束。"""

    def test_stage0_overhead_under_5_percent(self) -> None:
        valid_json = json.dumps({"key_" + str(i): i for i in range(100)})
        n = 10000
        baseline = timeit.timeit(lambda: json.loads(valid_json), number=n)
        relaxed = timeit.timeit(lambda: relaxed_json_loads(valid_json), number=n)
        overhead = (relaxed - baseline) / baseline
        assert overhead < 0.05, f"Stage-0 开销 {overhead:.1%} 超过 5%"


from scrivai.models.pes import PESConfig


class TestPESConfigStrictJson:
    """PESConfig.strict_json 字段测试。"""

    def test_default_false(self) -> None:
        cfg = PESConfig(
            name="extractor",
            prompt_text="test prompt",
            phases={},
        )
        assert cfg.strict_json is False

    def test_explicit_true(self) -> None:
        cfg = PESConfig(
            name="extractor",
            prompt_text="test prompt",
            phases={},
            strict_json=True,
        )
        assert cfg.strict_json is True
