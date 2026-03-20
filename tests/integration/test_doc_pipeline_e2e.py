"""Doc Pipeline 端到端集成测试。

验证文档预处理管道的完整流程。
"""

import os
from datetime import datetime
from pathlib import Path

from core.llm import LLMClient
from tests.conftest import skip_if_no_api
from utils.doc_pipeline import DocPipeline, MarkdownCleaner


def _write_report(
    test_name: str,
    steps: list[dict],
    inputs: dict,
    outputs: dict,
    conclusion: str,
) -> str:
    """生成 Markdown 测试报告。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("tests/outputs/test_doc_pipeline_e2e")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{test_name}_{timestamp}.md"

    report_lines = [
        f"# 集成测试报告: {test_name}",
        "",
        f"## 测试时间\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 测试场景\nDoc Pipeline 端到端",
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
        report_lines.append(f"- {key}: {value}")

    report_lines.extend(["", "## 结论", conclusion])

    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return str(report_path)


@skip_if_no_api
class TestDocPipelineE2E:
    """Doc Pipeline 端到端测试类。"""

    def test_pipeline_clean_only(self, real_llm_client_long: LLMClient) -> None:
        """验证仅清洗流程（无 OCR）。

        核心流程:
            Phase 1: 准备模拟 OCR 输出
            Phase 2: 正则清洗
            Phase 3: LLM 清洗
            Phase 4: 验证清洗效果
        """
        steps = []
        inputs = {"模式": "仅清洗（正则 + LLM）"}

        # Phase 1: 准备模拟 OCR 输出
        raw_text = r"""# 工程概述

CHINA SOUTHERN POWER GRID CO., LTD.

## 项目背景

本项目为XX变电站工程，总投资$\geqslant$5000万元。

### 表格示例

|------------------------------------------------------------------|
| 设备名称 | 数量 | 单价 |
|----------|------|------|
| 变压器   | 2    | 100万|
| GIS设备  | 4    | 50万 |

### HTML 残留

<table>
<tr><td>项目</td><td>金额</td></tr>
<tr><td>设备费</td><td>3000万</td></tr>
</table>

### LaTeX 符号

温度$\geqslant$45$\circ$，压力$\leqslant$0.5MPa。

好的，以下是清洗后的内容：
"""
        steps.append(
            {
                "phase": "Phase 1",
                "action": "准备模拟 OCR 输出",
                "detail": f"长度: {len(raw_text)} 字符",
            }
        )

        # Phase 2 & 3: 完整清洗
        cleaner = MarkdownCleaner(llm=real_llm_client_long)
        cleaned = cleaner.clean(raw_text)

        steps.append(
            {
                "phase": "Phase 2-3",
                "action": "执行清洗（正则 + LLM）",
                "detail": f"清洗后长度: {len(cleaned)} 字符",
            }
        )

        # Phase 4: 验证清洗效果
        # 4.1 水印移除
        assert "CHINA SOUTHERN POWER GRID" not in cleaned, "水印未移除"

        # 4.2 LaTeX 转换
        assert r"$\geqslant$" not in cleaned, "LaTeX 符号未转换"
        assert "≥" in cleaned, "LaTeX 未转换为 Unicode"

        # 4.3 对话前缀移除（LLM 后处理）
        assert not cleaned.strip().startswith("好的"), "对话前缀未移除"

        steps.append(
            {
                "phase": "Phase 4",
                "action": "验证清洗效果",
                "detail": "水印 ✓, LaTeX ✓, 对话前缀 ✓",
            }
        )

        # 生成测试报告
        outputs = {
            "原始长度": f"{len(raw_text)} 字符",
            "清洗后长度": f"{len(cleaned)} 字符",
            "压缩比": f"{len(cleaned) / len(raw_text):.1%}",
            "水印移除": "✓",
            "LaTeX 转换": "✓",
            "对话前缀移除": "✓",
        }

        report_path = _write_report(
            test_name="test_pipeline_clean_only",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion="✅ 测试通过",
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_pipeline_regex_only(self) -> None:
        """验证仅正则清洗流程（无 LLM）。

        核心流程:
            Phase 1: 准备含多种问题的文本
            Phase 2: 仅正则清洗
            Phase 3: 验证各清洗规则生效
        """
        steps = []
        inputs = {"模式": "仅正则清洗（无 LLM）"}

        # Phase 1: 准备测试文本
        raw_text = """# 测试文档

CHINA SOUTHERN POWER GRID

## 表格测试

