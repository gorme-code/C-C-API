"""Smoke tests for the waivers router."""


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
