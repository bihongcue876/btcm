"""任务对象定义与请求体模型。

请求体结构对应 share/protocol.md v0.9 中 POST /api/invoke 的约定：
- 顶层字段含 user_query / candidate / evidence / context_summary /
  enable_creative / enable_validator / config
- config 仅可覆盖运行时参数（max_iterations、timeout、各 Agent 的温度、
  token 上限、单请求超时及专属参数）
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class RuntimeAgentConfig(BaseModel):
    """请求内 config.agents.<name> 的运行时覆盖项（全部可选）。"""

    num_candidates: int | None = Field(default=None, ge=1, le=10)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=256, le=32768)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    enable_web_search: bool | None = None
    web_sources: list[str] | None = None
    log_intermediate: bool | None = None


class RuntimeConfig(BaseModel):
    """请求内 config 对象。"""

    max_iterations: int | None = Field(default=None, ge=1, le=10)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    agents: dict[str, RuntimeAgentConfig] = Field(default_factory=dict)


class InvokeRequest(BaseModel):
    """POST /api/invoke 请求体。

    两个启用开关缺省为 None：未提供时由路由层回落到全局配置的默认值
    （协议 v0.9：请求体未提供则使用全局配置的 enable_creative / enable_validator）。
    """

    request_id: str | None = None
    user_query: str = Field(..., min_length=1)
    candidate: str | None = None
    evidence: list[str] = Field(default_factory=list)
    context_summary: str | None = None
    enable_creative: bool | None = None
    enable_validator: bool | None = None
    config: RuntimeConfig | None = None


class Task(BaseModel):
    """一次调用内部使用的任务对象，由请求体解析得到。"""

    request_id: str
    user_query: str
    candidate: str | None
    evidence: list[str]
    context_summary: str | None
    enable_creative: bool
    enable_validator: bool
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
            runtime_config=req.config,
        )
