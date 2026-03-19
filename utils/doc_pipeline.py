"""文档预处理管道模块。

提供 PDF → Markdown 的转换和清洗能力，支持多种 OCR 后端。
"""

import logging
import os
import re
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from core.llm import LLMClient

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# OCRAdapter 抽象基类
# ═══════════════════════════════════════════════════════════════════════════════


class OCRAdapter(ABC):
    """OCR 后端抽象基类，统一接口。

    所有 OCR 适配器必须实现 to_markdown() 方法。
    """

    @abstractmethod
    def to_markdown(self, file_path: str) -> str:
        """将 PDF 文件转换为原始 Markdown。

        Args:
            file_path: 本地 PDF 文件路径

        Returns:
            原始 Markdown 文本（未清洗）

        Raises:
            ValueError: 非 PDF 文件
            RuntimeError: OCR 处理失败
        """
        ...

    @staticmethod
    def _validate_pdf(file_path: str) -> None:
        """验证文件是否为 PDF。

        Args:
            file_path: 文件路径

        Raises:
            ValueError: 非 PDF 文件或文件不存在
        """
        if not os.path.isfile(file_path):
            raise ValueError(f"文件不存在: {file_path}")

        if not file_path.lower().endswith(".pdf"):
            raise ValueError(f"只支持 PDF 文件，当前文件: {file_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MonkeyOCRAdapter
# ═══════════════════════════════════════════════════════════════════════════════


class MonkeyOCRAdapter(OCRAdapter):
    """MonkeyOCR 远程服务适配器。

    实现流程:
        POST /parse 上传 PDF → 获取 download_url → 下载 ZIP → 提取 .md

    Args:
        base_url: MonkeyOCR 服务地址
        timeout: 请求超时时间（秒）
    """

    def __init__(self, base_url: str, timeout: int = 120) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def to_markdown(self, file_path: str) -> str:
        """将 PDF 转换为原始 Markdown。

        Args:
            file_path: 本地 PDF 文件路径

        Returns:
            原始 Markdown 文本

        Raises:
            ValueError: 非 PDF 文件
            RuntimeError: OCR 处理失败
        """
        # Phase 1: 验证文件（必须是 PDF）
        self._validate_pdf(file_path)

        logger.info("MonkeyOCR 处理开始: %s", file_path)

        # Phase 2: POST /parse 上传
        upload_url = f"{self._base_url}/parse"
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            try:
                response = requests.post(upload_url, files=files, timeout=self._timeout)
                response.raise_for_status()
            except requests.RequestException as e:
                raise RuntimeError(f"MonkeyOCR 上传失败: {e}") from e

        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"MonkeyOCR 处理失败: {result.get('msg', '未知错误')}")

        download_url = result.get("data", {}).get("download_url")
        if not download_url:
            raise RuntimeError("MonkeyOCR 返回数据中缺少 download_url")

        # Phase 3: 下载 ZIP
        try:
            zip_response = requests.get(download_url, timeout=self._timeout)
            zip_response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"下载 OCR 结果失败: {e}") from e

        # Phase 4: 提取 .md 文件
        try:
            with zipfile.ZipFile(BytesIO(zip_response.content)) as zf:
                md_files = [name for name in zf.namelist() if name.endswith(".md")]
                if not md_files:
                    raise RuntimeError("ZIP 文件中未找到 .md 文件")

                # 读取第一个 .md 文件
                md_content = zf.read(md_files[0]).decode("utf-8")
                logger.info("MonkeyOCR 处理完成，提取文件: %s", md_files[0])
                return md_content
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"ZIP 文件解析失败: {e}") from e


# ═══════════════════════════════════════════════════════════════════════════════
# DoclingAdapter
# ═══════════════════════════════════════════════════════════════════════════════


class DoclingAdapter(OCRAdapter):
    """Docling 本地 OCR 适配器。

    实现流程:
        DocumentConverter().convert(path) → document.export_to_markdown()

    注意: docling 库延迟导入，避免不必要的依赖加载。
    """

    def __init__(self) -> None:
        pass  # docling 延迟导入

    def to_markdown(self, file_path: str) -> str:
        """将 PDF 转换为原始 Markdown。

        Args:
            file_path: 本地 PDF 文件路径

        Returns:
            原始 Markdown 文本

        Raises:
            ValueError: 非 PDF 文件
            RuntimeError: OCR 处理失败
        """
        # Phase 1: 验证文件（必须是 PDF）
        self._validate_pdf(file_path)

        logger.info("Docling 处理开始: %s", file_path)

        # Phase 2: 延迟导入 docling
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            raise RuntimeError("未安装 docling 库，请执行: pip install docling") from e

        # Phase 3: 转换并导出 Markdown
        try:
            converter = DocumentConverter()
            result = converter.convert(file_path)
            md_content = result.document.export_to_markdown()
            logger.info("Docling 处理完成")
            return md_content
        except Exception as e:
            raise RuntimeError(f"Docling 转换失败: {e}") from e


