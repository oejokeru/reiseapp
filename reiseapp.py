import streamlit as st
from datetime import datetime, date, timedelta
import os
import math
from amadeus import Client, ResponseError

# ======================================================
# AMADEUS (miljøvariabler)
# ======================================================
AMADEUS = Client(
    client_id=os.getenv("AMADEUS_CLIENT_ID"),
    client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
)

# ======================================================
# TRANSFER/SCORE PROFILER
# ======================================================
OUTBOUND = dict(
    bonus_ideal=-800,         # 120–200
    penalty_ok=800,           # 200–360
    penalty_long=2500,        # 360–480
    penalty_overnight=6000,   # >480
    penalty_too_short=12000,  # <120
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
# BOOKING-LENKER (carrier-sider)
# ======================================================
AIRLINE_BOOKING_URLS = {
    "LH": "https://www.lufthansa.com/no/en/flight-search",
    "SQ": "https://www.singaporeair.com/en_UK/no/plan-travel/book-flight/",
    "SK": "https://www.flysas.com/no-en/book/",
    "QR": "https://www.qatarairways.com/en-no/book.html",
    "EK": "https://www.emirates.com/no/english/book/",
    "TK": "https://www.turkishairlines.com/en-no/flights/booking/",
    "QF": "https://www.qantas.com/no/en/book-a-trip/flights.html",
    "VA": "https://www.virginaustralia.com/au/en/book/",
}

# ======================================================
# FLYPLASSINFO (kort, menneskelig)
# ======================================================
AIRPORT_INFO = {
    "OSL": ("Oslo Gardermoen", "Norge", "Oversiktlig og effektiv hovedflyplass."),
    "SIN": ("Singapore Changi", "Singapore", "En av verdens beste flyplasser. Veldig familievennlig."),
    "KUL": ("Kuala Lumpur", "Malaysia", "Ofte billig innfallsport til Sørøst-Asia."),
    "BKK": ("Bangkok Suvarnabhumi", "Thailand", "Stor og travel hub. Mange ruter."),
    "FRA": ("Frankfurt", "Tyskland", "Stor europeisk hub. Vanlig mellomlanding."),
    "MUC": ("München", "Tyskland", "Ofte ryddig og effektiv transfer."),
    "LHR": ("London Heathrow", "Storbritannia", "Veldig travel. God transfertid er viktig."),
    "CDG": ("Paris CDG", "Frankrike", "Stor flyplass. Kan gi lange avstander/terminalbytte."),
    "AMS": ("Amsterdam Schiphol", "Nederland", "Ofte effektiv transferflyplass."),
    "IST": ("Istanbul", "Tyrkia", "Svært stor, moderne hub."),
    "DOH": ("Doha Hamad", "Qatar", "Moderne og familievennlig hub."),
    "DXB": ("Dubai", "UAE", "Stor hub. Kan være mye folk og lange avstander."),
    "MEL": ("Melbourne", "Australia", "God inngang til Australia. Ofte gunstig videre."),
    "SYD": ("Sydney", "Australia", "Større knutepunkt. Mange ruter, kan være dyrere."),
}

# ======================================================
# APP
# ======================================================
st.set_page_config(page_title="Reiseapp – Komplett", layout="wide")
st.title("✈️ Reiseapp – Komplett reise (LIVE)")
st.caption("Sekvensiell planlegging: OSL → Asia (open jaw) → Australia (open jaw) → OSL")

# ======================================================
# SIDEBAR – PASSASJERER
# ======================================================
st.sidebar.header("👨‍👩‍👧‍👦 Passasjerer")

adult_base = st.sidebar.number_input("Voksne (18+)", 1, 6, 2)
num_children = st.sidebar.number_input("Barn (0–17)", 0, 6, 3)

child_ages = []
for i in range(num_children):
    default_age = [15, 13, 8][i] if i < 3 else 8
    child_ages.append(
        st.sidebar.number_input(
            f"Alder barn {i+1}",
            0, 17, default_age,
            key=f"child_age_{i}"
        )
    )

# Alderslogikk (12+ = voksen)
adult_count = adult_base
child_count = 0
infant_count = 0
for age in child_ages:
    if age < 2:
        infant_count += 1
    elif age < 12:
        child_count += 1
    else:
        adult_count += 1

total_pax = adult_count + child_count

st.sidebar.divider()

# ======================================================
# SIDEBAR – DESTINASJONER (open jaw i Asia + Australia)
# ======================================================
st.sidebar.header("🌏 Flyplasser")

asia_choices = {"SIN": "Singapore", "KUL": "Kuala Lumpur", "BKK": "Bangkok"}
asia_arrivals = st.sidebar.multiselect(
    "Asia (ankomst) – OSL → Asia",
    options=list(asia_choices.keys()),
    default=["SIN"],
    format_func=lambda x: f"{asia_choices[x]} ({x})"
)

asia_departures = st.sidebar.multiselect(
    "Asia (avreise) – Asia → Australia",
    options=list(asia_choices.keys()),
    default=["KUL", "SIN"],
    format_func=lambda x: f"{asia_choices[x]} ({x})"
)

aus_choices = {"MEL": "Melbourne", "SYD": "Sydney"}
aus_arrivals = st.sidebar.multiselect(
    "Australia (ankomst) – Asia → Australia",
    options=list(aus_choices.keys()),
    default=["MEL", "SYD"],
    format_func=lambda x: f"{aus_choices[x]} ({x})"
)

aus_departures = st.sidebar.multiselect(
    "Australia (hjemreise fra) – Australia → OSL",
    options=list(aus_choices.keys()),
    default=["MEL", "SYD"],
    format_func=lambda x: f"{aus_choices[x]} ({x})"
)

st.sidebar.divider()

# ======================================================
# SIDEBAR – REISEPLAN (sekvens)
# ======================================================
st.sidebar.header("📅 Reiseplan")

oslasia_depart = st.sidebar.date_input("Avreise OSL → Asia", date(2026, 7, 1))
flex_days = st.sidebar.slider("Fleksibilitet (± dager)", 0, 7, 3)

asia_stay = st.sidebar.slider(
    "Opphold i Asia (min–maks dager)",
    min_value=3,
    max_value=30,
    value=(8, 12)
)

aus_stay = st.sidebar.slider(
    "Opphold i Australia (min–maks dager)",
    min_value=5,
    max_value=20,
    value=(6, 12)
)

# ======================================================
# HJELP
# ======================================================
def dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() / 60)

