"""Formato único de errores HTTP de la API."""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    doc_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_response(
    status_code: int, code: str, message: str, doc_id: str | None = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, doc_id=doc_id))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True), headers=headers)


class ApiError(Exception):
    """Error que se convierte en ``{"error": {...}}`` con su código HTTP."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)
