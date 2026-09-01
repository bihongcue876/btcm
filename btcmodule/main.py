"""BTCM 后端入口：FastAPI 应用，挂载 API 路由与静态面板。

运行（在 btcmodule 目录下）：
    uv run python -m uvicorn main:app --port 8000
或（任意位置）：
    uv run --project btcmodule python -m uvicorn btcmodule.main:app --port 8000

采用绝对导入，使 main 既可作为包模块（btcmodule.main）也可作为
顶层入口（main）被 uvicorn 加载。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from btcmodule.api.routes import router
from btcmodule.core.config import ConfigManager
from btcmodule.core.llm import ModelGateway
from btcmodule.core.logger import CallLogger
from btcmodule.core.loop import Engine
from btcmodule.core.result import ErrorInfo, fail

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    config_path: str | Path | None = None,
    log_path: str | Path | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    # 结构化运行日志：根 logger 无 handler（直跑 uvicorn 等）时补基础配置；
    # 已有 handler（如测试或外部装配）则不动
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    # 生产环境抬升 httpx/httpcore 日志级别，避免请求 URL（含 MCP 密钥）泄漏
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    static_dir = Path(static_dir) if static_dir else STATIC_DIR
    cm = ConfigManager(path=config_path) if config_path else ConfigManager()
    gateway = ModelGateway(cm)
    engine = Engine(cm, gateway)
    logger = CallLogger(path=log_path) if log_path else CallLogger()

    app = FastAPI(
        title="BTCM",
        description="副思考链模块（Beside-Thinking Chain Module）",
        version="0.0.0",
    )
    app.state.config_manager = cm
    app.state.engine = engine
    app.state.gateway = gateway
    app.state.logger = logger

    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        rid = str(uuid.uuid4())
        resp = fail(
            ErrorInfo(
                code="INVALID_REQUEST",
                message=(
                    f"请求体缺少必要字段或格式错误：{exc.errors()[0]['msg']}"
                    if exc.errors()
                    else "请求体缺少必要字段或格式错误"
                ),
            ),
            rid,
        )
        return JSONResponse(status_code=400, content=resp.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        """兜底：任何未捕获异常都返回统一外层结构，不回泄漏堆栈细节。"""
        rid = str(uuid.uuid4())
        resp = fail(
            ErrorInfo(
                code="INTERNAL_ERROR",
                message=f"服务器内部异常：{type(exc).__name__}: {exc}",
            ),
            rid,
        )
        return JSONResponse(status_code=500, content=resp.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """统一 HTTP 异常响应（含未匹配 404）。

        - Vue history 路由的深链接（如 /config、/logs）：无同名文件且无扩展名时
          回退控制面板 index.html，由前端路由接管（spec 单端口托管约定）
        - 其余 HTTP 异常（含 /api 下的 404）返回统一外层结构
        """
        path = request.url.path
        if exc.status_code == 404 and not path.startswith("/api"):
            index = static_dir / "index.html"
            if index.is_file() and "." not in Path(path).name:
                return FileResponse(index)
        rid = str(uuid.uuid4())
        resp = fail(
            ErrorInfo(
                code="NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
                message=f"{exc.status_code}: {exc.detail}",
            ),
            rid,
        )
        return JSONResponse(status_code=exc.status_code, content=resp.model_dump())

    # 阶段二构建产物存在时，由本体在同一端口托管控制面板
    if (static_dir / "index.html").exists():
        app.mount(
            "/", StaticFiles(directory=static_dir, html=True), name="static"
        )

    return app


app = create_app()
