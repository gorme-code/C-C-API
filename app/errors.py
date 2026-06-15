"""Consistent error shape for the React frontend.

Every error returned by the API follows section 6 of the API guide:
    { "error": "CODE", "message": "...", "status_code": 4xx }

This module defines the error classes AND the handlers that guarantee the
shape — including FastAPI/Pydantic request-validation errors and any
unexpected exception, so the frontend never sees a non-standard payload.
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")


class APIError(Exception):
    """Base application error mapped to the standard error shape.

    `message` is client-safe and returned in the response. `detail` is
    server-only (logged, never sent) — use it for sensitive/internal text.
    """

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, detail: str | None = None):
        if message is not None:
            self.message = message
        self.detail = detail
        # str(exc) shows detail when present so logs/scripts see the full story.
        super().__init__(self.detail or self.message)


class Unauthorized(APIError):
    code = "UNAUTHORIZED"
    status_code = 401
    message = "Missing or invalid Entra token."


class ContactNotFound(APIError):
    code = "CONTACT_NOT_FOUND"
    status_code = 403
    message = "Entra user has no matching Salesforce Contact."


class DistrictScopeViolation(APIError):
    code = "DISTRICT_SCOPE_VIOLATION"
    status_code = 403
    message = "You do not have access to this resource."


class ValidationError(APIError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "Request body failed validation."


class DuplicateSubmission(APIError):
    # Intentionally NOT raised. Per API guide Endpoint 3, a repeated External_Id
    # returns the existing Case (HTTP 200) for safe idempotent retries rather
    # than a 409. Kept defined for completeness / future opt-in.
    code = "DUPLICATE_SUBMISSION"
    status_code = 409
    message = "External_Id already exists."


class SalesforceError(APIError):
    code = "SALESFORCE_ERROR"
    status_code = 502
    # Client always gets this safe message; the raw SF error goes to `detail`.
    message = "Salesforce returned an error. Please try again."

    def __init__(self, detail: str | None = None):
        super().__init__(detail=detail)


class NotFound(APIError):
    code = "NOT_FOUND"
    status_code = 404
    message = "Resource not found."


def _payload(code: str, message: str, status_code: int) -> dict:
    return {"error": code, "message": message, "status_code": status_code}


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    # Log server-side for 5xx or whenever we carried internal detail.
    if exc.status_code >= 500 or exc.detail:
        logger.error("%s (%s): %s", exc.code, exc.status_code, exc.detail or exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content=_payload(exc.code, exc.message, exc.status_code),
    )


async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map FastAPI/Pydantic body-validation errors to VALIDATION_ERROR."""
    message = "Request body failed validation."
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        detail = first.get("msg", message)
        message = f"{loc}: {detail}" if loc else detail
    return JSONResponse(status_code=422, content=_payload("VALIDATION_ERROR", message, 422))


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler so even unexpected errors keep the standard shape."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content=_payload("INTERNAL_ERROR", "An unexpected error occurred.", 500),
    )
