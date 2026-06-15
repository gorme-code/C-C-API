"""Endpoints 8 & 9 — waiver cases.

GET   /api/waivers       — list waiver cases for the district
PATCH /api/waivers/{id}  — update / submit a waiver case
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.errors import DistrictScopeViolation, NotFound, ValidationError
from app.models.waiver_models import (
    Waiver,
    WaiverAction,
    WaiverUpdateRequest,
    WaiverUpdateResponse,
    WaiversListResponse,
)
from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/waivers", tags=["waivers"])

WAIVER_RT = "Closure_Waiver_Request"


@router.get("", response_model=WaiversListResponse)
def list_waivers(
    user: CurrentUser = Depends(get_current_user),
) -> WaiversListResponse:
    """List all waiver cases for the authenticated user's district."""
    records = sf.query(
        "SELECT Id, CaseNumber, Waiver_Status__c, Tier__c, "
        "Total_Missed_Days__c, Days_Made_Up__c, Days_Requested_For_Waiver__c, "
        "CreatedDate, Closure_Events_Count__c FROM Case "
        f"WHERE RecordType.DeveloperName = '{WAIVER_RT}' "
        f"AND Waiver_District__c = '{user.account_id}' "
        "ORDER BY CreatedDate DESC"
    )
    waivers = [
        Waiver(
            id=r["Id"],
            case_number=r["CaseNumber"],
            status=r.get("Waiver_Status__c"),
            tier=r.get("Tier__c"),
            total_missed_days=r.get("Total_Missed_Days__c"),
            days_made_up=r.get("Days_Made_Up__c"),
            days_requested_for_waiver=r.get("Days_Requested_For_Waiver__c"),
            created_date=r.get("CreatedDate"),
            closure_events_count=int(r["Closure_Events_Count__c"])
            if r.get("Closure_Events_Count__c") is not None
            else None,
        )
        for r in records
    ]
    return WaiversListResponse(waivers=waivers)


@router.patch("/{waiver_id}", response_model=WaiverUpdateResponse)
def update_waiver(
    waiver_id: str,
    body: WaiverUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> WaiverUpdateResponse:
    """Update a waiver case; submit routes it via SF Flow by tier."""
    record = sf.query_one(
        "SELECT Id, Waiver_District__c, Tier__c, Waiver_Status__c "
        f"FROM Case WHERE Id = '{waiver_id}' "
        f"AND RecordType.DeveloperName = '{WAIVER_RT}' LIMIT 1"
    )
    if not record:
        raise NotFound("Waiver case not found.")
    if record.get("Waiver_District__c") != user.account_id:
        raise DistrictScopeViolation("You do not have access to this waiver.")

    tier = record.get("Tier__c")

    # Tier 3+ requires superintendent certification before submit.
    if body.action == WaiverAction.submit and _is_tier_3_plus(tier):
        if not body.superintendent_certification:
            raise ValidationError(
                "Superintendent certification is required to submit a Tier 3+ waiver."
            )

    fields: dict[str, object] = {}
    if body.justification is not None:
        fields["Justification__c"] = body.justification
    if body.board_minutes_attached is not None:
        fields["Board_Minutes_Attached__c"] = body.board_minutes_attached
    if body.superintendent_certification is not None:
        fields["Superintendent_Certification__c"] = body.superintendent_certification

    new_status = record.get("Waiver_Status__c") or "Draft"
    routing = None
    if body.action == WaiverAction.submit:
        fields["Waiver_Status__c"] = "Submitted"
        new_status = "Submitted"
        routing = "Routed to SCDE Closures Compliance queue"

    if fields:
        sf.update("Case", waiver_id, fields)

    return WaiverUpdateResponse(
        success=True,
        waiver_id=waiver_id,
        new_status=new_status,
        tier=tier,
        routing=routing,
    )


def _is_tier_3_plus(tier: str | None) -> bool:
    if not tier:
        return False
    digits = "".join(ch for ch in tier if ch.isdigit())
    return bool(digits) and int(digits) >= 3