def flight_hours(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 1)

def airport_label(code: str) -> str:
    info = AIRPORT_INFO.get(code)
    if not info:
        return code
    n, c, _ = info
    return f"{n} ({code}), {c}"

def airport_note(code: str) -> str:
    info = AIRPORT_INFO.get(code)
    return info[2] if info else "Ingen ekstra info lagt inn ennå."

def google_flights_general(origin: str, dest: str, d: date) -> str:
    return f"https://www.google.com/travel/flights?q={origin}-{dest}-{d}"

def primary_airline(legs):
    for leg in legs:
        if leg["airline"] in AIRLINE_BOOKING_URLS:
            return leg["airline"]
    return None

def route_readable(legs) -> str:
    if not legs:
        return ""
    path = [legs[0]["from"]]
    for leg in legs:
        path.append(leg["to"])
    cleaned = []
    for x in path:
        if not cleaned or cleaned[-1] != x:
            cleaned.append(x)
    return " → ".join(airport_label(x) for x in cleaned)

# ======================================================
# LIVE SEARCH
# ======================================================
def live_search(origin_code: str, dest_code: str, depart_date: date, max_results: int = 40):
    offers = []
    try:
        res = AMADEUS.shopping.flight_offers_search.get(
            originLocationCode=origin_code,
            destinationLocationCode=dest_code,
            departureDate=str(depart_date),
            adults=adult_count,
            children=child_count,
            max=max_results,
            currencyCode="NOK",
        )
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
                "origin": origin_code,
                "dest": dest_code,
                "depart_date": depart_date,
                "price": int(float(o["price"]["total"])),
                "legs": legs,
                "google_link": google_flights_general(origin_code, dest_code, depart_date),
            })
    except ResponseError:
        return []
    return offers

# ======================================================
# ANALYSE (transfer-score)
# ======================================================
def analyze(offer, profile):
    score = offer["price"]
    prev_arr = None
    total_h = 0.0
    red, yellow, green = [], [], []

    for leg in offer["legs"]:
        d = dt(leg["depart"])
        a = dt(leg["arrive"])
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

    score += (len(offer["legs"]) - 1) * profile["cost_per_layover"]

    return {
        "score": int(score),
        "flight_hours": round(total_h, 1),
        "layovers": len(offer["legs"]) - 1,
        "red": red,
        "yellow": yellow,
        "green": green,
    }

def bucket(a):
    if a["red"]:
        return 2
    if a["yellow"]:
        return 1
    return 0

