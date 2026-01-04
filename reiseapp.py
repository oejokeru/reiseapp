import os
import math
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import List

import streamlit as st
from amadeus import Client, ResponseError

# ======================================================
# Amadeus (fra Secrets)
# ======================================================
AMADEUS = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
)

# ======================================================
# Transfer-profiler
# ======================================================
OUTBOUND = dict(
    min_transfer=120,
    bonus_ideal=-800,
    penalty_ok=800,
    penalty_long=2500,
    penalty_overnight=6000,
    penalty_too_short=12000,
    cost_per_flight_hour=400,
    cost_per_layover=1500,
)

HOME = dict(
    min_transfer=120,
    bonus_ideal=-200,
    penalty_ok=300,
    penalty_long=900,
    penalty_overnight=2000,
    penalty_too_short=12000,
    cost_per_flight_hour=350,
    cost_per_layover=1200,
)

AIRLINE_BOOKING_URLS = {
    "LH": "https://www.lufthansa.com",
    "SQ": "https://www.singaporeair.com",
    "QR": "https://www.qatarairways.com",
    "EK": "https://www.emirates.com",
    "TK": "https://www.turkishairlines.com",
    "QF": "https://www.qantas.com",
    "VA": "https://www.virginaustralia.com",
    "MH": "https://www.malaysiaairlines.com",
}

# ======================================================
# Datamodeller
# ======================================================
@dataclass
class Leg:
    origin: str
    dest: str
    depart: str
    arrive: str
    airline: str
    flight: str

@dataclass
class Offer:
    origin: str
    dest: str
    depart_date: str
    price: int
    legs: List[Leg]

# ======================================================
# UI
# ======================================================
st.set_page_config(page_title="Reiseapp – Stabil", layout="wide")
st.title("✈️ Reiseapp – Stabil (TOPP 5)")
st.caption("Inline detaljer • ingen hopping • robust mot 0 treff")

# ======================================================
# Sidebar – passasjerer
# ======================================================
st.sidebar.header("👨‍👩‍👧‍👦 Passasjerer")
adult_base = st.sidebar.number_input("Voksne (18+)", 1, 6, 2)
n_children = st.sidebar.number_input("Barn (0–17)", 0, 6, 3)

child_ages = []
for i in range(n_children):
    child_ages.append(
        st.sidebar.number_input(f"Alder barn {i+1}", 0, 17, [15, 13, 8][i] if i < 3 else 8)
    )

adults = adult_base
children = 0
for a in child_ages:
    if a >= 12:
        adults += 1
    else:
        children += 1

# ======================================================
# Sidebar – rutevalg
# ======================================================
st.sidebar.header("🌍 Flyplasser")
asia_arrival = st.sidebar.selectbox("Asia – ankomst", ["SIN", "KUL", "BKK"])
asia_depart = st.sidebar.selectbox("Asia – avreise", ["SIN", "KUL", "BKK"], index=1)
aus_arrival = st.sidebar.selectbox("Australia – ankomst", ["MEL", "SYD"])
aus_depart = st.sidebar.selectbox("Australia – avreise", ["MEL", "SYD"], index=1)

# ======================================================
# Sidebar – datoer
# ======================================================
st.sidebar.header("📅 Reisetid")
start_osl = st.sidebar.date_input("OSL → Asia", date(2026, 7, 1))
flex = st.sidebar.slider("Fleksibilitet ± dager", 0, 3, 1)
asia_stay = st.sidebar.slider("Opphold Asia (dager)", 5, 30, (8, 12))
aus_stay = st.sidebar.slider("Opphold Australia (dager)", 5, 20, (6, 12))

# ======================================================
# Helper-funksjoner
# ======================================================
def dt(s): return datetime.strptime(s, "%Y-%m-%d %H:%M")
def minutes(a, b): return int((b - a).total_seconds() / 60)
def flight_hours(a, b): return (b - a).total_seconds() / 3600

def route_codes(legs):
    path = [legs[0].origin] + [l.dest for l in legs]
    out = []
    for p in path:
        if not out or out[-1] != p:
            out.append(p)
    return " → ".join(out)

def analyze(o: Offer, profile):
    score = o.price
    prev = None
    red, yellow, green = [], [], []

    for leg in o.legs:
        d, a = dt(leg.depart), dt(leg.arrive)
        score += flight_hours(d, a) * profile["cost_per_flight_hour"]

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

    score += (len(o.legs) - 1) * profile["cost_per_layover"]
    return score, red, yellow, green

