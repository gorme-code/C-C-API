"""Smoke tests for the makeup router."""


def test_makeup_two_events_creates_day_and_links(client, mock_sf, mock_user):
    # District-check query returns both events in the user's district.
    mock_sf.query.return_value = [
        {"Id": "a0XEVENT0000000001", "District__c": mock_user.account_id},
        {"Id": "a0XEVENT0000000002", "District__c": mock_user.account_id},
    ]
    mock_sf.query_one.return_value = None  # no existing external_id
    mock_sf.create.return_value = {"id": "a1XMAKEUP000000001", "success": True}

    resp = client.post(
        "/api/makeup",
        json={
            "closure_event_ids": ["a0XEVENT0000000001", "a0XEVENT0000000002"],
            "makeup_date": "2026-01-24",
            "method": "Saturday",
            "hours_covered": 6.5,
            "external_id": "uuid-2",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["makeup_day_id"] == "a1XMAKEUP000000001"
    assert data["links_created"] == 2
    assert [e["new_status"] for e in data["closure_events_updated"]] == [
        "Make_Up_Pending",
        "Make_Up_Pending",
    ]
    # 1 Makeup_Day + 2 junction links = 3 creates.
    assert mock_sf.create.call_count == 3


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
