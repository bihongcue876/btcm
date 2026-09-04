"""创意生成 Agent（Creative Agent）。

职责：针对用户问题或给定候选，发散式生成多个候选方案。
输入：任务、当前候选（可选）、上一轮验证反馈（可选）、总控下轮方向（可选）。
输出：{"candidates": [...], "conclusion": 综合全部候选的推荐说明}。
"""

from __future__ import annotations

from ..core.config import ConfigManager, resolve_agent_params
from ..core.llm import ModelGateway
from ..core.task import RuntimeConfig, Task
from .base import (
    AgentOutputError,
    effort_directive,
    parse_json_object,
    require_keys,
    run_agent_with_retry,
)


class CreativeAgent:
    def __init__(self, cm: ConfigManager, gateway: ModelGateway) -> None:
        self._cm = cm
        self._gateway = gateway

    async def generate(
        self,
        task: Task,
        current_candidate: str | None,
        validation_feedback: dict | None,
        runtime: RuntimeConfig | None,
        next_direction: str | None = None,
        is_final: bool = False,
    ) -> dict:
        """生成候选列表与综合结论。首轮发散生成；后续轮基于最优候选与验证问题修正。"""

        def _bullet(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items)

        feedback_text = "（无）"
        if validation_feedback:
            lines = []
            if validation_feedback.get("issues"):
                lines.append("上一轮验证问题：\n" + _bullet(validation_feedback["issues"]))
            if validation_feedback.get("suggestions"):
                lines.append("验证建议：\n" + _bullet(validation_feedback["suggestions"]))
            if validation_feedback.get("best_candidate"):
                lines.append(f"上一轮最优候选：{validation_feedback['best_candidate']}")
            if lines:
                feedback_text = "\n".join(lines)

        params = resolve_agent_params(self._cm.config, runtime, "creative")
        num_candidates = params["num_candidates"]

        system = (
            "你是创意生成 Agent，为委托给你的思考任务生成候选方案。\n"
            "首轮（无验证反馈时）发散生成多个多样候选；"
            "后续轮（有验证反馈时）基于最优候选与验证问题修正，"
            "生成少量修正候选，不重新发散。\n"
            "发散是被鼓励的：候选之间保持真实差异；"
            "但每个候选必须完整可用、逻辑自洽，并附简要理由。\n"
            "候选数量不设硬性要求：能想到几个就几个，"
            "不要为凑数编造低质量候选。\n"
            "conclusion 必须综合全部候选：概括各候选的取舍与适用情形，"
            "不得只突出单一候选。\n"
            + effort_directive(task.effort)
            + "输出必须严格是 JSON 对象，格式为：\n"
            '{"candidates": ["候选1（含简要理由）", "候选2（含简要理由）", ...], '
            '"conclusion": "综合全部候选的推荐说明"}'
        )

        user_lines = [f"任务/用户问题：{task.user_query}"]
        if task.context_summary:
            user_lines.append(f"上下文摘要：{task.context_summary}")
        if task.evidence:
            user_lines.append(
                "参考证据：\n" + "\n".join(f"- {e}" for e in task.evidence)
            )
        if current_candidate:
            user_lines.append(f"已有候选/待改进内容：{current_candidate}")
        user_lines.append(f"上一轮验证反馈：\n{feedback_text}")
        if validation_feedback:
            user_lines.append(
                "本轮为修正轮：基于最优候选与验证问题生成 1-2 个修正候选，不重新发散。"
            )
        else:
            user_lines.append(
                f"本轮为发散轮：请生成多个多样候选方案（配置上限 {num_candidates} 个），"
                "数量不设硬性要求，能想到几个就几个。"
            )
        if is_final:
            user_lines.append(
                "本轮是最后一轮：请直接产出可直接采纳的最终候选，"
                "确保完整、自洽、不留待后续修正。"
            )
        if next_direction:
            user_lines.append(f"总控下轮方向：{next_direction}")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

        def _parse(content: str) -> dict:
            obj = parse_json_object(content)
            require_keys(obj, ["candidates"], "creative")
            candidates = obj["candidates"]
            if (
                not isinstance(candidates, list)
                or not candidates
                or not all(isinstance(c, str) and c.strip() for c in candidates)
            ):
                raise AgentOutputError("Agent 'creative' 输出的 candidates 非法或为空")
            cleaned = [c.strip() for c in candidates]
            conclusion = str(obj.get("conclusion", "")).strip()
            if not conclusion:
                # 回退：候选串联，保证结论仍覆盖全部候选
                conclusion = "；".join(cleaned)
            return {"candidates": cleaned, "conclusion": conclusion}

        return await run_agent_with_retry(
            self._gateway, "creative", messages, runtime, _parse
        )
