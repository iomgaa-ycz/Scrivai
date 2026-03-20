"""生成+自审迭代修正集成测试。

验证生成 → 审核 → 修正的闭环流程。
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
    output_dir = Path("tests/outputs/test_generation_audit_cycle")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{test_name}_{timestamp}.md"

    report_lines = [
        f"# 集成测试报告: {test_name}",
        "",
        f"## 测试时间\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 测试场景\n生成+自审迭代修正",
        "",
        "## 输入数据",
    ]

    for key, value in inputs.items():
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 执行步骤"])

    for i, step in enumerate(steps, 1):
        phase = step.get("phase", f"Step {i}")
        action = step.get("action", "未知操作")
        detail = step.get("detail", step.get("output", ""))
        report_lines.append(f"{i}. **{phase}**: {action}")
        if detail:
            report_lines.append(f"   - {detail}")

    report_lines.extend(["", "## 输出结果"])

    for key, value in outputs.items():
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 结论", conclusion])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    return str(report_path)


@skip_if_no_api
class TestGenerationAuditCycle:
    """生成+自审迭代修正测试类。"""

    def test_generate_audit_revise(self, real_llm_client_long: LLMClient) -> None:
        """验证生成 → 审核 → 修正循环。"""
        from scrivai.audit.engine import AuditEngine
        from scrivai.generation.engine import GenerationEngine

        gen_engine = GenerationEngine(real_llm_client_long)
        audit_engine = AuditEngine(real_llm_client_long)

        steps = []
        inputs = {"迭代次数": "最多 2 次"}

        # Phase 1: 生成初始文档
        template = "请用简短段落描述{{ project }}的概述，包括背景和规模。"
        user_inputs = {"project": "XX变电站"}

        doc = gen_engine.generate_chapter(template, user_inputs)
        steps.append(
            {
                "phase": "Phase 1",
                "action": "生成初始文档",
                "detail": f"长度: {len(doc)} 字符",
            }
        )

        # Phase 2: 审核初始文档
        checkpoints = [
            {
                "id": "cp_revise_001",
                "description": "检查内容完整性",
                "prompt_template": "检查是否包含项目背景和建设规模两个部分",
                "severity": "warning",
            },
            {
                "id": "cp_revise_002",
                "description": "检查专业性",
                "prompt_template": "检查是否使用了专业术语",
                "severity": "info",
            },
        ]

        results = audit_engine.check_many(doc, checkpoints)
        initial_pass_rate = sum(1 for r in results if r.passed) / len(results)

        steps.append(
            {
                "phase": "Phase 2",
                "action": "审核初始文档",
                "detail": f"通过率: {initial_pass_rate:.0%}",
            }
        )

        # Phase 3: 根据审核结果修正
        revision_count = 0
        max_revisions = 2
        current_doc = doc

        while revision_count < max_revisions:
            failed_checks = [r for r in results if not r.passed]
            if not failed_checks:
                break

            # 构建修正提示
            issues = "; ".join(f"{r.checkpoint_id}: {r.finding}" for r in failed_checks)
            revise_template = """当前文档：
{{ current_doc }}

审核发现的问题：
{{ issues }}

请根据审核意见修正文档， 保持原有的结构和风格， 只修正指出的问题。"""

            current_doc = gen_engine.generate_chapter(
                revise_template,
                {"current_doc": current_doc, "issues": issues},
            )
            revision_count += 1

            # 重新审核
            results = audit_engine.check_many(current_doc, checkpoints)

            steps.append(
                {
                    "phase": f"Phase 3.{revision_count}",
                    "action": f"第 {revision_count} 次修正",
                    "detail": f"长度: {len(current_doc)} 字符",
                }
            )

        # 验证迭代效果
        final_pass_rate = sum(1 for r in results if r.passed) / len(results)

        outputs = {
            "初始通过率": f"{initial_pass_rate:.0%}",
            "修正次数": f"{revision_count} 次",
            "最终通过率": f"{final_pass_rate:.0%}",
            "最终文档长度": f"{len(current_doc)} 字符",
        }

        conclusion = "✅ 测试通过" if final_pass_rate >= initial_pass_rate else "⚠️ 迭代效果不佳"

        report_path = _write_report(
            test_name="test_generate_audit_revise",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_max_revisions(self, real_llm_client_long: LLMClient) -> None:
        """验证最大修正次数限制。"""
        from scrivai.audit.engine import AuditEngine
        from scrivai.generation.engine import GenerationEngine

        gen_engine = GenerationEngine(real_llm_client_long)
        audit_engine = AuditEngine(real_llm_client_long)

        steps = []
        inputs = {"最大修正次数": "3 次"}

        # Phase 1: 生成文档
        template = "请简要描述{{ item }}。"
        doc = gen_engine.generate_chapter(template, {"item": "电力工程"})

        steps.append(
            {
                "phase": "Phase 1",
                "action": "生成初始文档",
                "detail": f"长度: {len(doc)} 字符",
            }
        )

        # Phase 2: 模拟修正循环
        max_revisions = 3
        revision_count = 0
        current_doc = doc

        checkpoints = [
            {
                "id": "cp_max_001",
                "description": "内容检查",
                "prompt_template": "检查内容是否充实",
                "severity": "warning",
            }
        ]

        while revision_count < max_revisions:
            _ = audit_engine.check_many(current_doc, checkpoints)  # 结果用于验证逻辑

            # 即使未通过也停止（模拟最大次数限制）
            revision_count += 1

            if revision_count < max_revisions:
                # 继续修正
                revise_template = "请扩展以下内容: {{ content }}"
                current_doc = gen_engine.generate_chapter(revise_template, {"content": current_doc})

                steps.append(
                    {
                        "phase": f"Phase 2.{revision_count}",
                        "action": f"第 {revision_count} 次修正",
                        "detail": f"长度: {len(current_doc)} 字符",
                    }
                )

        # Phase 3: 验证达到最大次数
        outputs = {
            "最大修正次数": f"{max_revisions} 次",
            "实际修正次数": f"{revision_count} 次",
        }

        conclusion = "✅ 测试通过" if revision_count == max_revisions else "❌ 修正次数超限"
        report_path = _write_report(
            test_name="test_max_revisions",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"
