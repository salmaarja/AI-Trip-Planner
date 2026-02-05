from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from datetime import date
from typing import List

from .db import Base, engine, SessionLocal
from .models import TripRequest, Itinerary, ItineraryDay, ItineraryActivity
from .schemas import TripRequestIn, ItineraryOut, ItineraryDayOut, ItineraryActivityOut
from .services.itinerary_generator import generate_itinerary_structured

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Trip Planner (Free)")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root():
    return {"message": "AI Trip Planner API is running", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/trip/build", response_model=ItineraryOut)
def build_trip(payload: TripRequestIn, db: Session = Depends(get_db)):
    # 1) save trip request
    tr = TripRequest(
        destination=payload.destination,
        start_date=payload.start_date,
        end_date=payload.end_date,
        party_type=payload.party_type,
        budget=payload.budget,
        interests=",".join(payload.interests)
    )
    db.add(tr)
    db.commit()
    db.refresh(tr)

    # 2) generate itinerary (free mode: local ollama or fallback)
    data = generate_itinerary_structured(
        destination=payload.destination,
        start_date=payload.start_date,
        end_date=payload.end_date,
        party_type=payload.party_type,
        budget=payload.budget,
        interests=payload.interests
    )

    # 3) save itinerary
    it = Itinerary(
        trip_request_id=tr.id,
        title=data.get("title", f"Trip to {payload.destination}"),
        notes=data.get("notes")
    )
    db.add(it)
    db.commit()
    db.refresh(it)

    # 4) save days+activities
    for day_obj in data.get("days", []):
        day_date = day_obj.get("date")
        d = ItineraryDay(
            itinerary_id=it.id,
            day_index=int(day_obj["day_index"]),
            date=date.fromisoformat(day_date) if isinstance(day_date, str) else day_date
        )
        db.add(d)
        db.commit()
        db.refresh(d)

        for a in day_obj.get("activities", []):
            db.add(ItineraryActivity(
                day_id=d.id,
                start_time=a["start_time"],
                end_time=a["end_time"],
                title=a["title"],
                category=a.get("category", "activity"),
                location=a.get("location"),
                description=a.get("description")
            ))
        db.commit()

    # 5) return assembled response
    db.refresh(it)
    days_out = []
    for d in it.days:
        acts = [
            ItineraryActivityOut(
                start_time=a.start_time,
                end_time=a.end_time,
                title=a.title,
                category=a.category,
                location=a.location,
                description=a.description
            )
            for a in d.activities
        ]
        days_out.append(ItineraryDayOut(day_index=d.day_index, date=d.date, activities=acts))

    return ItineraryOut(itinerary_id=it.id, title=it.title, notes=it.notes, days=days_out)

@app.get("/trip/history", response_model=List[ItineraryOut])
def trip_history(db: Session = Depends(get_db)):
    items = db.query(Itinerary).order_by(Itinerary.created_at.desc()).limit(20).all()
    out = []
    for it in items:
        days_out = []
        for d in it.days:
            acts = [
                ItineraryActivityOut(
                    start_time=a.start_time,
                    end_time=a.end_time,
                    title=a.title,
                    category=a.category,
                    location=a.location,
                    description=a.description
                )
                for a in d.activities
            ]
            days_out.append(ItineraryDayOut(day_index=d.day_index, date=d.date, activities=acts))
        out.append(ItineraryOut(itinerary_id=it.id, title=it.title, notes=it.notes, days=days_out))
    return out
