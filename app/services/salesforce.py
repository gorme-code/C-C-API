"""Salesforce connection and shared query helpers.

A single ``sf`` singleton is exported for use across routers. It lazily
authenticates via OAuth 2.0 client credentials, caches the connection, and
refreshes automatically when the session token expires.

The Python API is the ONLY thing that talks to Salesforce — see section 1 of
the API guide.
"""
from __future__ import annotations

from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError as SFLibError

from app.config import settings
from app.errors import SalesforceError


class SalesforceService:
    """Lazy, self-refreshing wrapper around a simple_salesforce client."""

    def __init__(self) -> None:
        self._client: Salesforce | None = None

    def _authenticate(self) -> Salesforce:
        """Create an authenticated Salesforce client via client credentials.

        Uses the OAuth 2.0 client credentials flow against the connected app.
        """
        try:
            return Salesforce(
                instance_url=settings.sf_instance_url,
                consumer_key=settings.sf_client_id,
                consumer_secret=settings.sf_client_secret,
                version=settings.sf_api_version,
            )
        except SFLibError as exc:  # pragma: no cover - network path
            raise SalesforceError(f"Salesforce authentication failed: {exc}") from exc

    @property
    def client(self) -> Salesforce:
        """Return a cached authenticated client, creating one if needed."""
        if self._client is None:
            self._client = self._authenticate()
        return self._client

    def reset(self) -> None:
        """Drop the cached client so the next call re-authenticates."""
        self._client = None

    # --- Query helpers -------------------------------------------------

    def query(self, soql: str) -> list[dict[str, Any]]:
        """Run a SOQL query and return the records list.

        Retries once on an auth failure (e.g. expired session token).
        """
        try:
            return self.client.query_all(soql)["records"]
        except SFLibError as exc:
            if _is_auth_error(exc):
                self.reset()
                try:
                    return self.client.query_all(soql)["records"]
                except SFLibError as retry_exc:  # pragma: no cover
                    raise SalesforceError(str(retry_exc)) from retry_exc
            raise SalesforceError(str(exc)) from exc

    def query_one(self, soql: str) -> dict[str, Any] | None:
        records = self.query(soql)
        return records[0] if records else None

    def create(self, sobject: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            return getattr(self.client, sobject).create(data)
        except SFLibError as exc:
            if _is_auth_error(exc):
                self.reset()
            raise SalesforceError(str(exc)) from exc

    def update(self, sobject: str, record_id: str, data: dict[str, Any]) -> int:
        try:
            return getattr(self.client, sobject).update(record_id, data)
        except SFLibError as exc:
            if _is_auth_error(exc):
                self.reset()
            raise SalesforceError(str(exc)) from exc


def _is_auth_error(exc: SFLibError) -> bool:
    status = getattr(exc, "status", None)
    return status in (401, 403)


def get_sf_connection() -> Salesforce:
    """Return the authenticated simple_salesforce client (raw)."""
    return sf.client


# Single shared instance used across all routers.
sf = SalesforceService()
