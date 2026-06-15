"""Shared test fixtures: mock Salesforce connection and mock auth.

These let routers be tested without a live Salesforce org or Entra tenant.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import CurrentUser, get_current_user


@pytest.fixture
def mock_sf(monkeypatch):
    """Replace the shared `sf` service with a MagicMock in every module."""
    fake = MagicMock()
    fake.query.return_value = []
    fake.query_one.return_value = None
    fake.create.return_value = {"id": "500FAKE0000000000", "success": True}
    fake.update.return_value = 204

    # Patch the singleton wherever it was imported.
    import app.services.salesforce as sf_module
    import app.routers.schools as schools_module
    import app.routers.closures as closures_module
    import app.routers.makeup as makeup_module
    import app.routers.waivers as waivers_module

    for module in (
        sf_module,
        schools_module,
        closures_module,
        makeup_module,
        waivers_module,
    ):
        monkeypatch.setattr(module, "sf", fake, raising=False)

    return fake


@pytest.fixture
def mock_user() -> CurrentUser:
    return CurrentUser(
        email="district.user@example.org",
        contact_id="003DISTRICTAUSER0",
        account_id="001DISTRICTA00000",
        name="Jane Smith",
    )


@pytest.fixture
def client(mock_sf, mock_user) -> TestClient:
    """TestClient with auth dependency overridden to a fixed district user."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
