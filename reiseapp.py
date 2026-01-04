import streamlit as st
from datetime import datetime, date, timedelta
import os
import math
import threading
from amadeus import Client, ResponseError

# ======================================================
# AMADEUS
# ======================================================
AMADEUS = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
)

# ======================================================
# TRANSFER-PROFILER
# ======================================================
OUTBOUND = dict(
    bonus_ideal=-800,
    penalty_ok=800,
    penalty_long=2500,
    penalty_overnight=6000,
    penalty_too_short=12000,
    cost_per_flight_hour=400,
    cost_per_layover=1500,
    min_transfer=120,
)

HOME = dict(
    bonus_ideal=-200,
    penalty_ok=300,
    penalty_long=900,
    penalty_overnight=2000,
    penalty_too_short=12000,
    cost_per_flight_hour=350,
    cost_per_layover=1200,
    min_transfer=120,
)

# ======================================================
# APP SETUP
# ======================================================
st.set_page_config("Reiseapp – Komplett", layout="wide")
st.title("✈️ Reiseapp – Komplett (LIVE)")
st.caption("OSL → Asia (open jaw) → Australia (open jaw) → OSL")

# ======================================================
# SIDEBAR – PASSASJERER
# ======================================================
st.sidebar.header("👨‍👩‍👧‍👦 Passasjerer")

adults_base = st.sidebar.number_input("Voksne (18+)", 1, 6, 2)
children_n = st.sidebar.number_input("Barn (0–17)", 0, 6, 3)

child_ages = []
for i in range(children_n):
    child_ages.append(
        st.sidebar.number_input(
            f"Alder barn {i+1}", 0, 17, [15, 13, 8][i] if i < 3 else 8
        )
    )

adults = adults_base
children = 0
infants = 0

for a in child_ages:
    if a < 2:
        infants += 1
    elif a < 12:
        children += 1
    else:
        adults += 1

total_pax = adults + children

# ======================================================
# SIDEBAR – DESTINASJONER
# ======================================================
st.sidebar.header("🌍 Flyplasser")

asia_arrivals = st.sidebar.multiselect(
    "Asia – ankomst",
    ["SIN", "KUL", "BKK"],
    default=["SIN"],
)

asia_departures = st.sidebar.multiselect(
    "Asia – avreise",
    ["SIN", "KUL", "BKK"],
    default=["SIN", "KUL"],
)

aus_arrivals = st.sidebar.multiselect(
    "Australia – ankomst",
    ["MEL", "SYD"],
    default=["MEL", "SYD"],
)

aus_departures = st.sidebar.multiselect(
    "Australia – hjemreise",
    ["MEL", "SYD"],
    default=["MEL", "SYD"],
)

# ======================================================
# SIDEBAR – DATOER
# ======================================================
st.sidebar.header("📅 Reisetid")

start_osl = st.sidebar.date_input("OSL → Asia", date(2026, 7, 1))
flex = st.sidebar.slider("Fleksibilitet ± dager", 0, 7, 3)

asia_stay = st.sidebar.slider("Asia-opphold (dager)", 5, 30, (8, 12))
aus_stay = st.sidebar.slider("Australia-opphold (dager)", 5, 20, (6, 12))

# ======================================================
# HJELPEFUNKSJONER
# ======================================================
def dt(x): 
    return datetime.strptime(x, "%Y-%m-%d %H:%M")

def minutes(a, b): 
    return int((b - a).total_seconds() / 60)

def analyze(offer, profile):
    score = offer["price"]
    prev = None
    red, yellow, green = [], [], []

    for leg in offer["legs"]:
        d, a = dt(leg["depart"]), dt(leg["arrive"])
        score += ((a - d).total_seconds() / 3600) * profile["cost_per_flight_hour"]

        if prev:
            t = minutes(prev, d)
            if t < profile["min_transfer"]:
                red.append(f"For kort transfer ({t} min)")
                score += profile["penalty_too_short"]
            elif t <= 200:
                green.append(f"Ideell transfer ({t} min)")
                score += profile["bonus_ideal"]
            elif t <= 360:
                yellow.append(f"Litt lang transfer ({t} min)")
                score += profile["penalty_ok"]
            else:
                yellow.append(f"Lang transfer ({t} min)")
                score += profile["penalty_long"]
        prev = a

    score += (len(offer["legs"]) - 1) * profile["cost_per_layover"]
    return score, red, yellow, green

def prioritized_dates(start, end):
    days = (end - start).days
    mid = days // 2
    out = []
    for i in range(days + 1):
        for d in (mid + i, mid - i):
            if 0 <= d <= days:
                out.append(start + timedelta(days=d))
    return list(dict.fromkeys(out))

