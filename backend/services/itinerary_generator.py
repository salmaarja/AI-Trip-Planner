from datetime import timedelta
from typing import List, Dict
from .ollama_client import generate_with_ollama
import json

TIME_SLOTS = [
    ("09:00", "11:00", "Morning"),
    ("12:30", "14:00", "Lunch"),
    ("15:30", "17:30", "Afternoon"),
    ("19:30", "21:30", "Dinner"),
]

FOOD_SUGGESTIONS = {
    "istanbul": [
        ("Grand Bazaar & Spice Bazaar", "market", "Historic markets for spices, sweets, and snacks."),
        ("Karaköy food walk", "food", "Street food + modern cafés (try simit and baklava)."),
        ("Kadıköy Market", "market", "Local Asian-side market: olives, cheese, meze."),
        ("Traditional Turkish breakfast", "food", "Kahvaltı: cheeses, olives, menemen, tea."),
        ("Seafood by the Bosphorus", "food", "Try balik ekmek (fish sandwich) and mezze."),
    ]
}

def _fallback_plan(destination: str, interests: List[str]) -> List[Dict]:
    key = destination.lower()
    picks = FOOD_SUGGESTIONS.get(key, [
        ("Local food market", "market", "Explore local market stalls and taste seasonal food."),
        ("Signature street food", "food", "Try the city’s most famous street food."),
        ("Traditional restaurant", "food", "Book a local restaurant and try classic dishes."),
        ("Dessert tasting", "food", "Sample local desserts and coffee/tea."),
    ])
    # Always focus on food in MVP
    return [{"title": t, "category": c, "description": d} for (t, c, d) in picks]

def _build_prompt(destination: str, party_type: str, budget: str, interests: List[str], days: int) -> str:
    return f"""
You are a travel itinerary planner.
Create a {days}-day itinerary for: {destination}.
Party type: {party_type}. Budget: {budget}. Interests: {', '.join(interests) if interests else 'general'}.

Return STRICT JSON only (no markdown), with this schema:
{{
  "title": "...",
  "notes": "...",
  "days": [
    {{
      "day_index": 1,
      "activities": [
        {{
          "start_time": "09:00",
          "end_time": "11:00",
          "title": "...",
          "category": "food|market|sightseeing|culture",
          "location": "...",
          "description": "..."
        }}
      ]
    }}
  ]
}}

Rules:
- 4 activities per day (morning, lunch, afternoon, dinner)
- Emphasize FOOD experiences if interest includes "food"
- Keep locations plausible and varied
"""

def generate_itinerary_structured(destination: str, start_date, end_date, party_type: str, budget: str, interests: List[str]):
    days_count = (end_date - start_date).days + 1
    # Try Ollama first
    prompt = _build_prompt(destination, party_type, budget, interests, days_count)
    text = generate_with_ollama(prompt)

    if text:
        # try parse JSON safely
        try:
            data = json.loads(text)
            return data
        except Exception:
            # fall back
            pass

    # Fallback (no Ollama / parse failed)
    plan_items = _fallback_plan(destination, interests)
    data = {
        "title": f"{destination} – {days_count}-Day Food-Focused Trip",
        "notes": "Generated in FREE mode (no cloud APIs). You can enable Ollama for richer plans.",
        "days": []
    }

    for i in range(days_count):
        day_date = start_date + timedelta(days=i)
        activities = []
        # choose 4 items cycling
        for slot_idx, (st, et, _) in enumerate(TIME_SLOTS):
            item = plan_items[(i * 2 + slot_idx) % len(plan_items)]
            activities.append({
                "start_time": st,
                "end_time": et,
                "title": item["title"],
                "category": item["category"],
                "location": destination,
                "description": item["description"]
            })
        data["days"].append({"day_index": i + 1, "date": str(day_date), "activities": activities})

    return data
