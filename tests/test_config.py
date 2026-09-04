"""配置模块测试：默认值、文件读写、部分更新、生效参数解析。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from btcmodule.core.config import (
    ConfigError,
    ConfigManager,
    build_default_config,
    resolve_agent_params,
    resolve_agent_route,
    resolve_global_params,
)
from btcmodule.core.task import RuntimeConfig


def _cfg_bytes(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class ConfigDefaultTest(unittest.TestCase):
    def test_default_values(self):
        cfg = build_default_config()
        self.assertEqual(cfg.max_iterations, 2)
        self.assertEqual(cfg.timeout, 300)
        self.assertTrue(cfg.enable_creative)
        self.assertTrue(cfg.enable_validator)
        self.assertIn("deepseek", cfg.providers)
        self.assertIn("ollama-local", cfg.providers)
        self.assertEqual(
            set(cfg.agents.keys()), {"creative", "validator", "controller", "meta"}
        )
        self.assertEqual(cfg.agents["creative"].temperature, 0.8)
        self.assertEqual(cfg.agents["validator"].temperature, 0.3)
        self.assertEqual(cfg.agents["controller"].max_tokens, 16384)
        self.assertEqual(cfg.agents["validator"].timeout, 300)
        self.assertEqual(cfg.agents["meta"].temperature, 0.3)
        self.assertEqual(cfg.agents["meta"].max_tokens, 16384)
        self.assertEqual(cfg.agents["meta"].provider, "deepseek")


class ConfigManagerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "btcm.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_run_generates_file(self):
        cm = ConfigManager(path=self.path)
        self.assertTrue(self.path.exists())
        data = _cfg_bytes(self.path)
        self.assertEqual(data["max_iterations"], 2)
        self.assertTrue(data["enable_creative"])

    def test_load_existing_file(self):
        cfg = build_default_config().model_dump()
        cfg["max_iterations"] = 7
        self.path.write_text(json.dumps(cfg), encoding="utf-8")
        cm = ConfigManager(path=self.path)
        self.assertEqual(cm.config.max_iterations, 7)
        self.assertEqual(cm.config.timeout, 300)
        self.assertEqual(
            set(cm.config.agents.keys()),
            {"creative", "validator", "controller", "meta"},
        )

    def test_load_invalid_json_raises(self):
        self.path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            ConfigManager(path=self.path)

    def test_load_missing_agent_raises(self):
        cfg = build_default_config().model_dump()
        del cfg["agents"]["controller"]
        self.path.write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ConfigError):
            ConfigManager(path=self.path)

    def test_update_partial_deep_merge(self):
        cm = ConfigManager(path=self.path)
        cm.update(
            {
                "max_iterations": 5,
                "providers": {"deepseek": {"api_key": "sk-test"}},
                "agents": {"validator": {"temperature": 0.5}},
            }
        )
        cfg = cm.config
        self.assertEqual(cfg.max_iterations, 5)
        self.assertEqual(cfg.timeout, 300)  # 未覆盖
        self.assertEqual(cfg.providers["deepseek"].api_key, "sk-test")
        self.assertEqual(cfg.providers["deepseek"].base_url, "https://api.deepseek.com/v1")
        self.assertEqual(cfg.agents["validator"].temperature, 0.5)
        self.assertEqual(cfg.agents["creative"].temperature, 0.8)
        # 持久化到文件
        self.assertEqual(_cfg_bytes(self.path)["max_iterations"], 5)

    def test_update_list_replaced_not_merged(self):
        cm = ConfigManager(path=self.path)
        cm.update({"agents": {"validator": {"web_sources": ["example.com"]}}})
        self.assertEqual(
            cm.config.agents["validator"].web_sources, ["example.com"]
        )

    def test_update_invalid_value_raises(self):
        cm = ConfigManager(path=self.path)
        with self.assertRaises(ConfigError):
            cm.update({"max_iterations": 99})

    def test_update_invalid_agent_raises(self):
        cm = ConfigManager(path=self.path)
        with self.assertRaises(ConfigError):
            cm.update({"agents": {"creative": None, "validator": None}})

    def test_update_null_removes_provider(self):
        """null 表示删除（RFC 7386）：否则深合并会让已删条目从旧配置复活。"""
        cm = ConfigManager(path=self.path)
        cm.update({
            "providers": {
                "temp": {
                    "base_url": "https://api.example.com/v1",
                    "models": [],
                    "enabled": True,
                }
            }
        })
        self.assertIn("temp", cm.config.providers)
        cm.update({"providers": {"temp": None}})
        self.assertNotIn("temp", cm.config.providers)
        self.assertNotIn("temp", _cfg_bytes(self.path)["providers"])

    def test_update_null_removes_mcp_server(self):
        cm = ConfigManager(path=self.path)
        cm.update({
            "mcp_servers": {
                "temp": {"url": "https://example.com/mcp", "enabled": True}
            }
        })
        self.assertIn("temp", cm.config.mcp_servers)
        cm.update({"mcp_servers": {"temp": None}})
        self.assertNotIn("temp", cm.config.mcp_servers)

    def test_provider_base_url_rejects_bad_scheme(self):
        cm = ConfigManager(path=self.path)
        for bad in ("ftp://api.example.com/v1", "api.example.com/v1", ""):
            with self.assertRaises(ConfigError):
                cm.update({"providers": {"bad": {"base_url": bad}}})
        # 本地推理服务经 http 接入是合法用法，不受私网限制
        cm.update({
            "providers": {"local": {"base_url": "http://localhost:11434/v1"}}
        })
        self.assertIn("local", cm.config.providers)

    def test_as_public_dict_hides_api_key(self):
        cm = ConfigManager(path=self.path)
        cm.update({"providers": {"deepseek": {"api_key": "sk-secret"}}})
        data = cm.as_public_dict()
        for provider in data["providers"].values():
            self.assertNotIn("api_key", provider)
        # 文件里保留
        self.assertEqual(_cfg_bytes(self.path)["providers"]["deepseek"]["api_key"], "sk-secret")

    def test_reset_restores_default(self):
        cm = ConfigManager(path=self.path)
        cm.update({"max_iterations": 9})
        cm.reset()
        self.assertEqual(cm.config.max_iterations, 2)


class ResolveParamsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cm = ConfigManager(path=Path(self._tmp.name) / "btcm.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_global_priority(self):
        cfg = self.cm.config
        self.assertEqual(resolve_global_params(cfg, None), (2, 300))
        runtime = RuntimeConfig(max_iterations=5, timeout=100)
        self.assertEqual(resolve_global_params(cfg, runtime), (5, 100))
        partial = RuntimeConfig(max_iterations=5)
        self.assertEqual(resolve_global_params(cfg, partial), (5, 300))

    def test_agent_defaults(self):
        params = resolve_agent_params(self.cm.config, None, "creative")
        self.assertEqual(params["num_candidates"], 3)
        self.assertEqual(params["temperature"], 0.8)
        self.assertEqual(params["max_tokens"], 16384)
        # creative 未设 agent timeout -> 用 provider timeout（deepseek 默认 300）
        self.assertEqual(params["timeout"], 300)

    def test_agent_timeout_falls_back_to_provider(self):
        params = resolve_agent_params(self.cm.config, None, "validator")
        # validator 自身 timeout=300
        self.assertEqual(params["timeout"], 300)

    def test_request_overrides_agent_and_provider(self):
        runtime = RuntimeConfig(
            agents={"validator": {"temperature": 0.9, "timeout": 60}}
        )
        params = resolve_agent_params(self.cm.config, runtime, "validator")
        self.assertEqual(params["temperature"], 0.9)
        self.assertEqual(params["timeout"], 60)

    def test_request_enable_web_search(self):
        runtime = RuntimeConfig(
            agents={"validator": {"enable_web_search": True}}
        )
        params = resolve_agent_params(self.cm.config, runtime, "validator")
        self.assertTrue(params["enable_web_search"])

    def test_route_missing_provider_raises(self):
        # Provider existence now checked at config update time;
        # test runtime resolution path directly with a constructed config.
        cfg = self.cm.config.model_copy(deep=True)
        cfg.agents["creative"].provider = "nope"
        with self.assertRaises(ConfigError):
            resolve_agent_route(cfg, "creative")

    def test_gateway_chat_propagates_route_error(self):
        """update 时校验 provider 存在且启用，无效路由在持久化阶段即被拒绝。"""
        with self.assertRaises(ConfigError):
            self.cm.update({"agents": {"validator": {"provider": "nope"}}})


class GatewayFriendlyErrorTest(unittest.TestCase):
    def test_missing_api_key_friendly_error(self):
        """非本地提供商缺 api_key：直接给出可操作的错误，不发网络请求。"""
        import asyncio

        from btcmodule.core.llm import LLMError, ModelGateway

        with tempfile.TemporaryDirectory() as d:
            cm = ConfigManager(path=Path(d) / "btcm.json")
            gw = ModelGateway(cm)
            with self.assertRaises(LLMError) as ctx:
                asyncio.run(
                    gw.chat(
                        "creative",
                        [{"role": "user", "content": "hi"}],
                        None,
                    )
                )
            self.assertIn("未配置 api_key", ctx.exception.message)


class UsageRecordTest(unittest.TestCase):
    def test_record_usage_accumulates(self):
        """usage 上下文累计：token 用量与调用次数。"""
        from btcmodule.core import llm as llm_mod

        init = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "llm_calls": 0,
            "tool_calls": 0,
        }
        token = llm_mod.usage_var.set(init)
        try:

            class U:
                prompt_tokens = 10
                completion_tokens = 5

            llm_mod._record_usage(U(), llm_calls=1)
            llm_mod._record_usage(None, tool_calls=2)
            self.assertEqual(
                init,
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "llm_calls": 1,
                    "tool_calls": 2,
                },
            )
        finally:
            llm_mod.usage_var.reset(token)

    def test_record_usage_noop_without_context(self):
        """未进入 invoke 上下文（如单测直连网关）时记账为空操作。"""
        from btcmodule.core import llm as llm_mod

        llm_mod._record_usage(None, llm_calls=1, tool_calls=1)  # 不应抛出


if __name__ == "__main__":
    unittest.main()
