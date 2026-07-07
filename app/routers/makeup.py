"""Endpoint 7 — POST /api/makeup.

Creates a Makeup_Day__c and links it to closure events via
Closure_Makeup_Link__c junction records. One makeup day can cover several
closure events.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.errors import DistrictScopeViolation, ValidationError
from app.models.makeup_models import (
    ClosureEventStatusUpdate,
    MakeupCreateRequest,
    MakeupCreateResponse,
)
from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/makeup", tags=["makeup"])


@router.post("", response_model=MakeupCreateResponse)
def create_makeup(
    body: MakeupCreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> MakeupCreateResponse:
    """Create a makeup day and junction links to the given closure events."""
    if not body.closure_event_ids:
        raise ValidationError("closure_event_ids must not be empty.")

    # Enforce all closure events belong to the user's district.
    id_list = ", ".join(f"'{cid}'" for cid in body.closure_event_ids)
    events = sf.query(
        "SELECT Id, District__c FROM Closure_Event__c "
        f"WHERE Id IN ({id_list})"
    )
    found_ids = {e["Id"] for e in events}
    missing = set(body.closure_event_ids) - found_ids
    if missing:
        raise ValidationError(f"Unknown closure_event_ids: {', '.join(missing)}")
    if any(e.get("District__c") != user.account_id for e in events):
        raise DistrictScopeViolation(
            "One or more closure events belong to another district."
        )

    # Idempotency on external_id.
    safe_ext = body.external_id.replace("'", r"\'")
    existing = sf.query_one(
        "SELECT Id FROM Makeup_Day__c "
        f"WHERE External_Id__c = '{safe_ext}' LIMIT 1"
    )
    if existing:
        makeup_id = existing["Id"]
    else:
        # Hours_Covered__c lives on the junction, NOT on Makeup_Day__c.
        result = sf.create(
            "Makeup_Day__c",
            {
                "Makeup_Date__c": body.makeup_date.isoformat(),
                "Method__c": body.method,
                "Status__c": "Proposed",
                "External_Id__c": body.external_id,
            },
        )
        makeup_id = result["id"]

    links_created = 0
    for cid in body.closure_event_ids:
        sf.create(
            "Closure_Makeup_Link__c",
            {
                "Makeup_Day__c": makeup_id,
                "Closure_Event__c": cid,
                "Hours_Covered__c": body.hours_covered,
            },
        )
        sf.update("Closure_Event__c", cid, {"Status__c": "Make_Up_Pending"})
        links_created += 1

    updated = [
        ClosureEventStatusUpdate(id=cid, new_status="Make_Up_Pending")
        for cid in body.closure_event_ids
    ]
    return MakeupCreateResponse(
        makeup_day_id=makeup_id,
        links_created=links_created,
        closure_events_updated=updated,
    )
