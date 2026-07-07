"""Test Approval_Decision_Date__c stamping on approve and reject.

Creates closure submissions for 2026-07-23 and 2026-07-24, submits the
resulting waiver(s) to the SF approval process, approves one and rejects
the other, then verifies Approval_Decision_Date__c is stamped on both.

Requirements:
  - AUTH_DISABLED=true in the environment (dev bypass identity)
  - The service account must be a member of SCDE_Closures_Compliance queue
    (or have Modify All on Cases) to approve/reject via the REST API

Run from project root:
    .venv\\Scripts\\python.exe scripts\\test_approve_reject.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.salesforce import sf  # noqa: E402

client = TestClient(app)


# ── helpers ────────────────────────────────────────────────────────────────

def post_closure(school_id: str, date_str: str, label: str) -> dict:
    """Submit a single-day closure and return the parsed response."""
    import uuid
    r = client.post("/api/closures", json={
        "scope": "Single_School",
        "school_ids": [school_id],
        "closure_start_date": date_str,
        "closure_end_date": date_str,
        "closure_type": "Closed",
        "closure_reason": "Weather_Conditions",
        "hours_missed": 6.5,
        "comments": f"test_approve_reject — {label}",
        "external_id": f"TAR-{date_str}-{uuid.uuid4()}",
    })
    if r.status_code != 200:
        print(f"  ERROR creating closure for {label}: {r.status_code} {r.text}")
        sys.exit(1)
    body = r.json()
    print(f"  closure {label}: case={body['case_id']}  "
          f"tier={body['current_tier']}  "
          f"waiver_auto_created={body['waiver_auto_created']}  "
          f"waiver_case={body.get('waiver_case_id')}")
    return body


def submit_waiver(waiver_id: str) -> None:
    """PATCH the waiver to Submitted, triggering Route_Waiver_By_Tier flow."""
    payload = {
        "action": "submit",
        "justification": "test_approve_reject automated submission",
        "superintendent_certification": True,
        "board_minutes_attached": False,
    }
    r = client.patch(f"/api/waivers/{waiver_id}", json=payload)
    if r.status_code != 200:
        print(f"  ERROR submitting waiver {waiver_id}: {r.status_code} {r.text}")
        sys.exit(1)
    print(f"  waiver {waiver_id} submitted → {r.json().get('new_status')}")


def get_work_item_id(case_id: str) -> str | None:
    """Return the pending ProcessInstanceWorkitem ID for a Case.

    Approve/Reject on process/approvals/ requires the work item Id (04i...),
    not the Case Id (500...). Without this you get INVALID_CROSS_REFERENCE_KEY.
    """
    rec = sf.query_one(
        "SELECT Id FROM ProcessInstanceWorkitem "
        f"WHERE ProcessInstance.TargetObjectId = '{case_id}' "
        "AND ProcessInstance.Status = 'Pending' "
        "ORDER BY CreatedDate DESC LIMIT 1"
    )
    return rec.get("Id") if rec else None


def sf_approval_action(work_item_id: str, action: str, comment: str) -> None:
    """Call the SF process/approvals REST API to approve or reject a work item."""
    url = sf.client.base_url + "process/approvals/"
    payload = json.dumps({
        "requests": [{
            "actionType": action,
            "contextId": work_item_id,
            "comments": comment,
        }]
    })
    resp = sf.client.session.post(
        url,
        headers={**sf.client.headers, "Content-Type": "application/json"},
        data=payload,
    )
    if resp.status_code not in (200, 201):
        print(f"  ERROR {action} on {work_item_id}: {resp.status_code} {resp.text}")
        sys.exit(1)
    results = resp.json()
    success = results[0].get("success") if isinstance(results, list) else None
    print(f"  SF {action} {work_item_id} → success={success}")


def waiver_tier(waiver_id: str) -> str | None:
    """Query Tier__c for a waiver Case."""
    rec = sf.query_one(f"SELECT Tier__c FROM Case WHERE Id = '{waiver_id}' LIMIT 1")
    return rec.get("Tier__c") if rec else None


def check_decision_date(case_id: str) -> str | None:
    """Query and return Approval_Decision_Date__c for a Case."""
    rec = sf.query_one(
        f"SELECT Approval_Decision_Date__c FROM Case WHERE Id = '{case_id}' LIMIT 1"
    )
    return rec.get("Approval_Decision_Date__c") if rec else None


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Pick the first school available to the dev user.
    r = client.get("/api/schools")
    schools = r.json().get("schools", [])
    if not schools:
        print("No schools found for this dev identity — check DEV_CONTACT_ID.")
        sys.exit(1)
    school_id = schools[0]["id"]
    school_name = schools[0].get("name", school_id)
    print(f"\nUsing school: {school_name} ({school_id})\n")

    # 2. Submit closures for 7/23 and 7/24.
    print("--- Creating closures ---")
    resp_approve = post_closure(school_id, "2026-07-23", "approve-test")
    resp_reject  = post_closure(school_id, "2026-07-24", "reject-test")

    waiver_approve = resp_approve.get("waiver_case_id")
    waiver_reject  = resp_reject.get("waiver_case_id")

    # 3. Discard Tier 1 waivers — Route_Waiver_By_Tier auto-returns them
    #    immediately and never submits to an approval process, so calling
    #    process/approvals/ on them gives INVALID_CROSS_REFERENCE_KEY.
    for slot, wid in [("approve", waiver_approve), ("reject", waiver_reject)]:
        if wid:
            t = waiver_tier(wid)
            if t not in ("Tier 2", "Tier 3"):
                print(f"  Auto-created waiver {wid} is {t} — skipping "
                      f"(auto-returned by flow, no approval process item).")
                if slot == "approve":
                    waiver_approve = None
                else:
                    waiver_reject = None

    # Fall back to existing Tier 2/3 waivers for any empty slot.
    if not waiver_approve or not waiver_reject:
        print("\nSearching for existing Draft/Submitted Tier 2 or Tier 3 waivers …")
        existing = client.get("/api/waivers").json().get("waivers", [])
        candidates = [
            w for w in existing
            if w.get("tier") in ("Tier 2", "Tier 3")
            and w.get("status") in ("Draft", "Submitted")
            and w["id"] not in (waiver_approve, waiver_reject)
        ]
        needed = (0 if waiver_approve else 1) + (0 if waiver_reject else 1)
        if len(candidates) < needed:
            print(f"  Found {len(candidates)} candidate(s), need {needed}. "
                  "Create Tier-2/3 waivers in SF (Draft status) and re-run.")
            sys.exit(1)
        idx = 0
        if not waiver_approve:
            waiver_approve = candidates[idx]["id"]
            print(f"  Using existing waiver for approve test: {waiver_approve}")
            idx += 1
        if not waiver_reject:
            waiver_reject = candidates[idx]["id"]
            print(f"  Using existing waiver for reject test:  {waiver_reject}")

    # 4. Submit both waivers (Route_Waiver_By_Tier flow → approval process).
    print("\n--- Submitting waivers ---")
    submit_waiver(waiver_approve)
    submit_waiver(waiver_reject)

    # Allow the async flow + approval process submission to settle.
    print("  (waiting 3 s for SF async processing …)")
    time.sleep(3)

    # 5. Approve the first, reject the second via SF REST API.
    #    process/approvals/ requires the ProcessInstanceWorkitem Id (04i...),
    #    not the Case Id (500...).
    print("\n--- Resolving approval work items ---")
    wi_approve = get_work_item_id(waiver_approve)
    wi_reject  = get_work_item_id(waiver_reject)
    print(f"  approve work item: {wi_approve}")
    print(f"  reject  work item: {wi_reject}")
    if not wi_approve or not wi_reject:
        print("  One or both waivers have no pending work item — the flow may not "
              "have submitted them yet, or they were already processed.")
        sys.exit(1)

    print("\n--- Running SF approval actions ---")
    sf_approval_action(wi_approve, "Approve", "test_approve_reject: approve path")
    sf_approval_action(wi_reject,  "Reject",  "test_approve_reject: reject path")

    # Allow field updates to commit.
    time.sleep(2)

    # 6. Verify Approval_Decision_Date__c is set on both.
    print("\n--- Verifying Approval_Decision_Date__c ---")
    date_approve = check_decision_date(waiver_approve)
    date_reject  = check_decision_date(waiver_reject)

    ok_approve = bool(date_approve)
    ok_reject  = bool(date_reject)

    print(f"  Approve waiver {waiver_approve}: Approval_Decision_Date__c = {date_approve!r}  "
          f"{'PASS' if ok_approve else 'FAIL'}")
    print(f"  Reject  waiver {waiver_reject}: Approval_Decision_Date__c = {date_reject!r}  "
          f"{'PASS' if ok_reject else 'FAIL'}")

    if ok_approve and ok_reject:
        print("\nAll checks passed.")
    else:
        print("\nOne or more checks FAILED — deploy the updated metadata and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
