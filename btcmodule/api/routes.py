"""REST API 路由：/api/invoke、/api/config、/api/logs、/api/health。

统一外层结构 {success, data, error, request_id}，见协议第 1.3 节。
配置 admin_token 后，PUT /api/config、POST /api/config/reset、GET /api/logs
要求 X-Admin-Token 请求头；/api/invoke、GET /api/config 与 /api/health
保持开放（响应不含任何密钥）。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..core.config import ConfigError
from ..core.llm import usage_var
from ..core.result import BTCMError, ErrorInfo, fail, ok
from ..core.task import InvokeRequest, Task

router = APIRouter(prefix="/api")

logger = logging.getLogger("btcmodule")

# invoke 并发上限：防止失误循环或脚本误调用打爆模型账单；
# 满载时立即返回 429，不排队
INVOKE_CONCURRENCY = 4
_invoke_semaphore = asyncio.Semaphore(INVOKE_CONCURRENCY)

# 进程启动时间（/api/health 的 uptime）
_STARTED_AT = time.monotonic()


def _rid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _denied(request: Request) -> JSONResponse | None:
    """admin_token 已设置时校验 X-Admin-Token；未通过返回 401 响应。"""
    cm = request.app.state.config_manager
    token = cm.config.admin_token
    if not token:
        return None
    provided = request.headers.get("x-admin-token", "")
    if secrets.compare_digest(provided, token):
        return None
    return JSONResponse(
        status_code=401,
        content=fail(
            ErrorInfo(
                code="UNAUTHORIZED",
                message="缺少或错误的 X-Admin-Token 请求头",
            ),
            _rid(),
        ).model_dump(),
    )


@router.post("/invoke")
async def invoke(body: InvokeRequest, request: Request) -> JSONResponse:
    engine = request.app.state.engine
    call_logger = request.app.state.logger
    cm = request.app.state.config_manager

    # 开关未提供时回落全局配置默认值
    task = Task.from_request(
        body,
        default_enable_creative=cm.config.enable_creative,
        default_enable_validator=cm.config.enable_validator,
    )

    # 纯验证形态下 candidate 必填
    if not task.enable_creative and task.enable_validator and not task.candidate:
        await call_logger.append(
            {
                "request_id": task.request_id,
                "timestamp": _now(),
                "enable_creative": task.enable_creative,
                "enable_validator": task.enable_validator,
                "verdict": None,
                "iterations_used": None,
                "termination_reason": None,
                "user_query": task.user_query,
                "duration_ms": 0,
                "error": "INVALID_REQUEST",
            }
        )
        resp = fail(
            ErrorInfo(
                code="INVALID_REQUEST",
                message="纯验证形态（enable_creative=false）下 candidate 必填",
            ),
            task.request_id,
        )
        return JSONResponse(status_code=400, content=resp.model_dump())

    if _invoke_semaphore.locked():
        await call_logger.append(
            {
                "request_id": task.request_id,
                "timestamp": _now(),
                "enable_creative": task.enable_creative,
                "enable_validator": task.enable_validator,
                "verdict": None,
                "iterations_used": None,
                "termination_reason": None,
                "user_query": task.user_query,
                "duration_ms": 0,
                "error": "RATE_LIMITED",
            }
        )
        logger.warning(
            "invoke 并发达上限（%d），request_id=%s 被拒",
            INVOKE_CONCURRENCY,
            task.request_id,
        )
        return JSONResponse(
            status_code=429,
            content=fail(
                ErrorInfo(
                    code="RATE_LIMITED",
                    message=f"并发调用已达上限（{INVOKE_CONCURRENCY}），请稍后重试",
                ),
                task.request_id,
            ).model_dump(),
        )

    start = time.monotonic()
    usage_var.set(
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "llm_calls": 0,
            "tool_calls": 0,
        }
    )
    async with _invoke_semaphore:
        try:
            data = await engine.run(task)
        except BTCMError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            await call_logger.append(
                {
                    "request_id": task.request_id,
                    "timestamp": _now(),
                    "enable_creative": task.enable_creative,
                    "enable_validator": task.enable_validator,
                    "verdict": None,
                    "iterations_used": None,
                    "termination_reason": None,
                    "user_query": task.user_query,
                    "duration_ms": duration_ms,
                    "error": e.code,
                }
            )
            logger.warning(
                "invoke 失败 code=%s request_id=%s 耗时=%dms",
                e.code,
                task.request_id,
                duration_ms,
            )
            resp = fail(
                ErrorInfo(code=e.code, message=e.message, details=e.details),
                task.request_id,
            )
            return JSONResponse(
                status_code=e.status_code, content=resp.model_dump()
            )

    usage = usage_var.get()
    if usage and usage.get("llm_calls", 0) > 0:
        data["usage"] = usage

    duration_ms = int((time.monotonic() - start) * 1000)
    await call_logger.append(
        {
            "request_id": task.request_id,
            "timestamp": _now(),
            "enable_creative": task.enable_creative,
            "enable_validator": task.enable_validator,
            "verdict": data.get("verdict"),
            "iterations_used": data.get("iterations_used"),
            "termination_reason": data.get("termination_reason"),
            "user_query": task.user_query,
            "duration_ms": duration_ms,
            "conclusion": data.get("conclusion"),
            "usage": data.get("usage"),
        }
    )
    logger.info(
        "invoke 完成 形态=%s/%s 终止=%s 轮次=%s 耗时=%dms tokens=%s/%s",
        task.enable_creative,
        task.enable_validator,
        data.get("termination_reason"),
        data.get("iterations_used"),
        duration_ms,
        (usage or {}).get("prompt_tokens"),
        (usage or {}).get("completion_tokens"),
    )
    return JSONResponse(content=ok(data, task.request_id).model_dump())


@router.get("/config")
async def get_config(request: Request) -> JSONResponse:
    cm = request.app.state.config_manager
    return JSONResponse(
        content=ok(cm.as_public_dict(), _rid()).model_dump()
    )


@router.put("/config")
async def update_config(request: Request) -> JSONResponse:
    denied = _denied(request)
    if denied is not None:
        return denied
    cm = request.app.state.config_manager
    rid = _rid()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=fail(
                ErrorInfo(
                    code="CONFIG_VALIDATION_ERROR",
                    message="请求体必须为 JSON 对象",
                ),
                rid,
            ).model_dump(),
        )
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=fail(
                ErrorInfo(
                    code="CONFIG_VALIDATION_ERROR",
                    message="请求体必须为 JSON 对象",
                ),
                rid,
            ).model_dump(),
        )
    try:
        cm.update(body)
    except ConfigError as e:
        return JSONResponse(
            status_code=400,
            content=fail(
                ErrorInfo(code="CONFIG_VALIDATION_ERROR", message=str(e)), rid
            ).model_dump(),
        )
    return JSONResponse(content=ok(cm.as_public_dict(), rid).model_dump())


@router.post("/config/reset")
async def reset_config(request: Request) -> JSONResponse:
    """重置配置为内置默认值（前端控制面板"重置为默认"按钮后端入口）。"""
    denied = _denied(request)
    if denied is not None:
        return denied
    cm = request.app.state.config_manager
    rid = _rid()
    try:
        cm.reset()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=fail(
                ErrorInfo(code="INTERNAL_ERROR", message=f"配置重置失败：{e}"),
                rid,
            ).model_dump(),
        )
    return JSONResponse(content=ok(cm.as_public_dict(), rid).model_dump())


@router.get("/logs")
async def get_logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    denied = _denied(request)
    if denied is not None:
        return denied
    call_logger = request.app.state.logger
    total, items = call_logger.list(limit, offset)
    return JSONResponse(
        content=ok({"total": total, "items": items}, _rid()).model_dump()
    )


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """探活端点：宿主 Agent 或运维检查用，恒开放、无敏感信息。"""
    from btcmodule import __version__

    return JSONResponse(
        content=ok(
            {
                "status": "ok",
                "version": __version__,
                "uptime_s": int(time.monotonic() - _STARTED_AT),
            },
            _rid(),
        ).model_dump()
    )
