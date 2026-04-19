"""relaxed_json_loads 单元测试。"""

from __future__ import annotations

import json

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
