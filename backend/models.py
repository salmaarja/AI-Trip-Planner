from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .db import Base

class TripRequest(Base):
    __tablename__ = "trip_requests"

    id = Column(Integer, primary_key=True, index=True)
    destination = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    party_type = Column(String, nullable=False)   # solo/couple/family/friends...
    budget = Column(String, nullable=False)       # cheap/balanced/luxury/flexible
    interests = Column(String, nullable=False)    # comma-separated
    created_at = Column(DateTime, default=datetime.utcnow)

    itinerary = relationship("Itinerary", back_populates="trip_request", uselist=False)

class Itinerary(Base):
    __tablename__ = "itineraries"

    id = Column(Integer, primary_key=True, index=True)
    trip_request_id = Column(Integer, ForeignKey("trip_requests.id"), nullable=False)
    title = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    trip_request = relationship("TripRequest", back_populates="itinerary")
    days = relationship("ItineraryDay", back_populates="itinerary", cascade="all, delete-orphan")

class ItineraryDay(Base):
    __tablename__ = "itinerary_days"

    id = Column(Integer, primary_key=True, index=True)
    itinerary_id = Column(Integer, ForeignKey("itineraries.id"), nullable=False)
    day_index = Column(Integer, nullable=False)  # 1..N
    date = Column(Date, nullable=False)

    itinerary = relationship("Itinerary", back_populates="days")
    activities = relationship("ItineraryActivity", back_populates="day", cascade="all, delete-orphan")

class ItineraryActivity(Base):
    __tablename__ = "itinerary_activities"

    id = Column(Integer, primary_key=True, index=True)
    day_id = Column(Integer, ForeignKey("itinerary_days.id"), nullable=False)
    start_time = Column(String, nullable=False)  # "09:00"
    end_time = Column(String, nullable=False)    # "11:00"
    title = Column(String, nullable=False)
    category = Column(String, nullable=False)    # food/sightseeing/market/...
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    day = relationship("ItineraryDay", back_populates="activities")
