"""Project SDK 完整流程集成测试。

验证 Project 类的端到端使用场景。
"""

import os
from datetime import datetime
from pathlib import Path

from scrivai.llm import LLMClient
from tests.conftest import skip_if_no_api


def _write_report(
    test_name: str,
    steps: list[dict],
    inputs: dict,
    outputs: dict,
    conclusion: str,
) -> str:
    """生成 Markdown 测试报告。

    Args:
        test_name: 测试名称
        steps: 执行步骤列表
        inputs: 输入数据
        outputs: 输出结果
        conclusion: 结论

    Returns:
        报告文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("tests/outputs/test_project_sdk_flow")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{test_name}_{timestamp}.md"

    report_lines = [
        f"# 集成测试报告: {test_name}",
        "",
        f"## 测试时间\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 测试场景\nProject SDK 完整流程",
        "",
        "## 输入数据",
    ]

    for key, value in inputs.items():
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 执行步骤"])
    for i, step in enumerate(steps, 1):
        report_lines.append(f"{i}. {step.get('phase', '')}: {step.get('action', '')}")
        if step.get("input"):
            report_lines.append(f"   - 输入: {step['input']}")
        if step.get("output"):
            report_lines.append(f"   - 输出: {step['output'][:200]}...")

    report_lines.extend(["", "## 输出结果"])
    for key, value in outputs.items():
        if isinstance(value, str) and len(value) > 500:
            value = value[:500] + "..."
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 结论", conclusion])

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return str(report_path)


@skip_if_no_api
class TestProjectSDKFlow:
    """Project SDK 完整流程测试类。"""

    def test_sdk_full_flow(self, real_llm_client_long: LLMClient) -> None:
        """验证完整 SDK 流程：初始化 → 生成 → 审核 → 报告。

        核心流程:
            Phase 1: 初始化生成引擎和审核引擎
            Phase 2: 生成单章文档
            Phase 3: 执行审核
            Phase 4: 生成测试报告
        """
        from scrivai.audit.engine import AuditEngine
        from scrivai.generation.context import GenerationContext
        from scrivai.generation.engine import GenerationEngine

        # Phase 1: 初始化组件
        gen_engine = GenerationEngine(real_llm_client_long)
        _ = GenerationContext(real_llm_client_long)  # 上下文工具
        audit_engine = AuditEngine(real_llm_client_long)

        steps = []
        inputs = {
            "模板": "chapter_overview.md.j2",
            "用户输入": {"工程名称": "XX变电站", "投资金额": "5000万元"},
        }

        # Phase 2: 生成单章文档
        template = """## 第一章 工程概述

请根据以下信息撰写工程概述：

### 用户输入
{{ user_inputs | tojson(indent=2) }}

要求：
1. 包含项目背景、建设规模、投资估算
2. 使用专业术语
3. 控制在 300 字以内
"""
        user_inputs = {"工程名称": "XX变电站", "投资金额": "5000万元"}

        chapter = gen_engine.generate_chapter(template, {"user_inputs": user_inputs})
        steps.append(
            {
                "phase": "Phase 2",
                "action": "生成第一章",
                "input": str(user_inputs),
                "output": chapter,
            }
        )

        # 验证生成内容
        assert len(chapter) > 50, "生成内容过短"
        assert "变电站" in chapter or "工程" in chapter, "生成内容未包含关键词"

        # Phase 3: 执行审核
        checkpoints = [
            {
                "id": "cp_sdk_001",
                "description": "检查概述结构完整性",
                "prompt_template": "检查是否包含项目背景和建设规模",
                "severity": "warning",
            },
            {
                "id": "cp_sdk_002",
                "description": "检查投资信息",
                "prompt_template": "检查是否包含投资金额信息",
                "severity": "info",
            },
        ]

        results = audit_engine.check_many(chapter, checkpoints)
        steps.append(
            {
                "phase": "Phase 3",
                "action": "执行审核",
                "input": f"{len(checkpoints)} 个审核要点",
                "output": f"通过 {sum(1 for r in results if r.passed)}/{len(results)}",
            }
        )

        # 验证审核结果
        assert len(results) == 2, "审核结果数量不匹配"
        for r in results:
            assert r.checkpoint_id in ["cp_sdk_001", "cp_sdk_002"]

        # Phase 4: 生成测试报告
        outputs = {
            "生成内容长度": f"{len(chapter)} 字符",
            "审核结果": f"通过 {sum(1 for r in results if r.passed)}/{len(results)}",
        }

        passed_count = sum(1 for r in results if r.passed)
        conclusion = "✅ 测试通过" if passed_count >= 1 else "⚠️ 测试部分通过"

        report_path = _write_report(
            test_name="test_sdk_full_flow",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        steps.append(
            {
                "phase": "Phase 4",
                "action": "生成测试报告",
                "output": report_path,
            }
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_sdk_with_knowledge(self, real_llm_client_long: LLMClient) -> None:
        """验证知识库检索 + 生成流程（mock qmd）。

        由于集成测试不依赖真实 qmd，验证 GenerationEngine 在无知识库时正常工作，
        同时验证接口设计正确。
        """
        from scrivai.generation.engine import GenerationEngine

        # Phase 1: 创建无知识库的引擎
        engine = GenerationEngine(real_llm_client_long, store=None)

        steps = []
        inputs = {"知识库": "未配置", "模板": "简单生成模板"}

        # Phase 2: 正常生成（无检索）
        template = "请简述{{ topic }}的基本概念。"
        result = engine.generate_chapter(template, {"topic": "变电站工程"})

        steps.append(
            {
                "phase": "Phase 2",
                "action": "生成内容（无知识库）",
                "input": "topic=变电站工程",
                "output": result[:200] + "...",
            }
        )

        assert len(result) > 20, "生成内容过短"

        # Phase 3: 验证检索接口抛出正确异常
        try:
            engine.retrieve_cases("变压器")
            error_raised = False
        except RuntimeError as e:
            error_raised = True
            error_msg = str(e)

        steps.append(
            {
                "phase": "Phase 3",
                "action": "验证检索异常",
                "output": error_msg if error_raised else "无异常",
            }
        )

        assert error_raised, "未配置知识库时应抛出 RuntimeError"
        assert "未配置" in error_msg or "KnowledgeStore" in error_msg

        # Phase 4: 生成测试报告
        outputs = {
            "生成内容长度": f"{len(result)} 字符",
            "检索异常": "正确抛出",
        }

        report_path = _write_report(
            test_name="test_sdk_with_knowledge",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion="✅ 测试通过",
        )

        assert os.path.exists(report_path), "测试报告未生成"
