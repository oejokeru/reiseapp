import os
import math
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional

import streamlit as st
from amadeus import Client, ResponseError

# ======================================================
# Amadeus (Secrets / env)
# ======================================================
AMADEUS = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
)

# ======================================================
# Profiler (transfer-score)
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

# ======================================================
# Flyplassinfo (kan bygges videre)
# ======================================================
AIRPORT_INFO = {
    "OSL": ("Oslo Gardermoen", "Norge", "Oversiktlig og effektiv hovedflyplass."),
    "SIN": ("Singapore Changi", "Singapore", "En av verdens beste flyplasser. Veldig familievennlig."),
    "KUL": ("Kuala Lumpur", "Malaysia", "Ofte billig innfallsport til Sørøst-Asia."),
    "BKK": ("Bangkok Suvarnabhumi", "Thailand", "Stor og travel hub. Mange ruter."),
    "MEL": ("Melbourne", "Australia", "God inngang til Australia. Ofte gunstig videre."),
    "SYD": ("Sydney", "Australia", "Større knutepunkt. Mange ruter, kan være dyrere."),
    "FRA": ("Frankfurt", "Tyskland", "Stor hub. Vanlig mellomlanding."),
    "MUC": ("München", "Tyskland", "Ofte effektiv transfer."),
    "DOH": ("Doha Hamad", "Qatar", "Moderne og familievennlig hub."),
    "DXB": ("Dubai", "UAE", "Stor hub, lange avstander."),
    "IST": ("Istanbul", "Tyrkia", "Svært stor hub."),
    "AMS": ("Amsterdam", "Nederland", "Ofte effektiv transfer."),
    "CDG": ("Paris CDG", "Frankrike", "Stor. Terminalbytte kan koste tid."),
    "LHR": ("London Heathrow", "Storbritannia", "Travel. God transfertid anbefales."),
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
    "MH": "https://www.malaysiaairlines.com",
}

# ======================================================
# Datamodell
# ======================================================
@dataclass
class Leg:
    origin: str
    dest: str
    depart: str  # "YYYY-MM-DD HH:MM"
    arrive: str  # "YYYY-MM-DD HH:MM"
    airline: str
    flight: str

@dataclass
class Offer:
    origin: str
    dest: str
    depart_date: str  # "YYYY-MM-DD"
    price_total: int  # totalpris fra Amadeus
    legs: List[Leg]
    google_link: str

@dataclass
class Analysis:
    score: int
    flight_hours: float
    layovers: int
    red: List[str]
    yellow: List[str]
    green: List[str]


# ======================================================
# UI setup
# ======================================================
st.set_page_config(page_title="Reiseapp – Topp 5", layout="wide")
st.title("✈️ Reiseapp – LIVE (TOPP 5 klikkbart)")
st.caption("Stabil i Streamlit Cloud: få kall, caching, og full detaljvisning i fokus-seksjon.")

# ======================================================
# Sidebar – passasjerer
# ======================================================
st.sidebar.header("👨‍👩‍👧‍👦 Passasjerer")
adult_base = st.sidebar.number_input("Voksne (18+)", 1, 6, 2)
n_children = st.sidebar.number_input("Barn (0–17)", 0, 6, 3)

child_ages: List[int] = []
for i in range(n_children):
    default = [15, 13, 8][i] if i < 3 else 8
    child_ages.append(st.sidebar.number_input(f"Alder barn {i+1}", 0, 17, default, key=f"age_{i}"))

# 12+ = voksen (som dere ønsket)
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
    st.warning("⚠️ Infant (<2 år) er registrert. Ikke fullt støttet (kan avvike ved booking).")

st.sidebar.divider()

# ======================================================
# Sidebar – open jaw valg (stabil: én valgt per etappe per scan)
# ======================================================
st.sidebar.header("🌍 Flyplasser (open jaw)")

asia_codes = ["SIN", "KUL", "BKK"]
aus_codes = ["MEL", "SYD"]

asia_arrival = st.sidebar.selectbox("Asia – ankomst (OSL → Asia)", asia_codes, index=0)
asia_depart = st.sidebar.selectbox("Asia – avreise (Asia → Australia)", asia_codes, index=1 if "KUL" in asia_codes else 0)

aus_arrival = st.sidebar.selectbox("Australia – ankomst (Asia → Australia)", aus_codes, index=0)
aus_depart = st.sidebar.selectbox("Australia – avreise (Australia → OSL)", aus_codes, index=1 if len(aus_codes) > 1 else 0)

st.sidebar.divider()

# ======================================================
# Sidebar – datoer
# ======================================================
st.sidebar.header("📅 Reiseplan")

