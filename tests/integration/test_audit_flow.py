"""审核引擎端到端流程集成测试。

使用真实 LLM API 验证完整审核流程。
"""

import os
import tempfile

import yaml

from scrivai.audit.engine import AuditEngine, AuditResult
from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


@skip_if_no_api
class TestAuditFlow:
    """审核引擎端到端流程测试类。"""

    def test_audit_flow_full_document(self, real_llm_client_long: LLMClient) -> None:
        """验证完整文档审核流程。"""
        engine = AuditEngine(real_llm_client_long)

        document = """
# XX变电站工程设计方案

## 第一章 概述

### 1.1 项目背景

随着区域经济发展，用电需求持续增长，亟需新建变电站以满足供电需求。

### 1.2 建设规模

本期建设2台120MVA主变压器，远期规划4台。

## 第二章 设计方案

### 2.1 电气主接线

110kV侧采用双母线接线方式，10kV侧采用单母线分段接线。

### 2.2 主要设备

- 主变压器：120MVA，110/10kV
- GIS设备：110kV气体绝缘开关设备
- 电容器组：2×6Mvar
"""
        checkpoints = [
            {
                "id": "cp_full_001",
                "description": "检查概述章节完整性",
                "prompt_template": "检查是否包含项目背景和建设规模",
                "severity": "warning",
            },
            {
                "id": "cp_full_002",
                "description": "检查设计方案技术参数",
                "prompt_template": "检查是否包含电气参数和设备规格",
                "severity": "error",
            },
            {
                "id": "cp_full_003",
                "description": "检查文档结构",
                "prompt_template": "检查文档是否有清晰的章节结构",
                "severity": "info",
            },
        ]

        results = engine.check_many(document, checkpoints)

        # 验证：返回正确数量的结果
        assert len(results) == 3
        for r in results:
            assert isinstance(r, AuditResult)
            # 检查必要字段
            assert r.checkpoint_id in ["cp_full_001", "cp_full_002", "cp_full_003"]
            assert r.severity in ["warning", "error", "info"]
            assert isinstance(r.passed, bool)

    def test_audit_flow_with_checkpoints_file(self, real_llm_client_long: LLMClient) -> None:
        """验证从 YAML 加载 checkpoints 并审核。"""
        engine = AuditEngine(real_llm_client_long)

        # 创建临时 checkpoints 文件
        checkpoints_data = {
            "checkpoints": [
                {
                    "id": "cp_file_001",
                    "description": "检查内容完整性",
                    "prompt_template": "检查文档是否有实质性内容",
                    "severity": "warning",
                },
            ]
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(checkpoints_data, f)
            tmp_path = f.name

        try:
            # 加载 checkpoints
            loaded = engine.load_checkpoints(tmp_path)
            assert len(loaded) == 1
            assert loaded[0]["id"] == "cp_file_001"

            # 执行审核
            document = "## 概述\n\n本项目为XX工程，投资5000万元。"
            results = engine.check_many(document, loaded)

            assert len(results) == 1
            assert results[0].checkpoint_id == "cp_file_001"
        finally:
            os.unlink(tmp_path)
