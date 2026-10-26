from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: Mapping[str, str] | None = None
    ) -> None:
        self.status, self.code, self.message, self.headers = status, code, message, headers
        super().__init__(message)


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "error": {"code": code, "message": message, "details": details or []},
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            request,
            exc.status_code,
            f"http_{exc.status_code}",
            str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep raw input, arbitrary messages and validator context out of responses.
        # Only these fixed, application-owned contest messages are safe to expose.
        contest_messages = {
            "contest_entry_order": ("entry_closes_at", "Entry opens must be before entry closes."),
            "contest_lock_order": ("starts_at", "Entry closes must be before the contest starts."),
            "contest_end_order": ("ends_at", "Contest ends must be after the contest starts."),
            "contest_holdings_order": (
                "max_holdings",
                "Maximum holdings must be at least minimum holdings.",
            ),
            "contest_eligible_duplicates": (
                "eligible_instrument_ids",
                "Choose each eligible stock only once.",
            ),
            "contest_eligible_count": (
                "eligible_instrument_ids",
                "Select at least as many eligible stocks as minimum holdings.",
            ),
        }
        details = []
        for error in exc.errors():
            detail = {"location": list(error["loc"]), "type": error["type"]}
            if error["type"] in contest_messages:
                field, message = contest_messages[error["type"]]
                detail["location"] = [*error["loc"], field]
                detail["message"] = message
            details.append(detail)
        message = next((d["message"] for d in details if "message" in d), "Invalid request")
        return error_response(request, 422, "validation_error", message, details)
