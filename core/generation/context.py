"""上下文工具模块。

提供摘要生成、术语提取、引用提取能力，保障长文档连贯性。
独立可用，不依赖 GenerationEngine。
模板外置：j2 骨架 + md 内容分离。
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import jinja2

from core.llm import LLMClient

logger = logging.getLogger(__name__)

# 模板目录（相对于项目根目录）
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates" / "prompts"


def _load_template(name: str) -> tuple[jinja2.Template, str]:
    """加载 j2 骨架模板。

    Args:
        name: 模板名称（不含扩展名），如 "summarize"

    Returns:
        (Jinja2 模板对象, prompt 内容)
    """
    j2_path = _TEMPLATES_DIR / f"{name}.j2"
    md_path = _TEMPLATES_DIR / f"{name}.md"

    # 读取 j2 骨架
    j2_content = j2_path.read_text(encoding="utf-8")

    # 读取 md 内容（如果存在）
    prompt_content = ""
    if md_path.exists():
        prompt_content = md_path.read_text(encoding="utf-8")

    # 创建模板并返回
    template = jinja2.Template(j2_content)
    return template, prompt_content


class GenerationContext:
    """上下文工具，保障长文档连贯性。

    提供三个核心能力：
    - 摘要生成：压缩前文，控制上下文窗口
    - 术语提取：构建术语表，保证一致性
    - 引用提取：追踪交叉引用关系

    Args:
        llm: LLM 客户端
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def summarize(self, text: str) -> str:
        """生成前文摘要。

        Args:
            text: 已生成的章节文本

        Returns:
            压缩后的摘要文本（约 200 字）
        """
        template, prompt_content = _load_template("summarize")
        rendered = template.render(prompt_content=prompt_content, text=text)
        response = self._llm.chat([{"role": "user", "content": rendered}])
        return response.strip()

    def extract_terms(self, text: str, existing: dict[str, str]) -> dict[str, str]:
        """提取术语并合并到已有术语表。

        用于长文档生成时，从已生成章节提取专业术语及其定义，
        构建术语表传递给后续章节，确保全文术语使用一致。

        Args:
            text: 章节文本
            existing: 已有术语表 {术语: 定义}

        Returns:
            合并后的术语表（existing + 新提取的术语）
        """
        template, prompt_content = _load_template("extract_terms")
        rendered = template.render(
            prompt_content=prompt_content,
            text=text,
            existing_terms=list(existing.keys()),
        )
        response = self._llm.chat([{"role": "user", "content": rendered}])

        new_terms = self._parse_json_response(response, {})
        if not isinstance(new_terms, dict):
            logger.warning("术语提取返回非 dict，跳过合并")
            return existing

        # 合并：新术语覆盖旧定义
        return {**existing, **new_terms}

    def extract_references(self, text: str) -> list[dict[str, Any]]:
        """提取交叉引用。

        Args:
            text: 章节文本

        Returns:
            引用列表，每项包含：
            - source: 来源标识（如 "ch03"）
            - target: 被引用对象（如 "第2章"、"表3-1"）
            - type: 引用类型 (section/table/figure)
        """
        template, prompt_content = _load_template("extract_references")
        rendered = template.render(prompt_content=prompt_content, text=text)
        response = self._llm.chat([{"role": "user", "content": rendered}])

        refs = self._parse_json_response(response, [])
        if not isinstance(refs, list):
            logger.warning("引用提取返回非 list，返回空列表")
            return []

        # 验证每项结构
        valid_refs = []
        for ref in refs:
            if isinstance(ref, dict) and "target" in ref and "type" in ref:
                valid_refs.append(
                    {
                        "source": ref.get("source", ""),
                        "target": ref["target"],
                        "type": ref["type"],
                    }
                )
        return valid_refs

    def _parse_json_response(self, response: str, default: Any) -> Any:
        """解析 LLM 返回的 JSON。

        Args:
            response: LLM 原始响应
            default: 解析失败时的默认返回值

        Returns:
            解析后的 Python 对象，或 default
        """
        # 尝试提取 JSON 块
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 尝试直接解析
            json_str = response.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON 解析失败: %s, 响应片段: %s", e, response[:100])
            return default
