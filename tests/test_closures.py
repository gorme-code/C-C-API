"""Smoke tests for the closures router."""


def test_list_closures_scopes_to_district(client, mock_sf, mock_user):
    mock_sf.query.return_value = []
    resp = client.get("/api/closures")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"closures": [], "total": 0, "ytd_missed_days_by_school": {}}
    # District filter is always applied.
    soql = mock_sf.query.call_args[0][0]
    assert mock_user.account_id in soql


def test_get_closure_wrong_district_returns_403(client, mock_sf):
    mock_sf.query_one.return_value = {
        "Id": "a0XOTHER000000000",
        "District__c": "001OTHERDISTRICT0",
        "Status__c": "Make_Up_Pending",
    }
    resp = client.get("/api/closures/a0XOTHER000000000")
    assert resp.status_code == 403
    assert resp.json()["error"] == "DISTRICT_SCOPE_VIOLATION"