# ======================================================
# UI helpers
# ======================================================
def render_offer(title, offer, analysis):
    st.subheader(title)
    per_person = math.ceil(offer["price"] / max(1, total_pax))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totalpris", f"{offer['price']:,} kr")
    c2.metric("≈ per person", f"{per_person:,} kr")
    c3.metric("Flytimer", analysis["flight_hours"])
    c4.metric("Layovers", analysis["layovers"])

    readable = route_readable(offer["legs"])
    if readable:
        st.markdown(f"**Rute forklart:** {readable}")

    kids_under_12 = [a for a in child_ages if a < 12]
    kids_str = ", ".join(str(a) for a in kids_under_12) if kids_under_12 else "—"
    st.caption(
        f"Søk bruker: {adult_count} voksne + {child_count} barn (under 12: {kids_str} år). "
        f"Barn 12+ prises som voksne."
    )

    if analysis["red"]:
        st.error("❌ Røde flagg")
        for r in analysis["red"]:
            st.write("🔴", r)
    elif analysis["yellow"]:
        st.warning("⚠️ Noen kompromisser")
        for y in analysis["yellow"]:
            st.write("🟡", y)
    else:
        st.success("✅ Ser veldig bra ut")
        for g in analysis["green"]:
            st.write("✔️", g)

    with st.expander("✈️ Flydetaljer + flyplassinfo + booking"):
        prev = None
        for idx, leg in enumerate(offer["legs"], start=1):
            st.markdown(
                f"### Etappe {idx}: {leg['from']} → {leg['to']}\n"
                f"**{airport_label(leg['from'])}** → **{airport_label(leg['to'])}**  \n"
                f"{leg['airline']} {leg['flight']}  \n"
                f"🕒 {leg['depart']} → {leg['arrive']}"
            )
            st.info(f"ℹ️ **{leg['to']}**: {airport_note(leg['to'])}")

            if prev:
                t = minutes(prev, dt(leg["depart"]))
                st.write(f"⏱️ Transfertid: **{t} min**")
            prev = dt(leg["arrive"])

        carrier = primary_airline(offer["legs"])
        if carrier:
            st.markdown(f"[🛫 Søk hos flyselskap ({carrier})]({AIRLINE_BOOKING_URLS[carrier]})")
        st.markdown(f"[🌍 Google Flights (søk)]({offer['google_link']})")

# ======================================================
# Guard / status
# ======================================================
if infant_count > 0:
    st.warning("⚠️ Infant (<2 år) er registrert. Ikke fullt støttet i appen ennå (kan gi avvik i booking).")

if not asia_arrivals:
    st.warning("Velg minst én Asia-ankomst (OSL → Asia).")
    st.stop()

if not asia_departures:
    st.warning("Velg minst én Asia-avreise (Asia → Australia).")
    st.stop()

if not aus_arrivals:
    st.warning("Velg minst én Australia-ankomst (Asia → Australia).")
    st.stop()

if not aus_departures:
    st.warning("Velg minst én Australia-avreise (Australia → OSL).")
    st.stop()

# ======================================================
# Plan display
# ======================================================
st.markdown("### 🧭 Plan (slik appen tolker valgene)")
st.write(
    f"- **OSL → Asia (ankomst)**: {', '.join(asia_arrivals)} rundt {oslasia_depart} (± {flex_days} dager)\n"
    f"- **Opphold i Asia**: {asia_stay[0]}–{asia_stay[1]} dager\n"
    f"- **Asia (avreise) → Australia (ankomst)**: {', '.join(asia_departures)} → {', '.join(aus_arrivals)}\n"
    f"- **Opphold i Australia**: {aus_stay[0]}–{aus_stay[1]} dager\n"
    f"- **Australia (avreise) → OSL**: {', '.join(aus_departures)} → OSL (*open jaw mulig*)"
)

run = st.button("🔍 Start komplett scan")

if not run:
    st.info("Trykk **Start komplett scan** når du er klar.")
    st.stop()

st.info(f"Passasjerer brukt i søk: **{adult_count} voksne + {child_count} barn** (12+ regnes som voksne)")

# ======================================================
# 1) OSL -> ASIA (ankomst)
# ======================================================
st.markdown("## 1) OSL → Asia (ankomst)")
oslasia_offers = []
with st.spinner("Scanner OSL → Asia..."):
    for off in range(-flex_days, flex_days + 1):
        d = oslasia_depart + timedelta(days=off)
        for dest in asia_arrivals:
            oslasia_offers.extend(live_search("OSL", dest, d))

st.write(f"Treff funnet: **{len(oslasia_offers)}**")

if not oslasia_offers:
    st.error("Ingen treff for OSL → Asia. Prøv større fleksibilitet eller andre Asia-flyplasser.")
    st.stop()

