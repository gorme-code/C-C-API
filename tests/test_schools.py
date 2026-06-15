"""Tests for Endpoint 1 — GET /api/schools."""


def test_get_schools_returns_district_schools(client, mock_sf, mock_user):
    mock_sf.query.return_value = [
        {"Id": "001AAA0000000001", "Name": "Abbeville High School"},
        {"Id": "001AAA0000000002", "Name": "Abbeville Middle School"},
    ]

    resp = client.get("/api/schools")

    assert resp.status_code == 200
    # sidn is null until a SIDN field exists on Account in the org.
    assert resp.json() == {
        "schools": [
            {"id": "001AAA0000000001", "name": "Abbeville High School", "sidn": None},
            {"id": "001AAA0000000002", "name": "Abbeville Middle School", "sidn": None},
        ]
    }
    # The query must not select a nonexistent SIDN field.
    assert "SIDN" not in mock_sf.query.call_args[0][0]


def test_get_schools_scopes_query_to_user_district(client, mock_sf, mock_user):
    mock_sf.query.return_value = []

    resp = client.get("/api/schools")

    assert resp.status_code == 200
    assert resp.json() == {"schools": []}
    soql = mock_sf.query.call_args[0][0]
    assert "RecordType.DeveloperName = 'School'" in soql
    assert f"ParentId = '{mock_user.account_id}'" in soql


def test_get_schools_sidn_is_null(client, mock_sf):
    mock_sf.query.return_value = [
        {"Id": "001AAA0000000003", "Name": "Some School"},
    ]

    resp = client.get("/api/schools")

    assert resp.status_code == 200
    assert resp.json()["schools"][0]["sidn"] is None


def test_closure_reasons_shape(client, mock_sf):
    mock_sf.query.return_value = [
        {
            "DeveloperName": "Weather_Snow",
            "MasterLabel": "Weather – Snow",
            "Requires_Makeup_Default__c": True,
        },
        {
            "DeveloperName": "Safety_Threat",
            "MasterLabel": "Safety Threat",
            "Requires_Makeup_Default__c": False,
        },
    ]

    resp = client.get("/api/closure-reasons")

    assert resp.status_code == 200
    assert resp.json() == {
        "reasons": [
            {"value": "Weather_Snow", "label": "Weather – Snow", "requires_makeup_default": True},
            {"value": "Safety_Threat", "label": "Safety Threat", "requires_makeup_default": False},
        ]
    }
