"""SDK 入口模块。

提供 Project 类作为统一入口，负责配置加载和组件组装。
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from scrivai.audit.engine import AuditEngine
from scrivai.generation.context import GenerationContext
from scrivai.generation.engine import GenerationEngine
from scrivai.knowledge.store import KnowledgeStore
from scrivai.llm import LLMClient, LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class ProjectConfig:
    """项目配置。

    Attributes:
        llm: LLM 配置
        knowledge: 知识库配置（可选）
        generation: 生成引擎配置（可选）
        audit: 审核引擎配置（可选）
    """

    llm: LLMConfig
    knowledge: dict[str, Any] = field(
        default_factory=lambda: {"db_path": "data/scrivai.db", "namespace": "default"}
    )
    generation: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)


class Project:
    """SDK 入口，配置加载 + 组件组装。

    Args:
        config_path: 项目配置文件路径（YAML 格式）

    Attributes:
        llm: LLM 客户端
        store: 知识库（可选）
        gen: 生成引擎
        audit: 审核引擎
        ctx: 上下文工具（GenerationContext）

    Example:
        >>> proj = Project("scrivai-project.yaml")
        >>> doc = proj.gen.generate_chapter(template, variables)
        >>> results = proj.audit.check_many(doc, checkpoints)
    """

    def __init__(self, config_path: str) -> None:
        """从 YAML 配置文件初始化所有组件。

        核心流程:
            Phase 1: 加载 YAML 配置
            Phase 2: 从 .env 读取敏感信息（覆盖 api_key）
            Phase 3: 实例化 LLMClient
            Phase 4: 实例化 KnowledgeStore（可选）
            Phase 5: 实例化 GenerationEngine + GenerationContext
            Phase 6: 实例化 AuditEngine
        """
        # Phase 1: 加载 YAML
        config = self._load_config(config_path)

        # Phase 2: 从 .env 读取 API key
        load_dotenv()
        api_key = os.getenv("LLM_API_KEY") or config.llm.api_key

        # Phase 3: 实例化 LLMClient（必须）
        llm_config = LLMConfig(
            model=config.llm.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            api_base=config.llm.api_base,
            api_key=api_key,
        )
        self.llm = LLMClient(llm_config)
        logger.info("LLMClient 初始化完成: model=%s", llm_config.model)

        # Phase 4: 实例化 KnowledgeStore（可选，默认启用）
        # 只有显式设为 null/false 才禁用
        self.store: KnowledgeStore | None = None
        kb_cfg = config.knowledge
        if kb_cfg is not None and kb_cfg is not False:
            db_path = kb_cfg.get("db_path", "data/scrivai.db")
            namespace = kb_cfg.get("namespace", "default")
            # 确保 db 目录存在
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.store = KnowledgeStore(db_path, namespace)
            logger.info("KnowledgeStore 初始化完成: db=%s, ns=%s", db_path, namespace)

        # Phase 5: 实例化 GenerationEngine + GenerationContext
        self.gen = GenerationEngine(self.llm, self.store)
        self.ctx = GenerationContext(self.llm)
        logger.info("GenerationEngine + GenerationContext 初始化完成")

        # Phase 6: 实例化 AuditEngine
        self.audit = AuditEngine(self.llm, self.store)
        logger.info("AuditEngine 初始化完成")

        # 保存原始配置（供用户访问）
        self._config = config

    def _load_config(self, config_path: str) -> ProjectConfig:
        """加载 YAML 配置文件。

        Args:
            config_path: 配置文件路径

        Returns:
            解析后的配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置格式错误
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "llm" not in data:
            raise ValueError("配置文件必须包含 llm 字段")

        llm_data = data["llm"]
        llm_config = LLMConfig(
            model=llm_data.get("model"),
            temperature=llm_data.get("temperature", 0.7),
            max_tokens=llm_data.get("max_tokens", 4096),
            api_base=llm_data.get("api_base"),
            api_key=llm_data.get("api_key"),
        )

        return ProjectConfig(
            llm=llm_config,
            knowledge=data.get("knowledge", {}),
            generation=data.get("generation", {}),
            audit=data.get("audit", {}),
        )

    @property
    def config(self) -> ProjectConfig:
        """访问原始配置对象。"""
        return self._config
