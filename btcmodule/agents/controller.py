"""总控 Agent（Controller Agent）—— meta 职责：总体认识与批判性控制。

两个职责：
1. 完整循环反思：对当轮创意生成与验证结果作总体认识与批判性控制，
   输出结论要点、风险缺口与下轮方向。
2. 长链持续思考：当创意与验证 Agent 均未启用时，作为唯一执行者逐轮
   批判性深化（think），最后由 finalize 批判性整合全部轮次为最终结论。
"""

from __future__ import annotations

from ..core.config import ConfigManager
from ..core.llm import ModelGateway
from ..core.task import RuntimeConfig, Task
from .base import AgentOutputError, parse_json_object, require_keys, run_agent_with_retry


class ControllerAgent:
    def __init__(self, cm: ConfigManager, gateway: ModelGateway) -> None:
        self._cm = cm
        self._gateway = gateway

    # ---------- 完整循环：反思 ----------

    async def reflect(
        self,
        task: Task,
        candidates: list[str],
        validation_report: dict,
        iteration: int,
        runtime: RuntimeConfig | None,
    ) -> dict:
        """整合当轮结果，输出要点级反思。返回 reflect 输出 dict。"""
        candidate_lines = "\n".join(f"- {c}" for c in candidates)
        system = (
            "你是总控 Agent，承担 meta 职责：对当轮创意生成与验证结果作"
            "总体认识与批判性控制。\n"
            "总体认识：提炼当轮结论的核心要点。\n"
            "批判性控制：判断结论是否成立、风险与缺口何在、是否需要继续修正。\n"
            "只输出短句要点，不展开长篇推理。\n"
            "输出必须严格是 JSON 对象，格式为：\n"
            '{"conclusion": "当轮总体认识（结论要点）", '
            '"remaining_issues": ["批判性发现的风险与缺口", ...], '
            '"next_direction": "下轮修正方向要点", '
            '"decision": "continue 或 stop"}'
        )

        user_lines = [f"任务/用户问题：{task.user_query}"]
        if task.context_summary:
            user_lines.append(f"上下文摘要：{task.context_summary}")
        user_lines.append(f"第 {iteration} 轮候选：\n{candidate_lines}")
        user_lines.append(
            f"验证判定：{validation_report.get('verdict')}\n"
            f"验证问题：\n"
            + "\n".join(f"- {i}" for i in validation_report.get("issues", []))
            + "\n验证建议：\n"
            + "\n".join(f"- {s}" for s in validation_report.get("suggestions", []))
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

        def _parse(content: str) -> dict:
            obj = parse_json_object(content)
            require_keys(obj, ["conclusion"], "controller")
            return {
                "conclusion": str(obj.get("conclusion", "")),
                "remaining_issues": [str(i) for i in obj.get("remaining_issues", [])],
                "next_direction": str(obj.get("next_direction", "")),
                "decision": str(obj.get("decision", "continue")),
            }

        return await run_agent_with_retry(
            self._gateway, "controller", messages, runtime, _parse
        )

    # ---------- 长链持续思考 ----------

    async def think(
        self,
        task: Task,
        previous_thoughts: list[str],
        iteration: int,
        runtime: RuntimeConfig | None,
    ) -> dict:
        """单轮长链思考：基于任务与已有要点输出新一轮思考要点。"""
        system = (
            "你是总控 Agent，处于长链持续思考，承担 meta 职责。\n"
            "每轮对任务与已有要点作批判性深化：检验逻辑、发现漏洞、补充论据、"
            "收敛结论，逐轮逼近一个合理的结果。\n"
            "只输出本轮新的要点，不重复已有内容，不展开长篇推理。\n"
            "输出必须严格是 JSON 对象，格式为："
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
            user_lines.append(
                "此前思考要点：\n"
                + "\n".join(f"- {t}" for t in previous_thoughts)
            )
        user_lines.append(f"这是第 {iteration} 轮思考，请输出本轮新的思考要点。")

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
