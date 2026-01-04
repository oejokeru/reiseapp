import os
import math
from datetime import datetime, date, timedelta

import streamlit as st
from amadeus import Client, ResponseError

# ======================================================
# Amadeus client (leses fra Streamlit Secrets / env)
# ======================================================
AMADEUS = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
)

# ======================================================
# Enkle “profiler” for transfer-score
# ======================================================
OUTBOUND = dict(
    min_transfer=120,
    bonus_ideal=-800,         # 120–200
    penalty_ok=800,           # 200–360
    penalty_long=2500,        # 360–480
    penalty_overnight=6000,   # >480
    penalty_too_short=12000,  # <120
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

AIRPORT_INFO = {
    "OSL": ("Oslo Gardermoen", "Norge", "Oversiktlig og effektiv hovedflyplass."),
    "SIN": ("Singapore Changi", "Singapore", "En av verdens beste flyplasser. Veldig familievennlig."),
    "KUL": ("Kuala Lumpur", "Malaysia", "Ofte billig innfallsport til Sørøst-Asia."),
    "BKK": ("Bangkok Suvarnabhumi", "Thailand", "Stor og travel hub. Mange ruter."),
    "MEL": ("Melbourne", "Australia", "God inngang til Australia. Ofte gunstig videre."),
    "SYD": ("Sydney", "Australia", "Større knutepunkt. Mange ruter, kan være dyrere."),
    "FRA": ("Frankfurt", "Tyskland", "Stor hub. Vanlig mellomlanding."),
    "MUC": ("München", "Tyskland", "Ofte effektiv transfer."),
    "DOH": ("Doha", "Qatar", "Moderne og familievennlig hub."),
    "DXB": ("Dubai", "UAE", "Stor hub, lange avstander."),
    "IST": ("Istanbul", "Tyrkia", "Svært stor hub."),
}

AIRLINE_BOOKING_URLS = {
    "LH": "https://www.lufthansa.com",
    "SQ": "https://www.singaporeair.com",
    "SK": "https://www.flysas.com",
    "QR": "https://www.qatarairways.com",
    "EK": "https://www.emirates.com",
    "TK": "https://www.turkishairlines.com",
    "QF": "https://www.qantas.com",
    "VA": "https://www.virginaustralia.com",
}

# ======================================================
# App
# ======================================================
st.set_page_config(page_title="Reiseapp – Stabil LIVE", layout="wide")
st.title("✈️ Reiseapp – Stabil LIVE (open jaw)")
st.caption("Stabilt i Streamlit Cloud: færre kall, smalere søk, cache og tydelig progresjon.")

# ======================================================
# Sidebar – passasjerer
# ======================================================
st.sidebar.header("👨‍👩‍👧‍👦 Passasjerer")
adult_base = st.sidebar.number_input("Voksne (18+)", 1, 6, 2)
n_children = st.sidebar.number_input("Barn (0–17)", 0, 6, 3)

child_ages = []
for i in range(n_children):
    default = [15, 13, 8][i] if i < 3 else 8
    child_ages.append(st.sidebar.number_input(f"Alder barn {i+1}", 0, 17, default, key=f"age_{i}"))

# 12+ regnes som voksen (som dere ønsket)
adults = adult_base
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
if infants > 0:
    st.warning("⚠️ Infant (<2 år) er registrert. Ikke fullt støttet i denne versjonen (kan gi avvik ved booking).")

# ======================================================
# Sidebar – flyplasser (open jaw, men én valgt i hver boks)
# ======================================================
st.sidebar.divider()
st.sidebar.header("🌍 Flyplasser")

asia_codes = ["SIN", "KUL", "BKK"]
aus_codes = ["MEL", "SYD"]

asia_arrival = st.sidebar.selectbox("Asia – ankomst (OSL → Asia)", asia_codes, index=0)
asia_depart = st.sidebar.selectbox("Asia – avreise (Asia → Australia)", asia_codes, index=1 if "KUL" in asia_codes else 0)

aus_arrival = st.sidebar.selectbox("Australia – ankomst (Asia → Australia)", aus_codes, index=0)
aus_depart = st.sidebar.selectbox("Australia – avreise (Australia → OSL)", aus_codes, index=1 if len(aus_codes) > 1 else 0)

# ======================================================
# Sidebar – datoer (smalere søk)
# ======================================================
st.sidebar.divider()
st.sidebar.header("📅 Reiseplan")

oslasia_depart = st.sidebar.date_input("Avreise OSL → Asia", date(2026, 7, 1))

# Viktig: hold flex lav for stabilitet i cloud
flex = st.sidebar.slider("Fleksibilitet (± dager) – anbefalt 0–2", 0, 4, 2)

asia_stay = st.sidebar.slider("Opphold i Asia (min–maks dager)", 5, 30, (8, 12))
aus_stay = st.sidebar.slider("Opphold i Australia (min–maks dager)", 5, 20, (6, 12))

# ======================================================
# Helpers
# ======================================================
def dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() / 60)