# ═══════════════════════════════════════════════════════════════════════════════
# MarkdownCleaner
# ═══════════════════════════════════════════════════════════════════════════════


class MarkdownCleaner:
    """两阶段 Markdown 清洗。

    Phase 1（正则，必须）:
        - 水印移除
        - 异常表格分隔行修复
        - 残留 HTML 标签清理
        - LaTeX 符号 → Unicode

    Phase 2（LLM，可选）:
        - 分块 → 语义清洗 → 后处理

    Args:
        llm: LLM 客户端（可选，传 None 跳过 LLM 清洗）
        chunk_size: LLM 清洗时的分块大小（字符数）
    """

    # LaTeX 符号 → Unicode 映射表
    # 按长度降序排列，避免部分匹配（如 \geqslant 先于 \geq）
    LATEX_SYMBOL_MAP: dict[str, str] = {
        r"\geqslant": "≥",
        r"\leqslant": "≤",
        r"\leftrightarrow": "↔",
        r"\bigstar": "★",
        r"\rightarrow": "→",
        r"\leftarrow": "←",
        r"\Rightarrow": "⇒",
        r"\Leftarrow": "⇐",
        r"\uparrow": "↑",
        r"\downarrow": "↓",
        r"\subseteq": "⊆",
        r"\supseteq": "⊇",
        r"\emptyset": "∅",
        r"\parallel": "∥",
        r"\geq": "≥",
        r"\leq": "≤",
        r"\ge": "≥",
        r"\le": "≤",
        r"\neq": "≠",
        r"\ne": "≠",
        r"\times": "×",
        r"\approx": "≈",
        r"\infty": "∞",
        r"\degree": "°",
        r"\circ": "°",
        r"\alpha": "α",
        r"\beta": "β",
        r"\gamma": "γ",
        r"\delta": "δ",
        r"\epsilon": "ε",
        r"\theta": "θ",
        r"\lambda": "λ",
        r"\mu": "μ",
        r"\pi": "π",
        r"\sigma": "σ",
        r"\omega": "ω",
        r"\phi": "φ",
        r"\psi": "ψ",
        r"\rho": "ρ",
        r"\tau": "τ",
        r"\chi": "χ",
        r"\Delta": "Δ",
        r"\Sigma": "Σ",
        r"\Omega": "Ω",
        r"\Pi": "Π",
        r"\Phi": "Φ",
        r"\sqrt": "√",
        r"\cdot": "·",
        r"\bullet": "•",
        r"\star": "★",
        r"\pm": "±",
        r"\mp": "∓",
        r"\div": "÷",
        r"\sim": "~",
        r"\propto": "∝",
        r"\perp": "⊥",
        r"\subset": "⊂",
        r"\supset": "⊃",
        r"\in": "∈",
        r"\notin": "∉",
        r"\cup": "∪",
        r"\cap": "∩",
        r"\forall": "∀",
        r"\exists": "∃",
        r"\neg": "¬",
        r"\land": "∧",
        r"\lor": "∨",
        r"\triangle": "△",
        r"\square": "□",
        r"\boxdot": "☑",
        r"\checkmark": "✓",
    }

    def __init__(self, llm: "LLMClient | None" = None, chunk_size: int = 2000) -> None:
        self._llm = llm
        self._chunk_size = chunk_size

    def clean(self, text: str) -> str:
        """执行两阶段清洗。

        Args:
            text: 原始 Markdown 文本

        Returns:
            清洗后的 Markdown 文本
        """
        logger.info("开始 Markdown 清洗")

        # Phase 1: 正则清洗（必须）
        text = self._regex_clean(text)
        logger.debug("正则清洗完成")

        # Phase 2: LLM 清洗（可选）
        if self._llm is not None:
            text = self._llm_clean(text)
            logger.debug("LLM 清洗完成")

        logger.info("Markdown 清洗完成")
        return text

    def _regex_clean(self, text: str) -> str:
        """正则清洗阶段。

        Args:
            text: 原始文本

        Returns:
            清洗后文本
        """
        # 1. 移除水印
        text = self._remove_watermark(text)

        # 2. 修复异常表格分隔行
        text = self._fix_table_separators(text)

        # 3. 清理 HTML 标签
        text = self._clean_html_tags(text)

        # 4. LaTeX 符号转换
        text = self._convert_latex_symbols(text)

        # 5. 压缩连续空行
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    @staticmethod
    def _remove_watermark(text: str) -> str:
        """移除 OCR 残留水印。"""
        # 移除 CHINA SOUTHERN POWER GRID 及变体
        text = re.sub(
            r"(?i)CHINA\s+SOUTHERN\s+POWER\s+GRID(?:\s+CO\.?\s*,?\s*LTD\.?)?\s*",
            "",
            text,
        )
        return text

    @staticmethod
    def _fix_table_separators(text: str) -> str:
        """修复异常长的表格分隔行。

        处理:
        1. 超长管道分隔行（>500字符）压缩为 ---
        2. 纯 '-' 行（>50字符）压缩为 ---
        3. 以 | 开头但未以 | 结尾的分隔行补齐
        """
        lines = text.split("\n")
        fixed_lines = []

        for line in lines:
            stripped = line.strip()

            # Case 1: 超长管道分隔行（>500字符）
            if "|" in stripped and len(stripped) > 500:
                non_sep_chars = re.sub(r"[\s\-|:]", "", stripped)
                if len(non_sep_chars) < len(stripped) * 0.05:
                    fixed = re.sub(r"-{3,}", "---", stripped)
                    fixed_lines.append(fixed)
                    continue

            # Case 2: 管道分隔行（>200字符）
            if re.match(r"^\|[\s\-:|]+\|?$", stripped) and len(stripped) > 200:
                fixed = re.sub(r"-{3,}", "---", stripped)
                if not fixed.endswith("|"):
                    fixed += "|"
                fixed_lines.append(fixed)
                continue

            # Case 3: 纯 '-' 行（>50字符）
            if re.match(r"^-{50,}$", stripped):
                fixed_lines.append("---")
                continue

            fixed_lines.append(line)

        return "\n".join(fixed_lines)

    @staticmethod
    def _clean_html_tags(text: str) -> str:
        """清理残留 HTML 标签。

        - 将 HTML 表格转换为 Markdown 表格
        - 移除其他 HTML 标签，保留内部文本
        """

        def html_table_to_markdown(match: re.Match) -> str:
            """将 HTML <table> 转换为 GFM Markdown。"""
            table_html = match.group(0)

            try:
                # 提取行
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
                if not rows:
                    return table_html

                md_rows = []
                max_cols = 0

                for row in rows:
                    cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", row, re.DOTALL)
                    if not cells:
                        continue

                    # 清理单元格内容
                    cleaned_cells = []
                    for cell in cells:
                        cell = re.sub(r"<br\s*/?>", " ", cell)
                        cell = re.sub(r"<[^>]+>", "", cell)
                        cell = " ".join(cell.split())
                        cleaned_cells.append(cell.strip())

                    if cleaned_cells:
                        max_cols = max(max_cols, len(cleaned_cells))
                        md_rows.append(cleaned_cells)

                if not md_rows:
                    return ""

                # 补齐列数
                for i in range(len(md_rows)):
                    while len(md_rows[i]) < max_cols:
                        md_rows[i].append("")

                # 构建 Markdown 表格
                result_lines = []
                result_lines.append("| " + " | ".join(md_rows[0]) + " |")
                result_lines.append("| " + " | ".join(["---"] * max_cols) + " |")
                for row in md_rows[1:]:
                    result_lines.append("| " + " | ".join(row) + " |")

                return "\n".join(result_lines)

            except Exception:
                cleaned = re.sub(r"<[^>]+>", " ", table_html)
                return " ".join(cleaned.split())

        # 转换 HTML 表格
        text = re.sub(
            r"<table[^>]*>.*?</table>",
            html_table_to_markdown,
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # 移除自闭合标签
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)

        # 移除其他标签，保留文本
        text = re.sub(
            r"</?(?:sup|sub|em|strong|b|i|u|s|span|div|p|font)[^>]*>",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*[^>]*>", "", text, flags=re.IGNORECASE)

        return text

    def _convert_latex_symbols(self, text: str) -> str:
        r"""转换 LaTeX 符号为 Unicode。

        处理模式:
        - $\symbol$ → unicode
        - $N^{\circ}$ → N°
        - $\symbol VALUE$ → unicode+value
        """
        # 处理角度模式: $45^{\circ}$ → 45°
        text = re.sub(r"\$\s*(\d+)\s*\^\s*\{?\s*\\circ\s*\}?\s*\$", r"\1°", text)

        # 处理独立 $\circ$ → °
        text = re.sub(r"\$\s*\\circ\s*\$", "°", text)

        # 处理 $^\circ$ 模式
        text = re.sub(r"\$\s*\^\s*\{?\s*\\circ\s*\}?\s*\$", "°", text)

        # 按长度降序处理符号映射
        sorted_symbols = sorted(self.LATEX_SYMBOL_MAP.keys(), key=len, reverse=True)

        for latex_cmd in sorted_symbols:
            unicode_char = self.LATEX_SYMBOL_MAP[latex_cmd]
            escaped = re.escape(latex_cmd)
            # 匹配 $\cmd$
            pattern = r"\$\s*" + escaped + r"\s*\$"
            text = re.sub(pattern, unicode_char, text)

        # 处理 $\symbol VALUE$ 模式（比较符号后跟数值）
        comparison_symbols = {
            r"\geqslant": "≥",
            r"\leqslant": "≤",
            r"\geq": "≥",
            r"\leq": "≤",
            r"\ge": "≥",
            r"\le": "≤",
            r"\approx": "≈",
            r"\neq": "≠",
            r"\ne": "≠",
        }
        sorted_comp = sorted(comparison_symbols.keys(), key=len, reverse=True)
        for latex_cmd in sorted_comp:
            unicode_char = comparison_symbols[latex_cmd]
            escaped = re.escape(latex_cmd)
            pattern = r"\$\s*" + escaped + r"\s*([0-9][0-9a-zA-Z.,%]*)\s*\$"
            text = re.sub(pattern, unicode_char + r"\1", text)

        return text

    def _llm_clean(self, text: str) -> str:
        """LLM 清洗阶段。

        Args:
            text: 正则清洗后的文本

        Returns:
            LLM 清洗后的文本
        """
        chunks = self._chunk_text(text)
        logger.info("LLM 清洗分块: 共 %d 块", len(chunks))

        cleaned_chunks = []
        for i, chunk in enumerate(chunks):
            logger.debug("处理第 %d/%d 块", i + 1, len(chunks))
            try:
                result = self._llm.chat_with_template(
                    template="templates/prompts/clean.j2",
                    variables={"prompt_content": self._load_prompt(), "text": chunk},
                )
                result = self._post_process(result)
                cleaned_chunks.append(result)
            except Exception as e:
                logger.warning("LLM 清洗块 %d 异常，保留原文: %s", i + 1, e)
                cleaned_chunks.append(chunk)

        return "\n\n".join(cleaned_chunks)

    def _chunk_text(self, content: str) -> list[str]:
        """基于段落的智能分块。

        1. 按双换行分割段落
        2. 累积段落直到达到 chunk_size
        3. 标题处提前截断以保持结构完整
        """
        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para_len = len(para)
            is_header = para.strip().startswith("#")

            # 判断是否需要截断
            if (current_length + para_len > self._chunk_size) or (
                is_header and current_length > self._chunk_size * 0.5
            ):
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0

            current_chunk.append(para)
            current_length += para_len + 2

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    @staticmethod
    def _load_prompt() -> str:
        """加载 LLM 清洗 prompt。"""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "prompts",
            "clean.md",
        )
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()

    def _post_process(self, text: str) -> str:
        """LLM 输出后处理。"""
        # 1. 移除对话性前缀
        preamble_patterns = [
            r"^\s*好的[，,。！!：:\s]*",
            r"^\s*以下是[^\n]*[：:\n]",
            r"^\s*当然[，,。！!：:\s]*",
            r"^\s*我来[^\n]*[：:\n]",
            r"^\s*为[您你][^\n]*[：:\n]",
            r"^\s*没问题[，,。！!：:\s]*",
            r"^\s*收到[，,。！!：:\s]*",
            r"^\s*明白[，,。！!：:\s]*",
            r"^\s*可以的?[，,。！!：:\s]*",
            r"^\s*让我[^\n]*[：:\n]",
            r"^\s*下面是[^\n]*[：:\n]",
            r"^\s*请看[^\n]*[：:\n]",
            r"^\s*处理完成[^\n]*[：:\n]",
            r"^\s*优化如下[^\n]*[：:\n]",
            r"^\s*Here is[^\n]*[:\n]",
            r"^\s*Sure[,!.:\s]*",
            r"^\s*I have[^\n]*[:\n]",
            r"^\s*The following[^\n]*[:\n]",
            r"^\s*Markdown\s*内容如下[：:\s]*",
        ]
        for pattern in preamble_patterns:
            text = re.sub(pattern, "", text, count=1)

        # 2. 移除对话性后缀
        suffix_patterns = [
            r"\n\s*以上是[^\n]*$",
            r"\n\s*希望[^\n]*$",
            r"\n\s*如[有需][^\n]*$",
            r"\n\s*处理完成[^\n]*$",
        ]
        for pattern in suffix_patterns:
            text = re.sub(pattern, "", text)

        # 3. 移除残留水印
        text = self._remove_watermark(text)

        # 4. 移除代码块包裹
        text = re.sub(r"^\s*```(?:markdown)?\s*\n", "", text)
        text = re.sub(r"\n\s*```\s*$", "", text)

        # 5. 修复异常表格分隔行
        text = self._fix_table_separators(text)

        # 6. LaTeX 符号转换
        text = self._convert_latex_symbols(text)

        # 7. 清理 HTML 标签
        text = self._clean_html_tags(text)

        return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# DocPipelineResult
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DocPipelineResult:
    """文档处理结果。

    Attributes:
        raw_md: OCR 原始输出
        cleaned_md: 清洗后输出
        warnings: 验证警告列表
    """

    raw_md: str
    cleaned_md: str
    warnings: list[str]


