"""Live WRITE-path integration test against the Salesforce sandbox.

Runs the Step 12 / Section 5 matrix in order, creating real records, then
queries Salesforce to confirm what actually landed and whether the Flows fired.

Uses far-future 2099 dates with a unique per-run tag so the Create_Closure_Events
duplicate-check never skips rows and tier math starts from a clean school year.

Requires AUTH_DISABLED=true (development) pointed at Abbeville.
Run from project root:
    .venv\\Scripts\\python.exe scripts\\write_path.py
"""
import datetime as dt
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.salesforce import sf  # noqa: E402

client = TestClient(app)

SCHOOL_1 = "001Va00000xts7UIAQ"   # Test School
SCHOOL_3 = "001Va00000xuDDWIA2"   # Test School 3

RUN = uuid.uuid4().hex[:8]
# Distinct date window per run (somewhere in 2099) to avoid duplicate-skip.
BASE = dt.date(2099, 1, 1) + dt.timedelta(days=uuid.uuid4().int % 280)


def d(offset: int) -> str:
    return (BASE + dt.timedelta(days=offset)).isoformat()


def post(label: str, body: dict):
    r = client.post("/api/closures", json=body)
    print(f"\n[{label}] POST /api/closures -> {r.status_code}")
    j = r.json()
    if r.status_code == 200:
        print(f"  case_id={j['case_id']}  events_created={j['events_created']}  "
              f"ytd={j['ytd_missed_days']}  tier={j['current_tier']}  "
              f"makeup_required={j['makeup_required']}  "
              f"waiver_auto_created={j['waiver_auto_created']}  waiver={j['waiver_case_id']}")
    else:
        print(f"  {j}")
    return j


def sf_event_count(case_id: str) -> int:
    return len(sf.query(
        f"SELECT Id FROM Closure_Event__c WHERE Source_Case__c = '{case_id}'"
    ))


def main() -> None:
    print(f"RUN={RUN}  date window starts {BASE.isoformat()}")

    # UC-01 — single school, single day
    ext1 = f"WP-{RUN}-uc01"
    uc01 = post("UC-01 single/1day", {
        "scope": "Single_School", "school_ids": [SCHOOL_1],
        "closure_start_date": d(0), "closure_end_date": d(0),
        "closure_type": "Closed", "closure_reason": "Weather_Snow",
        "hours_missed": 6.5, "external_id": ext1,
    })
    print(f"  SF confirms events for case: {sf_event_count(uc01['case_id'])}")

    # UC-03/04 — district-wide, 2 days (3 schools x 2 days = 6)
    uc03 = post("UC-03 district/2day", {
        "scope": "District_Wide", "school_ids": [],
        "closure_start_date": d(10), "closure_end_date": d(11),
        "closure_type": "Closed", "closure_reason": "Weather_Snow",
        "hours_missed": 6.5, "external_id": f"WP-{RUN}-uc03",
    })
    print(f"  SF confirms events for case: {sf_event_count(uc03['case_id'])}  (expect 6)")

    # Idempotency — repeat UC-01 exactly
    dup = post("Idempotency (repeat UC-01)", {
        "scope": "Single_School", "school_ids": [SCHOOL_1],
        "closure_start_date": d(0), "closure_end_date": d(0),
        "closure_type": "Closed", "closure_reason": "Weather_Snow",
        "hours_missed": 6.5, "external_id": ext1,
    })
    print(f"  same case_id as UC-01? {dup['case_id'] == uc01['case_id']}")

    # Tier boundary — 5 days for one fresh school => > 3 missed days
    tier = post("Tier boundary (5 days)", {
        "scope": "Single_School", "school_ids": [SCHOOL_3],
        "closure_start_date": d(20), "closure_end_date": d(24),
        "closure_type": "Closed", "closure_reason": "Weather_Snow",
        "hours_missed": 6.5, "external_id": f"WP-{RUN}-tier",
    })
    print(f"  SF confirms events for case: {sf_event_count(tier['case_id'])}  (expect 5)")

    # Makeup — cover 2 of the district-wide events
    ev = sf.query(
        f"SELECT Id, Status__c FROM Closure_Event__c "
        f"WHERE Source_Case__c = '{uc03['case_id']}' LIMIT 2"
    )
    ev_ids = [e["Id"] for e in ev]
    print(f"\n[Makeup] linking events {ev_ids}")
    r = client.post("/api/makeup", json={
        "closure_event_ids": ev_ids,
        "makeup_date": d(30), "method": "Saturday",
        "hours_covered": 6.5, "external_id": f"WP-{RUN}-mk",
    })
    print(f"  POST /api/makeup -> {r.status_code}: {r.json()}")
    after = sf.query(
        "SELECT Id, Status__c FROM Closure_Event__c "
        f"WHERE Id IN ('{ev_ids[0]}','{ev_ids[1]}')"
    )
    print("  SF event statuses after makeup:")
    for e in after:
        print(f"    {e['Id']}  Status__c={e['Status__c']}")


if __name__ == "__main__":
    main()
