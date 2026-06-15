"""Auth middleware matrix row — no token / bad token → HTTP 401.

Uses a TestClient WITHOUT the get_current_user override so the real
dependency runs. No network is hit: the missing-header and malformed-token
paths both fail before any JWKS fetch.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_no_token_returns_401():
    with TestClient(app) as c:
        resp = c.get("/api/schools")
    assert resp.status_code == 401
    assert resp.json()["error"] == "UNAUTHORIZED"


def test_malformed_token_returns_401():
    with TestClient(app) as c:
        resp = c.get(
            "/api/schools",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
    assert resp.status_code == 401
    assert resp.json()["error"] == "UNAUTHORIZED"
