"""结果对象定义与统一响应外层结构。

统一外层结构 {success, data, error, request_id}，对应协议第 1.3 节。
data 按运行形态分化，由主循环组装，此处以 dict 承载。
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ApiResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: ErrorInfo | None = None
    request_id: str


class BTCMError(Exception):
    """业务异常：携带错误码与 HTTP 状态码，由 API 层统一转成错误响应。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code


def ok(data: dict, request_id: str) -> ApiResponse:
    return ApiResponse(success=True, data=data, error=None, request_id=request_id)


def fail(error: ErrorInfo, request_id: str) -> ApiResponse:
    return ApiResponse(success=False, data=None, error=error, request_id=request_id)