oslasia_depart = st.sidebar.date_input("Avreise OSL → Asia", date(2026, 7, 1))

# For cloud: keep flex modest
flex = st.sidebar.slider("Fleksibilitet ± dager (anbefalt 0–2)", 0, 4, 2)

asia_stay = st.sidebar.slider("Opphold i Asia (min–maks dager)", 5, 30, (8, 12))
aus_stay = st.sidebar.slider("Opphold i Australia (min–maks dager)", 5, 20, (6, 12))

st.sidebar.divider()

scan_topn = st.sidebar.selectbox("Hvor mange alternativer per etappe", [3, 5, 8], index=1)
cache_ttl_hours = st.sidebar.selectbox("Cache (timer) – gjør gjentatte scan raskere", [1, 3, 6, 12], index=2)

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

def google_flights_link(origin: str, dest: str, d: date) -> str:
    return f"https://www.google.com/travel/flights?q={origin}-{dest}-{d}"

def route_codes(legs: List[Leg]) -> str:
    if not legs:
        return ""
    path = [legs[0].origin] + [l.dest for l in legs]
    cleaned = []
    for x in path:
        if not cleaned or cleaned[-1] != x:
            cleaned.append(x)
    return " → ".join(cleaned)

def route_human(legs: List[Leg]) -> str:
    if not legs:
        return ""
    path = [legs[0].origin] + [l.dest for l in legs]
    cleaned = []
    for x in path:
        if not cleaned or cleaned[-1] != x:
            cleaned.append(x)
    return " → ".join(airport_label(x) for x in cleaned)

def primary_airline(legs: List[Leg]) -> Optional[str]:
    for leg in legs:
        if leg.airline in AIRLINE_BOOKING_URLS:
            return leg.airline
    return None

