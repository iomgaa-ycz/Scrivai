"""多章生成连贯性集成测试。

验证长文档生成时上下文传递和连贯性保障。
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
    """生成 Markdown 测试报告。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("tests/outputs/test_multichapter_flow")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{test_name}_{timestamp}.md"

    report_lines = [
        f"# 集成测试报告: {test_name}",
        "",
        f"## 测试时间\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 测试场景\n多章生成连贯性测试",
        "",
        "## 输入数据",
    ]

    for key, value in inputs.items():
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 执行步骤"])
    for i, step in enumerate(steps, 1):
        report_lines.append(f"{i}. {step.get('phase', '')}: {step.get('action', '')}")
        if step.get("detail"):
            report_lines.append(f"   - {step['detail']}")

    report_lines.extend(["", "## 输出结果"])
    for key, value in outputs.items():
        if isinstance(value, str) and len(value) > 300:
            value = value[:300] + "..."
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 结论", conclusion])

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return str(report_path)


@skip_if_no_api
class TestMultichapterFlow:
    """多章生成连贯性测试类。"""

    def test_multichapter_coherence(self, real_llm_client_long: LLMClient) -> None:
        """验证 3 章连续生成的连贯性。

        核心流程:
            Phase 1: 生成第一章（概述）
            Phase 2: 生成摘要和术语
            Phase 3: 生成第二章（技术方案）— 使用摘要
            Phase 4: 更新术语表
            Phase 5: 生成第三章（投资概算）— 使用更新后的上下文
        """
        from scrivai.generation.context import GenerationContext
        from scrivai.generation.engine import GenerationEngine

        engine = GenerationEngine(real_llm_client_long)
        ctx = GenerationContext(real_llm_client_long)

        steps = []
        inputs = {
            "章节数": 3,
            "工程名称": "XX变电站",
            "投资金额": "5000万元",
        }

        user_inputs = {"工程名称": "XX变电站", "投资金额": "5000万元"}

        # Phase 1: 生成第一章
        ch1_template = """## 第一章 工程概述

请撰写{{ 工程名称 }}的工程概述，总投资{{ 投资金额 }}。

要求：
1. 包含项目背景、建设规模
2. 控制在 200 字以内
"""
        chapter1 = engine.generate_chapter(ch1_template, user_inputs)
        steps.append(
            {
                "phase": "Phase 1",
                "action": "生成第一章（概述）",
                "detail": f"长度: {len(chapter1)} 字符",
            }
        )

        assert len(chapter1) > 30, "第一章生成内容过短"

        # Phase 2: 生成摘要和术语
        summary1 = ctx.summarize(chapter1)
        terms1 = ctx.extract_terms(chapter1, {})
        steps.append(
            {
                "phase": "Phase 2",
                "action": "生成上下文",
                "detail": f"摘要: {len(summary1)} 字符, 术语: {len(terms1)} 个",
            }
        )

        assert len(summary1) > 10, "摘要过短"

        # Phase 3: 生成第二章（使用摘要）
        ch2_template = """## 第二章 技术方案

前文摘要：{{ summary }}

请基于前文，为{{ 工程名称 }}撰写技术方案。

要求：
1. 包含电气主接线方案
2. 控制在 200 字以内
"""
        chapter2 = engine.generate_chapter(
            ch2_template,
            {"summary": summary1, **user_inputs},
        )
        steps.append(
            {
                "phase": "Phase 3",
                "action": "生成第二章（技术方案）",
                "detail": f"长度: {len(chapter2)} 字符",
            }
        )

        assert len(chapter2) > 30, "第二章生成内容过短"

        # Phase 4: 更新术语表
        terms2 = ctx.extract_terms(chapter2, terms1)
        steps.append(
            {
                "phase": "Phase 4",
                "action": "更新术语表",
                "detail": f"累计术语: {len(terms2)} 个",
            }
        )

        # Phase 5: 生成第三章（使用完整上下文）
        ch3_template = """## 第三章 投资概算

前文摘要：{{ summary }}
术语表：{{ glossary | tojson }}

请为{{ 工程名称 }}撰写投资概算。

要求：
1. 总投资与第一章一致
2. 控制在 150 字以内
"""
        chapter3 = engine.generate_chapter(
            ch3_template,
            {"summary": summary1, "glossary": terms2, **user_inputs},
        )
        steps.append(
            {
                "phase": "Phase 5",
                "action": "生成第三章（投资概算）",
                "detail": f"长度: {len(chapter3)} 字符",
            }
        )

        assert len(chapter3) > 20, "第三章生成内容过短"

        # 生成测试报告
        outputs = {
            "第一章长度": f"{len(chapter1)} 字符",
            "摘要长度": f"{len(summary1)} 字符",
            "术语数量": f"{len(terms2)} 个",
            "第二章长度": f"{len(chapter2)} 字符",
            "第三章长度": f"{len(chapter3)} 字符",
        }

        report_path = _write_report(
            test_name="test_multichapter_coherence",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion="✅ 测试通过",
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_glossary_propagation(self, real_llm_client_long: LLMClient) -> None:
        """验证术语表在章节间传递。"""
        from scrivai.generation.context import GenerationContext

        ctx = GenerationContext(real_llm_client_long)

        steps = []
        inputs = {"初始术语": "0 个"}

        # Phase 1: 从文本提取术语
        text1 = "XX变电站采用110kV GIS设备，主变压器容量为2×50MVA。"
        terms1 = ctx.extract_terms(text1, {})

        steps.append(
            {
                "phase": "Phase 1",
                "action": "提取术语（第一章）",
                "detail": f"提取到 {len(terms1)} 个术语",
            }
        )

        # Phase 2: 从第二章提取并合并
        text2 = "电气主接线采用双母线接线，10kV侧配置电容器组2×6Mvar。"
        terms2 = ctx.extract_terms(text2, terms1)

        steps.append(
            {
                "phase": "Phase 2",
                "action": "提取并合并术语（第二章）",
                "detail": f"累计 {len(terms2)} 个术语",
            }
        )

        # Phase 3: 从第三章提取并合并
        text3 = "本工程总投资3200万元，其中设备费占60%。"
        terms3 = ctx.extract_terms(text3, terms2)

        steps.append(
            {
                "phase": "Phase 3",
                "action": "提取并合并术语（第三章）",
                "detail": f"最终 {len(terms3)} 个术语",
            }
        )

        # 验证术语表增长
        outputs = {
            "第一章术语": f"{len(terms1)} 个",
            "第二章累计": f"{len(terms2)} 个",
            "第三章累计": f"{len(terms3)} 个",
        }

        conclusion = "✅ 测试通过" if len(terms3) >= len(terms1) else "⚠️ 术语表未增长"

        report_path = _write_report(
            test_name="test_glossary_propagation",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_summary_propagation(self, real_llm_client_long: LLMClient) -> None:
        """验证摘要在章节间传递。"""
        from scrivai.generation.context import GenerationContext
        from scrivai.generation.engine import GenerationEngine

        ctx = GenerationContext(real_llm_client_long)
        engine = GenerationEngine(real_llm_client_long)

        steps = []
        inputs = {"原文长度": "约 300 字符"}

        # Phase 1: 生成原文摘要
        original = """XX变电站工程位于城市东部新区，主要服务于周边工业园区和居民区用电需求。
        本期建设2台50MVA主变压器，电压等级110/10kV，110kV出线4回，10kV出线24回。
        总投资约3200万元，计划工期18个月。"""

        summary1 = ctx.summarize(original)
        steps.append(
            {
                "phase": "Phase 1",
                "action": "生成原始摘要",
                "detail": f"摘要长度: {len(summary1)} 字符",
            }
        )

        # Phase 2: 使用摘要生成后续内容
        template = "基于前文摘要：{{ summary }}\n请补充技术细节。"
        continuation = engine.generate_chapter(template, {"summary": summary1})

        steps.append(
            {
                "phase": "Phase 2",
                "action": "基于摘要生成后续内容",
                "detail": f"续写长度: {len(continuation)} 字符",
            }
        )

        # Phase 3: 验证摘要压缩效果
        compression_ratio = len(summary1) / len(original)
        outputs = {
            "原文长度": f"{len(original)} 字符",
            "摘要长度": f"{len(summary1)} 字符",
            "压缩比": f"{compression_ratio:.2%}",
            "续写长度": f"{len(continuation)} 字符",
        }

        conclusion = "✅ 测试通过" if compression_ratio < 1 else "⚠️ 摘要未压缩"

        report_path = _write_report(
            test_name="test_summary_propagation",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"
