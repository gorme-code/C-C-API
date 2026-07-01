"""Smoke tests for the closures router."""
import json

_VALID_BODY = {
    "scope": "District_Wide",
    "school_ids": [],
    "closure_dates": [
        {
            "date": "2026-01-15",
            "closure_type": "Closed",
            "closure_reason": "Weather_Conditions",
            "hours_missed": 6.5,
        }
    ],
    "external_id": "ABVL-1234-2026-01-15-uuid",
}


def test_create_closure_sets_district_from_contact_not_client(client, mock_sf, mock_user):
    mock_sf.query_one.return_value = None  # no existing external_id
    mock_sf.query.return_value = []

    resp = client.post("/api/closures", json=_VALID_BODY)

    assert resp.status_code == 200
    assert resp.json()["case_id"] == "500FAKE0000000000"
    payload = mock_sf.create.call_args[0][1]
    assert payload["Submission_District__c"] == mock_user.account_id
    assert payload["Reported_By_Contact__c"] == mock_user.contact_id
    assert payload["RecordTypeId"] == "012FAKE0000000000"
    assert payload["Submission_Scope__c"] == "District_Wide"
    assert payload["Submission_Status__c"] == "Submitted"  # fires the Flow
    assert "Closure_Date_Entries__c" in payload
    entries = json.loads(payload["Closure_Date_Entries__c"])
    assert len(entries) == 1
    assert entries[0]["closure_reason"] == "Weather_Conditions"


# --- Step 10 explicit tests ---------------------------------------------------

def test_step10_t1_two_date_entries_closed_and_elearning(client, mock_sf):
    """Test 1: POST with 2 date entries (one Closed, one eLearning).

    Verifies:
    - Case created with Closure_Date_Entries__c as valid JSON
    - Response includes events_created, ytd_missed_days, current_tier,
      makeup_required, waiver_auto_created
    """
    mock_sf.query_one.return_value = None
    mock_sf.query.return_value = [
        {"Id": "a0X1", "Make_Up_Required__c": True, "Waiver_Request_Case__c": None},
        {"Id": "a0X2", "Make_Up_Required__c": False, "Waiver_Request_Case__c": None},
    ]
    body = {
        "scope": "Single_School",
        "school_ids": ["001AAA0000000001"],
        "closure_dates": [
            {
                "date": "2026-01-15",
                "closure_type": "Closed",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
                "make_up_method": "Scheduled Weather Makeup Day",
                "scheduled_makeup_date": "2026-01-22",
            },
            {
                "date": "2026-01-16",
                "closure_type": "Closed - eLearning",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
                "elearning_day_number": 1,
            },
        ],
        "external_id": "step10-t1-uuid",
    }

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 200
    # Verify Case payload has valid JSON in Closure_Date_Entries__c
    sf_payload = mock_sf.create.call_args[0][1]
    assert "Closure_Date_Entries__c" in sf_payload
    entries = json.loads(sf_payload["Closure_Date_Entries__c"])
    assert len(entries) == 2
    assert entries[0]["closure_type"] == "Closed"
    assert entries[0]["scheduled_makeup_date"] == "2026-01-22"
    assert entries[1]["closure_type"] == "Closed - eLearning"
    assert entries[1]["elearning_day_number"] == 1
    # Verify response shape
    data = resp.json()
    assert data["events_created"] == 2
    assert "ytd_missed_days" in data
    assert "current_tier" in data
    assert "makeup_required" in data
    assert "waiver_auto_created" in data


def test_step10_t2_idempotency_same_external_id(client, mock_sf):
    """Test 2: POST same payload twice; second call returns existing Case, no new create."""
    mock_sf.query_one.return_value = {"Id": "500EXISTING000000"}
    mock_sf.query.return_value = []

    body = {**_VALID_BODY, "external_id": "idempotent-key-xyz"}
    resp1 = client.post("/api/closures", json=body)
    resp2 = client.post("/api/closures", json=body)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["case_id"] == resp2.json()["case_id"] == "500EXISTING000000"
    mock_sf.create.assert_not_called()


