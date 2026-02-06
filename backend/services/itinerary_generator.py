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
    interests_l = [i.lower().strip() for i in (interests or [])]
    interests_text = ", ".join(interests_l) if interests_l else "general"

    party = (party_type or "solo").lower().strip()
    bud = (budget or "balanced").lower().strip()

    # Party-type rules (this is the key: different inputs => different plan)
    if party in {"family"}:
        party_rules = [
            "Keep the pace relaxed with fewer long walks.",
            "Prefer family-friendly and safe places; avoid nightlife.",
            "Dinner should be early and calm.",
            "Include parks/markets/easy attractions."
        ]
        vibe = "family-friendly, relaxed, safe"
    elif party in {"couple"}:
        party_rules = [
            "Include romantic/beautiful spots (views, waterfront, cozy cafés).",
            "Balance sightseeing with relaxing experiences.",
            "Dinner can be nicer and scenic."
        ]
        vibe = "romantic, relaxed, scenic"
    elif party in {"friends"}:
        party_rules = [
            "More energetic pace is OK.",
            "Include trendy areas, street food, and social places.",
            "Dinner can be later; include optional evening activity."
        ]
        vibe = "social, energetic, trendy"
    else:  # solo
        party_rules = [
            "Mix culture + food + easy navigation.",
            "Prefer safe, well-known areas and clear routes.",
            "Include at least one flexible/free exploration block."
        ]
        vibe = "independent, safe, flexible"

    # Budget rules
    if bud in {"cheap", "low", "budget"}:
        budget_rules = [
            "Prioritize free/low-cost attractions and walking routes.",
            "Use street food, markets, simple local restaurants.",
            "Avoid expensive tours unless clearly worth it."
        ]
        budget_style = "budget-conscious, mostly free/low-cost"
    elif bud in {"luxury", "high"}:
        budget_rules = [
            "Include premium experiences (fine dining, paid attractions, guided tour suggestion).",
            "Prefer comfortable options over long walking.",
            "Quality over quantity."
        ]
        budget_style = "premium, comfort-focused"
    else:  # balanced / medium
        budget_rules = [
            "Mix free attractions with 1 paid highlight per day if appropriate.",
            "Use a mix of casual + one nicer meal."
        ]
        budget_style = "balanced, mixed-cost"

    # Interest rules (weights)
    interest_rules = []
    if "food" in interests_l:
        interest_rules.append("Strongly emphasize food experiences (markets, street food, breakfast/dessert spots).")
    if "shopping" in interests_l:
        interest_rules.append("Include shopping options (bazaars, streets, malls) without repeating the same type daily.")
    if "history" in interests_l:
        interest_rules.append("Include historical/cultural highlights (old town, museums, landmarks).")
    if "culture" in interests_l:
        interest_rules.append("Include cultural experiences (local neighborhoods, art, traditions).")
    if "nature" in interests_l:
        interest_rules.append("Include nature/parks/viewpoints (not shopping).")  # fix your earlier typo
    if not interest_rules:
        interest_rules.append("Keep a general balanced itinerary (food + sightseeing + local area).")

    rules_block = "\n".join(f"- {r}" for r in (party_rules + budget_rules + interest_rules))

    return f"""
You are an AI travel planning system.

Create a {days}-day itinerary for:
Destination: {destination}
Dates: {start_date} to {end_date}
Party type: {party_type}
Budget: {budget}
Interests: {interests_text}

Return STRICT JSON ONLY (no markdown, no extra text) using EXACTLY this schema:

{{
  "title": "...",
  "notes": "Profile: party={party}, budget={bud}, vibe={vibe}, budget_style={budget_style}",
  "explanations": [
    "..."
  ],
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

Hard rules:
- Output must be VALID JSON parseable by Python json.loads()
- Output JSON only (no text before/after)
- Include an "explanations" array with EXACTLY 5 items.

Each explanation MUST:
1. Explicitly mention ONE user input (party_type OR budget OR interests OR trip length).
2. Explain WHY the itinerary decisions match that input.
3. Use causal language (because, therefore, so that).

Bad example:
"Family friendly activities were selected."

Good example:
"Because the party type is family, activities were chosen with short walking distances and safe public areas."

Do NOT repeat the same reasoning twice.

- Generate exactly 4 activities per day (morning, lunch, afternoon, dinner)
- Keep descriptions short (max ~160 characters)
- Avoid using double quotes inside values; if needed escape as \\"
- "notes" MUST be a single string, not a list, not an object.

Party-type rules:
- If party_type = family → prefer safe areas, parks, markets, shorter activities, relaxed pace.
- If party_type = solo → allow longer walks, niche food spots, flexible timing.
- If party_type = couple → prefer romantic areas, scenic cafés, evening dining.
- If party_type = friends → include lively streets, shared food experiences.
Budget rules:
- cheap → street food, markets, free attractions, public spaces.
- medium → mix of casual restaurants and paid attractions.
- luxury → fine dining, premium experiences, fewer but higher-quality activities.
Repetition rules:
- Do NOT repeat the same venue name across different days.
- If a venue appears once, choose a different venue for later meals.
- Variety is required across days.


Planning constraints to follow:
{rules_block}
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
        raise RuntimeError("Ollama is not running or did not return a response.")

    if text:
        print("AI mode: Ollama response received ✅")
        # try parse JSON safely
        try:
            #data = json.loads(text)
            data = safe_json_loads(text)

            # Ensure notes is a string (DB expects TEXT)
            if isinstance(data.get("notes"), list):
                data["notes"] = " | ".join(str(x) for x in data["notes"])

            if "explanations" not in data or not isinstance(data["explanations"], list) or not data["explanations"]:
                raise ValueError("AI output missing explanations[]")

            data = _normalize_ai_output(data, destination, start_date, days_count, poi_pool)
            data = _enforce_uniqueness(data, poi_pool, destination)

            dest_media = get_destination_media(destination)
            data["destination_image_url"] = dest_media.get("image_url")
            data["destination_info_url"] = dest_media.get("info_url")
            return data
        except Exception as e:
            print("---- RAW OLLAMA OUTPUT START ----")
            print(text[:4000])
            print("---- RAW OLLAMA OUTPUT END ----")
            raise RuntimeError(f"Ollama returned invalid JSON: {e}")



