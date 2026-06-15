"""Smoke tests for the waivers router."""


def test_list_waivers_scopes_to_district(client, mock_sf, mock_user):
    mock_sf.query.return_value = [
        {
            "Id": "500WAIVER00000000",
            "CaseNumber": "00001234",
            "Waiver_Status__c": "Draft",
            "Tier__c": "Tier 2",
            "Total_Missed_Days__c": 4.0,
            "Days_Already_Made_Up__c": 1.0,
            "Days_Requested_For_Waiver__c": 3.0,
            "CreatedDate": "2026-01-16T09:00:00.000+0000",
            "WaiverCase__r": {"totalSize": 4, "records": [{"Id": "a0X1"}]},
        }
    ]

    resp = client.get("/api/waivers")

    assert resp.status_code == 200
    waiver = resp.json()["waivers"][0]
    assert waiver["case_number"] == "00001234"
    assert waiver["days_made_up"] == 1.0
    assert waiver["closure_events_count"] == 4
    soql = mock_sf.query.call_args[0][0]
    assert "Closure_Waiver_Request" in soql
    assert f"Waiver_District__c = '{mock_user.account_id}'" in soql
    assert "ORDER BY CreatedDate DESC" in soql


def test_submit_tier3_without_cert_returns_422(client, mock_sf, mock_user):
    mock_sf.query_one.return_value = {
        "Id": "500WAIVER00000000",
        "Waiver_District__c": mock_user.account_id,
        "Tier__c": "Tier 3",
        "Waiver_Status__c": "Draft",
    }
    resp = client.patch(
        "/api/waivers/500WAIVER00000000",
        json={"action": "submit", "superintendent_certification": False},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "VALIDATION_ERROR"


def test_submit_with_cert_succeeds(client, mock_sf, mock_user):
    mock_sf.query_one.return_value = {
        "Id": "500WAIVER00000000",
        "Waiver_District__c": mock_user.account_id,
        "Tier__c": "Tier 3",
        "Waiver_Status__c": "Draft",
    }
    resp = client.patch(
        "/api/waivers/500WAIVER00000000",
        json={
            "action": "submit",
            "superintendent_certification": True,
            "justification": "4 weather days.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_status"] == "Submitted"
    assert "Compliance" in body["routing"]