oslasia_scored = [(o, analyze(o, OUTBOUND)) for o in oslasia_offers]
oslasia_sorted = sorted(oslasia_scored, key=lambda x: (bucket(x[1]), x[1]["score"]))
best_oslasia_offer, best_oslasia_an = oslasia_sorted[0]
render_offer("🏆 Beste OSL → Asia", best_oslasia_offer, best_oslasia_an)

asia_arrival_airport = best_oslasia_offer["dest"]
asia_base_date = best_oslasia_offer["depart_date"]  # ca-dato; senere kan vi bruke reell ankomsttid

# ======================================================
# 2) ASIA (avreise) -> AUSTRALIA (ankomst)
# ======================================================
st.markdown("## 2) Asia → Australia (ankomst MEL/SYD)")
earliest_asia_to_aus = asia_base_date + timedelta(days=asia_stay[0])
latest_asia_to_aus = asia_base_date + timedelta(days=asia_stay[1])
st.caption(f"Asia → Australia søkes i vinduet: **{earliest_asia_to_aus} → {latest_asia_to_aus}** (± flex per dag)")

asiaaus_offers = []
with st.spinner("Scanner Asia → Australia..."):
    span = (latest_asia_to_aus - earliest_asia_to_aus).days
    for base in range(span + 1):
        base_date = earliest_asia_to_aus + timedelta(days=base)
        for off in range(-flex_days, flex_days + 1):
            d = base_date + timedelta(days=off)
            for origin_asia in asia_departures:
                for dest_aus in aus_arrivals:
                    asiaaus_offers.extend(live_search(origin_asia, dest_aus, d))

st.write(f"Treff funnet: **{len(asiaaus_offers)}**")

if not asiaaus_offers:
    st.error("Ingen treff for Asia → Australia i dette vinduet. Prøv større fleksibilitet eller flere flyplasser.")
    st.stop()

asiaaus_scored = [(o, analyze(o, OUTBOUND)) for o in asiaaus_offers]
asiaaus_sorted = sorted(asiaaus_scored, key=lambda x: (bucket(x[1]), x[1]["score"]))
best_asiaaus_offer, best_asiaaus_an = asiaaus_sorted[0]
render_offer("🏆 Beste Asia → Australia", best_asiaaus_offer, best_asiaaus_an)

aus_arrival_airport = best_asiaaus_offer["dest"]
aus_base_date = best_asiaaus_offer["depart_date"]

# ======================================================
# 3) AUSTRALIA (avreise) -> OSL (open jaw)
# ======================================================
st.markdown("## 3) Australia → OSL (hjemreise – open jaw)")
earliest_home = aus_base_date + timedelta(days=aus_stay[0])
latest_home = aus_base_date + timedelta(days=aus_stay[1])
st.caption(f"Hjemreise søkes i vinduet: **{earliest_home} → {latest_home}** (± flex per dag)")

home_offers = []
with st.spinner("Scanner Australia → OSL..."):
    span = (latest_home - earliest_home).days
    for base in range(span + 1):
        base_date = earliest_home + timedelta(days=base)
        for off in range(-flex_days, flex_days + 1):
            d = base_date + timedelta(days=off)
            for origin_aus in aus_departures:
                home_offers.extend(live_search(origin_aus, "OSL", d))

st.write(f"Treff funnet: **{len(home_offers)}**")

if not home_offers:
    st.error("Ingen treff for hjemreise Australia → OSL i dette vinduet. Prøv større fleksibilitet.")
    st.stop()

home_scored = [(o, analyze(o, HOME)) for o in home_offers]
home_sorted = sorted(home_scored, key=lambda x: (bucket(x[1]), x[1]["score"]))
best_home_offer, best_home_an = home_sorted[0]
render_offer("🏆 Beste Australia → OSL", best_home_offer, best_home_an)

# ======================================================
# Oppsummering
# ======================================================
st.divider()
st.markdown("## ✅ Reiseoppsummering (open jaw støttet)")

st.write(
    f"**OSL → {best_oslasia_offer['dest']}** (ankomst Asia)  \n"
    f"**{best_asiaaus_offer['origin']} → {best_asiaaus_offer['dest']}** (ankomst Australia)  \n"
    f"**{best_home_offer['origin']} → OSL** (hjemreise fra Australia)  \n"
)

st.caption(
    "Merk: Open jaw i Asia betyr at dere kan fly inn til én Asia-by og videre fra en annen. "
    "Open jaw i Australia betyr at dere kan ankomme i MEL og reise hjem fra SYD (eller omvendt)."
)
