"""MCP 配置与验证 Agent 工具接入测试；附长链历史窗口检查。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from btcmodule.agents.controller import ControllerAgent
from btcmodule.agents.validator import ValidatorAgent
from btcmodule.core.config import ConfigError, ConfigManager, resolve_mcp_url
from btcmodule.core.mcp import openai_tool_name
from btcmodule.core.task import RuntimeConfig

from .common import TestHarness, VALIDATOR_OUTPUT, make_task


def _run(coro):
    return asyncio.run(coro)


class McpConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cm = ConfigManager(path=Path(self._tmp.name) / "btcm.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_unknown_preset_raises(self):
        with self.assertRaises(ConfigError):
            self.cm.update({"mcp_servers": {"bad": {"preset": "no-such"}}})

    def test_missing_url_and_preset_raises(self):
        with self.assertRaises(ConfigError):
            self.cm.update({"mcp_servers": {"bad": {"enabled": True}}})

    def test_agent_reference_unknown_server_raises(self):
        with self.assertRaises(ConfigError):
            self.cm.update(
                {"agents": {"validator": {"mcp_servers": ["ghost"]}}}
            )

    def test_valid_update_and_reference(self):
        self.cm.update(
            {
                "mcp_servers": {
                    "tavily": {"preset": "tavily", "api_key": "tvly-x"}
                },
                "agents": {
                    "validator": {
                        "enable_web_search": True,
                        "mcp_servers": ["tavily"],
                    }
                },
            }
        )
        cfg = self.cm.config
        self.assertTrue(cfg.agents["validator"].enable_web_search)
        self.assertEqual(cfg.agents["validator"].mcp_servers, ["tavily"])

    def test_cache_invalidated_on_config_change(self):
        """配置 update/reset 后 MCP 连接与失败标记全部作废。"""
        from btcmodule.core.mcp import MCPManager

        mcp = MCPManager(self.cm)
        mcp._failed.add("tavily")
        mcp._tools["tavily"] = []
        self.cm.update({"max_iterations": 3})
        self.assertEqual(mcp._failed, set())
        self.assertEqual(mcp._tools, {})
        self.cm.reset()
        self.assertEqual(mcp._failed, set())

    def test_public_dict_hides_secrets(self):
        self.cm.update(
            {
                "admin_token": "tok-123",
                "mcp_servers": {
                    "tavily": {"preset": "tavily", "api_key": "tvly-secret"}
                },
            }
        )
        data = self.cm.as_public_dict()
        self.assertNotIn("admin_token", data)
        for server in data["mcp_servers"].values():
            self.assertNotIn("api_key", server)
        # 文件里仍保留
        raw = Path(self.cm.path).read_text(encoding="utf-8")
        self.assertIn("tvly-secret", raw)
        self.assertIn("tok-123", raw)


class ResolveUrlTest(unittest.TestCase):
    def _srv(self, **kwargs):
        from btcmodule.core.config import MCPServerConfig

        return MCPServerConfig(**kwargs)

    def test_preset_without_key(self):
        url = resolve_mcp_url("test-srv", self._srv(preset="deepwiki"))
        self.assertEqual(url, "https://mcp.deepwiki.com/mcp")

    def test_preset_with_key_substituted(self):
        url = resolve_mcp_url("test-srv", self._srv(preset="tavily", api_key="tvly-abc"))
        self.assertIn("tvly-abc", url)

    def test_preset_needing_key_without_key_raises(self):
        with self.assertRaises(ConfigError):
            resolve_mcp_url("test-srv", self._srv(preset="tavily"))

    def test_direct_url_wins(self):
        url = resolve_mcp_url(
            "test-srv",
            self._srv(url="http://localhost:9999/mcp", preset="tavily", allow_private=True),
        )
        self.assertEqual(url, "http://localhost:9999/mcp")

    def test_tool_name_sanitized(self):
        name = openai_tool_name("my server", "web.search!")
        self.assertEqual(name, "my_server_web_search_")
        self.assertLessEqual(len(openai_tool_name("x" * 80, "t")), 64)


class _FakeMCP:
    """MCPManager 桩：返回一个工具与执行器。"""

    def __init__(self) -> None:
        self.requested: list[list[str]] = []

    async def openai_tools(self, server_names):
        self.requested.append(list(server_names))

        async def executor(name, args):
            return "工具结果"

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "tavily_tavily_search",
                    "description": "搜索",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        return tools, executor


class _FakeToolsGateway:
    """记录 chat_with_tools 入参的桩网关。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat_with_tools(
        self, agent_name, messages, tools, tool_executor, runtime=None
    ):
        self.calls.append({"tools": tools, "messages": messages})
        return VALIDATOR_OUTPUT


class ValidatorToolPathTest(unittest.TestCase):
    def _cm(self, root: Path) -> ConfigManager:
        cm = ConfigManager(path=root / "btcm.json")
        cm.update(
            {
                "mcp_servers": {
                    "tavily": {"preset": "tavily", "api_key": "tvly-x"}
                },
                "agents": {
                    "validator": {
                        "enable_web_search": True,
                        "mcp_servers": ["tavily"],
                    }
                },
            }
        )
        return cm

    def test_tools_passed_to_chat_with_tools(self):
        with tempfile.TemporaryDirectory() as d:
            cm = self._cm(Path(d))
            gateway = _FakeToolsGateway()
            mcp = _FakeMCP()
            agent = ValidatorAgent(cm, gateway, mcp)
            report = _run(
                agent.validate(
                    make_task(), ["候选A"], RuntimeConfig()
                )
            )
            self.assertEqual(report["verdict"], "conditional_pass")
            self.assertEqual(mcp.requested, [["tavily"]])
            self.assertEqual(len(gateway.calls), 1)
            tools = gateway.calls[0]["tools"]
            self.assertEqual(tools[0]["function"]["name"], "tavily_tavily_search")

    def test_search_disabled_uses_plain_chat(self):
        with tempfile.TemporaryDirectory() as d:
            cm = self._cm(Path(d))
            cm.update({"agents": {"validator": {"enable_web_search": False}}})
            h = TestHarness()
            mcp = _FakeMCP()
            try:
                agent = ValidatorAgent(h.cm, h.gateway, mcp)
                report = _run(agent.validate(make_task(), ["候选A"], None))
                self.assertEqual(report["verdict"], "conditional_pass")
                # 未走工具路径：MCP 管理器未被询问
                self.assertEqual(mcp.requested, [])
            finally:
                h.close()


class HistoryWindowTest(unittest.TestCase):
    def test_think_history_truncated(self):
        h = TestHarness()
        try:
            agent = ControllerAgent(h.cm, h.gateway)
            thoughts = [f"要点{i}" for i in range(1, 9)]
            _run(agent.think(make_task(), thoughts, 9, None))
            user = h.fake.calls[-1][1][1]["content"]
            self.assertIn("要点1", user)  # 首条保留
            self.assertIn("要点4", user)  # 最近 5 条：要点4~8
            self.assertIn("要点8", user)  # 最近一条保留
            self.assertNotIn("要点2", user)  # 中间要点被省略
            self.assertNotIn("要点3", user)
            self.assertIn("已省略", user)
        finally:
            h.close()

    def test_think_short_history_kept_all(self):
        h = TestHarness()
        try:
            agent = ControllerAgent(h.cm, h.gateway)
            _run(agent.think(make_task(), ["要点1", "要点2"], 3, None))
            user = h.fake.calls[-1][1][1]["content"]
            self.assertIn("要点1", user)
            self.assertIn("要点2", user)
            self.assertNotIn("已省略", user)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