# ======================================================
# Amadeus-søk (cached)
# ======================================================
@st.cache_data(ttl=60 * 60 * 6)
def search(origin, dest, d):
    try:
        res = AMADEUS.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=dest,
            departureDate=str(d),
            adults=adults,
            children=children,
            max=25,
            currencyCode="NOK",
        )
        offers = []
        for o in res.data:
            legs = []
            for it in o["itineraries"]:
                for s in it["segments"]:
                    legs.append(
                        Leg(
                            origin=s["departure"]["iataCode"],
                            dest=s["arrival"]["iataCode"],
                            airline=s["carrierCode"],
                            flight=f"{s['carrierCode']}{s['number']}",
                            depart=s["departure"]["at"].replace("T", " ")[:16],
                            arrive=s["arrival"]["at"].replace("T", " ")[:16],
                        )
                    )
            offers.append(
                Offer(
                    origin=origin,
                    dest=dest,
                    depart_date=str(d),
                    price=int(float(o["price"]["total"])),
                    legs=legs,
                )
            )
        return offers
    except ResponseError:
        return []

def search_block(origin, dest, dates):
    out = []
    for d in dates:
        out += search(origin, dest, d)
    return out

# ======================================================
# Render TOPP 5 – TRYGG
# ======================================================
def render_top(title, offers, profile):
    if not offers:
        st.warning(f"Ingen treff for {title}. Prøv andre datoer eller flyplasser.")
        return None

    scored = [(o, *analyze(o, profile)) for o in offers]
    scored.sort(key=lambda x: (len(x[2]) > 0, len(x[3]) > 0, x[1]))
    top = scored[:5]

    st.subheader(title)
    for i, (o, score, red, yellow, green) in enumerate(top, start=1):
        badge = "🟢"
        if red: badge = "🔴"
        elif yellow: badge = "🟡"

        with st.expander(f"{badge} {i}. {route_codes(o.legs)} • {o.price:,} kr"):
            st.write(f"**Dato:** {o.depart_date}")
            for leg in o.legs:
                st.write(
                    f"{leg.origin} → {leg.dest} | "
                    f"{leg.airline} {leg.flight} | "
                    f"{leg.depart} → {leg.arrive}"
                )

            if red:
                st.error("Røde flagg")
                for r in red: st.write("🔴", r)
            elif yellow:
                st.warning("Kompromiss")
                for y in yellow: st.write("🟡", y)
            else:
                st.success("Ser veldig bra ut")

            airline = o.legs[0].airline
            if airline in AIRLINE_BOOKING_URLS:
                st.markdown(f"[Flyselskap]({AIRLINE_BOOKING_URLS[airline]})")
            st.markdown(
                f"[Google Flights]"
                f"(https://www.google.com/travel/flights?q={o.origin}-{o.dest}-{o.depart_date})"
            )

    return top[0][0].depart_date

# ======================================================
# START
# ======================================================
if not st.button("🔍 Start scan"):
    st.stop()

# ======================================================
# 1) OSL → Asia
# ======================================================
st.header("1️⃣ OSL → Asia")
dates1 = [start_osl + timedelta(days=i) for i in range(-flex, flex + 1)]
offers1 = search_block("OSL", asia_arrival, dates1)
asia_base = render_top("OSL → Asia (TOPP 5)", offers1, OUTBOUND)
if not asia_base:
    st.stop()

# ======================================================
# 2) Asia → Australia
# ======================================================
st.header("2️⃣ Asia → Australia")
start2 = date.fromisoformat(asia_base) + timedelta(days=asia_stay[0])
dates2 = [start2 + timedelta(days=i) for i in range(3)]
offers2 = search_block(asia_depart, aus_arrival, dates2)
aus_base = render_top("Asia → Australia (TOPP 5)", offers2, OUTBOUND)
if not aus_base:
    st.stop()

# ======================================================
# 3) Australia → OSL
# ======================================================
st.header("3️⃣ Australia → OSL")
start3 = date.fromisoformat(aus_base) + timedelta(days=aus_stay[0])
dates3 = [start3 + timedelta(days=i) for i in range(3)]
offers3 = search_block(aus_depart, "OSL", dates3)
render_top("Australia → OSL (TOPP 5)", offers3, HOME)

st.success("Scan fullført – klikk på et alternativ for detaljer.")
