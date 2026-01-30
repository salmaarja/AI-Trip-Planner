from pydantic import BaseModel, Field
from datetime import date
from typing import List, Optional

class TripRequestIn(BaseModel):
    destination: str = Field(..., examples=["Istanbul, Turkey"])
    start_date: date
    end_date: date
    party_type: str = Field(..., examples=["solo", "couple", "family", "friends"])
    budget: str = Field(..., examples=["cheap", "balanced", "luxury", "flexible"])
    interests: List[str] = Field(default_factory=list, examples=[["food", "history"]])

class ItineraryActivityOut(BaseModel):
    start_time: str
    end_time: str
    title: str
    category: str
    location: Optional[str] = None
    description: Optional[str] = None

class ItineraryDayOut(BaseModel):
    day_index: int
    date: date
    activities: List[ItineraryActivityOut]

class ItineraryOut(BaseModel):
    itinerary_id: int
    title: str
    notes: Optional[str] = None
    days: List[ItineraryDayOut]