def pick_dates_slim(start: date, end: date, extra_each_side: int) -> List[date]:
    """
    Stabil søkestrategi:
    - søker midten av intervallet først
    - og et lite belte rundt (styrt av flex)
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
    # unik + behold rekkefølge
    seen = set()
    out = []
    for d in dates:
        if d not in seen:
            out.append(d); seen.add(d)
    return out

def analyze_offer(o: Offer, profile: dict) -> Analysis:
    score = o.price_total
    prev_arr = None
    total_h = 0.0
    red: List[str] = []
    yellow: List[str] = []
    green: List[str] = []

    for leg in o.legs:
        d = dt(leg.depart)
        a = dt(leg.arrive)
        h = flight_hours(d, a)
        total_h += h
        score += h * profile["cost_per_flight_hour"]

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

    layovers = max(0, len(o.legs) - 1)
    score += layovers * profile["cost_per_layover"]

    return Analysis(
        score=int(score),
        flight_hours=round(total_h, 1),
        layovers=layovers,
        red=red, yellow=yellow, green=green
    )

def bucket(a: Analysis) -> int:
    if a.red:
        return 2
    if a.yellow:
        return 1
    return 0

# ======================================================
# Cached Amadeus search
# ======================================================
# TTL styres av sidebar: vi bygger en cache-key ved å inkludere TTL (enkel måte)
@st.cache_data(ttl=60 * 60 * 6)
def _amadeus_search_cached(origin: str, dest: str, depart_date: str, adults_n: int, children_n: int, max_results: int):
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

        offers: List[Offer] = []
        for o in res.data:
            legs: List[Leg] = []
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

            price_total = int(float(o["price"]["total"]))
            offers.append(
                Offer(
                    origin=origin,
                    dest=dest,
                    depart_date=depart_date,
                    price_total=price_total,
                    legs=legs,
                    google_link=google_flights_link(origin, dest, date.fromisoformat(depart_date)),
                )
            )

        return offers
    except ResponseError:
        return []
    except Exception:
        return []

def amadeus_search_cached(origin: str, dest: str, d: date, max_results: int = 30) -> List[Offer]:
    # enkel “ttl switch”: endrer cache-key via max_results (stabilt) + vi kan også inkludere cache_ttl_hours i key
    # (Streamlit cache TTL kan ikke settes dynamisk per kall på en ryddig måte)
    _ = cache_ttl_hours  # bare for å “knytte” den til rerun-logikk i UI
    return _amadeus_search_cached(origin, dest, str(d), adults, children, max_results=max_results)

def search_leg(origin: str, dest: str, dates: List[date], max_calls: int = 6, max_results_per_call: int = 30) -> List[Offer]:
    """
    Stabil: få API-kall + progresjon.
    """
    offers: List[Offer] = []
    calls = 0
    progress = st.progress(0.0)
    status = st.empty()

    for d in dates:
        if calls >= max_calls:
            break
        calls += 1
        status.write(f"Søker {origin} → {dest} ({calls}/{max_calls}) • {d}")
        offers.extend(amadeus_search_cached(origin, dest, d, max_results=max_results_per_call))
        progress.progress(calls / max_calls)

    progress.empty()
    status.empty()
    return offers

def top_offers(offers: List[Offer], profile: dict, top_n: int) -> List[Tuple[Offer, Analysis]]:
    scored: List[Tuple[Offer, Analysis]] = [(o, analyze_offer(o, profile)) for o in offers]
    scored.sort(key=lambda x: (bucket(x[1]), x[1].score, x[0].price_total))
    return scored[:top_n]

# ======================================================
# Render helpers – topp 5 med “velg”
# ======================================================
def render_toplist(leg_key: str, title: str, scored: List[Tuple[Offer, Analysis]], per_person_div: int):
    st.subheader(title)

    if not scored:
        st.error("Ingen treff i dette søket.")
        return

    # Vis kompakt liste
    for i, (o, a) in enumerate(scored, start=1):
        price_pp = math.ceil(o.price_total / max(1, per_person_div))
        badge = "🟢"
        if a.red:
            badge = "🔴"
        elif a.yellow:
            badge = "🟡"

        cols = st.columns([6, 2, 2, 2])
        cols[0].markdown(
            f"**{badge} {i}.** `{route_codes(o.legs)}` • {o.depart_date}  \n"
            f"{route_human(o.legs)}"
        )
        cols[1].metric("Total", f"{o.price_total:,} kr")
        cols[2].metric("≈/pers", f"{price_pp:,} kr")
        cols[3].metric("Layovers", f"{a.layovers}")

        if cols[0].button(f"Vis detaljer #{i}", key=f"btn_{leg_key}_{i}"):
            st.session_state["focus_leg"] = leg_key
            st.session_state["focus_idx"] = i - 1  # 0-basert
            st.session_state["focus_title"] = title

def render_focus_panel(
    leg_key: str,
    title: str,
    scored: List[Tuple[Offer, Analysis]],
    per_person_div: int,
    profile_name: str,
):
    """
    Fokusvisning nederst: viser full detalj for valgt alternativ.
    """
    if not scored:
        return

    idx = st.session_state.get("focus_idx", 0)
    focus_leg = st.session_state.get("focus_leg", leg_key)

    if focus_leg != leg_key:
        return

    idx = max(0, min(idx, len(scored) - 1))
    o, a = scored[idx]

    st.markdown("---")
    st.header(f"🔎 Detaljer: {title} (valg #{idx+1})")
    price_pp = math.ceil(o.price_total / max(1, per_person_div))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totalpris", f"{o.price_total:,} kr")
    c2.metric("≈ per person", f"{price_pp:,} kr")
    c3.metric("Flytimer", f"{a.flight_hours}")
    c4.metric("Layovers", f"{a.layovers}")

    st.markdown(f"**Rute forklart:** {route_human(o.legs)}")
    st.caption(f"Profil: {profile_name} • Transfer-minimum: {OUTBOUND['min_transfer']} min (alltid rødt under dette)")

    if a.red:
        st.error("❌ Røde flagg")
        for r in a.red:
            st.write("🔴", r)
    elif a.yellow:
        st.warning("⚠️ Kompromiss")
        for y in a.yellow:
            st.write("🟡", y)
    else:
        st.success("✅ Ser veldig bra ut")
        for g in a.green:
            st.write("✔️", g)

    st.subheader("✈️ Etapper")
    prev_arr = None
    for n, leg in enumerate(o.legs, start=1):
        st.markdown(
            f"### Etappe {n}: {leg.origin} → {leg.dest}\n"
            f"**{airport_label(leg.origin)}** → **{airport_label(leg.dest)}**  \n"
            f"{leg.airline} {leg.flight}  \n"
            f"🕒 {leg.depart} → {leg.arrive}"
        )
        st.info(f"ℹ️ {leg.dest}: {airport_note(leg.dest)}")

        if prev_arr:
            t = minutes(prev_arr, dt(leg.depart))
            if t < OUTBOUND["min_transfer"]:
                st.error(f"⏱️ Transfer: **{t} min** (for kort)")
            elif t <= 200:
                st.success(f"⏱️ Transfer: **{t} min** (ideell)")
            elif t <= 360:
                st.warning(f"⏱️ Transfer: **{t} min** (litt lang)")
            else:
                st.warning(f"⏱️ Transfer: **{t} min** (lang)")
        prev_arr = dt(leg.arrive)

    st.subheader("🔗 Lenker")
    carrier = primary_airline(o.legs)
    if carrier:
        st.markdown(f"[🛫 Flyselskap ({carrier})]({AIRLINE_BOOKING_URLS[carrier]})")
    st.markdown(f"[🌍 Google Flights (søk)]({o.google_link})")

# ======================================================
# Plan + start
# ======================================================
st.markdown("### 🧭 Plan (open jaw)")
st.write(
    f"- **OSL → {asia_arrival}**\n"
    f"- **{asia_depart} → {aus_arrival}** (Asia → Australia)\n"
    f"- **{aus_depart} → OSL** (hjem)\n"
    f"- Flex: ±{flex} dager"
)

run = st.button("🔍 Start scan (TOPP alternativer)")
if not run:
    st.info("Trykk Start scan når du er klar.")
    st.stop()

st.info(f"Passasjerer: **{adults} voksne + {children} barn** (12+ regnes som voksne).")

# ======================================================
# 1) OSL → Asia (bruker full flex range)
# ======================================================
st.markdown("## 1) OSL → Asia")
dates1 = [oslasia_depart + timedelta(days=i) for i in range(-flex, flex + 1)]
offers1 = search_leg("OSL", asia_arrival, dates1, max_calls=min(6, len(dates1)), max_results_per_call=40)
top1 = top_offers(offers1, OUTBOUND, scan_topn)

render_toplist("leg1", "OSL → Asia", top1, total_pax)
if not top1:
    st.stop()

# Base (sekvensiell): bruker valgt avreisedato fra topp 1 (praktisk, stabilt)
asia_base = date.fromisoformat(top1[0][0].depart_date)

# ======================================================
# 2) Asia → Australia (smalt vindu rundt midten + flex)
# ======================================================
st.markdown("## 2) Asia → Australia")
a2_start = asia_base + timedelta(days=asia_stay[0])
a2_end = asia_base + timedelta(days=asia_stay[1])
dates2 = pick_dates_slim(a2_start, a2_end, extra_each_side=flex)

offers2 = search_leg(asia_depart, aus_arrival, dates2, max_calls=min(6, len(dates2)), max_results_per_call=40)
top2 = top_offers(offers2, OUTBOUND, scan_topn)

render_toplist("leg2", "Asia → Australia", top2, total_pax)

if not top2:
    st.warning(
        "Ingen treff for Asia → Australia på denne kombinasjonen.\n\n"
        "Tips: bytt Asia-avreise eller Australia-ankomst, og hold flex lav (0–2)."
    )
    st.stop()

aus_base = date.fromisoformat(top2[0][0].depart_date)

# ======================================================
# 3) Australia → OSL (hjemreise-vindu)
# ======================================================
st.markdown("## 3) Australia → OSL")
h_start = aus_base + timedelta(days=aus_stay[0])
h_end = aus_base + timedelta(days=aus_stay[1])
dates3 = pick_dates_slim(h_start, h_end, extra_each_side=flex)

offers3 = search_leg(aus_depart, "OSL", dates3, max_calls=min(6, len(dates3)), max_results_per_call=40)
top3 = top_offers(offers3, HOME, scan_topn)

render_toplist("leg3", "Australia → OSL", top3, total_pax)

if not top3:
    st.warning("Ingen hjemreise-treff i dette vinduet. Prøv å øke opphold eller flex litt.")
    st.stop()

# ======================================================
# Fokuspanel (B): viser detaljer for klikket alternativ
# Default: hvis ingen klikk, viser vi automatisk leg2 (ofte mest interessant)
# ======================================================
if "focus_leg" not in st.session_state:
    st.session_state["focus_leg"] = "leg2"
    st.session_state["focus_idx"] = 0
    st.session_state["focus_title"] = "Asia → Australia"

# Render fokuspaneler (kun det valgte leg_key vises)
render_focus_panel("leg1", "OSL → Asia", top1, total_pax, "Utreise",)
render_focus_panel("leg2", "Asia → Australia", top2, total_pax, "Utreise",)
render_focus_panel("leg3", "Australia → OSL", top3, total_pax, "Hjemreise",)

# ======================================================
# Oppsummering
# ======================================================
st.markdown("---")
st.header("✅ Oppsummering (valgt topp #1 per etappe)")
st.write(
    f"**OSL → {asia_arrival}**  \n"
    f"**{asia_depart} → {aus_arrival}**  \n"
    f"**{aus_depart} → OSL**"
)
st.caption(
    "Klikk ‘Vis detaljer’ på et alternativ for å se full flyinformasjon i detaljseksjonen nederst."
)
