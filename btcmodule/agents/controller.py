"""总控 Agent（Controller Agent）—— 长链思考产成者。

当创意与验证 Agent 均未启用时，作为唯一执行者逐轮批判性深化（think），
最后由 finalize 批判性整合全部轮次为最终结论。
"""

from __future__ import annotations

from ..core.config import ConfigManager
from ..core.llm import ModelGateway
from ..core.task import RuntimeConfig, Task
from .base import (
    AgentOutputError,
    effort_directive,
    parse_json_object,
    require_keys,
    run_agent_with_retry,
)

HISTORY_KEEP = 5


def _history_lines(previous_thoughts: list[str]) -> str:
    """长链历史窗口：全部保留（少量）或 首条 + 最近 HISTORY_KEEP 条。"""
    total = len(previous_thoughts)
    if total <= HISTORY_KEEP + 1:
        selected = previous_thoughts
        omitted = 0
    else:
        selected = [previous_thoughts[0]] + previous_thoughts[-HISTORY_KEEP:]
        omitted = total - len(selected)
    lines = [f"- {t}" for t in selected]
    if omitted:
        lines.insert(1, f"……（中间 {omitted} 条要点已省略）")
    return "\n".join(lines)


class ControllerAgent:
    def __init__(self, cm: ConfigManager, gateway: ModelGateway) -> None:
        self._cm = cm
        self._gateway = gateway

    # ---------- 长链持续思考 ----------

    async def think(
        self,
        task: Task,
        previous_thoughts: list[str],
        iteration: int,
        runtime: RuntimeConfig | None,
        total_iterations: int | None = None,
    ) -> dict:
        """单轮长链思考：基于任务与已有要点输出新一轮思考要点。"""
        system = (
            "你是总控 Agent，处于长链持续思考。\n"
            "每轮对任务与已有要点作批判性深化：检验逻辑、发现漏洞、补充论据、"
            "收敛结论，逐轮逼近一个合理的结果。\n"
            "只输出本轮新的要点，不重复已有内容，不展开长篇推理。\n"
            + effort_directive(task.effort)
            + "输出必须严格是 JSON 对象，格式为："
            '{"thought": "本轮批判性思考要点"}'
        )

        user_lines = [f"任务/用户问题：{task.user_query}"]
        if task.context_summary:
            user_lines.append(f"上下文摘要：{task.context_summary}")
        if task.evidence:
            user_lines.append(
                "参考证据：\n" + "\n".join(f"- {e}" for e in task.evidence)
            )
        if previous_thoughts:
            user_lines.append("此前思考要点：\n" + _history_lines(previous_thoughts))
        round_note = f"这是第 {iteration} 轮思考"
        if total_iterations is not None:
            round_note += f"（共 {total_iterations} 轮）"
            if iteration >= total_iterations:
                round_note += (
                    "，本轮是最后一轮：请输出收敛性要点，"
                    "把思考收拢到可整合为最终结论的程度"
                )
        user_lines.append(round_note + "，请输出本轮新的思考要点。")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

        def _parse(content: str) -> dict:
            obj = parse_json_object(content)
            require_keys(obj, ["thought"], "controller")
            thought = str(obj["thought"]).strip()
            if not thought:
                raise AgentOutputError("controller 长链思考输出为空")
            return {"thought": thought}

        return await run_agent_with_retry(
            self._gateway, "controller", messages, runtime, _parse
        )

    async def finalize(
        self,
        task: Task,
        thoughts: list[str],
        runtime: RuntimeConfig | None,
    ) -> str:
        """整合全部思考轮次为最终结论。"""
        system = (
            "你是总控 Agent。以下是你此前多轮长链思考的全部要点，"
            "请作批判性整合为一份最终结论。\n"
            "要求：覆盖要点关键信息，剔除矛盾与不可靠部分，结构清晰、"
            "可直接作为对用户问题的答复，不要罗列草稿。\n"
            "输出必须严格是 JSON 对象，格式为："
            '{"conclusion": "最终结论"}'
        )

        thought_lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(thoughts))
        user_lines = [
            f"任务/用户问题：{task.user_query}",
            f"全部思考要点：\n{thought_lines}",
        ]

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

        def _parse(content: str) -> str:
            obj = parse_json_object(content)
            require_keys(obj, ["conclusion"], "controller")
            return str(obj["conclusion"]).strip()

        return await run_agent_with_retry(
            self._gateway, "controller", messages, runtime, _parse
        )
