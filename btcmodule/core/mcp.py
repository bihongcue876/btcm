"""MCP（Model Context Protocol）最小客户端：Streamable HTTP 传输。

仅实现验证 Agent 所需的子集：
- initialize 握手（JSON-RPC 2.0 over HTTP POST，支持 JSON 与 SSE 两种响应）
- tools/list 枚举工具
- tools/call 执行工具

工具不可用（连接失败、握手失败、超时）时按"可用才调用"原则静默降级：
当次调用退回纯逻辑验证，不抛出。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

import httpx

from .config import MCPServerConfig, resolve_mcp_url

logger = logging.getLogger("btcmodule.mcp")

# 工具输出截断上限：工具结果是验证 Agent 的思考材料，从宽保留，
# 仅防御性截断异常超长的返回（如整页 HTML）
TOOL_OUTPUT_LIMIT = 12000


class MCPError(Exception):
    """MCP 服务器通信失败。"""


# 异常消息中密钥值消毒模式：apikey=<secret>/apiKey=<secret> 等 query 参数
_SECRET_QUERY_RE = re.compile(
    r"((?:api[_-]?key|token|key|password)=)[^&\s'\"]+", re.IGNORECASE
)


def _sanitize(text: str) -> str:
    """消毒异常文本：预设 URL 以 query 参数携带密钥（如 tavilyApiKey=...），
    httpx 部分异常的 str 含完整 URL，进日志前先抹掉密钥值。"""
    return _SECRET_QUERY_RE.sub(r"\1***", text)


def openai_tool_name(server: str, tool: str) -> str:
    """生成 OpenAI function 名：{server}_{tool}，清理非法字符并限长。"""
    raw = f"{server}_{tool}"
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:64]


class MCPServerConnection:
    """单个 MCP 服务器的 Streamable HTTP 连接（惰性握手）。"""

    def __init__(self, name: str, url: str, timeout: int) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    async def _rpc(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict | None = None,
        notify: bool = False,
    ) -> tuple[dict, httpx.Headers]:
        """发送一次 JSON-RPC 请求，返回 (响应体, 响应头)。"""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            payload["id"] = uuid.uuid4().hex

        resp = await client.post(
            self.url,
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code == 202 and notify:
            return {}, resp.headers
        if resp.status_code != 200:
            raise MCPError(
                f"MCP '{self.name}' {method} 失败：HTTP {resp.status_code}"
            )

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse(resp.text), resp.headers
        try:
            return resp.json(), resp.headers
        except json.JSONDecodeError as e:
            raise MCPError(f"MCP '{self.name}' 响应非 JSON：{e}") from e

    @staticmethod
    def _parse_sse(text: str) -> dict:
        """解析 SSE 流中的 JSON-RPC 响应，取最后一个带 result/error 的事件。"""
        message: dict | None = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                message = parsed
        if message is None:
            raise MCPError("SSE 流中未找到 JSON-RPC 响应")
        return message

    async def initialize(self, client: httpx.AsyncClient) -> None:
        """握手并捕获 session id，随后发送 initialized 通知。"""
        resp, headers = await self._rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "btcmodule", "version": "0.0.0"},
            },
        )
        if "error" in resp:
            raise MCPError(f"MCP '{self.name}' 握手失败：{resp['error']}")
        self._session_id = headers.get("MCP-Session-Id")
        await self._rpc(client, "notifications/initialized", notify=True)

    async def list_tools(self, client: httpx.AsyncClient) -> list[dict]:
        resp, _ = await self._rpc(client, "tools/list", {})
        if "error" in resp:
            raise MCPError(f"MCP '{self.name}' tools/list 失败：{resp['error']}")
        tools = resp.get("result", {}).get("tools", [])
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    async def call_tool(
        self, client: httpx.AsyncClient, name: str, arguments: dict
    ) -> str:
        resp, _ = await self._rpc(
            client, "tools/call", {"name": name, "arguments": arguments}
        )
        if "error" in resp:
            raise MCPError(f"MCP '{self.name}' tools/call 失败：{resp['error']}")
        result = resp.get("result", {})
        parts = result.get("content") or []
        texts = [
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        output = "\n".join(t for t in texts if t).strip()
        if result.get("isError"):
            raise MCPError(f"MCP '{self.name}' 工具执行报错：{output[:200]}")
        return output


class MCPManager:
    """MCP 服务器注册表连接管理与工具暴露。

    - 按服务器名缓存连接与工具列表（进程内）
    - 不可用的服务器记入失败集合，当次及后续调用跳过（不反复敲死掉的端点）
    - openai_tools 返回 OpenAI function-calling 格式的工具定义与执行器
    """

    def __init__(self, cm) -> None:
        self._cm = cm
        self._conns: dict[str, MCPServerConnection] = {}
        self._tools: dict[str, list[dict]] = {}
        self._failed: set[str] = set()
        # 配置变更后旧连接与失败标记全部作废
        cm.add_change_listener(self.invalidate)

    def invalidate(self) -> None:
        """清空连接/工具/失败标记（配置 update/reset 时触发）。"""
        self._conns.clear()
        self._tools.clear()
        self._failed.clear()

    def _server_cfg(self, name: str) -> MCPServerConfig | None:
        srv = self._cm.config.mcp_servers.get(name)
        if srv is None or not srv.enabled:
            return None
        return srv

    async def _ensure(self, name: str, srv: MCPServerConfig) -> list[dict]:
        """连接（或复用连接）并枚举工具；失败记入 failed 并返回空。"""
        if name in self._tools:
            return self._tools[name]
        try:
            url = resolve_mcp_url(name, srv)
            conn = MCPServerConnection(name, url, srv.timeout)
            async with httpx.AsyncClient() as client:
                await conn.initialize(client)
                tools = await conn.list_tools(client)
            self._conns[name] = conn
            self._tools[name] = tools
            return tools
        except (MCPError, httpx.HTTPError, OSError) as e:
            self._failed.add(name)
            logger.warning(
                "MCP 服务器 '%s' 不可用，本次退回纯逻辑验证：%s",
                name,
                _sanitize(str(e)),
            )
            return []

    async def openai_tools(
        self, server_names: list[str]
    ) -> tuple[list[dict], Callable[[str, dict], Awaitable[str]] | None]:
        """聚合多个服务器的工具为 OpenAI 格式；全部不可用时返回 ([], None)。"""
        tools_out: list[dict] = []
        name_map: dict[str, tuple[str, str]] = {}

        for name in server_names:
            srv = self._server_cfg(name)
            if srv is None or name in self._failed:
                continue
            raw_tools = await self._ensure(name, srv)
            allowed = srv.allowed_tools
            for t in raw_tools:
                tool_name = t["name"]
                if allowed and tool_name not in allowed:
                    continue
                exposed = openai_tool_name(name, tool_name)
                if exposed in name_map:
                    continue
                name_map[exposed] = (name, tool_name)
                tools_out.append(
                    {
                        "type": "function",
                        "function": {
                            "name": exposed,
                            "description": t.get("description") or tool_name,
                            "parameters": t.get("inputSchema")
                            or {"type": "object", "properties": {}},
                        },
                    }
                )

        if not tools_out:
            return [], None

        async def execute(exposed_name: str, arguments: dict) -> str:
            mapping = name_map.get(exposed_name)
            if mapping is None:
                raise MCPError(f"未知工具：{exposed_name}")
            server_name, tool_name = mapping
            return await self.call(server_name, tool_name, arguments)

        return tools_out, execute

    async def call(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """执行工具调用；连接失效时重连一次再试。"""
        srv = self._server_cfg(server_name)
        if srv is None:
            raise MCPError(f"MCP 服务器未注册或已停用：{server_name}")
        conn = self._conns.get(server_name)
        if conn is None:
            raise MCPError(f"MCP 服务器未连接：{server_name}")
        try:
            async with httpx.AsyncClient() as client:
                return await conn.call_tool(client, tool_name, arguments)
        except (MCPError, httpx.HTTPError, OSError):
            self._tools.pop(server_name, None)
            self._conns.pop(server_name, None)
            await self._ensure(server_name, srv)
            conn = self._conns.get(server_name)
            if conn is None:
                raise MCPError(f"MCP 服务器不可用：{server_name}") from None
            async with httpx.AsyncClient() as client:
                return await conn.call_tool(client, tool_name, arguments)
