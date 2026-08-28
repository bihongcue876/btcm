"""Agent 公共辅助：LLM 调用重试与结构化输出解析。

协议约定：解析失败与单请求超时均按"一次重试后降级 fail"处理。
run_agent_with_retry 覆盖两类失败（LLM 层失败与解析失败）各重试一次：
- creative / controller 失败没有 fail 语义，重试后抛出异常，由主循环层转为 INTERNAL_ERROR
- validator 的降级由 validator.py 自行捕获并返回 fail 报告
"""

from __future__ import annotations

import json
import re

from ..core.llm import LLMError, ModelGateway
from ..core.task import RuntimeConfig


class AgentOutputError(Exception):
    """Agent 结构化输出解析失败（重试后仍失败）。"""


async def run_agent_with_retry(
    gateway: ModelGateway,
    agent_name: str,
    messages: list[dict],
    runtime: RuntimeConfig | None,
    parse_fn,
):
    """调用 LLM 并解析；LLM 失败或解析失败均重试一次，仍失败抛出最后一次异常。"""
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            content = await gateway.chat(agent_name, messages, runtime)
            return parse_fn(content)
        except LLMError as e:
            last_exc = e
        except AgentOutputError as e:
            last_exc = e
    assert last_exc is not None
    raise last_exc


def parse_json_object(text: str) -> dict:
    """从模型输出中解析 JSON 对象；支持 ```json 围栏与正文截取兜底。"""
    candidate = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise AgentOutputError(f"无法从输出中解析 JSON：{text[:200]!r}")


def require_keys(obj: dict, keys: list[str], agent_name: str) -> None:
    """校验解析结果包含必要键。"""
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AgentOutputError(f"Agent '{agent_name}' 输出缺少字段：{missing}")
