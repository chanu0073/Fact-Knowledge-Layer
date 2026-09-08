"""Centralised API error envelope: ``{"error": {"code", "message", "details"}}``.

All handlers live here so controllers can keep raising HTTPException /
APIError and the shape stays uniform. Generic 500s never leak stack traces or
secrets — the message is static unless explicitly provided.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    """Raised by API layers for expected, typed failures."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


# Map common HTTP statuses to stable machine-readable codes.
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "unavailable",
}


def _error_body(code: str, message: str, details: Any = None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


async def _handler_api_error(request: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details))


async def _handler_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = _STATUS_CODES.get(exc.status_code, "error")
    details = None if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(status_code=exc.status_code, content=_error_body(code, message, details))


async def _handler_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=_error_body("validation_error", "Invalid request", details))


async def _handler_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Deliberately no traceback/args leak; the message is generic.
    print(f"[api-error] {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content=_error_body("internal_error", "An unexpected error occurred"))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, _handler_api_error)
    app.add_exception_handler(StarletteHTTPException, _handler_http)
    app.add_exception_handler(RequestValidationError, _handler_validation)
    app.add_exception_handler(Exception, _handler_unexpected)