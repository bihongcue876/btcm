"""主循环控制器（Engine）。

按 enable_creative / enable_validator 组合分派四种运行形态：
- 双开：完整循环（生成-验证-反思，多轮）
- 仅创意：纯创意（单次生成候选）
- 仅验证：纯验证（单次验证 candidate）
- 双关：长链持续思考（controller 多轮自我迭代 + 最终整合）

终止判定仅三类机械规则：validation_passed / max_iterations / timeout。
"""

from __future__ import annotations

import time

from ..agents.controller import ControllerAgent
from ..agents.creative import CreativeAgent
from ..agents.validator import ValidatorAgent
from .config import ConfigManager, resolve_agent_params, resolve_global_params
from .llm import LLMError, ModelGateway
from .result import BTCMError
from .task import RuntimeConfig, Task

# 非 validator 的 Agent 调用失败（LLM 错误 / 解析失败）统一映射为内部错误
_INTERNAL_MESSAGES = {
    "llm_timeout": "内部 Agent 单请求超时",
    "llm_error": "内部 Agent 请求失败",
    "llm_empty": "内部 Agent 返回空内容",
}


def _validation_conclusion(report: dict) -> str:
    verdict = report.get("verdict", "")
    best = report.get("best_candidate")
    if best:
        return f"验证结果：{verdict}；最优候选：{best}"
    return f"验证结果：{verdict}"


