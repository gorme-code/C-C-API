"""Pydantic request/response models for makeup days."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class MakeupCreateRequest(BaseModel):
    closure_event_ids: list[str]
    makeup_date: date
    method: str
    hours_covered: float
    external_id: str  # idempotency key


class ClosureEventStatusUpdate(BaseModel):
    id: str
    new_status: str


class MakeupCreateResponse(BaseModel):
    makeup_day_id: str
    links_created: int
    closure_events_updated: list[ClosureEventStatusUpdate] = Field(default_factory=list)