def test_step10_t3_tier_boundary_waiver_auto_created(client, mock_sf):
    """Test 3: Enough events to cross Tier 2 — waiver_auto_created=true in response."""
    mock_sf.query_one.return_value = None
    mock_sf.query.return_value = [
        {"Id": "a0X1", "Make_Up_Required__c": True,
         "Waiver_Request_Case__c": "500WAIVER00000000"},
        {"Id": "a0X2", "Make_Up_Required__c": True,
         "Waiver_Request_Case__c": "500WAIVER00000000"},
        {"Id": "a0X3", "Make_Up_Required__c": True,
         "Waiver_Request_Case__c": "500WAIVER00000000"},
        {"Id": "a0X4", "Make_Up_Required__c": True,
         "Waiver_Request_Case__c": "500WAIVER00000000"},
    ]
    # 4 date entries pushes past Tier 2 (>3 missed days)
    body = {
        **_VALID_BODY,
        "closure_dates": [
            {
                "date": f"2026-01-1{i}",
                "closure_type": "Closed",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
            }
            for i in range(1, 5)
        ],
        "external_id": "tier-boundary-uuid",
    }

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["waiver_auto_created"] is True
    assert data["waiver_case_id"] == "500WAIVER00000000"


def test_create_single_school_one_day_events_created(client, mock_sf):
    mock_sf.query_one.return_value = None  # no existing external_id
    mock_sf.query.return_value = [
        {"Id": "a0X1", "Make_Up_Required__c": True, "Waiver_Request_Case__c": None},
    ]
    body = {**_VALID_BODY, "scope": "Single_School", "school_ids": ["001AAA0000000001"]}

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["events_created"] == 1
    assert data["makeup_required"] is True
    assert "ytd_missed_days" in data and "current_tier" in data


def test_create_district_wide_six_events(client, mock_sf):
    mock_sf.query_one.return_value = None
    mock_sf.query.return_value = [
        {"Id": f"a0X{i}", "Make_Up_Required__c": True, "Waiver_Request_Case__c": None}
        for i in range(6)
    ]

    resp = client.post("/api/closures", json=_VALID_BODY)  # District_Wide

    assert resp.status_code == 200
    assert resp.json()["events_created"] == 6


def test_create_tier_boundary_flags_waiver(client, mock_sf):
    mock_sf.query_one.return_value = None
    mock_sf.query.return_value = [
        {"Id": "a0X1", "Make_Up_Required__c": True,
         "Waiver_Request_Case__c": "500WAIVER00000000"},
    ]

    resp = client.post("/api/closures", json=_VALID_BODY)

    assert resp.status_code == 200
    data = resp.json()
    assert data["waiver_auto_created"] is True
    assert data["waiver_case_id"] == "500WAIVER00000000"


def test_create_closure_idempotent_returns_existing(client, mock_sf):
    mock_sf.query_one.return_value = {"Id": "500EXISTING000000"}
    mock_sf.query.return_value = []

    resp = client.post("/api/closures", json=_VALID_BODY)

    assert resp.status_code == 200
    assert resp.json()["case_id"] == "500EXISTING000000"
    mock_sf.create.assert_not_called()  # no duplicate


# --- Step 13 end-to-end tests -------------------------------------------------

def test_step13_two_entries_elearning_day3(client, mock_sf):
    """Step 13 scenario 1: 2 date entries (Closed+scheduled, eLearning day 3).

    Verifies:
    - Closure_Date_Entries__c JSON contains both entries with correct fields
    - Response: events_created=2, current_tier present, waiver_auto_created present
    """
    mock_sf.query_one.return_value = None  # idempotency + school validation + YTD + waiver
    mock_sf.query.return_value = [
        {"Id": "a0X1", "Make_Up_Required__c": False, "Waiver_Request_Case__c": None},
        {"Id": "a0X2", "Make_Up_Required__c": False, "Waiver_Request_Case__c": None},
    ]
    body = {
        "scope": "Single_School",
        "school_ids": ["001SCHOOL0000001"],
        "closure_dates": [
            {
                "date": "2026-01-15",
                "closure_type": "Closed",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
                "make_up_method": "Scheduled Weather Makeup Day",
                "scheduled_makeup_date": "2026-01-22",
            },
            {
                "date": "2026-01-16",
                "closure_type": "Closed – eLearning",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
                "elearning_day_number": 3,
            },
        ],
        "external_id": "step13-t1-uuid",
    }

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 200
    sf_payload = mock_sf.create.call_args[0][1]
    entries = json.loads(sf_payload["Closure_Date_Entries__c"])
    assert len(entries) == 2
    assert entries[0]["make_up_method"] == "Scheduled Weather Makeup Day"
    assert entries[0]["scheduled_makeup_date"] == "2026-01-22"
    assert entries[1]["closure_type"] == "Closed – eLearning"
    assert entries[1]["elearning_day_number"] == 3

    data = resp.json()
    assert data["events_created"] == 2
    assert "current_tier" in data
    assert "waiver_auto_created" in data


