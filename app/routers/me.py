"""GET /api/me — the authenticated user's profile (name + primary role)."""
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/me", tags=["me"])

# Per-contact cache keyed by contact_id. Profile and role change very rarely;
# 10 min TTL keeps it fresh without hammering Salesforce on every page load.
_ME_CACHE: dict[str, dict] = {}
_ME_TTL_SECONDS = 600


class MeResponse(BaseModel):
    contact_id: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None
    primary_role: str | None = None


@router.get("", response_model=MeResponse)
def get_me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the authenticated user's Contact name fields and primary role."""
    now = time.monotonic()
    cached = _ME_CACHE.get(user.contact_id)
    if cached and now < cached["expires_at"]:
        return cached["data"]

    record = sf.query_one(
        f"SELECT Id, FirstName, LastName, Name FROM Contact WHERE Id = '{user.contact_id}' LIMIT 1"
    )

    # Primary Contact_Role first, fall back to any active role.
    role_record = sf.query_one(
        "SELECT Role__c FROM Contact_Role__c "
        f"WHERE Contact__c = '{user.contact_id}' AND isActive__c = true "
        "ORDER BY Primary__c DESC LIMIT 1"
    )

    if not record:
        response = MeResponse(contact_id=user.contact_id, name=user.name)
    else:
        response = MeResponse(
            contact_id=record["Id"],
            first_name=record.get("FirstName"),
            last_name=record.get("LastName"),
            name=record.get("Name"),
            primary_role=role_record.get("Role__c") if role_record else None,
        )

    _ME_CACHE[user.contact_id] = {"data": response, "expires_at": now + _ME_TTL_SECONDS}
    return response