class Engine:
    def __init__(self, cm: ConfigManager, gateway: ModelGateway) -> None:
        self._cm = cm
        self._gateway = gateway
        self._creative = CreativeAgent(cm, gateway)
        self._validator = ValidatorAgent(cm, gateway)
        self._controller = ControllerAgent(cm, gateway)

    @property
    def config(self):
        return self._cm.config

    async def run(self, task: Task) -> dict:
        """执行一次调用，返回协议 data 结构。"""
        try:
            if task.enable_creative and task.enable_validator:
                return await self._run_hybrid(task)
            if task.enable_creative and not task.enable_validator:
                return await self._run_pure_creative(task)
            if not task.enable_creative and task.enable_validator:
                return await self._run_pure_validation(task)
            return await self._run_long_chain(task)
        except BTCMError:
            raise
        except Exception as e:
            # 兜底：任何未预期异常（如配置路由错误）统一转为内部错误
            raise BTCMError(
                "INTERNAL_ERROR",
                f"内部错误：{type(e).__name__}: {e}",
                status_code=500,
            ) from e

    # ---------- 完整循环 ----------

    async def _run_hybrid(self, task: Task) -> dict:
        runtime = task.runtime_config
        max_iterations, timeout = resolve_global_params(self.config, runtime)
        params = resolve_agent_params(self.config, runtime, "controller")
        log_intermediate = bool(params["log_intermediate"])

        start = time.monotonic()
        current_candidate = task.candidate
        validation_feedback: dict | None = None
        intermediate_log: list[dict] = []
        iterations = 0
        final_report: dict | None = None
        final_reflection: dict | None = None
        termination_reason = "max_iterations"

        for iteration in range(1, max_iterations + 1):
            if time.monotonic() - start >= timeout:
                termination_reason = "timeout"
                if iterations == 0:
                    raise BTCMError(
                        "TIMEOUT", "任务执行超时，且未完成任何一轮"
                    )
                break

            candidates = await self._safe_call(
                "creative",
                lambda: self._creative.generate(
                    task, current_candidate, validation_feedback, runtime
                ),
            )
            report = await self._validator.validate(task, candidates, runtime)
            reflection = await self._safe_call(
                "controller",
                lambda: self._controller.reflect(
                    task, candidates, report, iteration, runtime
                ),
            )

            iterations = iteration
            final_report = report
            final_reflection = reflection

            if log_intermediate:
                intermediate_log.append(
                    {
                        "iteration": iteration,
                        "creative_output": candidates,
                        "validator_output": {
                            "verdict": report["verdict"],
                            "issues": report["issues"],
                        },
                        "controller_reflection": {
                            "decision": reflection.get("decision", "continue")
                        },
                    }
                )

            if report["verdict"] == "pass":
                termination_reason = "validation_passed"
                break

            # 本轮结束即超过全局超时：返回已有结果（至少完成一轮）
            if time.monotonic() - start >= timeout:
                termination_reason = "timeout"
                break

            # 未通过：下轮基于最优候选与验证问题修正，不再重新发散
            current_candidate = report.get("best_candidate") or candidates[0]
            validation_feedback = report

        assert final_report is not None and final_reflection is not None
        data: dict = {
            "verdict": final_report["verdict"],
            "conclusion": final_reflection.get("conclusion", ""),
            "issues": final_report["issues"],
            "suggestions": final_report["suggestions"],
            "next_actions": final_report["next_actions"],
            "iterations_used": iterations,
            "termination_reason": termination_reason,
        }
        if log_intermediate:
            data["intermediate_log"] = intermediate_log
        return data

    # ---------- 纯创意 ----------

    async def _run_pure_creative(self, task: Task) -> dict:
        runtime = task.runtime_config
        candidates = await self._safe_call(
            "creative",
            lambda: self._creative.generate(task, task.candidate, None, runtime),
        )
        return {
            "candidates": candidates,
            "conclusion": candidates[0] if candidates else "",
            "iterations_used": 1,
            "termination_reason": "single_pass",
        }

    # ---------- 纯验证 ----------

    async def _run_pure_validation(self, task: Task) -> dict:
        runtime = task.runtime_config
        if not task.candidate:
            raise BTCMError(
                "INVALID_REQUEST",
                "纯验证形态（enable_creative=false）下 candidate 必填",
            )
        report = await self._validator.validate(
            task, [task.candidate], runtime
        )
        return {
            "verdict": report["verdict"],
            "conclusion": _validation_conclusion(report),
            "issues": report["issues"],
            "suggestions": report["suggestions"],
            "next_actions": report["next_actions"],
            "iterations_used": 1,
            "termination_reason": "single_pass",
        }

    # ---------- 长链持续思考 ----------

    async def _run_long_chain(self, task: Task) -> dict:
        runtime = task.runtime_config
        max_iterations, timeout = resolve_global_params(self.config, runtime)

        start = time.monotonic()
        thoughts: list[str] = []
        intermediate_log: list[dict] = []
        termination_reason = "max_iterations"

        for iteration in range(1, max_iterations + 1):
            if time.monotonic() - start >= timeout:
                termination_reason = "timeout"
                if not thoughts:
                    raise BTCMError(
                        "TIMEOUT", "任务执行超时，且未完成任何一轮思考"
                    )
                break

            out = await self._safe_call(
                "controller",
                lambda: self._controller.think(
                    task, thoughts, iteration, runtime
                ),
            )
            thoughts.append(out["thought"])
            intermediate_log.append(
                {"iteration": iteration, "thought": out["thought"]}
            )

            if time.monotonic() - start >= timeout:
                termination_reason = "timeout"
                break

        # timeout 终止时跳过 finalize（预算已耗尽，不再发起第 N+1 次调用），
        # 以最后一轮思考作结论；正常终止时 finalize 失败也回退最后一轮，
        # 避免把"已完成思考"降级成 INTERNAL_ERROR
        if termination_reason == "timeout":
            conclusion = thoughts[-1] if thoughts else ""
        else:
            try:
                conclusion = await self._safe_call(
                    "controller",
                    lambda: self._controller.finalize(task, thoughts, runtime),
                )
            except BTCMError:
                conclusion = thoughts[-1] if thoughts else ""
        return {
            "conclusion": conclusion,
            "iterations_used": len(thoughts),
            "termination_reason": termination_reason,
            "intermediate_log": intermediate_log,
        }

    # ---------- 内部错误包装 ----------

    async def _safe_call(self, agent_name: str, coro_factory):
        """creative / controller 无 fail 降级语义，调用失败统一转内部错误。"""
        try:
            return await coro_factory()
        except LLMError as e:
            raise BTCMError(
                "INTERNAL_ERROR",
                f"{_INTERNAL_MESSAGES.get(e.code, e.message)}（{agent_name}）",
                status_code=500,
            ) from e
        except BTCMError:
            raise
        except Exception as e:
            raise BTCMError(
                "INTERNAL_ERROR",
                f"内部错误（{agent_name}）：{e}",
                status_code=500,
            ) from e
