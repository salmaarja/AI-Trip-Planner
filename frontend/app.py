import streamlit as st
import requests
from datetime import date, timedelta

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI Trip Planner (FREE)", layout="wide")

# ---------- Helpers ----------
STEPS = [
    "Trip Basics",
    "Who is going?",
    "Preferences",
    "Budget",
    "Review & Generate"
]

def init_state():
    if "step" not in st.session_state:
        st.session_state.step = 0

    # form data
    st.session_state.setdefault("destination", "Istanbul, Turkey")
    st.session_state.setdefault("start_date", date.today() + timedelta(days=7))
    st.session_state.setdefault("end_date", date.today() + timedelta(days=10))
    st.session_state.setdefault("party_type", "solo")
    st.session_state.setdefault("interests", ["food"])
    st.session_state.setdefault("budget", "cheap")

    # result
    st.session_state.setdefault("last_result", None)

def stepper(current_step: int):
    # Top header
    st.title("🧳 AI Trip Planner (FREE)")
    st.caption("No paid APIs. Works with local Ollama if installed, otherwise uses a smart fallback.")

    # Progress bar
    progress = int(((current_step + 1) / len(STEPS)) * 100)
    st.progress(progress)

    # Step labels row
    cols = st.columns(len(STEPS))
    for i, name in enumerate(STEPS):
        if i < current_step:
            cols[i].markdown(f"✅ **{i+1}. {name}**")
        elif i == current_step:
            cols[i].markdown(f"➡️ **{i+1}. {name}**")
        else:
            cols[i].markdown(f"◻️ {i+1}. {name}")

    st.divider()

def can_go_next(step: int) -> bool:
    # minimal validation for each step
    if step == 0:
        return bool(st.session_state.destination.strip()) and st.session_state.start_date <= st.session_state.end_date
    if step == 2:
        # preferences: allow empty? we will require at least 1 for better UX
        return len(st.session_state.interests) > 0
    return True

def nav_buttons():
    col1, col2, col3 = st.columns([1, 1, 6])

    with col1:
        back_disabled = st.session_state.step == 0
        if st.button("⬅ Back", disabled=back_disabled):
            st.session_state.step -= 1
            st.session_state.last_result = None  # optional: clear old results while editing
            st.rerun()

    with col2:
        next_disabled = (st.session_state.step == len(STEPS) - 1) or (not can_go_next(st.session_state.step))
        if st.button("Next ➡", disabled=next_disabled):
            st.session_state.step += 1
            st.session_state.last_result = None
            st.rerun()

def generate_itinerary():
    payload = {
        "destination": st.session_state.destination,
        "start_date": str(st.session_state.start_date),
        "end_date": str(st.session_state.end_date),
        "party_type": st.session_state.party_type,
        "budget": st.session_state.budget,
        "interests": st.session_state.interests
    }

    with st.spinner("Generating itinerary..."):
        r = requests.post(f"{API_BASE}/trip/build", json=payload, timeout=600)

    if r.status_code != 200:
        st.error(f"API error: {r.status_code}\n{r.text}")
        return

    st.session_state.last_result = r.json()
    st.success("Done ✅")

def show_itinerary(data: dict):
    st.subheader(data["title"])
    if data.get("notes"):
        st.info(data["notes"])

    for day in data["days"]:
        st.markdown(f"### Day {day['day_index']} — {day['date']}")
        for a in day["activities"]:
            st.write(
                f"**{a['start_time']}–{a['end_time']}** • {a['title']}  \n"
                f"_{a['category']}_ • {a.get('location','')}"
            )
            if a.get("description"):
                st.caption(a["description"])
        st.divider()

# ---------- UI ----------
init_state()

tab_plan, tab_history = st.tabs(["Plan a Trip", "History"])

with tab_plan:
    stepper(st.session_state.step)

    # Step content
    if st.session_state.step == 0:
        st.header("Step 1: Trip Basics")
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.destination = st.text_input("Destination", st.session_state.destination)
        with col2:
            st.session_state.start_date = st.date_input("Start date", st.session_state.start_date)
            st.session_state.end_date = st.date_input("End date", st.session_state.end_date)

        if st.session_state.start_date > st.session_state.end_date:
            st.error("Start date must be <= end date")

    elif st.session_state.step == 1:
        st.header("Step 2: Who is going?")
        st.session_state.party_type = st.selectbox(
            "Select party type",
            ["solo", "couple", "family", "friends"],
            index=["solo", "couple", "family", "friends"].index(st.session_state.party_type)
        )
        st.caption("This helps tailor the itinerary (pace, activities, recommendations).")

    elif st.session_state.step == 2:
        st.header("Step 3: Preferences")
        st.session_state.interests = st.multiselect(
            "Pick your interests",
            ["food", "history", "culture", "nature", "shopping"],
            default=st.session_state.interests
        )
        if len(st.session_state.interests) == 0:
            st.warning("Please select at least one interest to generate a better plan.")

    elif st.session_state.step == 3:
        st.header("Step 4: Budget")
        st.session_state.budget = st.selectbox(
            "Choose budget level",
            ["cheap", "balanced", "luxury", "flexible"],
            index=["cheap", "balanced", "luxury", "flexible"].index(st.session_state.budget)
        )

    elif st.session_state.step == 4:
        st.header("Step 5: Review & Generate")

        colA, colB = st.columns([2, 3])
        with colA:
            st.markdown("#### Summary")
            st.write(f"**Destination:** {st.session_state.destination}")
            st.write(f"**Dates:** {st.session_state.start_date} → {st.session_state.end_date}")
            st.write(f"**Who:** {st.session_state.party_type}")
            st.write(f"**Budget:** {st.session_state.budget}")
            st.write(f"**Interests:** {', '.join(st.session_state.interests) if st.session_state.interests else '—'}")

            st.markdown("---")
            if st.button("✨ Build My Itinerary", type="primary"):
                generate_itinerary()

        with colB:
            st.markdown("#### Result")
            if st.session_state.last_result:
                show_itinerary(st.session_state.last_result)
            else:
                st.info("Click **Build My Itinerary** to generate your plan.")

    # Navigation buttons (hide on last step? no—keep Back available)
    if st.session_state.step < len(STEPS) - 1:
        nav_buttons()
    else:
        # Last step: allow Back but no Next
        col1, _, _ = st.columns([1, 1, 6])
        with col1:
            if st.button("⬅ Back"):
                st.session_state.step -= 1
                st.session_state.last_result = None
                st.rerun()

with tab_history:
    st.title("📜 History")

    if st.button("🔄 Refresh history"):
        st.rerun()

    try:
        r = requests.get(f"{API_BASE}/trip/history", timeout=30)
        if r.status_code != 200:
            st.error(f"API error: {r.status_code}\n{r.text}")
        else:
            trips = r.json()
            if not trips:
                st.info("No saved trips yet.")
            else:
                for t in trips:
                    st.markdown(f"## {t['title']}")
                    if t.get("notes"):
                        st.caption(t["notes"])
                    st.write(f"Itinerary ID: {t['itinerary_id']} | Days: {len(t['days'])}")
                    with st.expander("View details"):
                        show_itinerary(t)
                    st.divider()
    except Exception as e:
        st.error(f"Could not reach backend at {API_BASE}. Is FastAPI running?\n\n{e}")
