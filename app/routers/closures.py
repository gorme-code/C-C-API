"""Endpoints 3-6 — closure submission, listing, detail, and cancel.

POST   /api/closures            — submit a closure (creates a Case)
GET    /api/closures            — list closure events for the district
GET    /api/closures/{id}       — single closure event detail
POST   /api/closures/{id}/cancel — cancel a closure event
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.errors import DistrictScopeViolation, NotFound, ValidationError
from app.models.closure_models import (
    ClosureCancelRequest,
    ClosureCancelResponse,
    ClosureCreateRequest,
    ClosureCreateResponse,
    ClosureDetailResponse,
    ClosureEvent,
    ClosureScope,
    ClosuresListResponse,
    MakeupDaySummary,
)
from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/closures", tags=["closures"])

CLOSURE_SUBMISSION_RT = "Closure_Submission"


@router.post("", response_model=ClosureCreateResponse)
def create_closure(
    body: ClosureCreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ClosureCreateResponse:
    """Create a Closure_Submission Case; the SF Flow expands it into events.

    District is always taken from the resolved Contact — never the client.
    External_Id__c provides idempotency.
    """
    if body.scope != ClosureScope.district_wide and not body.school_ids:
        raise ValidationError("school_ids is required when scope is not District_Wide.")
    if body.closure_end_date < body.closure_start_date:
        raise ValidationError("closure_end_date cannot be before closure_start_date.")

    # Idempotency: if this external_id was already submitted, return that Case.
    safe_ext = body.external_id.replace("'", r"\'")
    existing = sf.query_one(
        "SELECT Id FROM Case "
        f"WHERE External_Id__c = '{safe_ext}' "
        f"AND RecordType.DeveloperName = '{CLOSURE_SUBMISSION_RT}' LIMIT 1"
    )
    if existing:
        return _build_create_response(existing["Id"], user.account_id)

    payload = {
        "Scope__c": body.scope.value,
        "Closure_Start_Date__c": body.closure_start_date.isoformat(),
        "Closure_End_Date__c": body.closure_end_date.isoformat(),
        "Closure_Type__c": body.closure_type,
        "Closure_Reason__c": body.closure_reason,
        "Hours_Missed__c": body.hours_missed,
        "External_Id__c": body.external_id,
        "Submission_District__c": user.account_id,
        "Reported_By_Contact__c": user.contact_id,
    }
    if body.school_ids:
        payload["School_Ids__c"] = ";".join(body.school_ids)

    result = sf.create("Case", payload)
    return _build_create_response(result["id"], user.account_id)


def _build_create_response(case_id: str, district_id: str) -> ClosureCreateResponse:
    """Assemble the create response from the Case + district YTD totals."""
    events = sf.query(
        "SELECT Id FROM Closure_Event__c "
        f"WHERE Source_Case__c = '{case_id}'"
    )
    account = sf.query_one(
        "SELECT Total_Missed_Days_YTD__c, Current_Tier__c "
        f"FROM Account WHERE Id = '{district_id}' LIMIT 1"
    ) or {}
    waiver = sf.query_one(
        "SELECT Id FROM Case "
        "WHERE RecordType.DeveloperName = 'Closure_Waiver_Request' "
        f"AND Waiver_District__c = '{district_id}' "
        "ORDER BY CreatedDate DESC LIMIT 1"
    )
    return ClosureCreateResponse(
        case_id=case_id,
        events_created=len(events),
        ytd_missed_days=float(account.get("Total_Missed_Days_YTD__c") or 0.0),
        current_tier=account.get("Current_Tier__c"),
        makeup_required=bool(account.get("Total_Missed_Days_YTD__c")),
        waiver_auto_created=waiver is not None,
        waiver_case_id=waiver["Id"] if waiver else None,
    )


@router.get("", response_model=ClosuresListResponse)
def list_closures(
    user: CurrentUser = Depends(get_current_user),
    status: str | None = Query(default=None),
    school_id: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    school_year: str | None = Query(default=None),
) -> ClosuresListResponse:
    """List closure events for the district with optional filters."""
    clauses = [f"District__c = '{user.account_id}'"]
    if status:
        clauses.append(f"Status__c = '{status}'")
    if school_id:
        clauses.append(f"School__c = '{school_id}'")
    if start_date:
        clauses.append(f"Closure_Date__c >= {start_date.isoformat()}")
    if end_date:
        clauses.append(f"Closure_Date__c <= {end_date.isoformat()}")
    if school_year:
        clauses.append(f"School_Year__c = '{school_year}'")
    where = " AND ".join(clauses)

    records = sf.query(
        "SELECT Id, Name, School__c, School__r.Name, Closure_Date__c, "
        "Closure_Type__c, Closure_Reason__c, Hours_Missed__c, Status__c, "
        "Make_Up_Required__c, Make_Up_Method__c, School_Year__c "
        f"FROM Closure_Event__c WHERE {where} ORDER BY Closure_Date__c"
    )

    closures = [_to_closure_event(r) for r in records]
    ytd: dict[str, float] = {}
    for r in records:
        sid = r.get("School__c")
        if sid:
            ytd[sid] = ytd.get(sid, 0.0) + float(r.get("Hours_Missed__c") or 0.0)

    return ClosuresListResponse(
        closures=closures,
        total=len(closures),
        ytd_missed_days_by_school=ytd,
    )


def _to_closure_event(r: dict) -> ClosureEvent:
    school = r.get("School__r") or {}
    return ClosureEvent(
        id=r["Id"],
        name=r.get("Name"),
        school_id=r.get("School__c"),
        school_name=school.get("Name") if isinstance(school, dict) else None,
        closure_date=r["Closure_Date__c"],
        closure_type=r.get("Closure_Type__c"),
        closure_reason=r.get("Closure_Reason__c"),
        hours_missed=r.get("Hours_Missed__c"),
        status=r.get("Status__c"),
        make_up_required=r.get("Make_Up_Required__c"),
        make_up_method=r.get("Make_Up_Method__c"),
        school_year=r.get("School_Year__c"),
    )


@router.get("/{closure_id}", response_model=ClosureDetailResponse)
def get_closure(
    closure_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> ClosureDetailResponse:
    """Return full detail for one closure event, with makeup days + waiver."""
    record = sf.query_one(
        "SELECT Id, Name, District__c, School__r.Name, Closure_Date__c, "
        "Closure_Type__c, Closure_Reason__c, Hours_Missed__c, Status__c, "
        "Make_Up_Required__c, Source_Case__c, Reported_By__r.Name, "
        "Reported_Date__c, "
        "(SELECT Makeup_Day__r.Id, Makeup_Day__r.Makeup_Date__c, "
        "Makeup_Day__r.Method__c, Makeup_Day__r.Status__c "
        "FROM Closure_Makeup_Links__r), "
        "(SELECT Case__c FROM Waiver_Closure_Links__r) "
        f"FROM Closure_Event__c WHERE Id = '{closure_id}' LIMIT 1"
    )
    if not record:
        raise NotFound("Closure event not found.")
    if record.get("District__c") != user.account_id:
        raise DistrictScopeViolation("You do not have access to this closure event.")

    makeup_days = []
    links = (record.get("Closure_Makeup_Links__r") or {}).get("records", []) \
        if isinstance(record.get("Closure_Makeup_Links__r"), dict) else []
    for link in links:
        md = link.get("Makeup_Day__r") or {}
        if md:
            makeup_days.append(
                MakeupDaySummary(
                    id=md["Id"],
                    makeup_date=md["Makeup_Date__c"],
                    method=md.get("Method__c"),
                    status=md.get("Status__c"),
                )
            )

    waiver_case_id = None
    wlinks = (record.get("Waiver_Closure_Links__r") or {}).get("records", []) \
        if isinstance(record.get("Waiver_Closure_Links__r"), dict) else []
    if wlinks:
        waiver_case_id = wlinks[0].get("Case__c")

    school = record.get("School__r") or {}
    reporter = record.get("Reported_By__r") or {}
    return ClosureDetailResponse(
        id=record["Id"],
        name=record.get("Name"),
        school_name=school.get("Name") if isinstance(school, dict) else None,
        closure_date=record["Closure_Date__c"],
        closure_type=record.get("Closure_Type__c"),
        closure_reason=record.get("Closure_Reason__c"),
        hours_missed=record.get("Hours_Missed__c"),
        status=record.get("Status__c"),
        make_up_required=record.get("Make_Up_Required__c"),
        source_case_id=record.get("Source_Case__c"),
        reported_by=reporter.get("Name") if isinstance(reporter, dict) else None,
        reported_date=record.get("Reported_Date__c"),
        makeup_days=makeup_days,
        waiver_case_id=waiver_case_id,
    )


@router.post("/{closure_id}/cancel", response_model=ClosureCancelResponse)
def cancel_closure(
    closure_id: str,
    body: ClosureCancelRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ClosureCancelResponse:
    """Cancel a closure event (set Status=Cancelled) + create amendment Case."""
    record = sf.query_one(
        "SELECT Id, District__c, Status__c "
        f"FROM Closure_Event__c WHERE Id = '{closure_id}' LIMIT 1"
    )
    if not record:
        raise NotFound("Closure event not found.")
    if record.get("District__c") != user.account_id:
        raise DistrictScopeViolation("You do not have access to this closure event.")
    if record.get("Status__c") in ("Cancelled", "Closed"):
        raise ValidationError("Closure event is already Cancelled or Closed.")

    sf.update("Closure_Event__c", closure_id, {"Status__c": "Cancelled"})

    amendment = sf.create(
        "Case",
        {
            "RecordType.DeveloperName": CLOSURE_SUBMISSION_RT,
            "Submission_District__c": user.account_id,
            "Reported_By_Contact__c": user.contact_id,
            "Subject": f"Amendment — cancel {closure_id}",
            "Description": (
                f"Cancelled Closure_Event {closure_id}. Reason: {body.reason}"
            ),
        },
    )
    return ClosureCancelResponse(
        success=True,
        closure_id=closure_id,
        amendment_case_id=amendment["id"],
    )
