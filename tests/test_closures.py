"""Smoke tests for the closures router."""

_VALID_BODY = {
    "scope": "District_Wide",
    "school_ids": [],
    "closure_start_date": "2026-01-15",
    "closure_end_date": "2026-01-17",
    "closure_type": "Closed",
    "closure_reason": "Weather_Snow",
    "hours_missed": 6.5,
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
    assert payload["Hours_Missed_Per_Day__c"] == 6.5


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
    assert body == {"closures": [], "total": 0, "ytd_missed_days_by_school": {}}
    # District filter is always applied.
    soql = mock_sf.query.call_args[0][0]
    assert mock_user.account_id in soql


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
