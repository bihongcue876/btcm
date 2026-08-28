"""API 层集成测试：统一外层结构、配置读写、四种形态、日志接口。"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from starlette.testclient import TestClient

from btcmodule.core.llm import ModelGateway
from btcmodule.main import create_app

from .common import FakeChat, DEFAULT_OUTPUTS


def make_client(sequences=None, raise_llm_error=None):
    """临时目录 + 完整 app + mock 模型网关，返回 (client, fake, patcher, tmp)。"""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    app = create_app(
        config_path=root / "btcm.json",
        log_path=root / "calls.jsonl",
    )
    fake = FakeChat(
        default_outputs=DEFAULT_OUTPUTS,
        sequences=sequences,
        raise_llm_error=raise_llm_error,
    )
    patcher = unittest.mock.patch.object(ModelGateway, "chat", fake)
    patcher.start()
    return TestClient(app), fake, patcher, tmp


class ConfigApiTest(unittest.TestCase):
    def test_get_config_hides_api_key(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.get("/api/config")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["max_iterations"], 2)
            self.assertTrue(data["data"]["enable_creative"])
            self.assertTrue(data["data"]["enable_validator"])
            for provider in data["data"]["providers"].values():
                self.assertNotIn("api_key", provider)
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_put_config_partial_and_persist(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.put("/api/config", json={"max_iterations": 5})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["data"]["max_iterations"], 5)
            self.assertEqual(r.json()["data"]["timeout"], 300)
            # 再 GET 一次验证持久化后的全局状态
            self.assertEqual(
                client.get("/api/config").json()["data"]["max_iterations"], 5
            )
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_put_config_invalid_value(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.put("/api/config", json={"max_iterations": 99})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"]["code"], "CONFIG_VALIDATION_ERROR")
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_put_config_non_dict_body(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.put("/api/config", json=[1, 2, 3])
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"]["code"], "CONFIG_VALIDATION_ERROR")
        finally:
            patcher.stop()
            tmp.cleanup()


class InvokeApiTest(unittest.TestCase):
    def test_pure_creative(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post(
                "/api/invoke",
                json={
                    "user_query": "设计一个周末活动方案",
                    "enable_creative": True,
                    "enable_validator": False,
                },
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertEqual(len(data["candidates"]), 2)
            self.assertEqual(data["termination_reason"], "single_pass")
            self.assertNotIn("verdict", data)
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_pure_validation(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post(
                "/api/invoke",
                json={
                    "user_query": "验证这个方案",
                    "candidate": "去公园野餐",
                    "enable_creative": False,
                    "enable_validator": True,
                },
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertEqual(data["verdict"], "conditional_pass")
            self.assertEqual(data["termination_reason"], "single_pass")
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_pure_validation_missing_candidate(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post(
                "/api/invoke",
                json={
                    "user_query": "验证这个方案",
                    "enable_creative": False,
                    "enable_validator": True,
                },
            )
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"]["code"], "INVALID_REQUEST")
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_hybrid(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post(
                "/api/invoke",
                json={"user_query": "给出一个旅行计划"},
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertEqual(data["verdict"], "conditional_pass")
            self.assertEqual(data["iterations_used"], 2)
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(len(data["intermediate_log"]), 2)
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_long_chain(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post(
                "/api/invoke",
                json={
                    "user_query": "深入思考一个难题",
                    "enable_creative": False,
                    "enable_validator": False,
                },
            )
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertEqual(data["conclusion"], "最终结论")
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(len(data["intermediate_log"]), 2)
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_global_switch_fallback(self):
        """请求体未提供开关时，使用全局配置默认值（协议 v0.9）。"""
        client, fake, patcher, tmp = make_client()
        try:
            client.put("/api/config", json={"enable_validator": False})
            r = client.post("/api/invoke", json={"user_query": "任务"})
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            # 全局 validator 关闭 → 请求缺省时走纯创意
            self.assertIn("candidates", data)
            self.assertNotIn("verdict", data)

            # 请求显式覆盖仍可开回来
            r = client.post(
                "/api/invoke",
                json={
                    "user_query": "任务",
                    "enable_creative": True,
                    "enable_validator": True,
                },
            )
            self.assertEqual(r.status_code, 200)
            self.assertIn("verdict", r.json()["data"])
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_missing_user_query(self):
        client, fake, patcher, tmp = make_client()
        try:
            r = client.post("/api/invoke", json={})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"]["code"], "INVALID_REQUEST")
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_llm_failure_returns_internal_error(self):
        client, fake, patcher, tmp = make_client(raise_llm_error={"creative"})
        try:
            r = client.post(
                "/api/invoke",
                json={"user_query": "会失败的任务"},
            )
            self.assertEqual(r.status_code, 500)
            self.assertEqual(r.json()["error"]["code"], "INTERNAL_ERROR")
        finally:
            patcher.stop()
            tmp.cleanup()


class LogsApiTest(unittest.TestCase):
    def test_logs_after_calls(self):
        client, fake, patcher, tmp = make_client()
        try:
            client.post(
                "/api/invoke",
                json={
                    "user_query": "hello",
                    "enable_creative": False,
                    "enable_validator": False,
                },
            )
            r = client.get("/api/logs?limit=10")
            self.assertEqual(r.status_code, 200)
            data = r.json()["data"]
            self.assertEqual(data["total"], 1)
            item = data["items"][0]
            self.assertEqual(item["user_query"], "hello")
            self.assertIsNone(item["verdict"])

            # 失败调用也落日志
            client.post(
                "/api/invoke",
                json={
                    "user_query": "坏请求",
                    "enable_creative": False,
                    "enable_validator": True,
                },
            )
            r = client.get("/api/logs?limit=10")
            self.assertEqual(r.json()["data"]["total"], 2)
        finally:
            patcher.stop()
            tmp.cleanup()

    def test_logs_pagination(self):
        client, fake, patcher, tmp = make_client()
        try:
            for i in range(3):
                client.post(
                    "/api/invoke",
                    json={
                        "user_query": f"q{i}",
                        "enable_creative": False,
                        "enable_validator": False,
                    },
                )
            r = client.get("/api/logs?limit=2&offset=0")
            data = r.json()["data"]
            self.assertEqual(data["total"], 3)
            self.assertEqual(len(data["items"]), 2)
            self.assertEqual(data["items"][0]["user_query"], "q2")  # 最新在前
            r = client.get("/api/logs?limit=2&offset=2")
            self.assertEqual(len(r.json()["data"]["items"]), 1)
        finally:
            patcher.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
