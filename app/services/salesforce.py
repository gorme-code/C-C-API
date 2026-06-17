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

import httpx
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceError as SFLibError

from app.config import settings
from app.errors import SalesforceError


def _build_client_credentials() -> Salesforce:
    """Authenticate via the OAuth 2.0 client-credentials flow.

    This is the Phase 1 production flow: a connected app + integration user,
    using only SF_CLIENT_ID / SF_CLIENT_SECRET (no username/password). Requires
    the connected app to have a "Run As" user set and the flow enabled.
    """
    token_url = settings.sf_instance_url.rstrip("/") + "/services/oauth2/token"
    resp = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.sf_client_id,
            "client_secret": settings.sf_client_secret,
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise SalesforceError(
            f"Client-credentials auth failed ({resp.status_code}): {resp.text}"
        )
    tok = resp.json()
    return Salesforce(
        instance_url=tok["instance_url"],
        session_id=tok["access_token"],
        version=settings.sf_api_version,
    )


def _build_session() -> Salesforce:
    """Authenticate with a pre-issued access token + instance URL.

    Reuses an existing session (e.g. from `sf org auth show-access-token`) so
    local dev needs no password, security token, or connected app. The token
    expires after a few hours — refresh it and update SF_ACCESS_TOKEN when it
    does (you'll see an INVALID_SESSION_ID error).
    """
    if not (settings.sf_access_token and settings.sf_instance_url):
        raise SalesforceError(
            "Session flow needs both SF_ACCESS_TOKEN and SF_INSTANCE_URL."
        )
    return Salesforce(
        instance_url=settings.sf_instance_url,
        session_id=settings.sf_access_token,
        version=settings.sf_api_version,
    )


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
    if flow in ("session", "client_credentials", "username_password", "jwt"):
        return flow
    # auto: session token wins, then JWT, username/password, client-credentials.
    if settings.sf_access_token:
        return "session"
    if settings.sf_jwt_key_file or settings.sf_jwt_key:
        return "jwt"
    if settings.sf_username and settings.sf_password:
        return "username_password"
    if settings.sf_client_id and settings.sf_client_secret:
        return "client_credentials"
    raise SalesforceError(
        "No Salesforce credentials configured. Set SF_CLIENT_ID/SF_CLIENT_SECRET "
        "for client credentials, SF_USERNAME/SF_PASSWORD for username/password, "
        "or SF_JWT_KEY_FILE/SF_JWT_KEY for JWT."
    )


def get_sf_connection() -> Salesforce:
    """Return a freshly authenticated simple_salesforce Salesforce instance.

    Chooses the username/password flow or the connected-app JWT flow based on
    SF_AUTH_FLOW (or auto-detection). Raises SalesforceError on auth failure.
    """
    flow = _select_flow()
    try:
        if flow == "session":
            return _build_session()
        if flow == "client_credentials":
            return _build_client_credentials()
        if flow == "jwt":
            return _build_jwt()
        return _build_username_password()
    except SFLibError as exc:  # pragma: no cover - network path
        raise SalesforceError(f"Salesforce authentication failed: {exc}") from exc


class SalesforceService:
    """Lazy, self-refreshing wrapper around a cached Salesforce connection."""

    def __init__(self) -> None:
        self._client: Salesforce | None = None
        self._rt_cache: dict[tuple[str, str], str] = {}

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

    def record_type_id(self, sobject: str, developer_name: str) -> str:
        """Resolve (and cache) a RecordTypeId by SObject + DeveloperName.

        A record type can only be set on insert via its 18-char Id, not its
        developer name — hence this lookup.
        """
        key = (sobject, developer_name)
        if key not in self._rt_cache:
            record = self.query_one(
                "SELECT Id FROM RecordType "
                f"WHERE SobjectType = '{sobject}' "
                f"AND DeveloperName = '{developer_name}' LIMIT 1"
            )
            if not record:
                raise SalesforceError(
                    f"RecordType {developer_name} not found for {sobject}."
                )
            self._rt_cache[key] = record["Id"]
        return self._rt_cache[key]

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
