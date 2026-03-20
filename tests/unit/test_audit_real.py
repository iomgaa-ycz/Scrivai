"""AuditEngine 真实调用测试。

使用真实 LLM API 验证审核功能。
"""

from scrivai.audit.engine import AuditEngine, AuditResult
from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


@skip_if_no_api
class TestAuditEngineReal:
    """AuditEngine 真实调用测试类。"""

    def test_real_check_one_pass(self, real_llm_client_long: LLMClient) -> None:
        """验证审核通过场景。"""
        engine = AuditEngine(real_llm_client_long)

        document = """
## 第一章 概述

本项目为XX变电站建设工程。工程总投资5000万元，建设周期18个月。
项目位于XX省XX市XX区。
"""
        checkpoint = {
            "id": "cp_001",
            "description": "检查概述章节是否包含项目基本信息",
            "prompt_template": "检查文档是否包含：项目名称、投资金额、建设地点",
            "severity": "warning",
        }

        result = engine.check_one(document, checkpoint)

        # 验证：返回 AuditResult 对象
        assert isinstance(result, AuditResult)
        assert result.checkpoint_id == "cp_001"
        assert result.severity == "warning"
        assert isinstance(result.passed, bool)
        assert isinstance(result.finding, str)

    def test_real_check_one_fail(self, real_llm_client_long: LLMClient) -> None:
        """验证审核失败场景。"""
        engine = AuditEngine(real_llm_client_long)

        # 空白文档应审核失败
        document = "## 第一章\n\n暂无内容。"
        checkpoint = {
            "id": "cp_002",
            "description": "检查是否包含技术参数",
            "prompt_template": "检查文档是否包含具体的技术参数和数值",
            "severity": "error",
        }

        result = engine.check_one(document, checkpoint)

        # 验证：返回 AuditResult 对象
        assert isinstance(result, AuditResult)
        assert result.checkpoint_id == "cp_002"
        assert result.severity == "error"

    def test_real_check_one_with_chinese_doc(self, real_llm_client_long: LLMClient) -> None:
        """验证中文文档审核。"""
        engine = AuditEngine(real_llm_client_long)

        document = """
## 工程概况

### 1.1 项目背景

随着区域经济发展，用电需求持续增长，亟需新建变电站以满足供电需求。

### 1.2 建设规模

本期建设2台120MVA主变压器，远期规划4台。
"""
        checkpoint = {
            "id": "cp_003",
            "description": "检查工程概况完整性",
            "prompt_template": "检查是否包含项目背景和建设规模说明",
            "severity": "info",
        }

        result = engine.check_one(document, checkpoint)

        # 验证：返回 AuditResult 对象
        assert isinstance(result, AuditResult)
        assert result.checkpoint_id == "cp_003"
        # 完整文档应通过或接近通过
        assert isinstance(result.passed, bool)

    def test_real_check_many(self, real_llm_client_long: LLMClient) -> None:
        """验证批量审核。"""
        engine = AuditEngine(real_llm_client_long)

        document = """
## 第一章 概述

本项目为XX变电站建设工程。

## 第二章 设计方案

采用GIS布置方式，节约用地。
"""
        checkpoints = [
            {
                "id": "cp_batch_001",
                "description": "检查概述",
                "prompt_template": "检查是否有概述内容",
                "severity": "warning",
            },
            {
                "id": "cp_batch_002",
                "description": "检查设计方案",
                "prompt_template": "检查是否有设计方案内容",
                "severity": "warning",
            },
        ]

        results = engine.check_many(document, checkpoints)

        # 验证：返回列表，数量匹配
        assert isinstance(results, list)
        assert len(results) == 2
        for r in results:
            assert isinstance(r, AuditResult)

    def test_real_check_with_scope_chapter(self, real_llm_client_long: LLMClient) -> None:
        """验证章节范围审核。"""
        engine = AuditEngine(real_llm_client_long)

        document = """
## 第一章 概述

这是概述章节。

## ch03 设计方案

这是设计章节，包含技术参数：电压等级110kV，容量120MVA。

## 第三章 施工计划

这是施工章节。
"""
        checkpoint = {
            "id": "cp_scope",
            "description": "检查设计章节技术参数",
            "prompt_template": "检查是否包含电压等级和容量参数",
            "severity": "warning",
            "scope": "chapter:ch03",
        }

        result = engine.check_one(document, checkpoint)

        # 验证：返回 AuditResult 对象，chapter_id 应被解析
        assert isinstance(result, AuditResult)
        assert result.chapter_id == "ch03"
