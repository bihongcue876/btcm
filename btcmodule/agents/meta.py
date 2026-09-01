"""meta Agent（Meta Agent）—— 检查管理职责：全局思维管理。

职责：以半个元认知的视角做全局思维管理——总体认识当轮结果、
批判性控制（接受合理发散，批驳怪异与逻辑错乱）、以资源意识给出
continue / stop 决定。decision 参与终止判定，next_direction 回灌下轮创意。
"""

from __future__ import annotations

from ..core.config import ConfigManager
from ..core.llm import ModelGateway
from ..core.task import RuntimeConfig, Task
from .base import parse_json_object, require_keys, run_agent_with_retry


class MetaAgent:
    def __init__(self, cm: ConfigManager, gateway: ModelGateway) -> None:
        self._cm = cm
        self._gateway = gateway

    async def reflect(
        self,
        task: Task,
        candidates: list[str],
        validation_report: dict,
        iteration: int,
        runtime: RuntimeConfig | None,
    ) -> dict:
        candidate_lines = "\n".join(f"- {c}" for c in candidates)
        system = (
            "你是 meta Agent，承担检查与管理职责：以全局视角管理整场思考。\n"
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
            require_keys(obj, ["conclusion"], "meta")
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
            self._gateway, "meta", messages, runtime, _parse
        )