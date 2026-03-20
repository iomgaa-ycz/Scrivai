"""审核引擎模块。

提供单要点审核 + 批量审核能力，四维检查统一走 check_one()。
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import jinja2
import yaml

from scrivai.knowledge.store import KnowledgeStore
from scrivai.llm import LLMClient

logger = logging.getLogger(__name__)

# 模板目录
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates" / "prompts"


@dataclass
class AuditResult:
    """审核结果。

    Attributes:
        passed: 是否通过
        severity: 严重级别 ("error" | "warning" | "info")
        checkpoint_id: 审核要点标识
        chapter_id: 章节标识（可选）
        finding: 审核发现
        evidence: 支撑证据
        suggestion: 修改建议
    """

    passed: bool
    severity: str
    checkpoint_id: str
    chapter_id: str | None
    finding: str
    evidence: str
    suggestion: str


class AuditEngine:
    """审核引擎，四维检查统一接口。

    Args:
        llm: LLM 客户端
        store: 知识库（用于检索规则条文，可选）
    """

    def __init__(self, llm: LLMClient, store: KnowledgeStore | None = None) -> None:
        self._llm = llm
        self._store = store

    def check_one(self, document: str, checkpoint: dict) -> AuditResult:
        """单要点审核。

        Args:
            document: 待审文档文本
            checkpoint: 审核要点配置

        Returns:
            审核结果

        核心流程:
            Phase 1: 根据 scope 截取文档范围
            Phase 2: 根据 rule_refs 检索规则条文
            Phase 3: 渲染 prompt → 调用 LLM 判定
            Phase 4: 解析 LLM 输出 → 构造 AuditResult
        """
        # Phase 1: 截取文档范围
        scope = checkpoint.get("scope", "full")
        doc_section = self._extract_scope(document, scope)
        chapter_id = self._parse_chapter_id(scope)

        # Phase 2: 检索规则条文
        rules_text = ""
        if "rule_refs" in checkpoint and self._store:
            rules_text = self._retrieve_rules(checkpoint["rule_refs"])

        # Phase 3: 渲染 prompt 并调用 LLM
        prompt = self._build_prompt(
            checkpoint=checkpoint,
            document=doc_section,
            rules=rules_text,
        )
        response = self._llm.chat([{"role": "user", "content": prompt}])

        # Phase 4: 解析结果
        result = self._parse_response(response, checkpoint, chapter_id)
        return result

    def check_many(self, document: str, checkpoints: list[dict]) -> list[AuditResult]:
        """批量审核。

        Args:
            document: 待审文档文本
            checkpoints: 审核要点列表

        Returns:
            审核结果列表
        """
        return [self.check_one(document, cp) for cp in checkpoints]

    def load_checkpoints(self, path: str) -> list[dict]:
        """从 YAML 文件加载审核要点配置。

        Args:
            path: YAML 文件路径

        Returns:
            审核要点列表
        """
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("checkpoints", [])

    # === 私有方法 ===

    def _extract_scope(self, document: str, scope: str) -> str:
        """根据 scope 截取文档范围。"""
        if scope == "full":
            return document
        # 解析 "chapter:ch03" 格式
        match = re.match(r"chapter:(.+)", scope)
        if match:
            chapter_id = match.group(1)
            return self._extract_chapter(document, chapter_id)
        return document

    def _extract_chapter(self, document: str, chapter_id: str) -> str:
        """从文档中提取指定章节。"""
        # 简单实现：按 ## 标题分割
        pattern = rf"^##\s+.*{re.escape(chapter_id)}.*$"
        match = re.search(pattern, document, re.MULTILINE | re.IGNORECASE)
        if not match:
            return document
        start = match.start()
        # 找到下一个 ## 标题
        next_match = re.search(r"^##\s+", document[start + 1 :], re.MULTILINE)
        if next_match:
            end = start + 1 + next_match.start()
        else:
            end = len(document)
        return document[start:end].strip()

    def _parse_chapter_id(self, scope: str) -> str | None:
        """从 scope 解析章节 ID。"""
        match = re.match(r"chapter:(.+)", scope)
        return match.group(1) if match else None

    def _retrieve_rules(self, rule_refs: list[dict]) -> str:
        """检索规则条文。"""
        if not self._store:
            return ""

        rules = []
        for ref in rule_refs:
            if "query" in ref:
                # 语义查询
                results = self._store.search(
                    ref["query"],
                    top_k=3,
                    filters={"type": "rule"},
                )
                for r in results:
                    rules.append(f"【{r.metadata.get('source', '未知')}】{r.content}")
            elif "source" in ref and "clause_id" in ref:
                # 精确引用
                filters = {
                    "type": "rule",
                    "source": ref["source"],
                    "clause_id": ref["clause_id"],
                }
                results = self._store.search("", top_k=1, filters=filters)
                for r in results:
                    rules.append(f"【{ref['source']} {ref['clause_id']}】{r.content}")

        return "\n\n".join(rules)

    def _build_prompt(self, checkpoint: dict, document: str, rules: str) -> str:
        """构建审核 prompt。"""
        template = self._load_template("audit")
        return template.render(
            description=checkpoint.get("description", ""),
            prompt_template=checkpoint.get("prompt_template", ""),
            document=document,
            rules=rules,
        )

    def _load_template(self, name: str) -> jinja2.Template:
        """加载模板。

        将 .md 指令文件内容注入到 .j2 模板的 {{ prompt_content }} 变量中。
        """
        j2_path = _TEMPLATES_DIR / f"{name}.j2"
        md_path = _TEMPLATES_DIR / f"{name}.md"

        j2_content = j2_path.read_text(encoding="utf-8")
        prompt_content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

        # 将 prompt_content 作为全局变量注入模板
        env = jinja2.Environment()
        template = env.from_string(j2_content)
        template.globals["prompt_content"] = prompt_content
        return template

    def _parse_response(
        self,
        response: str,
        checkpoint: dict,
        chapter_id: str | None,
    ) -> AuditResult:
        """解析 LLM 响应为 AuditResult。"""
        # 解析 JSON
        data = self._parse_json_response(response, None)

        # 检查是否为有效 dict 且包含 passed 字段
        if isinstance(data, dict) and "passed" in data:
            return AuditResult(
                passed=data.get("passed", False),
                severity=checkpoint.get("severity", "warning"),
                checkpoint_id=checkpoint.get("id", ""),
                chapter_id=chapter_id,
                finding=data.get("finding", ""),
                evidence=data.get("evidence", ""),
                suggestion=data.get("suggestion", ""),
            )

        # JSON 解析失败，返回默认结果
        logger.warning("审核结果 JSON 解析失败，使用默认值")
        return AuditResult(
            passed=False,
            severity=checkpoint.get("severity", "warning"),
            checkpoint_id=checkpoint.get("id", ""),
            chapter_id=chapter_id,
            finding="无法解析审核结果",
            evidence=response[:200],
            suggestion="请人工复核",
        )

    def _parse_json_response(self, response: str, default: any) -> any:  # noqa: ANN401
        """解析 LLM 返回的 JSON。复用 GenerationContext 的逻辑。"""
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON 解析失败: %s, 响应片段: %s", e, response[:100])
            return default