def test_step13_district_wide_one_entry_four_schools(client, mock_sf):
    """Step 13 scenario 2: District_Wide, 1 date entry — 4 events created (one per school).

    Verifies:
    - events_created=4
    - Closure_Date_Entries__c JSON contains 1 entry with all date fields present
    """
    mock_sf.query_one.return_value = None
    mock_sf.query.return_value = [
        {"Id": f"a0X{i}", "Make_Up_Required__c": True, "Waiver_Request_Case__c": None}
        for i in range(1, 5)
    ]
    body = {
        "scope": "District_Wide",
        "school_ids": [],
        "closure_dates": [
            {
                "date": "2026-01-15",
                "closure_type": "Closed",
                "closure_reason": "Weather_Conditions",
                "hours_missed": 6.5,
                "make_up_method": "Scheduled Weather Makeup Day",
                "scheduled_makeup_date": "2026-01-22",
            }
        ],
        "external_id": "step13-t2-uuid",
    }

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 200
    sf_payload = mock_sf.create.call_args[0][1]
    entries = json.loads(sf_payload["Closure_Date_Entries__c"])
    assert len(entries) == 1
    assert entries[0]["date"] == "2026-01-15"
    assert entries[0]["closure_type"] == "Closed"
    assert entries[0]["closure_reason"] == "Weather_Conditions"
    assert entries[0]["hours_missed"] == 6.5
    assert entries[0]["make_up_method"] == "Scheduled Weather Makeup Day"
    assert entries[0]["scheduled_makeup_date"] == "2026-01-22"
    assert sf_payload["Submission_Scope__c"] == "District_Wide"

    assert resp.json()["events_created"] == 4


def test_step13_cross_district_attempt_returns_403(client, mock_sf, mock_user):
    """Step 13 scenario 5: school_ids from a different district → HTTP 403."""
    # query_one call 1: idempotency check → no existing Case
    # query_one call 2: cross-district guard → finds a school whose ParentId ≠ user's district
    mock_sf.query_one.side_effect = [
        None,
        {"Id": "001SCHOOLB0000001"},  # wrong district school found
    ]
    body = {
        "scope": "Single_School",
        "school_ids": ["001SCHOOLB0000001"],
        "closure_dates": [
            {
                "date": "2026-01-15",
                "closure_type": "Closed",
                "closure_reason": "Weather_Conditions",
            }
        ],
        "external_id": "cross-district-uuid",
    }

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 403
    assert resp.json()["error"] == "DISTRICT_SCOPE_VIOLATION"
    mock_sf.create.assert_not_called()


def test_create_closure_requires_school_ids_when_scoped(client, mock_sf):
    body = {**_VALID_BODY, "scope": "Single_School", "school_ids": []}

    resp = client.post("/api/closures", json=body)

    assert resp.status_code == 422
    assert resp.json()["error"] == "VALIDATION_ERROR"


def test_pydantic_validation_uses_standard_error_shape(client, mock_sf):
    # Missing required fields fail at the Pydantic layer (before the route).
    resp = client.post("/api/closures", json={"scope": "District_Wide"})

    assert resp.status_code == 422
    body = resp.json()
    # Must be the standard shape, NOT FastAPI's default {"detail": [...]}.
    assert set(body) == {"error", "message", "status_code"}
    assert body["error"] == "VALIDATION_ERROR"
    assert body["status_code"] == 422


