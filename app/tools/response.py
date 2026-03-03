"""
统一 /tools/* 响应格式：
  成功: {"success": true,  "data": {...},           "request_id": "<uuid>"}
  失败: {"success": false, "error": {"code": "...", "message": "...", "details": {...}}, "request_id": "<uuid>"}

错误码：VALIDATION_ERROR / STATE_ERROR / NOT_FOUND / PERMISSION_ERROR / INTERNAL_ERROR
"""
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# HTTP 状态码 → 错误码映射
_HTTP_CODE_MAP = {
    400: "VALIDATION_ERROR",
    401: "PERMISSION_ERROR",
    403: "PERMISSION_ERROR",
    404: "NOT_FOUND",
    409: "STATE_ERROR",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
}


def _request_id() -> str:
    return str(uuid.uuid4())


def ok(data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "request_id": _request_id(),
        },
    )


def fail(
    code: str,
    message: str,
    details: Any = None,
    status_code: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "request_id": _request_id(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return fail(
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            details=exc.errors(),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
        return fail(
            code=code,
            message=str(exc.detail),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return fail(
            code="INTERNAL_ERROR",
            message="服务器内部错误",
            details={"type": type(exc).__name__},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
