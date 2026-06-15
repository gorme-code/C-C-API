"""Smoke tests for the makeup router."""


def test_makeup_rejects_cross_district_events(client, mock_sf):
    mock_sf.query.return_value = [
        {"Id": "a0XEVENT0000000001", "District__c": "001OTHERDISTRICT0"},
    ]
    resp = client.post(
        "/api/makeup",
        json={
            "closure_event_ids": ["a0XEVENT0000000001"],
            "makeup_date": "2026-01-24",
            "method": "Saturday",
            "hours_covered": 6.5,
            "external_id": "uuid-1",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "DISTRICT_SCOPE_VIOLATION"
