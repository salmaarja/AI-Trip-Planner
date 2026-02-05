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

def safe_json_loads(text: str):
    # try direct
    try:
        return json.loads(text)
    except Exception:
        pass

    # try extracting the largest JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end+1]
        return json.loads(candidate)  # may still raise
    raise ValueError("No valid JSON found")

def _fallback_plan(destination: str, interests: List[str]) -> List[Dict]:
    key = destination.split(",")[0].strip().lower()
    picks = FOOD_SUGGESTIONS.get(key, [
        ("Local food market", "market", "Explore local market stalls and taste seasonal food."),
        ("Signature street food", "food", "Try the city’s most famous street food."),
        ("Traditional restaurant", "food", "Book a local restaurant and try classic dishes."),
        ("Dessert tasting", "food", "Sample local desserts and coffee/tea."),
    ])
    # Always focus on food in MVP
    return [{"title": t, "category": c, "description": d} for (t, c, d) in picks]

def _build_prompt(destination: str, party_type: str, budget: str, interests: List[str],
                  start_date: str, end_date: str, days: int) -> str:
    return f"""
You are a travel itinerary planner.

Create a {days}-day itinerary for: {destination}.
Trip dates: {start_date} to {end_date}.
Party type: {party_type}. Budget: {budget}. Interests: {', '.join(interests) if interests else 'general'}.

Return STRICT JSON only (no markdown, no explanation), exactly this schema:
{{
  "title": "...",
  "notes": "...",
  "days": [
    {{
      "day_index": 1,
      "date": "YYYY-MM-DD",
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
- Return STRICT JSON only.
- Do NOT include markdown.
- Do NOT include comments.
- Do NOT include explanations.
- Do NOT include trailing commas.
- Do NOT include any text before or after the JSON.
- The JSON MUST be valid and parseable by Python json.loads().
- Generate exactly 4 activities per day (morning, lunch, afternoon, dinner).
- Dates must match the trip range and correspond to day_index.
- Emphasize FOOD experiences if interests include "food".
- Keep locations realistic, plausible, and varied.
- Use double quotes ONLY for JSON syntax. Do not use quotes inside values.
Example of VALID JSON (this is only an example, do not copy values):
{{"title":"Trip","notes":"...","days":[{{"day_index":1,"date":"2026-02-15","activities":[{{"start_time":"09:00","end_time":"11:00","title":"Activity","category":"food","location":"Istanbul","description":"..."}}]}}]}}
"""

def generate_itinerary_structured(destination: str, start_date, end_date, party_type: str, budget: str, interests: List[str]):
    days_count = (end_date - start_date).days + 1
    # Try Ollama first
    prompt = _build_prompt(destination=destination, party_type=party_type,
    budget=budget, interests=interests,
    start_date=str(start_date), end_date=str(end_date),
    days=days_count)
    print("AI mode: trying Ollama...")
    text = generate_with_ollama(prompt)

    if text is None:
        print("AI mode: Ollama returned None (unavailable/timeout/error) → fallback")

    if text:
        print("AI mode: Ollama response received ✅")
        # try parse JSON safely
        try:
            #data = json.loads(text)
            data = safe_json_loads(text)
            return data
        except Exception as e:
            # fall back
            print(f"[AI] Ollama returned non-JSON → fallback. Error: {e}")
            print("---- RAW OLLAMA OUTPUT START ----")
            print(text[:2000])  # print first 2000 chars
            print("---- RAW OLLAMA OUTPUT END ----")
            pass

    # Fallback (no Ollama / parse failed)
    print("AI mode: fallback (no Ollama / invalid JSON) ⚠️")

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
