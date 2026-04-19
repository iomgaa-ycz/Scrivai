"""文档格式转换 — pandoc / LibreOffice / MonkeyOCR HTTP。

外部依赖:
- pandoc 二进制(docx → markdown)
- libreoffice/soffice 二进制(doc → docx)
- MonkeyOCR HTTP 服务(默认 http://100.81.95.44:7861)的 Docker 容器

所有失败统一抛 IOError(明确错误信息);不静默回退。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests


def docx_to_markdown(path: str | Path) -> str:
    """pandoc docx → markdown(UTF-8)。

    参数:
        path: .docx 文件路径
    返回:
        markdown 文本
    异常:
        IOError — pandoc 不可用 / 文件不存在 / 转换失败
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"文件不存在:{src}")
    if shutil.which("pandoc") is None:
        raise IOError("未找到 pandoc 二进制(请 `apt install pandoc` 或 conda install)")

    proc = subprocess.run(
        ["pandoc", str(src), "-t", "markdown"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise IOError(f"pandoc 转换失败({src}):{proc.stderr.strip()}")
    return proc.stdout


def doc_to_markdown(path: str | Path) -> str:
    """LibreOffice headless 把 .doc 转成 .docx,再调 docx_to_markdown。

    LibreOffice 也能识别 .docx 输入,所以 .docx 也能走此路径(冗余但安全)。
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"文件不存在:{src}")
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice is None:
        raise IOError("未找到 libreoffice/soffice 二进制")

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(out_dir),
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise IOError(f"LibreOffice 转 docx 失败({src}):{proc.stderr.strip()}")
        # 输出文件名 = 原文件名 stem + .docx
        converted = out_dir / f"{src.stem}.docx"
        if not converted.is_file():
            raise IOError(f"LibreOffice 未生成预期文件:{converted}")
        return docx_to_markdown(converted)


def pdf_to_markdown(
    path: str | Path,
    *,
    base_url: str = "http://100.81.95.44:7861",
    timeout: int = 300,
) -> str:
    """MonkeyOCR HTTP 服务把 PDF 转 markdown。

    流程(参考 Reference/smart-construction-ai/crawler.py):
      1. POST {base_url}/parse 上传 PDF
      2. 响应取 download_url
      3. GET {download_url} 拿 ZIP
      4. 从 ZIP 中提取 .md 文件内容

    参数:
        path: .pdf 文件路径
        base_url: MonkeyOCR 服务地址(默认硬编码,由调用方按需覆盖)
        timeout: 单次 HTTP 请求超时(秒)
    返回:
        markdown 文本
    异常:
        IOError — 服务不可达 / 响应非 200 / 没有 .md 文件
    """
    src = Path(path)
    if not src.is_file():
        raise IOError(f"文件不存在:{src}")

    base = base_url.rstrip("/")

    # MonkeyOCR 通常是内网服务，绕过系统代理
    session = requests.Session()
    session.trust_env = False

    try:
        with src.open("rb") as f:
            files = {"file": (src.name, f, "application/pdf")}
            resp = session.post(f"{base}/parse", files=files, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise IOError(f"MonkeyOCR 网络请求失败({base}):{e}") from e

    if resp.status_code != 200:
        raise IOError(f"MonkeyOCR /parse 返回 {resp.status_code}:{resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise IOError(f"MonkeyOCR 处理失败:{data.get('message')}")
    download_url = data.get("download_url")
    if not download_url:
        raise IOError(f"MonkeyOCR 响应缺 download_url:{data}")

    full_url = f"{base}{download_url}" if download_url.startswith("/") else download_url

    try:
        zip_resp = session.get(full_url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise IOError(f"MonkeyOCR 下载 ZIP 失败({full_url}):{e}") from e

    if zip_resp.status_code != 200:
        raise IOError(f"MonkeyOCR 下载 ZIP 返回 {zip_resp.status_code}")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            md_files = [n for n in zf.namelist() if n.endswith(".md")]
            if not md_files:
                raise IOError("MonkeyOCR ZIP 中未找到 .md 文件")
            return zf.read(md_files[0]).decode("utf-8")
    except zipfile.BadZipFile as e:
        raise IOError(f"MonkeyOCR 返回的不是有效 ZIP:{e}") from e
