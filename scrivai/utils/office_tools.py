"""Office 文档预处理工具。

提供 Word 文档转 PDF、Word 文档转 Markdown 的原子工具函数，供调用方自行组合使用。
LibreOffice / Pandoc 均为系统依赖，需调用方自行安装，不作为 Python 包依赖管理。
"""

from __future__ import annotations

import locale
import shutil
import subprocess
from pathlib import Path

_WORD_SUFFIXES = {".doc", ".docx"}


def _resolve_executable(command: str, *, tool_name: str) -> str:
    """解析工具命令路径，缺失时给出明确报错。"""
    command_path = Path(command)
    if command_path.is_absolute() and command_path.exists():
        return str(command_path)

    resolved = shutil.which(command)
    if resolved is not None:
        return resolved

    raise RuntimeError(
        f"找不到 {tool_name} 可执行命令: {command!r}。"
        f"请先安装 {tool_name}，或通过参数显式传入正确的命令路径。"
    )


def _decode_command_output(raw: bytes | None) -> str:
    """按本机环境尽量容错解码外部命令输出。"""
    if not raw:
        return ""

    candidates: list[str] = []
    preferred = locale.getpreferredencoding(False)
    if preferred:
        candidates.append(preferred)
    for encoding in ("utf-8", "gbk"):
        if encoding not in candidates:
            candidates.append(encoding)

    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    return raw.decode(candidates[0], errors="replace")


def _run_command(args: list[str], *, tool_name: str, source_path: Path) -> None:
    """执行外部命令，将失败统一转成清晰错误。"""
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=False,
        )
    except OSError as exc:
        raise RuntimeError(f"执行 {tool_name} 失败: {exc}") from exc

    if result.returncode == 0:
        return

    stderr = _decode_command_output(result.stderr).strip()
    stdout = _decode_command_output(result.stdout).strip()
    detail_text = stderr or stdout
    detail = f" 详细信息: {detail_text}" if detail_text else ""
    raise RuntimeError(f"{tool_name} 处理文件失败: {source_path}{detail}")

def convert_word_to_docx_via_libreoffice(
    input_path: str | Path,
    output_path: str | Path,
    *,
    libreoffice_cmd: str,
) -> Path:
    """通过 LibreOffice headless 把 .doc / .docx 统一物化成 .docx。"""

    source_path = Path(input_path).resolve()
    if source_path.suffix.lower() not in {".doc", ".docx"}:
        raise ValueError("LibreOffice Word 预处理当前只支持 .doc / .docx 输入。")

    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    executable = _resolve_executable(libreoffice_cmd, tool_name="LibreOffice")
    produced_path = target_path.parent / f"{source_path.stem}.docx"

    _run_command(
        [
            executable,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(target_path.parent),
            str(source_path),
        ],
        tool_name="LibreOffice",
        source_path=source_path,
    )

    if not produced_path.exists() and target_path.exists():
        return target_path
    if not produced_path.exists():
        raise RuntimeError(f"LibreOffice 执行完成，但没有生成 DOCX 输出: {target_path.parent}")

    if produced_path != target_path:
        if target_path.exists():
            target_path.unlink()
        produced_path.replace(target_path)

    return target_path

def convert_word_to_pdf_via_libreoffice(
    input_path: str | Path,
    output_path: str | Path,
    *,
    libreoffice_cmd: str = "soffice",
) -> Path:
    """通过 LibreOffice headless 把 .doc / .docx 转成 PDF。

    参数:
        input_path: 输入的 Word 文件路径（.doc 或 .docx）。
        output_path: 期望输出的 PDF 路径，父目录不存在时自动创建。
        libreoffice_cmd: LibreOffice 可执行命令名或绝对路径，默认 ``soffice``。

    返回:
        最终生成的 PDF 文件路径。

    异常:
        ValueError: 输入文件后缀不是 .doc / .docx。
        RuntimeError: 找不到 LibreOffice 命令，或转换完成后未生成 PDF。
    """
    source_path = Path(input_path).resolve()
    if source_path.suffix.lower() not in _WORD_SUFFIXES:
        raise ValueError(
            f"只支持 .doc / .docx 输入，收到: {source_path.suffix!r}"
        )

    target_path = Path(output_path).resolve()  
    target_path.parent.mkdir(parents=True, exist_ok=True) 

    executable = _resolve_executable(libreoffice_cmd, tool_name="LibreOffice") 

    # LibreOffice 会在 outdir 下生成 <stem>.pdf，未必与 target_path 同名
    produced_path = target_path.parent / f"{source_path.stem}.pdf" 

    _run_command(
        [
            executable,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(target_path.parent),
            str(source_path),
        ],
        tool_name="LibreOffice",
        source_path=source_path,
    )

    if not produced_path.exists() and target_path.exists():  
        return target_path
    if not produced_path.exists():
        raise RuntimeError(
            f"LibreOffice 执行完成，但没有生成 PDF 输出: {target_path.parent}"
        )

    if produced_path != target_path: 
        if target_path.exists():
            target_path.unlink()
        produced_path.replace(target_path)

    return target_path


def convert_docx_to_markdown_via_pandoc(
    input_path: str | Path,
    output_path: str | Path,
    *,
    pandoc_cmd: str = "pandoc",
) -> Path:
    """通过 Pandoc 把 .docx 转成 Markdown。

    参数:
        input_path: 输入 .docx 文件路径。
        output_path: 输出 Markdown 文件路径，父目录不存在时自动创建。
        pandoc_cmd: Pandoc 可执行命令名或绝对路径，默认 ``pandoc``。

    返回:
        最终生成的 Markdown 文件路径。

    异常:
        ValueError: 输入文件后缀不是 .docx。
        RuntimeError: 找不到 Pandoc 命令，或转换完成后未生成输出文件。
    """
    source_path = Path(input_path).resolve()
    if source_path.suffix.lower() != ".docx":
        raise ValueError(
            f"只支持 .docx 输入，收到: {source_path.suffix!r}"
        )

    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    executable = _resolve_executable(pandoc_cmd, tool_name="Pandoc")
    _run_command(
        [
            executable,
            str(source_path),
            "--from",
            "docx",
            "--to",
            "markdown",
            "--output",
            str(target_path),
        ],
        tool_name="Pandoc",
        source_path=source_path,
    )

    if not target_path.exists():
        raise RuntimeError(
            f"Pandoc 执行完成，但没有生成 Markdown 输出: {target_path}"
        )
    return target_path
