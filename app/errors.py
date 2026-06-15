"""Consistent error shape for the React frontend.

Every error returned by the API follows:
    { "error": "CODE", "message": "...", "status_code": 4xx }
See section 6 of the API guide.
"""
from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Base application error mapped to the standard error shape."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None):
        if message is not None:
            self.message = message
        super().__init__(self.message)


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
    code = "DUPLICATE_SUBMISSION"
    status_code = 409
    message = "External_Id already exists."


class SalesforceError(APIError):
    code = "SALESFORCE_ERROR"
    status_code = 502
    message = "Salesforce returned an error."


class NotFound(APIError):
    code = "NOT_FOUND"
    status_code = 404
    message = "Resource not found."


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.code,
            "message": exc.message,
            "status_code": exc.status_code,
        },
    )
