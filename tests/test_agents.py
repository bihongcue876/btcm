"""四个 Agent 的单元测试：提示词构造、结构化解析、失败重试与降级。"""

from __future__ import annotations

import asyncio
import unittest

from btcmodule.agents.controller import ControllerAgent
from btcmodule.agents.creative import CreativeAgent
from btcmodule.agents.meta import MetaAgent
from btcmodule.agents.validator import ValidatorAgent
from btcmodule.core.llm import LLMError

from .common import TestHarness, make_task

BAD_JSON = "这不是 JSON"
VALIDATOR_BAD_VERDICT = '{"verdict": "maybe", "issues": []}'


def _run(coro):
    return asyncio.run(coro)


class CreativeAgentTest(unittest.TestCase):
    def test_generate_returns_candidates_and_conclusion(self):
        h = TestHarness()
        try:
            agent = CreativeAgent(h.cm, h.gateway)
            result = _run(agent.generate(make_task(), None, None, None))
            self.assertEqual(
                result["candidates"], ["候选方案A（理由）", "候选方案B（理由）"]
            )
            self.assertEqual(result["conclusion"], "综合推荐说明")
        finally:
            h.close()

    def test_generate_conclusion_fallback_joins_candidates(self):
        """conclusion 缺失时回退为候选串联，仍覆盖全部候选。"""
        h = TestHarness(
            sequences={
                "creative": ['{"candidates": ["甲方案", "乙方案"]}']
            }
        )
        try:
            agent = CreativeAgent(h.cm, h.gateway)
            result = _run(agent.generate(make_task(), None, None, None))
            self.assertEqual(result["conclusion"], "甲方案；乙方案")
        finally:
            h.close()

    def test_generate_retries_then_succeeds(self):
        h = TestHarness(sequences={"creative": [BAD_JSON]})
        try:
            agent = CreativeAgent(h.cm, h.gateway)
            result = _run(agent.generate(make_task(), None, None, None))
            self.assertEqual(len(result["candidates"]), 2)
            # 第一次解析失败重试，第二次成功 → 共调用两次
            self.assertEqual(len(h.fake.calls), 2)
        finally:
            h.close()

    def test_generate_fails_after_two_bad_outputs(self):
        h = TestHarness(sequences={"creative": [BAD_JSON, BAD_JSON]})
        try:
            agent = CreativeAgent(h.cm, h.gateway)
            from btcmodule.agents.base import AgentOutputError

            with self.assertRaises(AgentOutputError):
                _run(agent.generate(make_task(), None, None, None))
            self.assertEqual(len(h.fake.calls), 2)  # 调了两次
        finally:
            h.close()

    def test_generate_empty_candidates_raises(self):
        h = TestHarness(
            sequences={"creative": ['{"candidates": []}', '{"candidates": []}']}
        )
        try:
            agent = CreativeAgent(h.cm, h.gateway)
            from btcmodule.agents.base import AgentOutputError

            with self.assertRaises(AgentOutputError):
                _run(agent.generate(make_task(), None, None, None))
            self.assertEqual(len(h.fake.calls), 2)
        finally:
            h.close()


class ValidatorAgentTest(unittest.TestCase):
    def test_validate_returns_report(self):
        h = TestHarness()
        try:
            agent = ValidatorAgent(h.cm, h.gateway)
            report = _run(
                agent.validate(make_task(), ["候选方案A"], None)
            )
            self.assertEqual(report["verdict"], "conditional_pass")
            self.assertEqual(report["best_candidate"], "候选方案A")
            self.assertIn("问题1", report["issues"])
        finally:
            h.close()

    def test_validate_bad_verdict_degrades_to_fail(self):
        h = TestHarness(
            sequences={"validator": [VALIDATOR_BAD_VERDICT, VALIDATOR_BAD_VERDICT]}
        )
        try:
            agent = ValidatorAgent(h.cm, h.gateway)
            report = _run(agent.validate(make_task(), ["候选"], None))
            self.assertEqual(report["verdict"], "fail")
            self.assertIn("解析失败", report["issues"][0])
        finally:
            h.close()

    def test_validate_llm_error_degrades_to_fail(self):
        h = TestHarness(raise_llm_error={"validator"})
        try:
            agent = ValidatorAgent(h.cm, h.gateway)
            report = _run(agent.validate(make_task(), ["候选"], None))
            self.assertEqual(report["verdict"], "fail")
            self.assertIn("请求失败", report["issues"][0])
        finally:
            h.close()


class MetaAgentTest(unittest.TestCase):
    def test_reflect(self):
        h = TestHarness()
        try:
            agent = MetaAgent(h.cm, h.gateway)
            result = _run(
                agent.reflect(
                    make_task(),
                    ["候选A"],
                    {"verdict": "fail", "issues": ["问题"]},
                    1,
                    None,
                )
            )
            self.assertEqual(result["conclusion"], "meta 整合结论")
            self.assertEqual(result["decision"], "continue")
        finally:
            h.close()


class ControllerAgentTest(unittest.TestCase):
    def test_think(self):
        h = TestHarness()
        try:
            agent = ControllerAgent(h.cm, h.gateway)
            result = _run(agent.think(make_task(), [], 1, None))
            self.assertEqual(result["thought"], "本轮思考要点")
        finally:
            h.close()

    def test_finalize(self):
        h = TestHarness()
        try:
            agent = ControllerAgent(h.cm, h.gateway)
            result = _run(agent.finalize(make_task(), ["要点1", "要点2"], None))
            self.assertEqual(result, "最终结论")
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
