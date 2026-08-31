"""测试共享夹具：可编程的模型网关 mock 与临时配置/引擎。

FakeChat 支持：
- default_outputs：按 agent_name 返回固定输出
- sequences：按 agent_name 提供依次弹出的输出序列，耗尽后回落默认输出
- delay：模拟慢模型，用于超时路径测试
- calls：记录每次调用的 (agent_name, messages)
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from btcmodule.core.config import ConfigManager
from btcmodule.core.llm import LLMError, ModelGateway
from btcmodule.core.loop import Engine

CREATIVE_OUTPUT = (
    '{"candidates": ["候选方案A（理由）", "候选方案B（理由）"], '
    '"conclusion": "综合推荐说明"}'
)
VALIDATOR_OUTPUT = (
    '{"verdict": "conditional_pass", "best_candidate": "候选方案A", '
    '"issues": ["问题1"], "suggestions": ["建议1"], "next_actions": ["行动1"]}'
)
CONTROLLER_OUTPUT = (
    '{"conclusion": "整合结论", "remaining_issues": [], '
    '"next_direction": "方向", "decision": "continue"}'
)
CONTROLLER_STOP_OUTPUT = (
    '{"conclusion": "结论已可用", "remaining_issues": [], '
    '"next_direction": "", "decision": "stop"}'
)

DEFAULT_OUTPUTS = {
    "creative": CREATIVE_OUTPUT,
    "validator": VALIDATOR_OUTPUT,
    "controller": CONTROLLER_OUTPUT,
}


class FakeChat:
    def __init__(
        self,
        default_outputs: dict | None = None,
        sequences: dict | None = None,
        delay: float = 0.0,
        raise_llm_error: set[str] | None = None,
        finalize_raises: bool = False,
    ) -> None:
        self.default_outputs = default_outputs or {}
        self.sequences = {k: list(v) for k, v in (sequences or {}).items()}
        self.delay = delay
        self.raise_llm_error = set(raise_llm_error or ())
        self.finalize_raises = finalize_raises
        self.calls: list[tuple[str, list[dict]]] = []

    async def __call__(self, agent_name, messages, runtime=None) -> str:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append((agent_name, messages))

        if agent_name in self.raise_llm_error:
            raise LLMError("llm_error", f"{agent_name} 模拟请求失败")

        if self.sequences.get(agent_name):
            return self.sequences[agent_name].pop(0)

        # 长链持续思考：finalize 优先判断
        sys_content = messages[0]["content"]
        if "整合为一份最终结论" in sys_content:
            if self.finalize_raises:
                raise LLMError("llm_error", "finalize 模拟请求失败")
            return '{"conclusion": "最终结论"}'
        if "长链持续思考" in sys_content:
            return '{"thought": "本轮思考要点"}'

        if agent_name in self.default_outputs:
            return self.default_outputs[agent_name]
        raise AssertionError(f"FakeChat 未配置 Agent '{agent_name}' 的输出")


class TestHarness:
    """临时配置目录 + 真实 Engine（模型网关替换为 FakeChat）。"""

    def __init__(
        self,
        default_outputs: dict | None = None,
        sequences: dict | None = None,
        delay: float = 0.0,
        raise_llm_error: set[str] | None = None,
        finalize_raises: bool = False,
    ) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.cm = ConfigManager(path=root / "btcm.json")
        self.fake = FakeChat(
            default_outputs=default_outputs or DEFAULT_OUTPUTS,
            sequences=sequences,
            delay=delay,
            raise_llm_error=raise_llm_error,
            finalize_raises=finalize_raises,
        )
        self.gateway = ModelGateway(self.cm)
        self._patcher = patch.object(ModelGateway, "chat", self.fake)
        self._patcher.start()
        self.engine = Engine(self.cm, self.gateway)

    def close(self) -> None:
        self._patcher.stop()
        self._tmp.cleanup()


def make_task(user_query="测试任务", **kwargs):
    """构造 Task 对象的快捷方法。"""
    from btcmodule.core.task import RuntimeConfig, Task

    fields = {
        "request_id": "test-request",
        "user_query": user_query,
        "candidate": None,
        "evidence": [],
        "context_summary": None,
        "enable_creative": True,
        "enable_validator": True,
        "runtime_config": None,
    }
    fields.update(kwargs)
    if "runtime_config" in fields and isinstance(fields["runtime_config"], dict):
        fields["runtime_config"] = RuntimeConfig.model_validate(
            fields["runtime_config"]
        )
    return Task(**fields)
