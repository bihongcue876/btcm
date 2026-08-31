"""主循环控制器（Engine）。

按 enable_creative / enable_validator 组合分派四种运行形态：
- 双开：完整循环（生成-验证-反思，多轮）
- 仅创意：纯创意（单次生成候选）
- 仅验证：纯验证（单次验证 candidate）
- 双关：长链持续思考（controller 多轮自我迭代 + 最终整合）

终止判定：validation_passed / controller_stop / max_iterations / timeout。
全局 timeout 由 asyncio.timeout 强制执行：超时即掐断进行中的 LLM 调用；
已完成至少一轮则带结果返回（termination_reason=timeout），否则错误 TIMEOUT。
"""

from __future__ import annotations

import asyncio

from ..agents.controller import ControllerAgent
from ..agents.creative import CreativeAgent
from ..agents.validator import ValidatorAgent
from .config import ConfigManager, resolve_agent_params, resolve_global_params
from .llm import LLMError, ModelGateway
from .mcp import MCPManager
from .result import BTCMError
from .task import Task

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
        # MCPManager 自行注册配置变更回调（update/reset 时缓存失效）
        self._mcp = MCPManager(cm)
        self._creative = CreativeAgent(cm, gateway)
        self._validator = ValidatorAgent(cm, gateway, self._mcp)
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

        current_candidate = task.candidate
        validation_feedback: dict | None = None
        next_direction: str | None = None
        intermediate_log: list[dict] = []
        iterations = 0
        final_report: dict | None = None
        final_reflection: dict | None = None
        termination_reason = "max_iterations"

        try:
            async with asyncio.timeout(timeout):
                for iteration in range(1, max_iterations + 1):
                    gen = await self._safe_call(
                        "creative",
                        lambda: self._creative.generate(
                            task,
                            current_candidate,
                            validation_feedback,
                            runtime,
                            next_direction,
                        ),
                    )
                    candidates = gen["candidates"]
                    report = await self._validator.validate(
                        task, candidates, runtime
                    )
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
                                    "decision": reflection["decision"],
                                    "next_direction": reflection.get(
                                        "next_direction", ""
                                    ),
                                },
                            }
                        )

                    if report["verdict"] == "pass":
                        termination_reason = "validation_passed"
                        break

                    # 总控决定提前收敛：结论可用或继续修正边际收益过低。
                    # fail 时不允许 stop——验证判定存在严重问题时，
                    # 总控不得把失败提前定稿，必须继续修正轮
                    if (
                        reflection["decision"] == "stop"
                        and report["verdict"] != "fail"
                    ):
                        termination_reason = "controller_stop"
                        break

                    # 未通过：下轮基于最优候选、验证问题与总控方向修正，不再重新发散
                    current_candidate = (
                        report.get("best_candidate") or candidates[0]
                    )
                    validation_feedback = report
                    next_direction = reflection.get("next_direction") or None
        except TimeoutError:
            if iterations == 0:
                raise BTCMError(
                    "TIMEOUT", "任务执行超时，且未完成任何一轮"
                ) from None
            termination_reason = "timeout"

        if final_report is None or final_reflection is None:
            raise BTCMError(
                "INTERNAL_ERROR",
                "循环异常终止且无可用轮次结果",
                status_code=500,
            )
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
        _, timeout = resolve_global_params(self.config, runtime)
        try:
            async with asyncio.timeout(timeout):
                gen = await self._safe_call(
                    "creative",
                    lambda: self._creative.generate(
                        task, task.candidate, None, runtime
                    ),
                )
        except TimeoutError:
            raise BTCMError("TIMEOUT", "任务执行超时，且未完成") from None
        return {
            "candidates": gen["candidates"],
            "conclusion": gen["conclusion"],
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
        _, timeout = resolve_global_params(self.config, runtime)
        try:
            async with asyncio.timeout(timeout):
                report = await self._validator.validate(
                    task, [task.candidate], runtime
                )
        except TimeoutError:
            raise BTCMError("TIMEOUT", "任务执行超时，且未完成") from None
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

        thoughts: list[str] = []
        intermediate_log: list[dict] = []
        termination_reason = "max_iterations"
        conclusion = ""

        try:
            async with asyncio.timeout(timeout):
                for iteration in range(1, max_iterations + 1):
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

                # timeout 终止时不进入 finalize（预算已耗尽，不再发起额外调用）；
                # 正常终止时 finalize 失败也回退最后一轮，避免把
                # "已完成思考"降级成 INTERNAL_ERROR
                if thoughts:
                    try:
                        conclusion = await self._safe_call(
                            "controller",
                            lambda: self._controller.finalize(
                                task, thoughts, runtime
                            ),
                        )
                    except BTCMError:
                        conclusion = thoughts[-1]
        except TimeoutError:
            termination_reason = "timeout"
            if not thoughts:
                raise BTCMError(
                    "TIMEOUT", "任务执行超时，且未完成任何一轮思考"
                ) from None
            conclusion = thoughts[-1]

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
