"""Live read-path smoke test — exercises every GET endpoint in-process.

Hits the real Salesforce sandbox. Requires AUTH_DISABLED=true (development) so
the dev bypass supplies identity (Abbeville district).

Run from project root:
    .venv\\Scripts\\python.exe scripts\\smoke_endpoints.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

# A Closure_Event in a DIFFERENT district (Seed Test District) — for the 403.
FOREIGN_EVENT_ID = "a15Va000008JWJZIA4"


def get(path: str):
    r = client.get(path)
    print(f"\nGET {path} -> {r.status_code}")
    return r


def main() -> None:
    # 1. Schools
    r = get("/api/schools")
    print(f"  schools: {len(r.json()['schools'])}")

    # 2. Closure reasons
    r = get("/api/closure-reasons")
    print(f"  active reasons: {len(r.json()['reasons'])}")

    # 3. Closures — no filter (whole district)
    r = get("/api/closures")
    body = r.json()
    print(f"  total: {body['total']},  ytd_by_school keys: {len(body['ytd_missed_days_by_school'])}")
    first_id = body["closures"][0]["id"] if body["closures"] else None

    # 4. Filter by a status that exists
    r = get("/api/closures?status=Submitted")
    print(f"  status=Submitted -> {r.json()['total']}")

    # 5. Filter by a status that should match nothing here (proves filtering)
    r = get("/api/closures?status=Make_Up_Pending")
    print(f"  status=Make_Up_Pending -> {r.json()['total']} (expected 0)")

    # 6. Detail on a real in-district event
    if first_id:
        r = get(f"/api/closures/{first_id}")
        d = r.json()
        print(f"  name={d.get('name')}  status={d.get('status')}  "
              f"makeup_days={len(d.get('makeup_days', []))}  waiver={d.get('waiver_case_id')}")

    # 7. Detail on a foreign-district event -> 403
    r = get(f"/api/closures/{FOREIGN_EVENT_ID}")
    print(f"  expected 403 -> error={r.json().get('error')}")

    # 8. Detail on a nonexistent id -> 404
    r = get("/api/closures/a15000000000000XXX")
    print(f"  expected 404 -> error={r.json().get('error')}")

    # 9. Waivers (district-scoped)
    r = get("/api/waivers")
    ws = r.json()["waivers"]
    print(f"  waivers: {len(ws)}")
    for w in ws:
        print(f"    - {w['case_number']}  {w['status']}  {w['tier']}  "
              f"events={w['closure_events_count']}")


if __name__ == "__main__":
    main()
