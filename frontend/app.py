import streamlit as st
import requests
from datetime import date, timedelta

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI Trip Planner (Free)", layout="wide")

st.title("🧳 AI Trip Planner (FREE)")
st.caption("No paid APIs. Works with local Ollama if installed, otherwise uses a smart fallback.")

tab1, tab2 = st.tabs(["Plan a Trip", "History"])

with tab1:
    col1, col2 = st.columns(2)

    with col1:
        destination = st.text_input("Destination", value="Istanbul, Turkey")
        party_type = st.selectbox("Who is going?", ["solo", "couple", "family", "friends"])
        budget = st.selectbox("Budget", ["cheap", "balanced", "luxury", "flexible"])

    with col2:
        today = date.today()
        start_date = st.date_input("Start date", value=today + timedelta(days=7))
        end_date = st.date_input("End date", value=today + timedelta(days=10))
        interests = st.multiselect("Interests", ["food", "history", "culture", "nature", "shopping"], default=["food"])

    if start_date > end_date:
        st.error("Start date must be <= end date")

    if st.button("✨ Build My Itinerary", type="primary"):
        payload = {
            "destination": destination,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "party_type": party_type,
            "budget": budget,
            "interests": interests
        }

        with st.spinner("Generating itinerary..."):
            r = requests.post(f"{API_BASE}/trip/build", json=payload, timeout=180)

        if r.status_code != 200:
            st.error(f"API error: {r.status_code}\n{r.text}")
        else:
            data = r.json()
            st.success("Done ✅")

            st.subheader(data["title"])
            if data.get("notes"):
                st.info(data["notes"])

            for day in data["days"]:
                st.markdown(f"### Day {day['day_index']} — {day['date']}")
                for a in day["activities"]:
                    st.write(f"**{a['start_time']}–{a['end_time']}** • {a['title']}  \n"
                             f"_{a['category']}_ • {a.get('location','')}")
                    if a.get("description"):
                        st.caption(a["description"])
                st.divider()

with tab2:
    if st.button("🔄 Refresh history"):
        st.rerun()

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
                st.divider()
