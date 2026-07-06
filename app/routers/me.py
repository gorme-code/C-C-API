"""GET /api/me — the authenticated user's profile (name fields)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth import CurrentUser, get_current_user
from app.services.salesforce import sf

router = APIRouter(prefix="/api/me", tags=["me"])


class MeResponse(BaseModel):
    contact_id: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None


@router.get("", response_model=MeResponse)
def get_me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the authenticated user's Contact name fields."""
    record = sf.query_one(
        f"SELECT Id, FirstName, LastName, Name FROM Contact WHERE Id = '{user.contact_id}' LIMIT 1"
    )
    if not record:
        return MeResponse(contact_id=user.contact_id, name=user.name)
    return MeResponse(
        contact_id=record["Id"],
        first_name=record.get("FirstName"),
        last_name=record.get("LastName"),
        name=record.get("Name"),
    )
