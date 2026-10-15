"""One error shape for the whole API: ``{"error": {"code", "message", "details"}}``.

The browser translates ``errors.<code>`` itself; ``message`` is an English
fallback for logs and for codes the UI does not know yet.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("vf.errors")


class AppError(Exception):
    def __init__(self, code: str, status: int = 400, message: str | None = None, /, **details: Any):
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message or code.replace("_", " ")
        self.details = details

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFound(AppError):
    def __init__(self, what: str = "object", **details: Any):
        super().__init__("not_found", 404, f"{what} not found", what=what, **details)


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
               405: "method_not_allowed", 409: "conflict", 413: "too_large", 429: "too_many_requests"}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        fields = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(error_body("validation", "invalid request", {"fields": fields}), status_code=422)

    @app.exception_handler(HTTPException)
    async def _http(_request: Request, exc: HTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(error_body("internal", "internal error"), status_code=500)
