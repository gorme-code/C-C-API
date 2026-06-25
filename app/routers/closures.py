"""Endpoints 3-6 — closure submission, listing, detail, and cancel.

POST   /api/closures            — submit a closure (creates a Case)
GET    /api/closures            — list closure events for the district
GET    /api/closures/{id}       — single closure event detail
POST   /api/closures/{id}/cancel — cancel a closure event

Salesforce field names follow the Phase 1 data model & build guide. The
Closure_Submission Case carries Submission_* fields; the Flow expands it into
Closure_Event__c rows.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app.errors import DistrictScopeViolation, NotFound, ValidationError
from app.models.closure_models import (
    ClosureAmendRequest,
    ClosureAmendResponse,
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
WAIVER_RT = "Closure_Waiver_Request"

# Tier thresholds (days). Source of truth is Compliance_Rules__mdt.Default
# (Tier2=3, Tier3=6, Tier4=9); mirrored here for the response tier label.
_TIER2, _TIER3, _TIER4 = 3, 6, 9


def _tier_for_days(days: float) -> str:
    if days <= _TIER2:
        return "Tier 1"
    if days <= _TIER3:
        return "Tier 2"
    if days <= _TIER4:
        return "Tier 3"
    return "Tier 4"


@router.post("", response_model=ClosureCreateResponse)
def create_closure(
    body: ClosureCreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ClosureCreateResponse:
    """Create a Closure_Submission Case; the SF Flow expands it into events.

    District is always taken from the resolved Contact — never the client.
    External_Id__c provides idempotency. Submission_Status__c = 'Submitted'
    is what triggers the Create_Closure_Events Flow.
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
        "RecordTypeId": sf.record_type_id("Case", CLOSURE_SUBMISSION_RT),
        "Submission_Scope__c": body.scope.value,
        "Closure_Start_Date__c": body.closure_start_date.isoformat(),
        "Closure_End_Date__c": body.closure_end_date.isoformat(),
        "Closure_Type__c": body.closure_type,
        "Closure_Reason__c": body.closure_reason,
        "Hours_Missed_Per_Day__c": body.hours_missed,
        "Submission_Status__c": "Submitted",  # fires Create_Closure_Events Flow
        "External_Id__c": body.external_id,
        "Submission_District__c": user.account_id,
        "Reported_By_Contact__c": user.contact_id,
    }
    if body.school_ids:
        # Single_School uses the first id; Multiple_Schools uses the full list.
        payload["Affected_School_IDs__c"] = ",".join(body.school_ids)

    result = sf.create("Case", payload)
    return _build_create_response(result["id"], user.account_id)


