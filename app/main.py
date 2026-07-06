"""FastAPI app entry point — CORS, router registration, error handling.

Run locally:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import (
    APIError,
    api_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.routers import closures, district, makeup, me, schools, waivers

app = FastAPI(
    title="Calendars & Closures API",
    description="Python API layer between the Member Center React app and Salesforce.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standard error shape for the frontend — covers app errors, request-body
# validation, and any unexpected exception.
app.add_exception_handler(APIError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Endpoint groups.
app.include_router(schools.router)
app.include_router(closures.router)
app.include_router(makeup.router)
app.include_router(waivers.router)
app.include_router(district.router)
app.include_router(me.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "env": settings.api_env}
