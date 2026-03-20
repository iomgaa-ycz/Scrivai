"""GenerationEngine + GenerationContext 真实调用测试。

使用真实 LLM API 验证生成和上下文功能。
"""

import os
import tempfile

from scrivai.generation.context import GenerationContext
from scrivai.generation.engine import GenerationEngine
from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


@skip_if_no_api
class TestGenerationEngineReal:
    """GenerationEngine 真实调用测试类。"""

    def test_real_generate_chapter_simple(self, real_llm_client: LLMClient) -> None:
        """验证简单章节生成。"""
        engine = GenerationEngine(real_llm_client)

        template = "请写一段关于{{ topic }}的简短介绍，不超过50字。"
        result = engine.generate_chapter(template, {"topic": "电力工程"})

        # 验证：返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 10

    def test_real_generate_chapter_with_variables(self, real_llm_client: LLMClient) -> None:
        """验证带变量注入生成。"""
        engine = GenerationEngine(real_llm_client)

        template = """
项目名称：{{ project_name }}
建设单位：{{ org }}
请为该项目写一句简介。
"""
        result = engine.generate_chapter(
            template,
            {"project_name": "XX变电站工程", "org": "XX电力公司"},
        )

        # 验证：返回非空字符串
        assert isinstance(result, str)
        assert len(result) > 5

    def test_real_generate_chapter_from_template_file(self, real_llm_client: LLMClient) -> None:
        """验证从模板文件生成。"""
        engine = GenerationEngine(real_llm_client)

        # 创建临时模板文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".j2", delete=False, encoding="utf-8"
        ) as f:
            f.write("章节标题：{{ title }}\n请生成一段内容。")
            tmp_path = f.name

        try:
            result = engine.generate_chapter(tmp_path, {"title": "概述"})
            # 验证：返回非空字符串
            assert isinstance(result, str)
            assert len(result) > 5
        finally:
            os.unlink(tmp_path)


@skip_if_no_api
class TestGenerationContextReal:
    """GenerationContext 真实调用测试类。"""

    def test_real_summarize(self, real_llm_client_long: LLMClient) -> None:
        """验证摘要生成。"""
        ctx = GenerationContext(real_llm_client_long)

        text = """
## 第一章 概述

本项目为XX变电站建设工程，位于XX省XX市。项目总投资5000万元，
建设内容包括主变压器安装、配电装置安装、控制系统建设等。
工程计划工期为18个月，预计2025年竣工。
"""
        result = ctx.summarize(text)

        # 验证：返回非空字符串摘要
        assert isinstance(result, str)
        assert len(result) > 10
        # 宽松匹配：摘要应包含关键信息
        assert "变电站" in result or "工程" in result or "项目" in result

    def test_real_extract_terms(self, real_llm_client_long: LLMClient) -> None:
        """验证术语提取（验证 JSON 格式）。"""
        ctx = GenerationContext(real_llm_client_long)

        text = """
本工程采用GIS（气体绝缘金属封闭开关设备）技术，SVC（静止无功补偿器）
用于电压调节。主变压器容量为120MVA。
"""
        result = ctx.extract_terms(text, {})

        # 验证：返回字典格式
        assert isinstance(result, dict)
        # 可能提取到术语（宽松验证）
        # 注意：LLM 可能无法准确提取所有术语

    def test_real_extract_references(self, real_llm_client_long: LLMClient) -> None:
        """验证引用提取（验证列表格式）。"""
        ctx = GenerationContext(real_llm_client_long)

        text = """
详见第3章设计说明，参考表2-1设备参数。根据图4-5施工图纸进行安装。
"""
        result = ctx.extract_references(text)

        # 验证：返回列表格式
        assert isinstance(result, list)
        # 每个引用应包含必要字段
        for ref in result:
            assert isinstance(ref, dict)
            assert "target" in ref
            assert "type" in ref