def _build_create_response(case_id: str, district_id: str) -> ClosureCreateResponse:
    """Assemble the create response from the events + district YTD totals."""
    events = sf.query(
        "SELECT Id, Make_Up_Required__c, Waiver_Request_Case__c "
        "FROM Closure_Event__c "
        f"WHERE Source_Case__c = '{case_id}'"
    )
    account = sf.query_one(
        "SELECT Total_Missed_Days_YTD__c "
        f"FROM Account WHERE Id = '{district_id}' LIMIT 1"
    ) or {}
    ytd = float(account.get("Total_Missed_Days_YTD__c") or 0.0)

    makeup_required = any(e.get("Make_Up_Required__c") for e in events)

    # A waiver counts as auto-created by THIS submission only if it is tied to
    # one of this submission's events — via the direct lookup on the event, or
    # the Waiver_Closure_Link__c junction the Tier_Boundary_Check Flow writes.
    # (A loose "latest district waiver" fallback gives false positives.)
    waiver_case_id = next(
        (e["Waiver_Request_Case__c"] for e in events if e.get("Waiver_Request_Case__c")),
        None,
    )
    if not waiver_case_id:
        event_ids = [e["Id"] for e in events]
        if event_ids:
            id_list = ", ".join(f"'{i}'" for i in event_ids)
            link = sf.query_one(
                "SELECT Waiver_Case__c FROM Waiver_Closure_Link__c "
                f"WHERE Closure_Event__c IN ({id_list}) AND Waiver_Case__c != null "
                "ORDER BY CreatedDate DESC LIMIT 1"
            )
            waiver_case_id = link.get("Waiver_Case__c") if link else None

    return ClosureCreateResponse(
        case_id=case_id,
        events_created=len(events),
        ytd_missed_days=ytd,
        current_tier=_tier_for_days(ytd),
        makeup_required=makeup_required,
        waiver_auto_created=waiver_case_id is not None,
        waiver_case_id=waiver_case_id,
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

    # Per-school YTD comes from the authoritative Account roll-up (in days),
    # not from summing event hours.
    school_ids = {r["School__c"] for r in records if r.get("School__c")}
    ytd: dict[str, float] = {}
    if school_ids:
        id_list = ", ".join(f"'{sid}'" for sid in school_ids)
        for acc in sf.query(
            "SELECT Id, Total_Missed_Days_YTD__c FROM Account "
            f"WHERE Id IN ({id_list})"
        ):
            ytd[acc["Id"]] = float(acc.get("Total_Missed_Days_YTD__c") or 0.0)

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
        "Reported_Date__c, Waiver_Request_Case__c "
        f"FROM Closure_Event__c WHERE Id = '{closure_id}' LIMIT 1"
    )
    if not record:
        raise NotFound("Closure event not found.")
    if record.get("District__c") != user.account_id:
        raise DistrictScopeViolation("You do not have access to this closure event.")

    # Makeup days via the junction (separate query — robust against child
    # relationship-name ambiguity on Closure_Event__c).
    makeup_days = []
    for link in sf.query(
        "SELECT Makeup_Day__r.Id, Makeup_Day__r.Makeup_Date__c, "
        "Makeup_Day__r.Method__c, Makeup_Day__r.Status__c "
        f"FROM Closure_Makeup_Link__c WHERE Closure_Event__c = '{closure_id}'"
    ):
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
        waiver_case_id=record.get("Waiver_Request_Case__c"),
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

    # Amendment audit Case. Submission_Status__c is set to 'Acknowledged' (NOT
    # 'Submitted') so this record does not trigger Create_Closure_Events.
    amendment = sf.create(
        "Case",
        {
            "RecordTypeId": sf.record_type_id("Case", CLOSURE_SUBMISSION_RT),
            "Submission_District__c": user.account_id,
            "Reported_By_Contact__c": user.contact_id,
            "Submission_Status__c": "Acknowledged",
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


@router.post("/{closure_id}/amend", response_model=ClosureAmendResponse)
def amend_closure(
    closure_id: str,
    body: ClosureAmendRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ClosureAmendResponse:
    """Amend a closure event (UC-05).

    Never edits in place: the original event is set to Status='Amended', a new
    corrected Closure_Event is created with the supplied overrides (everything
    else copied from the original), and an Amendment Case records the reason.
    """
    record = sf.query_one(
        "SELECT Id, District__c, School__c, Closure_Date__c, Closure_Reason__c, "
        "Closure_Type__c, Hours_Missed__c, Instructional_Day__c, Status__c, "
        "Reported_By__c "
        f"FROM Closure_Event__c WHERE Id = '{closure_id}' LIMIT 1"
    )
    if not record:
        raise NotFound("Closure event not found.")
    if record.get("District__c") != user.account_id:
        raise DistrictScopeViolation("You do not have access to this closure event.")
    if record.get("Status__c") in ("Cancelled", "Closed", "Amended"):
        raise ValidationError(
            f"Closure event is {record.get('Status__c')} and cannot be amended."
        )

    # Amendment audit Case (Submission_Status__c='Acknowledged' so it does NOT
    # trigger Create_Closure_Events — we create the corrected event ourselves).
    amendment = sf.create(
        "Case",
        {
            "RecordTypeId": sf.record_type_id("Case", CLOSURE_SUBMISSION_RT),
            "Submission_District__c": user.account_id,
            "Reported_By_Contact__c": user.contact_id,
            "Submission_Status__c": "Acknowledged",
            "Subject": f"Amendment — amend {closure_id}",
            "Description": f"Amended Closure_Event {closure_id}. Reason: {body.reason}",
        },
    )

    # Mark the original as Amended.
    sf.update("Closure_Event__c", closure_id, {"Status__c": "Amended"})

    # Create the corrected event: copy the original, apply overrides.
    def pick(override, field):
        return override if override is not None else record.get(field)

    new_event = sf.create(
        "Closure_Event__c",
        {
            "School__c": record.get("School__c"),
            "District__c": record.get("District__c"),
            "Closure_Date__c": record.get("Closure_Date__c"),
            "Closure_Reason__c": pick(body.closure_reason, "Closure_Reason__c"),
            "Closure_Type__c": pick(body.closure_type, "Closure_Type__c"),
            "Hours_Missed__c": pick(body.hours_missed, "Hours_Missed__c"),
            "Instructional_Day__c": pick(body.instructional_day, "Instructional_Day__c"),
            "Reported_By__c": record.get("Reported_By__c"),
            "Source_Case__c": amendment["id"],
            "Status__c": "Submitted",
        },
    )

    return ClosureAmendResponse(
        success=True,
        original_id=closure_id,
        new_closure_id=new_event["id"],
        amendment_case_id=amendment["id"],
    )
