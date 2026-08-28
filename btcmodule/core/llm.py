"""模型网关：OpenAI 兼容提供商注册表 + 按 Agent 路由。

- 按 (base_url, api_key) 缓存 AsyncOpenAI 客户端
- 每次调用按四层优先级解析生效参数（temperature / max_tokens / 单请求超时）
- 单请求超时经 asyncio.wait_for 强制执行，超时抛 LLMError
"""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from .config import ConfigManager, resolve_agent_params, resolve_agent_route
from .task import RuntimeConfig


class LLMError(Exception):
    """LLM 调用失败（含超时），message 面向调用方可读。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelGateway:
    def __init__(self, cm: ConfigManager) -> None:
        self._cm = cm
        self._clients: dict[tuple[str, str], AsyncOpenAI] = {}

    def _client(self, base_url: str, api_key: str | None) -> AsyncOpenAI:
        key = (base_url, api_key or "")
        if key not in self._clients:
            self._clients[key] = AsyncOpenAI(
                api_key=api_key or "not-set",
                base_url=base_url,
                max_retries=0,
            )
        return self._clients[key]

    async def chat(
        self,
        agent_name: str,
        messages: list[dict],
        runtime: RuntimeConfig | None = None,
    ) -> str:
        """按 Agent 路由发起一次对话，返回模型文本输出。

        提示词、参数解析失败、单请求超时均不在本层做重试——由上层 Agent
        统一按"重试一次后降级 fail"处理。
        """
        cfg = self._cm.config
        base_url, api_key, model = resolve_agent_route(cfg, agent_name)
        params = resolve_agent_params(cfg, runtime, agent_name)

        client = self._client(base_url, api_key)
        request_kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
        }

        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(**request_kwargs),
                timeout=params["timeout"],
            )
        except asyncio.TimeoutError as e:
            raise LLMError(
                "llm_timeout",
                f"Agent '{agent_name}' 单请求超时（{params['timeout']}s）",
            ) from e
        except Exception as e:  # 网络错误、鉴权失败、模型不可用等
            raise LLMError("llm_error", f"Agent '{agent_name}' 请求失败：{e}") from e

        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise LLMError("llm_empty", f"Agent '{agent_name}' 返回空内容")
        return content
