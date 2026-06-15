"""Salesforce connection and shared query helpers.

Loads SF_CLIENT_ID, SF_CLIENT_SECRET, SF_INSTANCE_URL, SF_API_VERSION (plus the
flow-specific vars) from the environment via pydantic-settings, and builds an
authenticated ``simple_salesforce.Salesforce`` instance using EITHER:

  * the username/password flow, or
  * the connected-app JWT bearer flow.

The connection is cached and transparently refreshed when the session token
expires. A single ``sf`` singleton is exported for use across routers — the
Python API is the ONLY thing that talks to Salesforce (see section 1 of the
API guide).
"""
from __future__ import annotations

from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError as SFLibError

from app.config import settings
from app.errors import SalesforceError


def _build_username_password() -> Salesforce:
    """Authenticate via the SOAP username/password (+ security token) flow."""
    return Salesforce(
        username=settings.sf_username,
        password=settings.sf_password,
        security_token=settings.sf_security_token,
        domain=settings.sf_domain,
        version=settings.sf_api_version,
    )


def _build_jwt() -> Salesforce:
    """Authenticate via the connected-app JWT bearer flow.

    Uses either an on-disk PEM key (SF_JWT_KEY_FILE) or the key contents
    supplied directly (SF_JWT_KEY).
    """
    kwargs: dict[str, Any] = {
        "username": settings.sf_username,
        "consumer_key": settings.sf_client_id,
        "domain": settings.sf_domain,
        "version": settings.sf_api_version,
    }
    if settings.sf_jwt_key_file:
        kwargs["privatekey_file"] = settings.sf_jwt_key_file
    elif settings.sf_jwt_key:
        kwargs["privatekey"] = settings.sf_jwt_key
    else:
        raise SalesforceError(
            "JWT flow selected but neither SF_JWT_KEY_FILE nor SF_JWT_KEY is set."
        )
    return Salesforce(**kwargs)


def _select_flow() -> str:
    """Resolve which auth flow to use from config / available credentials."""
    flow = (settings.sf_auth_flow or "auto").lower()
    if flow in ("username_password", "jwt"):
        return flow
    # auto: prefer JWT if a key is present, else username/password.
    if settings.sf_jwt_key_file or settings.sf_jwt_key:
        return "jwt"
    if settings.sf_username and settings.sf_password:
        return "username_password"
    raise SalesforceError(
        "No Salesforce credentials configured. Set SF_USERNAME/SF_PASSWORD for "
        "the username/password flow, or SF_JWT_KEY_FILE/SF_JWT_KEY for JWT."
    )


def get_sf_connection() -> Salesforce:
    """Return a freshly authenticated simple_salesforce Salesforce instance.

    Chooses the username/password flow or the connected-app JWT flow based on
    SF_AUTH_FLOW (or auto-detection). Raises SalesforceError on auth failure.
    """
    flow = _select_flow()
    try:
        if flow == "jwt":
            return _build_jwt()
        return _build_username_password()
    except SFLibError as exc:  # pragma: no cover - network path
        raise SalesforceError(f"Salesforce authentication failed: {exc}") from exc


class SalesforceService:
    """Lazy, self-refreshing wrapper around a cached Salesforce connection."""

    def __init__(self) -> None:
        self._client: Salesforce | None = None

    @property
    def client(self) -> Salesforce:
        """Return the cached authenticated client, creating one on first use."""
        if self._client is None:
            self._client = get_sf_connection()
        return self._client

    def reset(self) -> None:
        """Drop the cached client so the next call re-authenticates."""
        self._client = None

    # --- Query / DML helpers (used across routers) ---------------------

    def query(self, soql: str) -> list[dict[str, Any]]:
        return self._with_refresh(lambda: self.client.query_all(soql)["records"])

    def query_one(self, soql: str) -> dict[str, Any] | None:
        records = self.query(soql)
        return records[0] if records else None

    def create(self, sobject: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._with_refresh(lambda: getattr(self.client, sobject).create(data))

    def update(self, sobject: str, record_id: str, data: dict[str, Any]) -> int:
        return self._with_refresh(
            lambda: getattr(self.client, sobject).update(record_id, data)
        )

    def _with_refresh(self, fn):
        """Run a SF call; on an expired-session error, re-auth once and retry."""
        try:
            return fn()
        except SFLibError as exc:
            if _is_auth_error(exc):
                self.reset()
                try:
                    return fn()
                except SFLibError as retry_exc:  # pragma: no cover
                    raise SalesforceError(str(retry_exc)) from retry_exc
            raise SalesforceError(str(exc)) from exc


def _is_auth_error(exc: SFLibError) -> bool:
    """True when the error looks like an expired / invalid session."""
    if getattr(exc, "status", None) in (401, 403):
        return True
    return "INVALID_SESSION_ID" in str(exc).upper()


# Single shared instance used across all routers.
sf = SalesforceService()
