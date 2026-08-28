"""配置加载、校验、持久化与生效参数解析。

- 配置文件：btcmodule/btcm.json（不受 git 管理）
- 内置默认配置作为兜底，首次启动自动生成文件（原子写入）
- PUT /api/config 部分更新：按字段深度合并后整体校验
- GET /api/config 回显时不输出任何 provider 的 api_key
- 生效参数四层优先级：请求内 config > Agent 级 > 提供商级(timeout) > 内置默认
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .task import RuntimeConfig

CONFIG_FILE = Path(__file__).resolve().parent.parent / "btcm.json"

DEFAULT_WEB_SOURCES = ["wikipedia.org", "gov.cn", "edu.cn"]

# 内置 Agent 必须齐全，配置加载与更新时强校验
REQUIRED_AGENTS = ("creative", "validator", "controller")

# 各 Agent 的默认温度与最大输出 token（creative 0.8/2048，validator 0.3/2048，controller 0.3/1024）
AGENT_DEFAULT_TEMPERATURE = {
    "creative": 0.8,
    "validator": 0.3,
    "controller": 0.3,
}
AGENT_DEFAULT_MAX_TOKENS = {
    "creative": 2048,
    "validator": 2048,
    "controller": 1024,
}


class ConfigError(Exception):
    """配置读取或校验失败。"""


class ProviderConfig(BaseModel):
    """OpenAI 兼容提供商注册表条目。"""

    base_url: str
    api_key: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = Field(default=120, ge=1, le=3600)


class AgentConfig(BaseModel):
    """Agent 路由与运行参数。"""

    provider: str
    model: str
    num_candidates: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=256, le=32768)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    enable_web_search: bool = False
    web_sources: list[str] = Field(default_factory=lambda: list(DEFAULT_WEB_SOURCES))
    log_intermediate: bool = True


class BTCMConfig(BaseModel):
    """全局配置（btcm.json 的完整结构）。"""

    max_iterations: int = Field(default=2, ge=1, le=10)
    timeout: int = Field(default=300, ge=1, le=3600)
    enable_creative: bool = True
    enable_validator: bool = True
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


def build_default_config() -> BTCMConfig:
    """构建内置默认配置。模型路由示例为 DeepSeek + 本地 Ollama。"""

    def agent(name: str) -> AgentConfig:
        return AgentConfig(
            provider="deepseek",
            model="deepseek-chat" if name != "validator" else "deepseek-reasoner",
            temperature=AGENT_DEFAULT_TEMPERATURE[name],
            max_tokens=AGENT_DEFAULT_MAX_TOKENS[name],
            timeout=300 if name == "validator" else None,
            enable_web_search=False,
            web_sources=list(DEFAULT_WEB_SOURCES),
            log_intermediate=True,
        )

    return BTCMConfig(
        max_iterations=2,
        timeout=300,
        enable_creative=True,
        enable_validator=True,
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com/v1",
                models=["deepseek-chat", "deepseek-reasoner"],
            ),
            "ollama-local": ProviderConfig(
                base_url="http://localhost:11434/v1",
                api_key="not-set",
                models=["llama3:8b"],
                timeout=600,
            ),
        },
        agents={name: agent(name) for name in ("creative", "validator", "controller")},
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并：嵌套 dict 递归合并，list/标量整体替换。"""
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class ConfigManager:
    """配置的加载、校验、持久化与读取。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else CONFIG_FILE
        self._config: BTCMConfig = self._load()

    # ---------- 加载 ----------

    def _load(self) -> BTCMConfig:
        if not self.path.exists():
            cfg = build_default_config()
            self._write(cfg)
            return cfg
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise ConfigError(f"配置文件无法读取或解析：{e}") from e
        try:
            cfg = BTCMConfig.model_validate(raw)
        except ValidationError as e:
            raise ConfigError(f"配置文件校验失败：{e}") from e
        self._check_agents(cfg)
        return cfg

    # ---------- 写入 ----------

    def _write(self, cfg: BTCMConfig) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # ---------- 读取 ----------

    @property
    def config(self) -> BTCMConfig:
        return self._config

    @staticmethod
    def _check_agents(cfg: BTCMConfig) -> None:
        """强校验三个内置 Agent 定义齐全。"""
        missing = [name for name in REQUIRED_AGENTS if name not in cfg.agents]
        if missing:
            raise ConfigError(
                f"配置必须包含 Agent 定义，缺失：{', '.join(missing)}"
            )

    def as_public_dict(self) -> dict:
        """对外可读配置：排除所有 provider 的 api_key。"""
        data = self._config.model_dump()
        for provider in data.get("providers", {}).values():
            provider.pop("api_key", None)
        return data

    # ---------- 更新 ----------

    def update(self, partial: dict[str, Any]) -> BTCMConfig:
        """部分更新：与当前配置深度合并后整体校验，通过则原子写入并立即生效。"""
        current = self._config.model_dump()
        merged = _deep_merge(current, partial)
        try:
            new_cfg = BTCMConfig.model_validate(merged)
        except ValidationError as e:
            raise ConfigError(f"配置更新校验失败：{e}") from e
        self._check_agents(new_cfg)
        self._write(new_cfg)
        self._config = new_cfg
        return new_cfg

    def reset(self) -> BTCMConfig:
        """重置为内置默认配置。"""
        cfg = build_default_config()
        self._write(cfg)
        self._config = cfg
        return cfg


# ---------- 生效参数解析（四层优先级） ----------


def resolve_global_params(
    cfg: BTCMConfig, runtime: RuntimeConfig | None
) -> tuple[int, int]:
    """解析全局 max_iterations 与 timeout（请求内 config 优先）。"""
    max_iterations = cfg.max_iterations
    timeout = cfg.timeout
    if runtime is not None:
        if runtime.max_iterations is not None:
            max_iterations = runtime.max_iterations
        if runtime.timeout is not None:
            timeout = runtime.timeout
    return max_iterations, timeout


def resolve_agent_params(
    cfg: BTCMConfig, runtime: RuntimeConfig | None, agent_name: str
) -> dict:
    """解析某 Agent 的生效参数。

    优先级（从高到低）：请求内 config.agents.<name> > Agent 级配置 >
    提供商级 timeout（仅当 Agent 级未设置且请求未覆盖）> 内置默认。
    返回含 temperature / max_tokens / timeout 及该 Agent 专属参数的 dict。
    """
    agent_cfg = cfg.agents.get(agent_name)
    if agent_cfg is None:
        raise ConfigError(f"配置缺少 Agent 定义：{agent_name}")

    effective: dict = agent_cfg.model_dump()

    if runtime is not None:
        override = runtime.agents.get(agent_name)
        if override is not None:
            for key, value in override.model_dump().items():
                if value is not None:
                    effective[key] = value

    # timeout 兜底：Agent 级与请求级均未设置时，使用所属提供商的 timeout（默认 120）
    if effective.get("timeout") is None:
        provider_cfg = cfg.providers.get(agent_cfg.provider)
        effective["timeout"] = provider_cfg.timeout if provider_cfg else 120

    return effective


def resolve_agent_route(cfg: BTCMConfig, agent_name: str) -> tuple[str, str | None, str]:
    """返回某 Agent 路由的 (base_url, api_key, model)，供模型网关使用。"""
    agent_cfg = cfg.agents.get(agent_name)
    if agent_cfg is None:
        raise ConfigError(f"配置缺少 Agent 定义：{agent_name}")
    provider_cfg = cfg.providers.get(agent_cfg.provider)
    if provider_cfg is None:
        raise ConfigError(
            f"Agent '{agent_name}' 引用的提供商不存在：{agent_cfg.provider}"
        )
    return provider_cfg.base_url, provider_cfg.api_key, agent_cfg.model
