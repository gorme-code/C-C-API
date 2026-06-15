"""Live PATCH /api/waivers/{id} test. Pass a Tier-3 waiver Case Id as argv[1].

    .venv\\Scripts\\python.exe scripts\\waiver_patch.py <waiver_case_id>

Tests: submit without cert -> 422; then submit with cert -> 200 Submitted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def main(waiver_id: str) -> None:
    print(f"waiver: {waiver_id}")

    r1 = client.patch(f"/api/waivers/{waiver_id}", json={
        "action": "submit", "superintendent_certification": False,
        "justification": "Live test - no cert",
    })
    print(f"\n[submit, NO cert] -> {r1.status_code}  (expect 422)")
    print(f"  {r1.json()}")

    r2 = client.patch(f"/api/waivers/{waiver_id}", json={
        "action": "submit", "superintendent_certification": True,
        "board_minutes_attached": True,
        "justification": "Live test - certified",
    })
    print(f"\n[submit, WITH cert] -> {r2.status_code}  (expect 200 Submitted)")
    print(f"  {r2.json()}")


if __name__ == "__main__":
    main(sys.argv[1])
