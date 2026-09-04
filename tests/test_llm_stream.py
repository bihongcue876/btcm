"""llm 层流式补全与略想开关测试：chunk 聚合、增量前传、usage 记账、options 注入。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from btcmodule.core.config import ConfigManager
from btcmodule.core.llm import LLMError, ModelGateway, effort_var, stream_sink, usage_var


def make_chunk(content=None, reasoning=None, usage=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


class FakeCompletions:
    """可编程 chat.completions：流式返回 chunk 序列，非流式返回固定响应。"""

    def __init__(self, chunks=None, result=None, create_delay: float = 0.0):
        self.chunks = chunks
        self.result = result
        self.create_delay = create_delay
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.create_delay:
            await asyncio.sleep(self.create_delay)
        if self.chunks is not None:

            async def _gen():
                for c in self.chunks:
                    yield c

            return _gen()
        return self.result


class StreamingGatewayTest(unittest.TestCase):
    def _gateway(self, completions: FakeCompletions) -> ModelGateway:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(path=Path(tmp.name) / "btcm.json")
        cm.update(
            {
                "providers": {
                    "local": {
                        "base_url": "http://localhost:9999/v1",
                        "models": ["m"],
                    }
                },
                "default_provider": "local",
                "default_model": "m",
                # 默认配置中各 Agent 显式指向 deepseek，需一并改路由
                "agents": {
                    name: {"provider": "local", "model": "m"}
                    for name in ("creative", "validator", "controller", "meta")
                },
            }
        )
        gw = ModelGateway(cm)

        def fake_client(self, base_url, api_key):
            return SimpleNamespace(chat=SimpleNamespace(completions=completions))

        patcher = patch.object(ModelGateway, "_client", fake_client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return gw

    def test_chat_streams_and_aggregates(self):
        """流式：content 聚合返回，reasoning/content 增量均经 sink 前传。"""
        events = []
        token = stream_sink.set(events.append)
        try:
            comp = FakeCompletions(
                chunks=[
                    make_chunk(reasoning="思考A"),
                    make_chunk(reasoning="思考B"),
                    make_chunk(content="答"),
                    make_chunk(content="案"),
                    make_chunk(
                        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=7)
                    ),
                ]
            )
            gw = self._gateway(comp)
            content = asyncio.run(
                gw.chat("creative", [{"role": "user", "content": "hi"}])
            )
        finally:
            stream_sink.reset(token)
        self.assertEqual(content, "答案")
        self.assertIs(comp.kwargs["stream"], True)
        self.assertEqual(
            [(e["agent"], e["kind"], e["text"]) for e in events],
            [
                ("creative", "reasoning", "思考A"),
                ("creative", "reasoning", "思考B"),
                ("creative", "content", "答"),
                ("creative", "content", "案"),
            ],
        )

    def test_no_sink_uses_non_streaming_path(self):
        """无 sink（常规 /invoke）不走流式：请求不带 stream 参数。"""
        comp = FakeCompletions(
            result=SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content="ok"))
                ],
                usage=None,
            )
        )
        gw = self._gateway(comp)
        content = asyncio.run(
            gw.chat("creative", [{"role": "user", "content": "hi"}])
        )
        self.assertEqual(content, "ok")
        self.assertNotIn("stream", comp.kwargs)

    def test_streaming_usage_recorded(self):
        events = []
        token = stream_sink.set(events.append)
        usage_token = usage_var.set(
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "llm_calls": 0,
                "tool_calls": 0,
            }
        )
        try:
            comp = FakeCompletions(
                chunks=[
                    make_chunk(content="答"),
                    make_chunk(
                        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=7)
                    ),
                ]
            )
            gw = self._gateway(comp)
            asyncio.run(gw.chat("creative", [{"role": "user", "content": "hi"}]))
        finally:
            stream_sink.reset(token)
            data = usage_var.get()
            usage_var.reset(usage_token)
        self.assertEqual(data["llm_calls"], 1)
        self.assertEqual(data["prompt_tokens"], 3)
        self.assertEqual(data["completion_tokens"], 7)

    def test_empty_stream_content_raises_llm_empty(self):
        """思考烧尽 max_tokens（仅 reasoning 无 content）仍判 llm_empty。"""
        events = []
        token = stream_sink.set(events.append)
        try:
            comp = FakeCompletions(chunks=[make_chunk(reasoning="只有思考")])
            gw = self._gateway(comp)
            with self.assertRaises(LLMError) as ctx:
                asyncio.run(
                    gw.chat("creative", [{"role": "user", "content": "hi"}])
                )
        finally:
            stream_sink.reset(token)
        self.assertEqual(ctx.exception.code, "llm_empty")


class EffortOptionsTest(unittest.TestCase):
    def _gateway(self, completions: FakeCompletions) -> ModelGateway:
        return StreamingGatewayTest._gateway(self, completions)

    def test_light_injects_enable_thinking_false_locally(self):
        """略想档对本地提供商注入 chat_template_kwargs.enable_thinking=false。"""
        comp = FakeCompletions(
            result=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            )
        )
        gw = self._gateway(comp)
        token = effort_var.set("light")
        try:
            asyncio.run(
                gw.chat("creative", [{"role": "user", "content": "hi"}])
            )
        finally:
            effort_var.reset(token)
        self.assertEqual(
            comp.kwargs["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}}
        )

    def test_standard_does_not_inject(self):
        comp = FakeCompletions(
            result=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            )
        )
        gw = self._gateway(comp)
        asyncio.run(gw.chat("creative", [{"role": "user", "content": "hi"}]))
        self.assertNotIn("extra_body", comp.kwargs)

    def test_light_keeps_existing_template_kwargs(self):
        """提供商 options 已有 chat_template_kwargs 时合并而非覆盖。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(path=Path(tmp.name) / "btcm.json")
        cm.update(
            {
                "providers": {
                    "local": {
                        "base_url": "http://localhost:9999/v1",
                        "models": ["m"],
                        "options": {
                            "chat_template_kwargs": {"top_k": 40}
                        },
                    }
                },
                "default_provider": "local",
                "default_model": "m",
                "agents": {
                    name: {"provider": "local", "model": "m"}
                    for name in ("creative", "validator", "controller", "meta")
                },
            }
        )
        comp = FakeCompletions(
            result=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            )
        )
        gw = ModelGateway(cm)
        with patch.object(
            ModelGateway,
            "_client",
            lambda self, base_url, api_key: SimpleNamespace(
                chat=SimpleNamespace(completions=comp)
            ),
        ):
            token = effort_var.set("light")
            try:
                asyncio.run(
                    gw.chat("creative", [{"role": "user", "content": "hi"}])
                )
            finally:
                effort_var.reset(token)
        self.assertEqual(
            comp.kwargs["extra_body"],
            {"chat_template_kwargs": {"top_k": 40, "enable_thinking": False}},
        )

    def test_light_injects_enable_thinking_false_in_streaming(self):
        """流式路径同样注入：SSE 下略想档本地关思考（回归：曾只在非流式生效）。"""
        events = []
        token = stream_sink.set(events.append)
        effort_token = effort_var.set("light")
        try:
            comp = FakeCompletions(chunks=[make_chunk(content="ok")])
            gw = self._gateway(comp)
            content = asyncio.run(
                gw.chat("creative", [{"role": "user", "content": "hi"}])
            )
        finally:
            stream_sink.reset(token)
            effort_var.reset(effort_token)
        self.assertEqual(content, "ok")
        self.assertIs(comp.kwargs["stream"], True)
        self.assertEqual(
            comp.kwargs["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}}
        )

    def test_streaming_missing_api_key_rejected_locally(self):
        """流式路径同样预检：非本地提供商缺 api_key 直接报可操作错误。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(path=Path(tmp.name) / "btcm.json")
        cm.update(
            {
                "providers": {
                    "remote": {
                        "base_url": "https://api.example.com/v1",
                        "models": ["m"],
                    }
                },
                "default_provider": "remote",
                "default_model": "m",
                "agents": {
                    name: {"provider": "remote", "model": "m"}
                    for name in ("creative", "validator", "controller", "meta")
                },
            }
        )
        gw = ModelGateway(cm)
        events = []
        token = stream_sink.set(events.append)
        try:
            with self.assertRaises(LLMError) as ctx:
                asyncio.run(
                    gw.chat("creative", [{"role": "user", "content": "hi"}])
                )
        finally:
            stream_sink.reset(token)
        self.assertEqual(ctx.exception.code, "llm_error")
        self.assertIn("api_key", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
