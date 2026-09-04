"""配置加载、校验、持久化与生效参数解析。

- 配置文件：btcmodule/btcm.json（不受 git 管理）
- 内置默认配置作为兜底，首次启动自动生成文件（原子写入）
- PUT /api/config 部分更新：按字段深度合并后整体校验
- GET /api/config 回显时不输出任何 provider / mcp 服务器的 api_key 与 admin_token
- 生效参数四层优先级：请求内 config > Agent 级 > 提供商级(timeout) > 内置默认
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Literal

from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, model_validator

from .task import RuntimeConfig

logger = logging.getLogger("btcmodule.config")

CONFIG_FILE = Path(__file__).resolve().parent.parent / "btcm.json"

DEFAULT_WEB_SOURCES = ["wikipedia.org", "gov.cn", "edu.cn"]

# 内置 Agent 必须齐全，配置加载与更新时强校验
REQUIRED_AGENTS = ("creative", "validator", "controller", "meta")

# 全局兜底模型：所有解析链最终回退目标
DEFAULT_FALLBACK_MODEL = "gpt-3.5-turbo"

# 内置 MCP 预设：市面常见远程 MCP 服务器（Streamable HTTP），url 中 {api_key} 会被替换
MCP_PRESETS: dict[str, dict] = {
    "tavily": {
        "url": "https://mcp.tavily.com/mcp/?tavilyApiKey={api_key}",
        "needs_key": True,
        "desc": "Tavily 网络搜索",
    },
    "exa": {
        "url": "https://mcp.exa.ai/mcp?exaApiKey={api_key}",
        "needs_key": True,
        "desc": "Exa 搜索",
    },
    "deepwiki": {
        "url": "https://mcp.deepwiki.com/mcp",
        "needs_key": False,
        "desc": "DeepWiki 开源仓库文档",
    },
    "fetch": {
        "url": "https://remote.mcpservers.org/fetch/mcp",
        "needs_key": False,
        "desc": "网页抓取",
    },
    "duckduckgo": {
        "url": "http://127.0.0.1:7070/mcp",
        "needs_key": False,
        "desc": "DuckDuckGo 搜索（本地 MCP 服务，免密钥，由后端自动拉起）",
    },
}

# 各 Agent 的默认温度与最大输出 token（creative 0.8/2048，validator 0.3/2048，controller 0.3/1024，meta 0.3/1024）
AGENT_DEFAULT_TEMPERATURE = {
    "creative": 0.8,
    "validator": 0.3,
    "controller": 0.3,
    "meta": 0.3,
}
AGENT_DEFAULT_MAX_TOKENS = {
    "creative": 16384,
    "validator": 16384,
    "controller": 16384,
    "meta": 16384,
}


class ConfigError(Exception):
    """配置读取或校验失败。"""


class ProviderConfig(BaseModel):
    """OpenAI 兼容提供商注册表条目。"""

    base_url: str
    api_key: str | None = None
    models: list[str] = Field(default_factory=list)
    timeout: int = Field(default=600, ge=1)
    enabled: bool = True
    options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_base_url(self) -> "ProviderConfig":
        # 本地推理服务（Ollama / LM Studio）经 http://localhost 接入是合法用法，
        # 故只校验 scheme 与主机名，不做 MCP 那套私网地址限制
        u = urlparse(self.base_url)
        if u.scheme not in ("http", "https"):
            raise ValueError(
                f"提供商 base_url scheme 仅允许 http/https，收到：{u.scheme or '（空）'}"
            )
        if not u.hostname:
            raise ValueError(f"提供商 base_url 缺少主机名：{self.base_url}")
        return self


class MCPServerConfig(BaseModel):
    """MCP 服务器注册表条目（Streamable HTTP 传输）。

    url 直接给出，或由 preset（内置市面 MCP 预设）推导。
    """

    preset: str | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    timeout: int = Field(default=60, ge=1)
    allowed_tools: list[str] = Field(default_factory=list)
    allow_private: bool = False

    @model_validator(mode="after")
    def _check_target(self) -> "MCPServerConfig":
        if not self.url and not self.preset:
            raise ValueError("MCP 服务器需要 url 或 preset 之一")
        if self.preset and self.preset not in MCP_PRESETS:
            raise ValueError(f"未知 MCP 预设：{self.preset}")
        check_url = self.url if self.url else MCP_PRESETS.get(self.preset, {}).get("url", "")
        if check_url:
            _validate_mcp_url(check_url, self.allow_private)
        return self


def _mcp_effective_key(srv_name: str, srv: MCPServerConfig) -> str | None:
    """MCP api_key：优先取环境变量 BTCM_MCP_<NAME>_API_KEY，其次配置文件。"""
    env_key = _env_secret("MCP", f"{srv_name}_API_KEY")
    return env_key if env_key is not None else srv.api_key


def provider_api_key(cfg: BTCMConfig, provider_name: str) -> str | None:
    """提供商 api_key：优先取环境变量 BTCM_PROVIDER_<NAME>_API_KEY，其次配置文件。"""
    env_key = _env_secret("PROVIDER", f"{provider_name}_API_KEY")
    if env_key is not None:
        return env_key
    provider = cfg.providers.get(provider_name)
    return provider.api_key if provider else None


_PRIVATE_HOSTS = {
    "localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0",
}


def _is_private_host(hostname: str) -> bool:
    """判定主机名是否为私网/回环/链路本地地址。"""
    if hostname.lower() in _PRIVATE_HOSTS:
        return True
    try:
        parts = hostname.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            first = int(parts[0])
            if first == 10:
                return True
            if first == 172 and 16 <= int(parts[1]) <= 31:
                return True
            if first == 192 and parts[1] == "168":
                return True
            if first == 169 and parts[1] == "254":
                return True
            if first == 127:
                return True
    except (ValueError, IndexError):
        pass
    if hostname.lower().startswith("fc") or hostname.lower().startswith("fd"):
        return True
    if hostname.lower().startswith("fe80"):
        return True
    return False


def _validate_mcp_url(url: str, allow_private: bool) -> None:
    """校验 MCP URL：仅允许 http/https，私网地址默认拒绝。"""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError(f"MCP URL scheme 仅允许 http/https，收到：{u.scheme}")
    if not allow_private and _is_private_host(u.hostname or ""):
        raise ValueError(
            f"MCP URL 指向私网地址（{u.hostname}），"
            "如需放行请设置 allow_private=true"
        )


def resolve_mcp_url(srv_name: str, srv: MCPServerConfig) -> str:
    """解析 MCP 服务器实际 URL；预设需要 api_key 而未提供时报错。"""
    if srv.url:
        return srv.url
    assert srv.preset is not None  # 模型校验已保证 url/preset 至少其一
    preset = MCP_PRESETS[srv.preset]
    api_key = _mcp_effective_key(srv_name, srv)
    if preset["needs_key"] and not api_key:
        raise ConfigError(f"MCP 预设 '{srv.preset}' 需要 api_key")
    url = preset["url"].format(api_key=api_key or "")
    _validate_mcp_url(url, srv.allow_private)
    return url


class AgentConfig(BaseModel):
    """Agent 路由与运行参数。provider/model 为空时跟随全局默认。

    options 为模型私有参数（如 chat_template_kwargs），覆盖提供商级 options。
    数值参数仅设下限、不设上限（用户自定义）；temperature 上限 2 为
    OpenAI 兼容 API 的通行约定，超过会被提供商拒绝，故保留。
    """

    provider: str | None = None
    model: str | None = None
    num_candidates: int = Field(default=3, ge=1)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=16384, ge=256)
    timeout: int | None = Field(default=None, ge=1)
    enable_web_search: bool = False
    web_sources: list[str] = Field(default_factory=lambda: list(DEFAULT_WEB_SOURCES))
    mcp_servers: list[str] = Field(default_factory=list)
    log_intermediate: bool = True
    options: dict = Field(default_factory=dict)


class BTCMConfig(BaseModel):
    """全局配置（btcm.json 的完整结构）。"""

    max_iterations: int = Field(default=2, ge=1, le=50)
    timeout: int = Field(default=3600, ge=1)
    enable_creative: bool = True
    enable_validator: bool = True
    admin_token: str | None = None
    lock_invoke: bool = False
    default_provider: str | None = None
    default_model: str | None = None
    structured_output: Literal["text", "json_object"] = "text"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_admin_token(self) -> "BTCMConfig":
        # X-Admin-Token 经 HTTP 头传递（头值为 latin-1），非 ASCII 值
        # 客户端无法发送、服务端无法比对，直接在配置层拒绝
        if self.admin_token is not None:
            try:
                self.admin_token.encode("latin-1")
            except UnicodeEncodeError as e:
                raise ValueError(
                    "admin_token 仅允许 ASCII / latin-1 字符"
                    "（需经 X-Admin-Token HTTP 头传递）"
                ) from e
        return self


def build_default_config() -> BTCMConfig:
    """构建内置默认配置。模型路由示例为 DeepSeek + 本地 Ollama。"""

    def agent(name: str) -> AgentConfig:
        return AgentConfig(
            provider="deepseek",
            model="deepseek-chat" if name != "validator" else "deepseek-reasoner",
            temperature=AGENT_DEFAULT_TEMPERATURE[name],
            max_tokens=AGENT_DEFAULT_MAX_TOKENS[name],
            timeout=600 if name == "validator" else None,
            enable_web_search=False,
            web_sources=list(DEFAULT_WEB_SOURCES),
            log_intermediate=True,
        )

    return BTCMConfig(
        max_iterations=2,
        timeout=3600,
        enable_creative=True,
        enable_validator=True,
        default_provider="deepseek",
        default_model="deepseek-chat",
        structured_output="text",
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
        agents={name: agent(name) for name in ("creative", "validator", "controller", "meta")},
    )


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并：嵌套 dict 递归合并，list/标量整体替换。

    遵循 JSON Merge Patch（RFC 7386）语义：override 中值为 null 的键表示删除。
    缺此语义时注册表条目无法删除——providers / mcp_servers 是 dict，
    递归合并会让 payload 中已移除的条目从旧配置复活。
    """
    out = dict(base)
    for key, value in override.items():
        if value is None:
            out.pop(key, None)
        elif key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class ConfigManager:
    """配置的加载、校验、持久化与读取。

    update/reset 为读-改-写操作，以 threading.Lock 串行化，
    防止并发 PUT 互相覆盖。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else CONFIG_FILE
        self._config: BTCMConfig = self._load()
        self._lock = threading.Lock()
        self._change_listeners: list = []

    def add_change_listener(self, callback) -> None:
        """注册配置变更回调（update/reset 成功后同步调用，签名 () -> None）。"""
        self._change_listeners.append(callback)

    def _notify_change(self) -> None:
        logger.info("配置已更新并持久化：%s", self.path)
        for callback in self._change_listeners:
            try:
                callback()
            except Exception:  # 观察者异常不影响配置更新本身
                logger.exception("配置变更回调执行失败")

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
        """强校验三个内置 Agent 定义齐全，且 mcp_servers 引用有效。
        显式 provider 必须存在且启用；跟随全局默认时不校验。
        """
        missing = [name for name in REQUIRED_AGENTS if name not in cfg.agents]
        if missing:
            raise ConfigError(
                f"配置必须包含 Agent 定义，缺失：{', '.join(missing)}"
            )
        for agent_name, agent_cfg in cfg.agents.items():
            unknown = [
                s for s in agent_cfg.mcp_servers if s not in cfg.mcp_servers
            ]
            if unknown:
                raise ConfigError(
                    f"Agent '{agent_name}' 引用了未注册的 MCP 服务器："
                    f"{', '.join(unknown)}"
                )
            if agent_cfg.provider:
                if agent_cfg.provider not in cfg.providers:
                    raise ConfigError(
                        f"Agent '{agent_name}' 引用的提供商不存在：{agent_cfg.provider}"
                    )
                if not cfg.providers[agent_cfg.provider].enabled:
                    raise ConfigError(
                        f"Agent '{agent_name}' 引用的提供商已停用：{agent_cfg.provider}"
                    )

    def as_public_dict(self) -> dict:
        """对外可读配置：不输出任何密钥内容，仅回显是否已设置的布尔。"""
        data = self._config.model_dump()
        for name, provider in data.get("providers", {}).items():
            provider.pop("api_key", None)
            provider["api_key_set"] = provider_api_key(self._config, name) is not None
        for name, server in data.get("mcp_servers", {}).items():
            server.pop("api_key", None)
            server["api_key_set"] = (
                _mcp_effective_key(name, self._config.mcp_servers[name]) is not None
            )
        admin_set = bool(
            os.environ.get("BTCM_ADMIN_TOKEN") or self._config.admin_token
        )
        data.pop("admin_token", None)
        data["admin_token_set"] = admin_set
        return data

    # ---------- 更新 ----------

    def update(self, partial: dict[str, Any]) -> BTCMConfig:
        """部分更新：与当前配置深度合并后整体校验，通过则原子写入并立即生效。"""
        with self._lock:
            current = self._config.model_dump()
            merged = _deep_merge(current, partial)
            try:
                new_cfg = BTCMConfig.model_validate(merged)
            except ValidationError as e:
                raise ConfigError(f"配置更新校验失败：{e}") from e
            self._check_agents(new_cfg)
            self._write(new_cfg)
            self._config = new_cfg
        self._notify_change()
        return new_cfg

    def reset(self) -> BTCMConfig:
        """重置为内置默认配置。"""
        with self._lock:
            cfg = build_default_config()
            self._write(cfg)
            self._config = cfg
        self._notify_change()
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

    # options 合并：提供商 options 为底，Agent 级 options 覆盖
    provider_name = resolve_provider_name(cfg, agent_name)
    provider_cfg = cfg.providers.get(provider_name)
    effective["options"] = {
        **(provider_cfg.options if provider_cfg else {}),
        **(effective.get("options") or {}),
    }

    # timeout 兜底：Agent 级与请求级均未设置时，使用所属提供商的 timeout（默认 600）
    if effective.get("timeout") is None:
        effective["timeout"] = provider_cfg.timeout if provider_cfg else 600

    return effective


def _env_secret(prefix: str, name: str) -> str | None:
    """从环境变量读取密钥，BTCM_<prefix>_<NAME>，NAME 中非字母数字转 _。"""
    key = f"BTCM_{prefix}_{''.join(c if c.isalnum() else '_' for c in name.upper())}"
    return os.environ.get(key)


def resolve_agent_route(cfg: BTCMConfig, agent_name: str) -> tuple[str, str | None, str]:
    """返回某 Agent 路由的 (base_url, api_key, model)，供模型网关使用。

    模型解析链（优先级从高到低）：
    agent.model → 全局 default_model（须在 provider.models 内）→ provider.models[0] → 全局兜底。
    provider 解析链：agent.provider → default_provider → 首个 enabled provider → 报错。
    api_key 优先取环境变量 BTCM_PROVIDER_<NAME>_API_KEY，其次配置文件。
    """
    agent_cfg = cfg.agents.get(agent_name)
    if agent_cfg is None:
        raise ConfigError(f"配置缺少 Agent 定义：{agent_name}")

    provider_name = resolve_provider_name(cfg, agent_name)
    provider_cfg = cfg.providers[provider_name]

    model = _resolve_model(cfg, agent_cfg, provider_cfg)

    api_key = provider_api_key(cfg, provider_name)
    return provider_cfg.base_url, api_key, model


def resolve_provider_name(cfg: BTCMConfig, agent_name: str) -> str:
    """返回某 Agent 实际使用的 provider 名（经解析链）。"""
    agent_cfg = cfg.agents.get(agent_name)
    if agent_cfg is None:
        raise ConfigError(f"配置缺少 Agent 定义：{agent_name}")
    return _resolve_provider(cfg, agent_cfg, agent_name)


def _resolve_provider(cfg: BTCMConfig, agent_cfg: AgentConfig, agent_name: str) -> str:
    """解析 agent 实际使用的 provider 名。"""
    if agent_cfg.provider:
        if agent_cfg.provider not in cfg.providers:
            raise ConfigError(
                f"Agent '{agent_name}' 引用的提供商不存在：{agent_cfg.provider}"
            )
        if not cfg.providers[agent_cfg.provider].enabled:
            raise ConfigError(
                f"Agent '{agent_name}' 引用的提供商已停用：{agent_cfg.provider}"
            )
        return agent_cfg.provider
    if cfg.default_provider:
        if cfg.default_provider not in cfg.providers:
            raise ConfigError(
                f"全局默认提供商不存在：{cfg.default_provider}"
            )
        if not cfg.providers[cfg.default_provider].enabled:
            raise ConfigError(
                f"全局默认提供商已停用：{cfg.default_provider}"
            )
        return cfg.default_provider
    # 回退：首个 enabled provider
    for name, p in cfg.providers.items():
        if p.enabled:
            return name
    raise ConfigError(
        f"Agent '{agent_name}' 无法解析提供商：无可用（已启用）的提供商"
    )


def _resolve_model(cfg: BTCMConfig, agent_cfg: AgentConfig, provider_cfg: ProviderConfig) -> str:
    """解析 agent 实际使用的 model 名。"""
    if agent_cfg.model:
        return agent_cfg.model
    if cfg.default_model and cfg.default_model in provider_cfg.models:
        return cfg.default_model
    if provider_cfg.models:
        return provider_cfg.models[0]
    return DEFAULT_FALLBACK_MODEL
