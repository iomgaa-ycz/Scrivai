"""文档切片工具。

提供纯函数式的文本切分能力，支持按标题层级和条款编号切片。
"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """文本切片。

    Attributes:
        text: 切片文本内容
        metadata: 附加信息（heading / clause_id / index 等）
    """

    text: str
    metadata: dict = field(default_factory=dict)


def split_by_heading(text: str, level: int = 2) -> list[Chunk]:
    """按 Markdown 标题层级切分文本。

    Args:
        text: 待切分的 Markdown 文本
        level: 标题层级（默认 2，即 ##）

    Returns:
        切片列表，每片 metadata 含 heading 和 index
    """
    if not text.strip():
        return []

    pattern = re.compile(rf"^(#{{{level}}})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))

    if not matches:
        return [Chunk(text=text.strip(), metadata={"heading": None, "index": 0})]

    chunks: list[Chunk] = []
    # 标题前的内容
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            chunks.append(Chunk(text=pre, metadata={"heading": None, "index": 0}))

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunks.append(
            Chunk(
                text=body,
                metadata={"heading": m.group(2).strip(), "index": len(chunks)},
            )
        )

    return chunks


def split_by_clause(text: str, pattern: str | None = None) -> list[Chunk]:
    """按条款编号切分文本。

    Args:
        text: 待切分的文本
        pattern: 条款匹配正则（默认匹配 "第X条" 或 "1.1" 格式）

    Returns:
        切片列表，每片 metadata 含 clause_id 和 index
    """
    if not text.strip():
        return []

    if pattern is None:
        pattern = r"(?:第[一二三四五六七八九十百千]+条|\d+\.\d+)"

    regex = re.compile(rf"^({pattern})", re.MULTILINE)
    matches = list(regex.finditer(text))

    if not matches:
        return [Chunk(text=text.strip(), metadata={"clause_id": None, "index": 0})]

    chunks: list[Chunk] = []
    # 条款前的内容
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            chunks.append(Chunk(text=pre, metadata={"clause_id": None, "index": 0}))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        chunks.append(
            Chunk(
                text=body,
                metadata={"clause_id": m.group(1), "index": len(chunks)},
            )
        )

    return chunks
