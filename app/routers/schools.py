"""Endpoints 1 & 2 — schools and closure reasons.

GET /api/schools         — schools in the authenticated user's district
GET /api/closure-reasons — active reasons from Closure_Reason__mdt (cached 1h)
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.models.closure_models import (
    ClosureReason,
    ClosureReasonsResponse,
    School,
    SchoolsResponse,
)
from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api", tags=["schools"])

# Per-contact cache for schools (keyed by contact_id — works for dev bypass and
# real Entra auth alike). Schools change very rarely; 10 min TTL is safe.
_SCHOOLS_CACHE: dict[str, dict] = {}
_SCHOOLS_TTL_SECONDS = 600

# Simple in-memory cache for closure reasons (CMDT changes rarely).
_REASONS_CACHE: dict[str, object] = {"data": None, "expires_at": 0.0}
_REASONS_TTL_SECONDS = 3600


# The C-C org has NO SIDN / State-ID field on Account (verified against the
# Salesforce repo). Selecting a nonexistent field errors the whole query, so
# `sidn` is returned as null. If a real field is added, set its API name here
# and it flows straight through to the response.
SCHOOL_SIDN_FIELD: str | None = None


@router.get("/schools", response_model=SchoolsResponse)
def get_schools(user: CurrentUser = Depends(get_current_user)) -> SchoolsResponse:
    """Return School Accounts the user has an active School Contact_Role for."""
    now = time.monotonic()
    cached = _SCHOOLS_CACHE.get(user.contact_id)
    if cached and now < cached["expires_at"]:
        return cached["data"]

    fields = ["Id", "Name"]
    if SCHOOL_SIDN_FIELD:
        fields.append(SCHOOL_SIDN_FIELD)
    records = sf.query(
        f"SELECT {', '.join(fields)} FROM Account "
        "WHERE RecordType.DeveloperName = 'School' "
        "AND Id IN ("
        "    SELECT Account__c FROM Contact_Role__c "
        f"   WHERE Contact__c = '{user.contact_id}' "
        "    AND Type__c = 'School' AND isActive__c = true"
        ") "
        "ORDER BY Name"
    )
    schools = [
        School(
            id=r["Id"],
            name=r["Name"],
            sidn=r.get(SCHOOL_SIDN_FIELD) if SCHOOL_SIDN_FIELD else None,
        )
        for r in records
    ]
    response = SchoolsResponse(schools=schools)
    _SCHOOLS_CACHE[user.contact_id] = {"data": response, "expires_at": now + _SCHOOLS_TTL_SECONDS}
    return response


@router.get("/closure-reasons", response_model=ClosureReasonsResponse)
def get_closure_reasons(
    _: CurrentUser = Depends(get_current_user),
) -> ClosureReasonsResponse:
    """Return active closure reasons from CMDT, cached for 1 hour."""
    now = time.monotonic()
    if _REASONS_CACHE["data"] is not None and now < _REASONS_CACHE["expires_at"]:
        return _REASONS_CACHE["data"]  # type: ignore[return-value]

    records = sf.query(
        "SELECT DeveloperName, MasterLabel, Requires_Makeup_Default__c "
        "FROM Closure_Reason__mdt WHERE Active__c = true"
    )
    reasons = [
        ClosureReason(
            value=r["DeveloperName"],
            label=r["MasterLabel"],
            requires_makeup_default=bool(r.get("Requires_Makeup_Default__c")),
        )
        for r in records
    ]
    response = ClosureReasonsResponse(reasons=reasons)
    _REASONS_CACHE["data"] = response
    _REASONS_CACHE["expires_at"] = now + _REASONS_TTL_SECONDS
    return response