# ======================================================
# HARD TIMEOUT SEARCH (VIKTIG)
# ======================================================
def search(origin, dest, d, timeout_seconds=12):
    result = []

    def _call():
        nonlocal result
        try:
            res = AMADEUS.shopping.flight_offers_search.get(
                originLocationCode=origin,
                destinationLocationCode=dest,
                departureDate=str(d),
                adults=adults,
                children=children,
                max=10,
                currencyCode="NOK",
            )
            for o in res.data:
                legs = []
                for it in o["itineraries"]:
                    for s in it["segments"]:
                        legs.append({
                            "from": s["departure"]["iataCode"],
                            "to": s["arrival"]["iataCode"],
                            "depart": s["departure"]["at"].replace("T", " ")[:16],
                            "arrive": s["arrival"]["at"].replace("T", " ")[:16],
                        })
                result.append({
                    "price": int(float(o["price"]["total"])),
                    "legs": legs
                })
        except Exception:
            pass

    t = threading.Thread(target=_call)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        return []   # hard stop – API hang

    return result

# ======================================================
# START SCAN
# ======================================================
if not st.button("🔍 Start komplett scan"):
    st.stop()

# ======================================================
# 1️⃣ OSL → ASIA
# ======================================================
st.header("1️⃣ OSL → Asia")

offers1 = []
for off in range(-flex, flex + 1):
    for dest in asia_arrivals:
        offers1 += search("OSL", dest, start_osl + timedelta(days=off))

if not offers1:
    st.error("Ingen treff OSL → Asia.")
    st.stop()

best1 = min(offers1, key=lambda o: analyze(o, OUTBOUND)[0])
asia_arrival = best1["legs"][-1]["to"]
asia_date = start_osl

st.success(f"Beste: OSL → {asia_arrival} ({best1['price']:,} kr)")

# ======================================================
# 2️⃣ ASIA → AUSTRALIA (KAN IKKE HENGE)
# ======================================================
st.header("2️⃣ Asia → Australia (stabil modus)")

start = asia_date + timedelta(days=asia_stay[0])
end = asia_date + timedelta(days=asia_stay[1])

MAX_CALLS = 40
calls = 0
offers2 = []

preferred_asia = [asia_arrival] + [a for a in asia_departures if a != asia_arrival]
dates = prioritized_dates(start, end)

progress = st.progress(0.0)
status = st.empty()

for d in dates:
    for origin in preferred_asia:
        for dest in aus_arrivals:
            if calls >= MAX_CALLS:
                break
            status.write(f"Søker {origin} → {dest} ({calls+1}/{MAX_CALLS})")
            offers2 += search(origin, dest, d)
            calls += 1
            progress.progress(calls / MAX_CALLS)
            if offers2:
                break
        if offers2 or calls >= MAX_CALLS:
            break
    if offers2 or calls >= MAX_CALLS:
        break

progress.empty()
status.empty()

if not offers2:
    st.warning(
        "Fant ingen ruter Asia → Australia innenfor rimelig tid.\n\n"
        "Dette er vanlig for Amadeus på denne ruten.\n"
        "Prøv færre Asia-byer eller smalere dato-vindu."
    )
    st.stop()

best2 = min(offers2, key=lambda o: analyze(o, OUTBOUND)[0])
aus_arrival = best2["legs"][-1]["to"]
aus_date = start

st.success(f"Beste: Asia → {aus_arrival} ({best2['price']:,} kr)")

# ======================================================
# 3️⃣ AUSTRALIA → OSL
# ======================================================
st.header("3️⃣ Australia → OSL")

home_start = aus_date + timedelta(days=aus_stay[0])
home_end = aus_date + timedelta(days=aus_stay[1])

offers3 = []
for d in prioritized_dates(home_start, home_end):
    for origin in aus_departures:
        offers3 += search(origin, "OSL", d)
        if offers3:
            break
    if offers3:
        break

if not offers3:
    st.error("Fant ingen hjemreiser Australia → OSL.")
    st.stop()

best3 = min(offers3, key=lambda o: analyze(o, HOME)[0])

st.success(f"Beste: {best3['legs'][0]['from']} → OSL ({best3['price']:,} kr)")

# ======================================================
# OPPSUMMERING
# ======================================================
st.divider()
st.header("✅ Oppsummering")

st.write(f"""
- **OSL → {asia_arrival}**
- **{asia_arrival} → {aus_arrival}**
- **{best3['legs'][0]['from']} → OSL**

Open jaw støttet i Asia og Australia.
""")
