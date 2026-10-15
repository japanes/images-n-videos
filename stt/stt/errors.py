"""Service errors and their HTTP mapping.

Every error response has the shape ``{"error": {"code": ..., "message": ...}}``.
"""

from __future__ import annotations

HTTP_STATUS: dict[str, int] = {
    "bad_request": 400,
    "not_found": 404,
    "model_not_found": 404,
    "busy": 409,
    "no_audio": 422,
    "download_failed": 502,
    "transcribe_failed": 500,
    "internal_error": 500,
}


class ServiceError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        if code not in HTTP_STATUS:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status(self) -> int:
        return HTTP_STATUS[self.code]

    def to_body(self) -> dict:
        return error_body(self.code, self.message)


class Cancelled(Exception):
    """The caller went away; the work was stopped on purpose."""


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
