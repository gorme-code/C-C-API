"""GET /api/district — the authenticated user's district (name + id).

Lets the front-end show the real district name instead of a hardcoded label.
District is resolved from the user's Contact.AccountId (the dev bypass uses
DEV_ACCOUNT_ID while AUTH_DISABLED=true).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/district", tags=["district"])


class DistrictResponse(BaseModel):
    id: str
    name: str | None = None


@router.get("", response_model=DistrictResponse)
def get_district(
    user: CurrentUser = Depends(get_current_user),
) -> DistrictResponse:
    """Return the authenticated user's district Account (id + name)."""
    acc = sf.query_one(
        f"SELECT Id, Name FROM Account WHERE Id = '{user.account_id}' LIMIT 1"
    )
    if not acc:
        return DistrictResponse(id=user.account_id, name=None)
    return DistrictResponse(id=acc["Id"], name=acc.get("Name"))
