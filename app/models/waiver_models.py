"""Pydantic request/response models for waiver cases."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Waiver(BaseModel):
    id: str
    case_number: str
    status: str | None = None
    tier: str | None = None
    total_missed_days: float | None = None
    days_made_up: float | None = None
    days_requested_for_waiver: float | None = None
    created_date: datetime | None = None
    closure_events_count: int | None = None


class WaiversListResponse(BaseModel):
    waivers: list[Waiver]


class WaiverAction(str, Enum):
    save = "save"
    submit = "submit"


class WaiverUpdateRequest(BaseModel):
    justification: str | None = None
    board_minutes_attached: bool | None = None
    superintendent_certification: bool | None = None
    days_requested_for_waiver: float | None = None
    action: WaiverAction = WaiverAction.save


class WaiverUpdateResponse(BaseModel):
    success: bool
    waiver_id: str
    new_status: str
    tier: str | None = None
    routing: str | None = None


# --- Board minutes upload (Requirements §9) ----------------------------

class BoardMinutesRequest(BaseModel):
    file_name: str
    content_base64: str  # base64-encoded file contents (no data: prefix)


class BoardMinutesResponse(BaseModel):
    success: bool
    waiver_id: str
    content_document_id: str
    file_name: str
