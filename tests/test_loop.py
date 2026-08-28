"""Engine 主循环测试：四种运行形态、终止条件与错误路径。"""

from __future__ import annotations

import asyncio
import unittest

from btcmodule.core.result import BTCMError

from .common import TestHarness, VALIDATOR_OUTPUT, make_task

VALIDATOR_PASS = '{"verdict": "pass", "best_candidate": "候选A", "issues": [], "suggestions": [], "next_actions": []}'


def _run(coro):
    return asyncio.run(coro)


class PureCreativeTest(unittest.TestCase):
    def test_pure_creative(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(enable_creative=True, enable_validator=False)
                )
            )
            self.assertEqual(len(data["candidates"]), 2)
            self.assertEqual(data["conclusion"], data["candidates"][0])
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(data["termination_reason"], "single_pass")
            self.assertNotIn("verdict", data)
        finally:
            h.close()


class PureValidationTest(unittest.TestCase):
    def test_pure_validation(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        candidate="待验证方案",
                        enable_creative=False,
                        enable_validator=True,
                    )
                )
            )
            self.assertEqual(data["verdict"], "conditional_pass")
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(data["termination_reason"], "single_pass")
        finally:
            h.close()

    def test_missing_candidate_raises_invalid_request(self):
        h = TestHarness()
        try:
            with self.assertRaises(BTCMError) as ctx:
                _run(
                    h.engine.run(
                        make_task(
                            candidate=None,
                            enable_creative=False,
                            enable_validator=True,
                        )
                    )
                )
            self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
        finally:
            h.close()


class HybridTest(unittest.TestCase):
    def test_hybrid_reaches_max_iterations(self):
        h = TestHarness()
        try:
            data = _run(h.engine.run(make_task()))
            self.assertEqual(data["verdict"], "conditional_pass")
            self.assertEqual(data["iterations_used"], 2)
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(len(data["intermediate_log"]), 2)
        finally:
            h.close()

    def test_hybrid_pass_on_second_round(self):
        h = TestHarness(
            sequences={"validator": [VALIDATOR_OUTPUT, VALIDATOR_PASS]}
        )
        try:
            data = _run(h.engine.run(make_task()))
            self.assertEqual(data["termination_reason"], "validation_passed")
            self.assertEqual(data["iterations_used"], 2)
        finally:
            h.close()

    def test_hybrid_pass_on_first_round(self):
        h = TestHarness(sequences={"validator": [VALIDATOR_PASS]})
        try:
            data = _run(h.engine.run(make_task()))
            self.assertEqual(data["termination_reason"], "validation_passed")
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(len(data["intermediate_log"]), 1)
        finally:
            h.close()

    def test_hybrid_creative_failure_is_internal_error(self):
        h = TestHarness(raise_llm_error={"creative"})
        try:
            with self.assertRaises(BTCMError) as ctx:
                _run(h.engine.run(make_task()))
            self.assertEqual(ctx.exception.code, "INTERNAL_ERROR")
        finally:
            h.close()

    def test_hybrid_log_disabled_omits_intermediate_log(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        runtime_config={
                            "agents": {"controller": {"log_intermediate": False}}
                        }
                    )
                )
            )
            self.assertNotIn("intermediate_log", data)
        finally:
            h.close()


class LongChainTest(unittest.TestCase):
    def test_long_chain(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        enable_creative=False, enable_validator=False
                    )
                )
            )
            self.assertEqual(data["conclusion"], "最终结论")
            self.assertEqual(data["iterations_used"], 2)
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(len(data["intermediate_log"]), 2)
            self.assertIn("thought", data["intermediate_log"][0])
        finally:
            h.close()

    def test_long_chain_timeout(self):
        h = TestHarness(delay=0.4)
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        enable_creative=False,
                        enable_validator=False,
                        runtime_config={"timeout": 1, "max_iterations": 3},
                    )
                )
            )
            self.assertEqual(data["termination_reason"], "timeout")
            # 已跑完至少一轮（有结果），且不超过 max_iterations
            self.assertGreaterEqual(data["iterations_used"], 1)
            self.assertLessEqual(data["iterations_used"], 3)
            # timeout 后不再调用 finalize（隐藏的第 N+1 次调用），
            # 以最后一轮思考作结论
            finalize_calls = [
                c
                for c in h.fake.calls
                if c[0] == "controller"
                and "整合为一份最终结论" in c[1][0]["content"]
            ]
            self.assertEqual(len(finalize_calls), 0)
            self.assertEqual(data["conclusion"], "本轮思考要点")
        finally:
            h.close()

    def test_long_chain_finalize_failure_falls_back(self):
        h = TestHarness(finalize_raises=True)
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        enable_creative=False, enable_validator=False
                    )
                )
            )
            # finalize 失败：回退最后一轮思考作结论，而非 INTERNAL_ERROR
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(data["iterations_used"], 2)
            self.assertEqual(data["conclusion"], "本轮思考要点")
        finally:
            h.close()

    def test_long_chain_single_iteration(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        enable_creative=False,
                        enable_validator=False,
                        runtime_config={"max_iterations": 1},
                    )
                )
            )
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(data["termination_reason"], "max_iterations")
            # finalize 仍然执行
            self.assertEqual(data["conclusion"], "最终结论")
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
