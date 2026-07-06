"""Entra ID token validation and Salesforce Contact resolution.

On every request the API:
  1. Validates the Entra ID bearer token against the tenant.
  2. Resolves the user's email/UPN to a Salesforce Contact.
  3. Exposes the Contact (id + district AccountId) so routers can scope
     all queries to the user's district.

See section 1 and Step 5 of the API guide.

Note on libraries: MSAL is the Microsoft-identity library used on the *React*
side to ACQUIRE the token. Validating an inbound token (signature, audience,
expiry) is a JWT-verification job, which MSAL does not perform — so we verify
against the tenant's published JWKS using python-jose. ENTRA_TENANT_ID and
ENTRA_CLIENT_ID drive the issuer and audience checks.
"""
from __future__ import annotations

from functools import lru_cache

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from jose.exceptions import JWTError
from pydantic import BaseModel

from app.config import settings
from app.errors import ContactNotFound, Unauthorized
from app.services.salesforce import sf

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """The validated, district-scoped identity injected into routers."""

    email: str
    contact_id: str
    account_id: str  # the user's district Account Id
    name: str | None = None


@lru_cache
def _jwks() -> dict:
    """Fetch and cache the tenant signing keys (JWKS)."""
    url = (
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
        "/discovery/v2.0/keys"
    )
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def validate_token(token: str) -> dict:
    """Validate an Entra ID bearer token and return its decoded claims.

    Verifies the RS256 signature against the tenant JWKS, the audience against
    ENTRA_CLIENT_ID, and the issuer against ENTRA_TENANT_ID. Raises
    Unauthorized (HTTP 401) on any signature, audience, or expiry failure.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = next((k for k in _jwks().get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise Unauthorized("Signing key not found for token.")

        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.entra_client_id,
            issuer=f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
        )
    except JWTError as exc:
        raise Unauthorized(f"Invalid or expired token: {exc}") from exc


def extract_email(claims: dict) -> str:
    """Pull the user's email/UPN from the decoded claims."""
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if not email:
        raise Unauthorized("Token does not contain an email/UPN claim.")
    return email


def resolve_contact(email: str) -> CurrentUser:
    """Resolve an Entra email to a Salesforce Contact + district.

    The Contact's AccountId is the user's district. This Contact Id becomes
    Reported_By_Contact__c on every record the user creates.
    """
    safe_email = email.replace("'", r"\'")
    record = sf.query_one(
        "SELECT Id, Name, AccountId, Email "
        f"FROM Contact WHERE Email = '{safe_email}' LIMIT 1"
    )
    if not record or not record.get("AccountId"):
        raise ContactNotFound()

    return CurrentUser(
        email=email,
        contact_id=record["Id"],
        account_id=record["AccountId"],
        name=record.get("Name"),
    )


def _dev_bypass_user() -> CurrentUser:
    """Stubbed identity for local dev when AUTH_DISABLED is on.

    Resolves the dev user's district from their Contact_Role records (same
    logic real auth will use), so testing against Salesforce data exercises
    the actual scoping path. Refuses to activate outside development.
    """
    if settings.api_env.lower() != "development":
        raise Unauthorized("AUTH_DISABLED is only permitted in development.")

    role = sf.query_one(
        "SELECT Account__c FROM Contact_Role__c "
        f"WHERE Contact__c = '{settings.dev_contact_id}' "
        "AND Type__c = 'District' AND isActive__c = true "
        "LIMIT 1"
    )
    if not role or not role.get("Account__c"):
        raise Unauthorized(
            f"Dev contact {settings.dev_contact_id} has no active District "
            "Contact_Role — add one in Salesforce or set DEV_ACCOUNT_ID as fallback."
        )

    return CurrentUser(
        email=settings.dev_user_email,
        contact_id=settings.dev_contact_id,
        account_id=role["Account__c"],
        name=settings.dev_user_name,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: validate the token and resolve the Contact.

    Inject this into any router that needs the authenticated, district-scoped
    user identity. With AUTH_DISABLED=true (development only), returns a
    stubbed dev user and skips token validation entirely.
    """
    if settings.auth_disabled:
        return _dev_bypass_user()

    if credentials is None or not credentials.credentials:
        raise Unauthorized("Authorization header missing.")

    claims = validate_token(credentials.credentials)
    email = extract_email(claims)
    return resolve_contact(email)
