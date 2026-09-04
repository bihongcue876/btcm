"""BTCM 后端入口：FastAPI 应用，挂载 API 路由与静态面板。

运行（在 btcmodule 目录下）：
    uv run python -m uvicorn main:app --port 8000
或（任意位置）：
    uv run --project btcmodule python -m uvicorn btcmodule.main:app --port 8000

采用绝对导入，使 main 既可作为包模块（btcmodule.main）也可作为
顶层入口（main）被 uvicorn 加载。
"""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
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

logger = logging.getLogger("btcmodule.main")

# duckduckgo 预设的本地 MCP 子进程参数：
# uvx 拉起 duckduckgo-mcp-server（含 browser extra，curl_cffi 用于
# Chrome TLS 伪装以绕过 DuckDuckGo 的指纹拦截），streamable-http 传输
DDG_MCP_ARGS = [
    "--from",
    "duckduckgo-mcp-server[browser]",
    "duckduckgo-mcp-server",
    "--transport",
    "streamable-http",
    "--host",
    "127.0.0.1",
    "--port",
    "7070",
]

# 端口就绪探测：uvx 首次运行需解析并拉取包，给足等待时间
DDG_READY_TIMEOUT_S = 60


def _spawn_ddg_sync() -> subprocess.Popen | None:
    """在工作线程中同步拉起 duckduckgo MCP 并等待端口就绪。

    不用 asyncio.create_subprocess_exec：uvicorn --reload 在 Windows 上
    使用 SelectorEventLoop，该循环不支持异步子进程（NotImplementedError）。
    同步 Popen + socket 探活与事件循环类型无关。
    """
    try:
        proc = subprocess.Popen(
            ["uvx", *DDG_MCP_ARGS],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        logger.warning("无法拉起 duckduckgo MCP 子进程（%s），检索验证将降级纯逻辑", e)
        return None
    deadline = time.monotonic() + DDG_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            logger.warning(
                "duckduckgo MCP 子进程提前退出（code=%s），检索验证将降级纯逻辑",
                proc.returncode,
            )
            return None
        try:
            with socket.create_connection(("127.0.0.1", 7070), timeout=1):
                pass
            logger.info("duckduckgo MCP 本地服务已就绪（127.0.0.1:7070）")
            return proc
        except OSError:
            time.sleep(1)
    logger.warning("duckduckgo MCP 本地服务启动超时，检索验证将降级纯逻辑")
    _kill_tree(proc)
    return None


def _kill_tree(proc: subprocess.Popen) -> None:
    """按进程树终止（Windows 下杀父进程不杀子进程，须 taskkill /T）。"""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


class DdgMcpSupervisor:
    """duckduckgo 本地 MCP 子进程的运行时管理：启停跟随配置变更。

    lifespan 启动时拉起；运行中 PUT /api/config 启用/停用预设条目时，
    经 ConfigManager 变更回调动态拉起/终止，无需重启进程。
    回调在配置锁内同步执行，故启停动作全部甩到后台线程。
    """

    def __init__(self, cm: ConfigManager) -> None:
        self._cm = cm
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        cm.add_change_listener(self._on_config_change)

    def _enabled(self) -> bool:
        return any(
            srv.enabled and srv.preset == "duckduckgo"
            for srv in self._cm.config.mcp_servers.values()
        )

    def _running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _on_config_change(self) -> None:
        """配置变更回调：后台线程执行启停，不阻塞配置更新。"""
        want, have = self._enabled(), self._running()
        if want and not have:
            threading.Thread(target=self.start, daemon=True).start()
        elif not want and have:
            threading.Thread(target=self.stop, daemon=True).start()

    def start(self) -> None:
        """确保子进程在运行（已运行则跳过）。"""
        with self._lock:
            if self._running():
                return
            proc = _spawn_ddg_sync()
            if proc is not None:
                self._proc = proc

    def stop(self) -> None:
        """终止子进程（幂等）。"""
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None:
            _kill_tree(proc)

    def startup(self) -> None:
        """进程启动时的初始拉起（配置启用时）。"""
        if self._enabled():
            self.start()

    def shutdown(self) -> None:
        """进程退出时的清理。"""
        self.stop()


@asynccontextmanager
async def _lifespan(cm: ConfigManager):
    supervisor = DdgMcpSupervisor(cm)
    await asyncio.to_thread(supervisor.startup)
    try:
        yield
    finally:
        await asyncio.to_thread(supervisor.shutdown)


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
        lifespan=lambda _app: _lifespan(cm),
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
