"""任务对象定义与请求体模型。

请求体结构对应 share/protocol.md 中 POST /api/invoke 的约定：
- 顶层字段含 user_query / candidate / evidence / context_summary /
  enable_creative / enable_validator / config
- config 仅可覆盖运行时参数（max_iterations、timeout、各 Agent 的温度、
  token 上限、单请求超时及专属参数）
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 思考深度三档：light 略想（强制单轮 + 快速提示词），standard 通用（默认），
# deep 深层（充分深思提示词）。映射详见 agents/base.py EFFORT_DIRECTIVES。
EFFORT_LEVELS = ("light", "standard", "deep")

# 输入长度上限：防超大请求体耗尽内存/ token 预算；对正常思考任务足够宽裕
MAX_QUERY_CHARS = 50_000
MAX_SUMMARY_CHARS = 50_000
MAX_EVIDENCE_ITEMS = 32
MAX_EVIDENCE_CHARS = 200_000


class RuntimeAgentConfig(BaseModel):
    """请求内 config.agents.<name> 的运行时覆盖项（全部可选）。

    数值参数仅设下限、不设上限（用户自定义）；temperature 上限 2 为
    OpenAI 兼容 API 的通行约定，超过会被提供商拒绝，故保留。
    """

    num_candidates: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=256)
    timeout: int | None = Field(default=None, ge=1)
    enable_web_search: bool | None = None
    web_sources: list[str] | None = None
    log_intermediate: bool | None = None


class RuntimeConfig(BaseModel):
    """请求内 config 对象。"""

    max_iterations: int | None = Field(default=None, ge=1, le=50)
    timeout: int | None = Field(default=None, ge=1)
    agents: dict[str, RuntimeAgentConfig] = Field(default_factory=dict)


class InvokeRequest(BaseModel):
    """POST /api/invoke 请求体。

    两个启用开关缺省为 None：未提供时由路由层回落到全局配置的默认值
    （协议约定：请求体未提供则使用全局配置的 enable_creative / enable_validator）。
    文本字段设长度上限：防超大请求体耗尽内存与 token 预算。
    """

    request_id: str | None = Field(default=None, max_length=64)
    user_query: str = Field(..., min_length=1, max_length=MAX_QUERY_CHARS)
    candidate: str | None = Field(default=None, max_length=MAX_QUERY_CHARS)
    evidence: list[str] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ITEMS
    )
    context_summary: str | None = Field(
        default=None, max_length=MAX_SUMMARY_CHARS
    )
    enable_creative: bool | None = None
    enable_validator: bool | None = None
    effort: Literal["light", "standard", "deep"] | None = None
    config: RuntimeConfig | None = None

    @field_validator("evidence")
    @classmethod
    def _check_evidence_size(cls, v: list[str]) -> list[str]:
        total = sum(len(item) for item in v)
        if total > MAX_EVIDENCE_CHARS:
            raise ValueError(
                f"evidence 总字符数超上限（{total} > {MAX_EVIDENCE_CHARS}）"
            )
        return v


class Task(BaseModel):
    """一次调用内部使用的任务对象，由请求体解析得到。"""

    request_id: str
    user_query: str
    candidate: str | None
    evidence: list[str]
    context_summary: str | None
    enable_creative: bool
    enable_validator: bool
    effort: str | None = None
    runtime_config: RuntimeConfig | None = None

    @classmethod
    def from_request(
        cls,
        req: InvokeRequest,
        default_enable_creative: bool = True,
        default_enable_validator: bool = True,
    ) -> "Task":
        """解析请求体；开关未提供时使用传入的全局默认值（默认 true）。"""
        return cls(
            request_id=req.request_id or str(uuid.uuid4()),
            user_query=req.user_query,
            candidate=req.candidate,
            evidence=list(req.evidence),
            context_summary=req.context_summary,
            enable_creative=(
                default_enable_creative
                if req.enable_creative is None
                else req.enable_creative
            ),
            enable_validator=(
                default_enable_validator
                if req.enable_validator is None
                else req.enable_validator
            ),
            effort=req.effort,
            runtime_config=req.config,
        )
