from datetime import timedelta
from typing import List, Dict
from .ollama_client import generate_with_ollama
import json
import requests
from urllib.parse import quote
import time


WIKI_CACHE: dict[str, dict] = {}
PHOTO_CACHE: dict[str, str] = {}
GEOCODE_CACHE: dict[str, tuple[float, float]] = {}

def _key(act: dict) -> str:
    t = (act.get("title") or "").strip().lower()
    loc = (act.get("location") or "").strip().lower()
    return f"{t}__{loc}"


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

SHOPPING_SUGGESTIONS = {
    "haifa": [
        ("Downtown shopping streets", "shopping", "Browse local boutiques and small shops in the city center."),
        ("Local mall visit", "shopping", "Spend time in a shopping mall with budget-friendly stores."),
        ("Market for souvenirs", "shopping", "Pick up local souvenirs, gifts, and snacks."),
        ("Second-hand / vintage shops", "shopping", "Explore thrift and vintage finds."),
    ]
}

def get_destination_media(destination: str) -> dict:
    if destination in WIKI_CACHE:
        return WIKI_CACHE[destination]

    # fetch Wikipedia summary + image
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{destination.replace(' ', '_')}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return {}

    j = r.json()
    media = {
        "info_url": j.get("content_urls", {}).get("desktop", {}).get("page"),
        "image_url": j.get("thumbnail", {}).get("source"),
    }

    WIKI_CACHE[destination] = media
    return media


def wiki_search_enrich(query: str) -> dict:
    """
    Uses Wikipedia REST API (free) to get a thumbnail + canonical page URL.
    Returns: {"image_url": str|None, "info_url": str|None}
    """
    q = query.strip().lower()
    if not q:
        return {"image_url": None, "info_url": None}

    if q in WIKI_CACHE:
        return WIKI_CACHE[q]

    # Wikipedia opensearch (lightweight)
    url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit=1&namespace=0&format=json"
    try:
        r = requests.get(url, timeout=10).json()
        if len(r) >= 4 and r[1]:
            title = r[1][0]
            page_url = r[3][0] if r[3] else f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"

            # get page image thumbnail
            img_api = (
                "https://en.wikipedia.org/w/api.php"
                f"?action=query&titles={quote(title)}&prop=pageimages&pithumbsize=640&format=json"
            )
            q2 = requests.get(img_api, timeout=10).json()
            pages = q2.get("query", {}).get("pages", {})
            thumb = None
            for _, p in pages.items():
                thumb = (p.get("thumbnail") or {}).get("source")
                break

            out = {"image_url": thumb, "info_url": page_url}
        else:
            out = {"image_url": None, "info_url": None}
    except Exception:
        out = {"image_url": None, "info_url": None}

    WIKI_CACHE[q] = out
    return out


def build_from_pool_unique(
    destination: str,
    start_date,
    end_date,
    days_count: int,
    poi_pool: List[dict],
) -> dict:
    """
    Build a multi-day itinerary by walking through the POI pool
    sequentially, ensuring no repeated activities across days.
    """

    data = {
        "title": f"{destination} – {days_count}-Day Trip",
        "notes": "Generated using free local data (fallback mode, no AI).",
        "days": []
    }

    pool_index = 0
    total_pois = len(poi_pool)

    if total_pois == 0:
        raise ValueError("POI pool is empty; cannot build itinerary")

    for day_idx in range(days_count):
        day_date = start_date + timedelta(days=day_idx)
        activities = []

        for slot_idx, (st, et, _) in enumerate(TIME_SLOTS):
            poi = poi_pool[pool_index % total_pois]
            pool_index += 1

            activities.append({
                "start_time": st,
                "end_time": et,
                "title": poi.get("title", "Activity"),
                "category": poi.get("category", "food"),
                "location": poi.get("location", destination),
                "description": poi.get("description", ""),
                "image_url": poi.get("image_url"),
            })

        data["days"].append({
            "day_index": day_idx + 1,
            "date": str(day_date),
            "activities": activities
        })

    return data


