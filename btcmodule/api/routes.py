"""REST API 路由：/api/invoke、/api/invoke/stream、/api/config、/api/logs、/api/health。

统一外层结构 {success, data, error, request_id}，见协议第 1.3 节。
配置 admin_token 后，PUT /api/config、POST /api/config/reset、GET /api/logs
与 GET /api/providers/{name}/models 要求 X-Admin-Token 请求头；
/api/invoke、GET /api/config 与 /api/health 保持开放（响应不含任何密钥）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config import ConfigError
from ..core.llm import LLMError, stream_sink, usage_var
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
    """admin_token 已设置时校验 X-Admin-Token；未通过返回 401 响应。
    token 优先取环境变量 BTCM_ADMIN_TOKEN，其次配置文件。
    """
    cm = request.app.state.config_manager
    token = os.environ.get("BTCM_ADMIN_TOKEN") or cm.config.admin_token
    if not token:
        return None
    provided = request.headers.get("x-admin-token", "")
    # encode 为 bytes：compare_digest 对 str 要求 ASCII-only，
    # 非 ASCII token 会抛 TypeError 变 500；bytes 比较不受限且时序安全
    if secrets.compare_digest(provided.encode(), token.encode()):
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


async def _precheck(request: Request, task: Task) -> JSONResponse | None:
    """/invoke 与 /invoke/stream 共用的流前校验。

    依次检查：lock_invoke 鉴权、纯验证缺 candidate、并发上限；
    拒绝路径记调用日志并返回对应错误响应，通过返回 None。
    """
    cm = request.app.state.config_manager
    call_logger = request.app.state.logger

    if cm.config.lock_invoke:
        denied = _denied(request)
        if denied is not None:
            return denied

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
        return JSONResponse(
            status_code=400,
            content=fail(
                ErrorInfo(
                    code="INVALID_REQUEST",
                    message="纯验证形态（enable_creative=false）下 candidate 必填",
                ),
                task.request_id,
            ).model_dump(),
        )

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
    return None


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

    rejected = await _precheck(request, task)
    if rejected is not None:
        return rejected

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


STREAM_HEARTBEAT_SECONDS = 15


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/invoke/stream")
async def invoke_stream(body: InvokeRequest, request: Request):
    """SSE 流式调用：与 /invoke 同语义同校验，Agent 增量思考内容经事件流前传。

    事件序列：start → (agent_start / delta / agent_done / iteration_done)* →
    done | error；done/error 的 data 为与 /invoke 响应同构的完整 ApiResponse。
    流开始前的校验失败（鉴权、缺 candidate、限流）直接返回 JSON 错误，
    与 /invoke 行为一致；流开始后的失败经 error 事件返回。
    """
    engine = request.app.state.engine
    call_logger = request.app.state.logger
    cm = request.app.state.config_manager

    task = Task.from_request(
        body,
        default_enable_creative=cm.config.enable_creative,
        default_enable_validator=cm.config.enable_validator,
    )

    rejected = await _precheck(request, task)
    if rejected is not None:
        return rejected

    queue: asyncio.Queue = asyncio.Queue()

    def _sink(event: dict) -> None:
        queue.put_nowait(("event", event))

    # sink 经 ContextVar 进入 create_task 复制的执行上下文，llm 层据此走流式
    stream_sink.set(_sink)

    async def _execute():
        try:
            async with _invoke_semaphore:
                usage_var.set(
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "llm_calls": 0,
                        "tool_calls": 0,
                    }
                )
                data = await engine.run(task)
                usage = usage_var.get()
                if usage and usage.get("llm_calls", 0) > 0:
                    data["usage"] = usage
            queue.put_nowait(("result", data))
        except BTCMError as e:
            queue.put_nowait(("error", e))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            queue.put_nowait(
                (
                    "error",
                    BTCMError(
                        "INTERNAL_ERROR",
                        f"内部错误：{type(e).__name__}: {e}",
                        status_code=500,
                    ),
                )
            )
        finally:
            queue.put_nowait(None)

    agent_task = asyncio.create_task(_execute())

    async def _gen():
        start = time.monotonic()
        result: dict | None = None
        error: BTCMError | None = None
        try:
            yield _sse(
                "start",
                {
                    "request_id": task.request_id,
                    "enable_creative": task.enable_creative,
                    "enable_validator": task.enable_validator,
                },
            )
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=STREAM_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                kind, payload = item
                if kind == "result":
                    result = payload
                elif kind == "error":
                    error = payload
                else:
                    yield _sse(payload["type"], payload)

            duration_ms = int((time.monotonic() - start) * 1000)
            if result is not None:
                await call_logger.append(
                    {
                        "request_id": task.request_id,
                        "timestamp": _now(),
                        "enable_creative": task.enable_creative,
                        "enable_validator": task.enable_validator,
                        "verdict": result.get("verdict"),
                        "iterations_used": result.get("iterations_used"),
                        "termination_reason": result.get("termination_reason"),
                        "user_query": task.user_query,
                        "duration_ms": duration_ms,
                        "conclusion": result.get("conclusion"),
                        "usage": result.get("usage"),
                    }
                )
                logger.info(
                    "invoke/stream 完成 形态=%s/%s 终止=%s 轮次=%s 耗时=%dms",
                    task.enable_creative,
                    task.enable_validator,
                    result.get("termination_reason"),
                    result.get("iterations_used"),
                    duration_ms,
                )
                yield _sse("done", ok(result, task.request_id).model_dump())
            else:
                e = error or BTCMError("INTERNAL_ERROR", "未知错误", status_code=500)
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
                    "invoke/stream 失败 code=%s request_id=%s 耗时=%dms",
                    e.code,
                    task.request_id,
                    duration_ms,
                )
                yield _sse(
                    "error",
                    fail(
                        ErrorInfo(code=e.code, message=e.message, details=e.details),
                        task.request_id,
                    ).model_dump(),
                )
        finally:
            # 客户端断开时掐断仍在执行的调用，避免空耗模型
            if not agent_task.done():
                agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.get("/providers/{name}/models")
async def provider_models(name: str, request: Request) -> JSONResponse:
    """拉取提供商可用模型列表（OpenAI 兼容 GET /models 的代理）。

    供控制面板 BYOK 配置：填充 providers.<name>.models。会触发一次
    对外请求，故与写配置同级保护（admin_token 设置时需 X-Admin-Token）。
    """
    denied = _denied(request)
    if denied is not None:
        return denied
    cm = request.app.state.config_manager
    gateway = request.app.state.gateway
    rid = _rid()
    if name not in cm.config.providers:
        return JSONResponse(
            status_code=404,
            content=fail(
                ErrorInfo(code="NOT_FOUND", message=f"提供商 '{name}' 不存在"),
                rid,
            ).model_dump(),
        )
    try:
        models = await gateway.list_models(name)
    except LLMError as e:
        return JSONResponse(
            status_code=502,
            content=fail(
                ErrorInfo(code="PROVIDER_ERROR", message=e.message), rid
            ).model_dump(),
        )
    logger.info("拉取模型列表 provider=%s 数量=%d", name, len(models))
    return JSONResponse(content=ok({"models": models}, rid).model_dump())


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