# ═══════════════════════════════════════════════════════════════════════════════
# DocPipeline
# ═══════════════════════════════════════════════════════════════════════════════


class DocPipeline:
    """文档预处理管道，组合 adapter + cleaner。

    Args:
        adapter: OCR 适配器
        cleaner: Markdown 清洗器
    """

    def __init__(self, adapter: OCRAdapter, cleaner: MarkdownCleaner) -> None:
        self._adapter = adapter
        self._cleaner = cleaner

    def run(self, file_path: str) -> DocPipelineResult:
        """执行完整管道: OCR → 清洗 → 验证。

        Args:
            file_path: PDF 文件路径

        Returns:
            处理结果（含原始/清洗文本和警告）
        """
        logger.info("DocPipeline 开始处理: %s", file_path)

        # Phase 1: OCR 转换
        raw_md = self._adapter.to_markdown(file_path)
        logger.info("OCR 转换完成，原始长度: %d", len(raw_md))

        # Phase 2: 清洗
        cleaned_md = self._cleaner.clean(raw_md)
        logger.info("清洗完成，清洗后长度: %d", len(cleaned_md))

        # Phase 3: 验证（生成警告，不抛异常）
        warnings = self._validate(raw_md, cleaned_md)

        logger.info("DocPipeline 处理完成，警告数: %d", len(warnings))
        return DocPipelineResult(raw_md=raw_md, cleaned_md=cleaned_md, warnings=warnings)

    def _validate(self, raw: str, cleaned: str) -> list[str]:
        """验证清洗结果，返回警告列表。

        Args:
            raw: 原始文本
            cleaned: 清洗后文本

        Returns:
            警告列表
        """
        warnings = []

        # 1. 字数损失检查（< 50%）
        if len(raw) > 0 and len(cleaned) / len(raw) < 0.5:
            warnings.append(f"字数损失过大: 原始 {len(raw)}, 清洗后 {len(cleaned)}")

        # 2. 幻觉短语检查
        hallucination_patterns = [
            r"^好的[，,。]",
            r"^以下是",
            r"^当然[，,。]",
            r"```markdown",
        ]
        for pattern in hallucination_patterns:
            if re.search(pattern, cleaned, re.MULTILINE):
                warnings.append(f"检测到幻觉短语: {pattern}")
                break

        # 3. 表格结构检查
        lines = cleaned.split("\n")
        for i, line in enumerate(lines):
            if "|" in line and line.count("|") < 2:
                warnings.append(f"第 {i + 1} 行表格管道符数量不足")
                break

        return warnings