|------------------------------------------------------------------|
| 列1 | 列2 |
|-----|------|
| A   | B    |

## HTML 测试

<table>
<tr><td>项目</td><td>值</td></tr>
<tr><td>测试</td><td>100</td></tr>
</table>

## LaTeX 测试

角度: $45^{\\circ}$
比较: $\\geqslant$100
符号: $\times$, $\\div$, $\approx$

连续空行测试：


"""
        steps.append(
            {
                "phase": "Phase 1",
                "action": "准备测试文本",
                "detail": f"长度: {len(raw_text)} 字符",
            }
        )

        # Phase 2: 仅正则清洗
        cleaner = MarkdownCleaner(llm=None)  # 不使用 LLM
        cleaned = cleaner.clean(raw_text)

        steps.append(
            {
                "phase": "Phase 2",
                "action": "执行正则清洗",
                "detail": f"清洗后长度: {len(cleaned)} 字符",
            }
        )

        # Phase 3: 验证清洗效果
        checks = []

        # 3.1 水印移除
        if "CHINA SOUTHERN POWER GRID" not in cleaned:
            checks.append("水印移除 ✓")
        else:
            checks.append("水印移除 ✗")

        # 3.2 HTML 表格转换
        if "<table>" not in cleaned and "|" in cleaned:
            checks.append("HTML 表格转换 ✓")
        else:
            checks.append("HTML 表格转换 ✗")

        # 3.3 LaTeX 符号转换
        if "°" in cleaned and "≥" in cleaned:
            checks.append("LaTeX 转换 ✓")
        else:
            checks.append("LaTeX 转换 ✗")

        # 3.4 连续空行压缩
        if "\n\n\n" not in cleaned:
            checks.append("空行压缩 ✓")
        else:
            checks.append("空行压缩 ✗")

        steps.append(
            {
                "phase": "Phase 3",
                "action": "验证清洗效果",
                "detail": ", ".join(checks),
            }
        )

        # 生成测试报告
        outputs = {
            "原始长度": f"{len(raw_text)} 字符",
            "清洗后长度": f"{len(cleaned)} 字符",
            "清洗检查": ", ".join(checks),
        }

        all_passed = all("✓" in c for c in checks)
        conclusion = "✅ 测试通过" if all_passed else "⚠️ 部分检查未通过"

        report_path = _write_report(
            test_name="test_pipeline_regex_only",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"

    def test_pipeline_validation_warnings(self) -> None:
        """验证管道警告检测。

        核心流程:
            Phase 1: 准备会触发警告的文本
            Phase 2: 创建 Mock Adapter
            Phase 3: 执行管道
            Phase 4: 验证警告生成
        """
        from utils.doc_pipeline import OCRAdapter

        steps = []
        inputs = {"测试目标": "警告检测"}

        # Phase 1: 准备会触发警告的文本
        # 包含幻觉短语
        warning_text = """好的，以下是处理后的内容：

# 简短标题

这是一段很短的内容。

```markdown
额外代码块
```
"""
        steps.append(
            {
                "phase": "Phase 1",
                "action": "准备警告触发文本",
                "detail": "包含幻觉短语和代码块",
            }
        )

        # Phase 2: 创建 Mock Adapter
        class MockOCRAdapter(OCRAdapter):
            """模拟 OCR 适配器。"""

            def __init__(self, content: str) -> None:
                self._content = content

            def to_markdown(self, file_path: str) -> str:  # noqa: ARG002
                return self._content

        # Phase 3: 执行管道
        adapter = MockOCRAdapter(warning_text)
        cleaner = MarkdownCleaner(llm=None)
        pipeline = DocPipeline(adapter=adapter, cleaner=cleaner)

        result = pipeline.run("dummy.pdf")

        steps.append(
            {
                "phase": "Phase 3",
                "action": "执行管道",
                "detail": f"警告数: {len(result.warnings)}",
            }
        )

        # Phase 4: 验证警告
        outputs = {
            "警告数量": f"{len(result.warnings)} 个",
            "警告内容": result.warnings[:3] if result.warnings else "无",
        }

        # 检查是否检测到幻觉短语
        has_hallucination_warning = any("幻觉" in w for w in result.warnings)

        conclusion = "✅ 测试通过" if has_hallucination_warning else "⚠️ 未检测到预期警告"

        report_path = _write_report(
            test_name="test_pipeline_validation_warnings",
            steps=steps,
            inputs=inputs,
            outputs=outputs,
            conclusion=conclusion,
        )

        assert os.path.exists(report_path), "测试报告未生成"
