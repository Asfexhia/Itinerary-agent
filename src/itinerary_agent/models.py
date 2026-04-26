from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserRequest(BaseModel):
    text: str


class ParsedIntent(BaseModel):
    city: str = "Seoul"
    days: int = 1
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "packed"] = "balanced"


class PlaceCandidate(BaseModel):
    place_id: str
    name: str
    category: str = "poi"


class ItineraryItem(BaseModel):
    day: int
    time: str
    title: str
    place_id: str | None = None
    notes: str | None = None


class Itinerary(BaseModel):
    city: str
    days: int
    items: list[ItineraryItem] = Field(default_factory=list)


class AgentState(BaseModel):
    request: UserRequest
    intent: ParsedIntent | None = None
    draft_itinerary: Itinerary | None = None
    enriched_itinerary: Itinerary | None = None
    validation_errors: list[str] = Field(default_factory=list)
    evaluation: dict[str, float] = Field(default_factory=dict)
