"""REST API 路由：/api/invoke、/api/config、/api/logs。

统一外层结构 {success, data, error, request_id}，见协议第 1.3 节。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..core.config import ConfigError
from ..core.result import BTCMError, ErrorInfo, fail, ok
from ..core.task import InvokeRequest, Task

router = APIRouter(prefix="/api")


def _rid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/invoke")
async def invoke(body: InvokeRequest, request: Request) -> JSONResponse:
    engine = request.app.state.engine
    logger = request.app.state.logger
    cm = request.app.state.config_manager

    # 开关未提供时回落全局配置默认值（协议 v0.9）
    task = Task.from_request(
        body,
        default_enable_creative=cm.config.enable_creative,
        default_enable_validator=cm.config.enable_validator,
    )

    # 纯验证形态下 candidate 必填（协议 2.1.1）
    if not task.enable_creative and task.enable_validator and not task.candidate:
        logger.append(
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

    start = time.monotonic()
    try:
        data = await engine.run(task)
    except BTCMError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.append(
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
        resp = fail(
            ErrorInfo(code=e.code, message=e.message, details=e.details),
            task.request_id,
        )
        return JSONResponse(status_code=e.status_code, content=resp.model_dump())

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.append(
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
        }
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


@router.get("/logs")
async def get_logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    logger = request.app.state.logger
    total, items = logger.list(limit, offset)
    return JSONResponse(
        content=ok({"total": total, "items": items}, _rid()).model_dump()
    )
