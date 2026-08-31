"""总控 Agent（Controller Agent）—— meta 职责：全局思维管理。

两个职责：
1. 完整循环反思：以半个元认知的视角做全局思维管理——总体认识当轮结果、
   批判性控制（接受合理发散，批驳怪异与逻辑错乱）、以资源意识给出
   continue / stop 决定。decision 参与终止判定，next_direction 回灌下轮创意。
2. 长链持续思考：当创意与验证 Agent 均未启用时，作为唯一执行者逐轮
   批判性深化（think），最后由 finalize 批判性整合全部轮次为最终结论。
"""

from __future__ import annotations

from ..core.config import ConfigManager
from ..core.llm import ModelGateway
from ..core.task import RuntimeConfig, Task
from .base import AgentOutputError, parse_json_object, require_keys, run_agent_with_retry

# 长链思考回灌给模型的历史要点上限：超出则保留首条 + 最近 5 条（控制有效 token）
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

    # ---------- 完整循环：反思 ----------

    async def reflect(
        self,
        task: Task,
        candidates: list[str],
        validation_report: dict,
        iteration: int,
        runtime: RuntimeConfig | None,
    ) -> dict:
        """整合当轮结果，输出要点级反思。decision / next_direction 具有实效。"""
        candidate_lines = "\n".join(f"- {c}" for c in candidates)
        system = (
            "你是总控 Agent，承担元认知职责：以全局视角管理整场思考，而非亲自执行。\n"
            "总体认识：提炼本轮候选与验证结果的核心要点；\n"
            "批判性控制：接受合理的发散与跳跃，"
            "但批驳过于怪异、逻辑错乱或偏离任务的候选，指出风险与缺口；\n"
            "资源意识：以有效 token 为限，只输出短句要点，不展开长篇推理，"
            "不为边际收益极低的修正继续消耗调用。\n"
            "decision 判定：当前最优候选可直接采纳，"
            "或仅剩调用方可自行消化的轻微问题时输出 stop；"
            "存在严重问题且仍有明确修正方向时输出 continue。\n"
            "输出必须严格是 JSON 对象，格式为：\n"
            '{"conclusion": "当轮总体认识（结论要点）", '
            '"remaining_issues": ["批判性发现的风险与缺口", ...], '
            '"next_direction": "下轮修正方向要点（decision 为 stop 时可省略）", '
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
            decision = str(obj.get("decision", "continue")).strip().lower()
            if decision not in ("continue", "stop"):
                decision = "continue"
            return {
                "conclusion": str(obj.get("conclusion", "")),
                "remaining_issues": [str(i) for i in obj.get("remaining_issues", [])],
                "next_direction": str(obj.get("next_direction", "")).strip(),
                "decision": decision,
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
            user_lines.append("此前思考要点：\n" + _history_lines(previous_thoughts))
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
