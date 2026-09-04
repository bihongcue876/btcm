"""Engine 主循环测试：四种运行形态、终止条件与错误路径。"""

from __future__ import annotations

import asyncio
import unittest

from btcmodule.core.result import BTCMError

from .common import (
    TestHarness,
    VALIDATOR_OUTPUT,
    META_STOP_OUTPUT,
    make_task,
)

VALIDATOR_PASS = '{"verdict": "pass", "best_candidate": "候选A", "issues": [], "suggestions": [], "next_actions": []}'
VALIDATOR_FAIL = '{"verdict": "fail", "best_candidate": null, "issues": ["严重问题"], "suggestions": [], "next_actions": []}'


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
            # conclusion 来自创意 Agent 对全部候选的综合，而非取第一个
            self.assertEqual(data["conclusion"], "综合推荐说明")
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
                            "agents": {"meta": {"log_intermediate": False}}
                        }
                    )
                )
            )
            self.assertNotIn("intermediate_log", data)
        finally:
            h.close()

    def test_hybrid_meta_stop_terminates_early(self):
        """meta decision=stop 参与终止判定：validation_passed 优先，其次 controller_stop。"""
        h = TestHarness(sequences={"meta": [META_STOP_OUTPUT]})
        try:
            data = _run(h.engine.run(make_task()))
            self.assertEqual(data["termination_reason"], "controller_stop")
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(data["conclusion"], "结论已可用")
        finally:
            h.close()

    def test_hybrid_next_direction_feeds_creative(self):
        """meta next_direction 回灌下一轮创意输入。"""
        h = TestHarness()
        try:
            _run(h.engine.run(make_task()))
            creative_calls = [c for c in h.fake.calls if c[0] == "creative"]
            self.assertEqual(len(creative_calls), 2)
            first_user = creative_calls[0][1][1]["content"]
            second_user = creative_calls[1][1][1]["content"]
            self.assertNotIn("总控下轮方向", first_user)
            self.assertIn("总控下轮方向：方向", second_user)
        finally:
            h.close()

    def test_hybrid_intermediate_log_includes_next_direction(self):
        h = TestHarness()
        try:
            data = _run(h.engine.run(make_task()))
            for entry in data["intermediate_log"]:
                self.assertIn("next_direction", entry["meta_reflection"])
        finally:
            h.close()

    def test_hybrid_fail_forbids_meta_stop(self):
        """验证判定 fail 时 meta 不得提前 stop：强制继续修正轮，不得定稿失败。"""
        h = TestHarness(
            sequences={
                "validator": [VALIDATOR_FAIL, VALIDATOR_FAIL],
                "meta": [META_STOP_OUTPUT, META_STOP_OUTPUT],
            }
        )
        try:
            data = _run(h.engine.run(make_task()))
            self.assertEqual(data["termination_reason"], "max_iterations")
            self.assertEqual(data["iterations_used"], 2)
        finally:
            h.close()

    def test_hybrid_timeout_returns_partial_result(self):
        """全局 timeout 掐断进行中的调用：已完成一轮则带结果返回 timeout。"""
        h = TestHarness(delay=0.25)
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        runtime_config={"timeout": 1, "max_iterations": 3}
                    )
                )
            )
            self.assertEqual(data["termination_reason"], "timeout")
            self.assertGreaterEqual(data["iterations_used"], 1)
        finally:
            h.close()

    def test_hybrid_timeout_without_completed_round_raises(self):
        """一轮都未完成时全局超时返回 TIMEOUT 错误。"""
        h = TestHarness(delay=0.6)
        try:
            with self.assertRaises(BTCMError) as ctx:
                _run(
                    h.engine.run(
                        make_task(
                            runtime_config={"timeout": 1, "max_iterations": 3}
                        )
                    )
                )
            self.assertEqual(ctx.exception.code, "TIMEOUT")
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


class EffortTest(unittest.TestCase):
    """思考深度三档：light 强制单轮，提示词按档位注入。"""

    def test_light_forces_single_iteration(self):
        h = TestHarness()
        try:
            data = _run(h.engine.run(make_task(effort="light")))
            self.assertEqual(data["iterations_used"], 1)
            self.assertEqual(data["termination_reason"], "max_iterations")
        finally:
            h.close()

    def test_light_injects_directive_and_is_final(self):
        h = TestHarness()
        try:
            _run(h.engine.run(make_task(effort="light")))
            sys_content = h.fake.calls[0][1][0]["content"]
            self.assertIn("略想", sys_content)
            creative_user = next(
                c[1][1]["content"] for c in h.fake.calls if c[0] == "creative"
            )
            self.assertIn("本轮是最后一轮", creative_user)
        finally:
            h.close()

    def test_deep_injects_directive(self):
        h = TestHarness()
        try:
            _run(h.engine.run(make_task(effort="deep")))
            sys_content = h.fake.calls[0][1][0]["content"]
            self.assertIn("深层", sys_content)
        finally:
            h.close()

    def test_standard_no_directive(self):
        h = TestHarness()
        try:
            _run(h.engine.run(make_task()))
            sys_content = h.fake.calls[0][1][0]["content"]
            self.assertNotIn("思考深度要求", sys_content)
        finally:
            h.close()

    def test_light_long_chain_single_iteration(self):
        h = TestHarness()
        try:
            data = _run(
                h.engine.run(
                    make_task(
                        effort="light",
                        enable_creative=False,
                        enable_validator=False,
                    )
                )
            )
            self.assertEqual(data["iterations_used"], 1)
        finally:
            h.close()


class RemainingIterationsTest(unittest.TestCase):
    """剩余轮次注入：meta 收到收束提示，creative 收到最后一轮标记。"""

    def test_meta_receives_remaining_iterations(self):
        h = TestHarness()
        try:
            _run(h.engine.run(make_task()))
            meta_calls = [c for c in h.fake.calls if c[0] == "meta"]
            self.assertEqual(len(meta_calls), 2)
            first_user = meta_calls[0][1][1]["content"]
            second_user = meta_calls[1][1][1]["content"]
            self.assertIn("剩余修正轮次：1", first_user)
            self.assertIn("最后一轮（无剩余轮次）", second_user)
        finally:
            h.close()

    def test_intermediate_log_includes_remaining_iterations(self):
        h = TestHarness()
        try:
            data = _run(h.engine.run(make_task()))
            for entry in data["intermediate_log"]:
                self.assertIn("remaining_iterations", entry["meta_reflection"])
        finally:
            h.close()

    def test_creative_final_round_on_last_iteration(self):
        h = TestHarness()
        try:
            _run(h.engine.run(make_task()))
            creative_calls = [c for c in h.fake.calls if c[0] == "creative"]
            self.assertEqual(len(creative_calls), 2)
            self.assertNotIn("本轮是最后一轮", creative_calls[0][1][1]["content"])
            self.assertIn("本轮是最后一轮", creative_calls[1][1][1]["content"])
        finally:
            h.close()

    def test_controller_receives_total_iterations(self):
        h = TestHarness()
        try:
            _run(
                h.engine.run(
                    make_task(enable_creative=False, enable_validator=False)
                )
            )
            think_calls = [
                c
                for c in h.fake.calls
                if c[0] == "controller" and "长链持续思考" in c[1][0]["content"]
            ]
            self.assertEqual(len(think_calls), 2)
            first_user = think_calls[0][1][1]["content"]
            second_user = think_calls[1][1][1]["content"]
            self.assertIn("（共 2 轮）", first_user)
            self.assertNotIn("最后一轮", first_user)
            self.assertIn("最后一轮：请输出收敛性要点", second_user)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