def flight_hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600.0

def airport_label(code: str) -> str:
    info = AIRPORT_INFO.get(code)
    if not info:
        return code
    return f"{info[0]} ({code}), {info[1]}"

def airport_note(code: str) -> str:
    info = AIRPORT_INFO.get(code)
    return info[2] if info else "Ingen ekstra info lagt inn ennå."

def route_readable(legs) -> str:
    if not legs:
        return ""
    path = [legs[0]["from"]] + [l["to"] for l in legs]
    cleaned = []
    for x in path:
        if not cleaned or cleaned[-1] != x:
            cleaned.append(x)
    return " → ".join(airport_label(x) for x in cleaned)

def primary_airline(legs):
    for leg in legs:
        cc = leg.get("airline")
        if cc in AIRLINE_BOOKING_URLS:
            return cc
    return None

def google_flights_link(origin: str, dest: str, d: date) -> str:
    return f"https://www.google.com/travel/flights?q={origin}-{dest}-{d}"

def pick_dates_slim(start: date, end: date, extra_each_side: int) -> list[date]:
    """
    Stabil strategi: søk midten av intervallet først, og bare et lite belte rundt.
    """
    if end < start:
        return [start]
    days = (end - start).days
    mid = start + timedelta(days=days // 2)
    dates = [mid]
    for i in range(1, extra_each_side + 1):
        if mid - timedelta(days=i) >= start:
            dates.append(mid - timedelta(days=i))
        if mid + timedelta(days=i) <= end:
            dates.append(mid + timedelta(days=i))
    return dates

def analyze_offer(offer, profile):
    score = offer["price"]
    prev_arr = None
    total_h = 0.0
    red, yellow, green = [], [], []

    for leg in offer["legs"]:
        d = dt(leg["depart"])
        a = dt(leg["arrive"])
        total_h += flight_hours(d, a)
        score += flight_hours(d, a) * profile["cost_per_flight_hour"]

        if prev_arr:
            t = minutes(prev_arr, d)
            if t < profile["min_transfer"]:
                red.append(f"For kort transfertid ({t} min)")
                score += profile["penalty_too_short"]
            elif t <= 200:
                green.append(f"Ideell transfertid ({t} min)")
                score += profile["bonus_ideal"]
            elif t <= 360:
                yellow.append(f"Litt lang transfertid ({t} min)")
                score += profile["penalty_ok"]
            elif t <= 480:
                yellow.append(f"Lang transfertid ({t} min)")
                score += profile["penalty_long"]
            else:
                red.append(f"Overnatting / ekstrem transfer ({t} min)")
                score += profile["penalty_overnight"]

        prev_arr = a

    score += (len(offer["legs"]) - 1) * profile["cost_per_layover"]
    return {
        "score": int(score),
        "flight_hours": round(total_h, 1),
        "layovers": max(0, len(offer["legs"]) - 1),
        "red": red, "yellow": yellow, "green": green
    }

def bucket(a):
    if a["red"]:
        return 2
    if a["yellow"]:
        return 1
    return 0

# ======================================================
# Amadeus call (cached)
# ======================================================
@st.cache_data(ttl=60 * 60 * 6)  # 6 timer cache
def amadeus_search_cached(origin: str, dest: str, depart_date: str, adults_n: int, children_n: int, max_results: int = 20):
    try:
        res = AMADEUS.shopping.flight_offers_search.get(
            originLocationCode=origin,
            destinationLocationCode=dest,
            departureDate=depart_date,
            adults=adults_n,
            children=children_n,
            max=max_results,
            currencyCode="NOK",
        )
        offers = []
        for o in res.data:
            legs = []
            for it in o["itineraries"]:
                for s in it["segments"]:
                    legs.append({
                        "from": s["departure"]["iataCode"],
                        "to": s["arrival"]["iataCode"],
                        "airline": s["carrierCode"],
                        "flight": f"{s['carrierCode']}{s['number']}",
                        "depart": s["departure"]["at"].replace("T", " ")[:16],
                        "arrive": s["arrival"]["at"].replace("T", " ")[:16],
                    })
            offers.append({
                "origin": origin,
                "dest": dest,
                "depart_date": depart_date,
                "price": int(float(o["price"]["total"])),
                "legs": legs,
                "google_link": google_flights_link(origin, dest, date.fromisoformat(depart_date)),
            })
        return offers
    except ResponseError:
        return []
    except Exception:
        # ekstra robusthet (cloud nett)
        return []

def search_many(origin: str, dest: str, dates: list[date], max_total_calls: int = 10):
    """
    Stabil: veldig få kall.
    """
    offers = []
    calls = 0
    prog = st.progress(0.0)
    status = st.empty()

    for d in dates:
        if calls >= max_total_calls:
            break
        calls += 1
        status.write(f"Søker {origin} → {dest} dato {d} ({calls}/{max_total_calls})")
        offers.extend(amadeus_search_cached(origin, dest, str(d), adults, children, max_results=20))
        prog.progress(calls / max_total_calls)

    prog.empty()
    status.empty()
    return offers

def render_best(title: str, offers: list[dict], profile: dict):
    st.subheader(title)

    if not offers:
        st.error("Ingen treff i dette søket.")
        return None, None

    scored = [(o, analyze_offer(o, profile)) for o in offers]
    scored.sort(key=lambda x: (bucket(x[1]), x[1]["score"]))

    best_o, best_a = scored[0]
    per_person = math.ceil(best_o["price"] / max(1, total_pax))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totalpris", f"{best_o['price']:,} kr")
    c2.metric("≈ per person", f"{per_person:,} kr")
    c3.metric("Flytimer", best_a["flight_hours"])
    c4.metric("Layovers", best_a["layovers"])

    st.markdown(f"**Rute:** {route_readable(best_o['legs'])}")

    if best_a["red"]:
        st.error("❌ Røde flagg")
        for r in best_a["red"]:
            st.write("🔴", r)
    elif best_a["yellow"]:
        st.warning("⚠️ Kompromiss")
        for y in best_a["yellow"]:
            st.write("🟡", y)
    else:
        st.success("✅ Ser veldig bra ut")
        for g in best_a["green"]:
            st.write("✔️", g)

    with st.expander("Detaljer + flyplassinfo + lenker"):
        prev = None
        for i, leg in enumerate(best_o["legs"], start=1):
            st.markdown(
                f"### Etappe {i}: {leg['from']} → {leg['to']}\n"
                f"**{airport_label(leg['from'])}** → **{airport_label(leg['to'])}**  \n"
                f"{leg['airline']} {leg['flight']}  \n"
                f"🕒 {leg['depart']} → {leg['arrive']}"
            )
            st.info(f"ℹ️ {leg['to']}: {airport_note(leg['to'])}")
            if prev:
                t = minutes(prev, dt(leg["depart"]))
                st.write(f"⏱️ Transfertid: **{t} min**")
            prev = dt(leg["arrive"])

        carrier = primary_airline(best_o["legs"])
        if carrier:
            st.markdown(f"[🛫 Flyselskap ({carrier})]({AIRLINE_BOOKING_URLS[carrier]})")
        st.markdown(f"[🌍 Google Flights]({best_o['google_link']})")

    # vis noen alternativer, men ikke mange
    with st.expander("Flere alternativer (topp 5)"):
        for idx, (o, a) in enumerate(scored[1:6], start=2):
            st.write(f"{idx}. {o['origin']}→{o['dest']} {o['depart_date']} • {o['price']:,} kr • score {a['score']}")

    return best_o, best_a

# ======================================================
# Plan / knapp
# ======================================================
st.markdown("### 🧭 Valgt open jaw-plan (stabil modus)")
st.write(
    f"- OSL → **{asia_arrival}**\n"
    f"- Asia → Australia: **{asia_depart} → {aus_arrival}**\n"
    f"- Australia → OSL: **{aus_depart} → OSL**\n"
    f"- Flex: ±{flex} dager (hold lav for stabilitet)"
)

run = st.button("🔍 Start stabil scan")
if not run:
    st.stop()

st.info(f"Passasjerer: **{adults} voksne + {children} barn** (12+ regnes som voksne).")

# ======================================================
# 1) OSL → ASIA (smalt søk)
# ======================================================
st.markdown("## 1) OSL → Asia")
dates_osl_asia = [oslasia_depart + timedelta(days=i) for i in range(-flex, flex + 1)]
offers1 = search_many("OSL", asia_arrival, dates_osl_asia, max_total_calls=min(len(dates_osl_asia), 7))

best1, _a1 = render_best("Beste OSL → Asia", offers1, OUTBOUND)
if not best1:
    st.stop()

# Base-date for Asia-opphold beregnes fra avreisedato (stabil)
asia_base = date.fromisoformat(best1["depart_date"])

# ======================================================
# 2) ASIA → AUSTRALIA (STABIL: én valgt rute + få datoer)
# ======================================================
st.markdown("## 2) Asia → Australia (stabil)")
asia_to_aus_start = asia_base + timedelta(days=asia_stay[0])
asia_to_aus_end = asia_base + timedelta(days=asia_stay[1])

# Søker kun midt + et lite belte rundt (ikke hele intervallet)
dates_asia_aus = pick_dates_slim(asia_to_aus_start, asia_to_aus_end, extra_each_side=flex)

offers2 = search_many(asia_depart, aus_arrival, dates_asia_aus, max_total_calls=min(len(dates_asia_aus), 7))
best2, _a2 = render_best("Beste Asia → Australia", offers2, OUTBOUND)

if not best2:
    st.warning(
        "Ingen treff på denne kombinasjonen akkurat nå.\n\n"
        "Tips (stabilt):\n"
        "• Bytt Asia-avreise (SIN/KUL/BKK)\n"
        "• Bytt Australia-ankomst (MEL/SYD)\n"
        "• Hold flex lav (0–2)\n"
        "• Prøv igjen (cache hjelper også)"
    )
    st.stop()

aus_base = date.fromisoformat(best2["depart_date"])

# ======================================================
# 3) AUSTRALIA → OSL (stabil)
# ======================================================
st.markdown("## 3) Australia → OSL (stabil)")
home_start = aus_base + timedelta(days=aus_stay[0])
home_end = aus_base + timedelta(days=aus_stay[1])
dates_home = pick_dates_slim(home_start, home_end, extra_each_side=flex)

offers3 = search_many(aus_depart, "OSL", dates_home, max_total_calls=min(len(dates_home), 7))
best3, _a3 = render_best("Beste Australia → OSL", offers3, HOME)

if not best3:
    st.stop()

# ======================================================
# Oppsummering
# ======================================================
st.divider()
st.markdown("## ✅ Oppsummering")
st.write(
    f"**OSL → {asia_arrival}**  \n"
    f"**{asia_depart} → {aus_arrival}**  \n"
    f"**{aus_depart} → OSL**"
)
st.caption(
    "Denne versjonen er laget for å være stabil i Streamlit Cloud: "
    "smalere søk, færre API-kall, og cache. Bytt kombinasjoner i menyen og trykk scan igjen for å utforske."
)