def fetch_pois_osm(destination: str, interests: List[str], limit: int = 60) -> List[dict]:
    interests_l = [i.lower().strip() for i in interests]

    # 1) Geocode city -> lat/lon using Nominatim (free)
    geo = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": destination, "format": "json", "limit": 1},
        headers={"User-Agent": "ai-trip-planner/1.0"},
        timeout=20
    ).json()

    if not geo:
        return []

    lat = float(geo[0]["lat"])
    lon = float(geo[0]["lon"])

    # 2) Overpass query for food + tourism nearby (free)
    radius = 7000  # 6km around city center

    want_shopping = "shopping" in interests_l
    want_food = "food" in interests_l

    # Build interest-aware Overpass blocks
    blocks = []


    if want_food or not interests_l:
        blocks += [
            "node(around:{r},{lat},{lon})[amenity=restaurant];",
            "node(around:{r},{lat},{lon})[amenity=cafe];",
            "node(around:{r},{lat},{lon})[amenity=fast_food];",
            "node(around:{r},{lat},{lon})[amenity=marketplace];",
        ]

    if want_shopping:
        blocks += [
            "node(around:{r},{lat},{lon})[shop];",
            "way(around:{r},{lat},{lon})[shop];",
            "node(around:{r},{lat},{lon})[shop=mall];",
            "way(around:{r},{lat},{lon})[shop=mall];",
            "node(around:{r},{lat},{lon})[amenity=shopping_mall];",
            "way(around:{r},{lat},{lon})[amenity=shopping_mall];",
        ]

        # Always allow some sightseeing diversity (optional)
        blocks += [
            "node(around:{r},{lat},{lon})[tourism=attraction];",
            "node(around:{r},{lat},{lon})[tourism=museum];",
            "node(around:{r},{lat},{lon})[tourism=viewpoint];",
        ]

    blocks_str = "\n      ".join(b.format(r=radius, lat=lat, lon=lon) for b in blocks)

    overpass_query = f"""
        [out:json][timeout:25];
        (
          {blocks_str}
        );
        out tags center;
        """

    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": overpass_query},
        headers={"User-Agent": "ai-trip-planner/1.0"},
        timeout=60
    ).json()

    elements = r.get("elements", [])
    pois = []

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        # Categorize
        if tags.get("amenity") in {"restaurant", "cafe", "fast_food"}:
            cat = "food"
        elif tags.get("amenity") == "marketplace":
            cat = "market"
        elif "shop" in tags or tags.get("amenity") in {"shopping_mall"}:
            cat = "shopping"
        elif tags.get("tourism") in {"attraction", "museum", "viewpoint"}:
            cat = "sightseeing"
        else:
            cat = "culture"

        loc = destination
        if "addr:street" in tags:
            loc = f"{name}, {tags.get('addr:street')}"

        #enriched = wiki_search_enrich(f"{name} {destination}")

        pois.append({
            "title": name,
            "category": cat,
            "location": loc,
            "description": tags.get("description") or f"Visit {name} in {destination}.",
            #"image_url": enriched.get("image_url"),
            #"info_url": enriched.get("info_url"),
            "image_url": None,
            "info_url": None,
        })

    # De-dupe
    seen = set()
    unique = []
    for p in pois:
        k = (p["title"].lower(), p["category"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(p)

    return unique[:limit]

def _enforce_uniqueness(data: dict, poi_pool: List[dict], destination: str) -> dict:
    used = set()
    pool_idx = 0

    for day in data.get("days", []):
        acts = day.get("activities", [])
        for j, act in enumerate(acts):
            # normalize category like "food|market"
            cat = act.get("category")
            if isinstance(cat, str) and "|" in cat:
                act["category"] = cat.split("|")[0].strip()

            k = _key(act)
            if not k or k in used or (act.get("title", "").strip().lower() in {"activity", "local restaurant"}):
                # replace from pool until unique
                while pool_idx < len(poi_pool):
                    candidate = poi_pool[pool_idx]
                    pool_idx += 1
                    cand_act = {
                        "start_time": act.get("start_time"),
                        "end_time": act.get("end_time"),
                        "title": candidate["title"],
                        "category": candidate["category"],
                        "location": candidate.get("location") or destination,
                        "description": candidate.get("description") or "",
                        "image_url": candidate.get("image_url"),  # optional
                    }
                    ck = _key(cand_act)
                    if ck and ck not in used:
                        act.update(cand_act)
                        k = ck
                        break

            if k:
                used.add(k)

    return data


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

def _normalize_ai_output(data: dict, destination: str, start_date, days_count: int, poi_pool: List[dict]) -> dict:
    # fallback pool
    plan_items = poi_pool if poi_pool else _fallback_plan(destination, [])

    if not isinstance(data, dict):
        raise ValueError("AI output is not a dict")

    days = data.get("days", [])
    if not isinstance(days, list):
        raise ValueError("AI output days is not a list")

    fixed_days = []
    for i in range(days_count):
        day_date = start_date + timedelta(days=i)

        day_obj = days[i] if i < len(days) and isinstance(days[i], dict) else {}
        activities = day_obj.get("activities", [])
        if not isinstance(activities, list):
            activities = []

        fixed_acts = []
        for slot_idx, (st, et, _) in enumerate(TIME_SLOTS):
            act = activities[slot_idx] if slot_idx < len(activities) and isinstance(activities[slot_idx], dict) else {}

            # pick fallback item for missing fields
            fb = plan_items[(i * 2 + slot_idx) % len(plan_items)]

            title = act.get("title") or fb["title"]
            category = act.get("category") or fb["category"]
            # normalize "food|market" -> "food"
            if isinstance(category, str) and "|" in category:
                category = category.split("|")[0].strip()

            location = act.get("location") or destination
            description = act.get("description") or fb["description"]

            fixed_acts.append({
                "start_time": act.get("start_time") or st,
                "end_time": act.get("end_time") or et,
                "title": title,
                "category": category,
                "location": location,
                "description": description,
            })

        fixed_days.append({
            "day_index": i + 1,
            "date": str(day_date),
            "activities": fixed_acts
        })

    data["title"] = data.get("title") or f"{destination} – {days_count}-Day Trip"
    data["notes"] = data.get("notes") or "Generated with local AI (Ollama) when available."
    data["days"] = fixed_days
    return data


def build_poi_pool(destination: str, interests: List[str]) -> List[dict]:
    key = destination.lower().strip()

    # 1) if we have curated city list (like Istanbul) use it first
    curated = FOOD_SUGGESTIONS.get(key, [])
    pool = [{"title": t, "category": c, "description": d, "location": destination} for (t, c, d) in curated]

    # 2) add dynamic OSM places
    try:
        osm = fetch_pois_osm(destination, interests, limit=60)
        pool.extend(osm)
    except Exception:
        pass

    # if still empty, last-resort generic
    if not pool:
        pool = [
            {"title": "Local food market", "category": "market", "location": destination, "description": "Explore local market stalls and taste seasonal food."},
            {"title": "Signature street food", "category": "food", "location": destination, "description": "Try the city’s most famous street food."},
            {"title": "Traditional restaurant", "category": "food", "location": destination, "description": "Book a local restaurant and try classic dishes."},
            {"title": "Dessert tasting", "category": "food", "location": destination, "description": "Sample local desserts and coffee/tea."},
        ]

    return pool


def _fallback_plan(destination: str, interests: List[str]) -> List[Dict]:
    key = destination.split(",")[0].strip().lower()

    interests_l = [i.lower().strip() for i in interests]

    if "shopping" in interests_l:
        picks = SHOPPING_SUGGESTIONS.get(key, [
            ("Local mall visit", "shopping", "Visit a mall with budget-friendly stores."),
            ("Shopping street walk", "shopping", "Walk through popular shopping streets and browse shops."),
            ("Souvenir market", "shopping", "Buy gifts, local products, and small souvenirs."),
            ("Outlet / discount stores", "shopping", "Look for discounts and affordable items."),
        ])
        return [{"title": t, "category": c, "description": d} for (t, c, d) in picks]

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
          "category": "food|market|shopping|sightseeing|culture",
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
- If interests include "shopping", make at least 2 of the 4 daily activities shopping-related.
- If interests include "history", make at least 2 of the 4 daily activities history-related.
- If interests include "culture", make at least 2 of the 4 daily activities culture-related.
- If interests include "nature", make at least 2 of the 4 daily activities shopping-related.
- Keep locations realistic, plausible, and varied.
- Use double quotes ONLY for JSON syntax. Do not use quotes inside values.

Example of VALID JSON (this is only an example, do not copy values):
{{"title":"Trip","notes":"...","days":[{{"day_index":1,"date":"2026-02-15","activities":[{{"start_time":"09:00","end_time":"11:00","title":"Activity","category":"food","location":"Istanbul","description":"..."}}]}}]}}
"""

def generate_itinerary_structured(destination: str, start_date, end_date, party_type: str, budget: str, interests: List[str]):
    days_count = (end_date - start_date).days + 1
    dest_media = wiki_search_enrich(destination)

    # Try Ollama first
    prompt = _build_prompt(destination=destination, party_type=party_type,
    budget=budget, interests=interests,
    start_date=str(start_date), end_date=str(end_date),
    days=days_count)
    print("AI mode: trying Ollama...")
    t0 = time.time()

    text = generate_with_ollama(prompt)
    print("Ollama time:", round(time.time() - t0, 2), "sec")

    t1 = time.time()
    poi_pool = build_poi_pool(destination, interests)
    print("POI pool time:", round(time.time() - t1, 2), "sec", "pool size:", len(poi_pool))

    if text is None:
        print("AI mode: Ollama returned None (unavailable/timeout/error) → fallback")

    if text:
        print("AI mode: Ollama response received ✅")
        # try parse JSON safely
        try:
            #data = json.loads(text)
            data = safe_json_loads(text)
            data = _normalize_ai_output(data, destination, start_date, days_count, poi_pool)
            data = _enforce_uniqueness(data, poi_pool, destination)

            dest_media = get_destination_media(destination)
            data["destination_image_url"] = dest_media.get("image_url")
            data["destination_info_url"] = dest_media.get("info_url")
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

    fallback_data = build_from_pool_unique(destination, start_date, end_date, days_count, poi_pool)

    fallback_data["destination_image_url"] = dest_media.get("image_url")
    fallback_data["destination_info_url"] = dest_media.get("info_url")

    return fallback_data

