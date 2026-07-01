"""Tests for Endpoint 1 — GET /api/schools and Endpoint 2 — GET /api/closure-reasons."""
import app.routers.schools as _schools_mod

# The 7 new v1.3 CMDT records (all require makeup — confirmed Step 1).
_NEW_CMDT_RECORDS = [
    {"DeveloperName": "Environmental_Issues",   "MasterLabel": "Environmental Issues",        "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Facility_Maintenance",   "MasterLabel": "Facility Maintenance",        "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Health_Safety_Concerns", "MasterLabel": "Health and Safety Concerns",  "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Honored_Remembrances",   "MasterLabel": "Honored Remembrances",        "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Other",                  "MasterLabel": "Other",                       "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Road_Conditions",        "MasterLabel": "Road Conditions",             "Requires_Makeup_Default__c": True},
    {"DeveloperName": "Weather_Conditions",     "MasterLabel": "Weather Conditions",          "Requires_Makeup_Default__c": True},
]

_OLD_DEVELOPER_NAMES = {
    "Weather_Snow", "Weather_Flooding", "Weather_Hurricane",
    "Infrastructure_Failure", "Safety_Threat", "Staffing_Shortage", "Other_Disruption",
}


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
    _schools_mod._REASONS_CACHE["data"] = None
    _schools_mod._REASONS_CACHE["expires_at"] = 0.0
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


def test_step12_new_cmdt_values_returned(client, mock_sf):
    """Step 12: GET /api/closure-reasons returns 7 new v1.3 reasons, no old ones.

    Verifies:
    - All 7 new DeveloperNames and MasterLabels are present
    - No old reasons (Weather_Snow, etc.) appear
    - requires_makeup_default = True on every new reason (confirmed Step 1)
    """
    # Reset module-level cache so sf.query is called fresh for this test.
    _schools_mod._REASONS_CACHE["data"] = None
    _schools_mod._REASONS_CACHE["expires_at"] = 0.0
    mock_sf.query.return_value = _NEW_CMDT_RECORDS

    resp = client.get("/api/closure-reasons")

    assert resp.status_code == 200
    reasons = resp.json()["reasons"]

    returned_values = {r["value"] for r in reasons}
    returned_labels = {r["label"] for r in reasons}

    # Exactly 7 reasons returned
    assert len(reasons) == 7

    # All 7 new DeveloperNames present
    assert returned_values == {
        "Environmental_Issues", "Facility_Maintenance", "Health_Safety_Concerns",
        "Honored_Remembrances", "Other", "Road_Conditions", "Weather_Conditions",
    }

    # All 7 new MasterLabels present
    assert returned_labels == {
        "Environmental Issues", "Facility Maintenance", "Health and Safety Concerns",
        "Honored Remembrances", "Other", "Road Conditions", "Weather Conditions",
    }

    # No old reasons in response
    assert returned_values.isdisjoint(_OLD_DEVELOPER_NAMES)

    # requires_makeup_default = True on every new reason (Step 1 confirmed)
    for reason in reasons:
        assert reason["requires_makeup_default"] is True, (
            f"{reason['value']} should have requires_makeup_default=True"
        )