def test_list_closures_scopes_to_district(client, mock_sf, mock_user):
    mock_sf.query.return_value = []
    resp = client.get("/api/closures")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "closures": [],
        "total": 0,
        "ytd_missed_days_by_school": {},
        "elearning_days_used_by_school": {},
    }
    # District filter is always applied (first query call is the main events query).
    soql = mock_sf.query.call_args_list[0][0][0]
    assert mock_user.account_id in soql


def test_step11_elearning_counter_and_new_fields(client, mock_sf, mock_user):
    """Step 11: 2 eLearning events for the same school.

    Verifies:
    - elearning_days_used_by_school shows that school with value 2
    - eLearning_Day_Number__c, Scheduled_Makeup_Date__c, Comments__c appear on each event
    """
    school_id = "001SCH0000000001"

    def _elearning_record(rec_id, day_num, closure_date, scheduled_makeup, comment):
        return {
            "Id": rec_id,
            "Name": f"CE-{rec_id}",
            "School__c": school_id,
            "School__r": {"Name": "Oakwood Elementary"},
            "Closure_Date__c": closure_date,
            "Closure_Type__c": "Closed – eLearning",
            "Closure_Reason__c": "Weather_Conditions",
            "Hours_Missed__c": 6.5,
            "Status__c": "Submitted",
            "Make_Up_Required__c": False,
            "Make_Up_Method__c": None,
            "School_Year__c": "2025-26",
            "eLearning_Day_Number__c": day_num,
            "Scheduled_Makeup_Date__c": scheduled_makeup,
            "Comments__c": comment,
        }

    event_1 = _elearning_record("a0X1", 1, "2026-01-15", None, "First eLearning day")
    event_2 = _elearning_record("a0X2", 2, "2026-01-22", "2026-02-10", "Second eLearning day")

    # Three sequential sf.query calls: main events, Account YTD, eLearning counter
    mock_sf.query.side_effect = [
        [event_1, event_2],                                          # main events (2 records)
        [{"Id": school_id, "Total_Missed_Days_YTD__c": 2.0}],       # YTD rollup
        [{"School__c": school_id, "cnt": 2}],                        # eLearning counter
    ]

    resp = client.get("/api/closures")

    assert resp.status_code == 200
    data = resp.json()

    # elearning_days_used_by_school shows the school with value 2
    assert data["elearning_days_used_by_school"] == {school_id: 2}
    assert data["total"] == 2

    # eLearning_Day_Number__c, Scheduled_Makeup_Date__c, Comments__c on each event
    ev1, ev2 = data["closures"]
    assert ev1["elearning_day_number"] == 1
    assert ev1["scheduled_makeup_date"] is None
    assert ev1["comments"] == "First eLearning day"

    assert ev2["elearning_day_number"] == 2
    assert ev2["scheduled_makeup_date"] == "2026-02-10"
    assert ev2["comments"] == "Second eLearning day"

    # eLearning SOQL contains correct type filter, school, and GROUP BY
    elearning_soql = mock_sf.query.call_args_list[2][0][0]
    assert "Closed – eLearning" in elearning_soql
    assert school_id in elearning_soql
    assert "GROUP BY School__c" in elearning_soql


def test_list_closures_status_filter_in_soql(client, mock_sf, mock_user):
    mock_sf.query.return_value = []

    resp = client.get("/api/closures?status=Make_Up_Pending")

    assert resp.status_code == 200
    soql = mock_sf.query.call_args[0][0]
    assert "Status__c = 'Make_Up_Pending'" in soql
    assert f"District__c = '{mock_user.account_id}'" in soql


def test_get_closure_wrong_district_returns_403(client, mock_sf):
    mock_sf.query_one.return_value = {
        "Id": "a0XOTHER000000000",
        "District__c": "001OTHERDISTRICT0",
        "Status__c": "Make_Up_Pending",
    }
    resp = client.get("/api/closures/a0XOTHER000000000")
    assert resp.status_code == 403
    assert resp.json()["error"] == "DISTRICT_SCOPE_VIOLATION"
