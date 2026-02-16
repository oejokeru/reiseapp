import streamlit as st
from datetime import datetime, date, timedelta
import random

# ======================================================
# KONFIG (familievennlig)
# ======================================================
MIN_TRANSFER = 120          # KRAV
TIGHT_TRANSFER = 200        # "gult" område (tight men ok)
MAX_TRANSFER_OK = 360       # over dette blir "lang transfer"

COST_PER_FLIGHT_HOUR = 400
COST_PER_LAYOVER = 1500
PENALTY_SHORT_TRANSFER = 10000
PENALTY_LONG_TRANSFER = 1200
BONUS_GOOD_TRANSFER = -300

# ======================================================
# FLYTID-DATA (simulert, grovt realistisk)
# (Du kan bygge dette videre etter hvert.)
# ======================================================
DUR_H = {
    ("OSL", "SIN"): 12.5,
    ("OSL", "KUL"): 12.8,
    ("OSL", "BKK"): 11.6,

    ("SIN", "KUL"): 1.2,
    ("KUL", "SIN"): 1.2,
    ("SIN", "BKK"): 2.3,
    ("BKK", "SIN"): 2.3,
    ("KUL", "BKK"): 2.1,
    ("BKK", "KUL"): 2.1,

    ("SIN", "MEL"): 7.7,
    ("SIN", "SYD"): 8.4,
    ("KUL", "MEL"): 8.7,
    ("KUL", "SYD"): 8.4,
    ("BKK", "MEL"): 9.1,
    ("BKK", "SYD"): 9.3,

    ("SIN", "NAN"): 10.0,
    ("KUL", "NAN"): 9.5,
    ("BKK", "NAN"): 10.5,

    ("NAN", "MEL"): 5.5,
    ("NAN", "SYD"): 5.0,

    # hjem (grovt)
    ("MEL", "OSL"): 16.0,
    ("SYD", "OSL"): 17.0,
}

AIRPORTS_ASIA = ["SIN", "KUL", "BKK"]
AIRPORTS_AUS = ["MEL", "SYD"]

# ======================================================
# APP
# ======================================================
st.set_page_config(page_title="Reiseapp", layout="wide")
st.title("✈️ Reiseapp – Familievennlig flyvurdering (SIMULERT MARKEDSSCAN)")
st.caption("Open-jaw støttes: f.eks. OSL → KUL og SIN → MEL • viser topp 5 med detaljer og røde flagg")

# ======================================================
# SIDEBAR – INPUTS
# ======================================================
st.sidebar.header("🧭 Reiseprofil")

origin = "OSL"
start_date = st.sidebar.date_input("Tidligste avreise", date(2026, 7, 1))
end_date = st.sidebar.date_input("Seneste hjemreise", date(2026, 7, 27))
flex_days = st.sidebar.slider("Datofleksibilitet (± dager)", 0, 5, 3)

st.sidebar.divider()
st.sidebar.subheader("🌏 Asia (open jaw)")
asia_arrival = st.sidebar.selectbox("Fly til Asia (OSL → …)", AIRPORTS_ASIA, index=1)  # default KUL
asia_depart = st.sidebar.selectbox("Fly fra Asia (… → Australia)", AIRPORTS_ASIA, index=0)  # default SIN

st.sidebar.subheader("🇦🇺 Australia (open jaw)")
aus_arrival = st.sidebar.selectbox("Ankomst Australia (… → …)", AIRPORTS_AUS, index=0)  # MEL
aus_depart = st.sidebar.selectbox("Hjemreise fra Australia (… → OSL)", AIRPORTS_AUS, index=1)  # SYD

st.sidebar.divider()
st.sidebar.subheader("⏱️ Opphold (dager)")
asia_days = st.sidebar.slider("Min / maks dager i Asia", 5, 20, (8, 12))
aus_days = st.sidebar.slider("Min / maks dager i Australia", 5, 20, (6, 12))

st.sidebar.divider()
adults = st.sidebar.number_input("Voksne", 1, 6, 2)
children = st.sidebar.number_input("Barn", 0, 6, 3)

st.sidebar.divider()
use_fiji = st.sidebar.checkbox("Vurder Fiji (optional)", True)
scan_intensity = st.sidebar.slider("Scan-intensitet (antall tilbud å teste)", 20, 300, 80, step=20)

run = st.sidebar.button("🔍 Start scan")

# ======================================================
# HJELPEFUNKSJONER
# ======================================================
def dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def fmt_dt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")

def minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() / 60)

def clamp_date(d: date, lo: date, hi: date) -> date:
    if d < lo: return lo
    if d > hi: return hi
    return d

def random_date_in_window(base: date, lo: date, hi: date, flex: int) -> date:
    offset = random.randint(-flex, flex)
    return clamp_date(base + timedelta(days=offset), lo, hi)

def google_link(frm: str, to: str, d: date) -> str:
    # enkel og robust Google Flights deep-link
    return f"https://www.google.com/travel/flights?q={frm}-{to}-{d}"

def duration_hours(frm: str, to: str) -> float:
    # fallback hvis vi mangler spesifikt par
    if (frm, to) in DUR_H:
        return DUR_H[(frm, to)]
    # grov fallback
    if frm == "OSL" or to == "OSL":
        return 13.5
    return 4.5

def pick_transfer_minutes() -> int:
    # realistisk: mest 120–300, noen tight/røde
    r = random.random()
    if r < 0.10:
        return random.randint(60, 115)      # rødt
    if r < 0.22:
        return random.randint(120, 170)     # tight/gul
    return random.randint(170, 330)         # ok

# ======================================================
# RUTE-BYGGING (dynamisk)
# ======================================================
def build_route_variant(include_fiji: bool) -> dict:
    """
    Bygger en rute med open-jaw:
    OSL -> asia_arrival -> (Asia transfer internt hvis open-jaw) -> asia_depart -> (evt Fiji) -> aus_arrival -> aus_depart -> OSL
    Merk: Asia internal fly (asia_arrival -> asia_depart) tas bare med hvis de er ulike.
    """
    legs = []

    # 1) OSL -> Asia arrival
    legs.append(("OSL", asia_arrival, "Longhaul", "LH/SQ/QR", "LH???"))

    # 2) internt Asia hvis open-jaw
    if asia_arrival != asia_depart:
        legs.append((asia_arrival, asia_depart, "Asia hop", "MH/SQ/AK", "MH???"))

    # 3) Asia depart -> Australia (evt via Fiji)
    if include_fiji:
        legs.append((asia_depart, "NAN", "Pacific", "FJ", "FJ???"))
        legs.append(("NAN", aus_arrival, "Pacific", "FJ", "FJ???"))
    else:
        legs.append((asia_depart, aus_arrival, "Longhaul", "SQ/QF/QR/EK", "SQ???"))

    # 4) innen Australia hvis open-jaw hjem
    if aus_arrival != aus_depart:
        legs.append((aus_arrival, aus_depart, "Domestic", "VA/QF", "VA???"))

    # 5) Australia -> OSL
    legs.append((aus_depart, "OSL", "Longhaul", "QR/EK/TK", "QR???"))

    return legs

# ======================================================
# GENERER "MARKEDSTILBUD" (simulert)
# ======================================================
def generate_offer(include_fiji: bool) -> dict:
    """
    Lager ett simulerte markedstreff:
    - setter dato/tid
    - varierer transfertid
    - varierer pris litt
    - respekterer oppholdslengder (Asia + Australia)
    """
    route_legs = build_route_variant(include_fiji)

    # Dato-logikk:
    # - Avreise OSL i vinduet
    # - Avreise Asia->AUS etter asia_days
    # - Hjemreise etter aus_days
    base_depart_osl = random_date_in_window(start_date, start_date, end_date, flex_days)

    # grov plan (datoer)
    asia_stay_days = random.randint(asia_days[0], asia_days[1])
    aus_stay_days = random.randint(aus_days[0], aus_days[1])

    depart_osl_dt = datetime.combine(base_depart_osl, datetime.strptime("12:05", "%H:%M").time())

    # vi lar "segment 0..n" flyttes videre med transfer og noen dag-hopp på riktige punkter
    offer_legs = []
    prev_arrival = None
    current_dt = depart_osl_dt

    # pris (grunnlag) – justeres etter kompleksitet
    base_price = 82000
    if include_fiji:
        base_price += 18000
    if asia_arrival != asia_depart:
        base_price += 1200
    if aus_arrival != aus_depart:
        base_price += 900

    # markedsvariasjon
    price = base_price * (1 + random.uniform(-0.12, 0.14))

    # Vi trenger å hoppe kalender ved:
    # - etter ankomst Asia (før asia->aus)
    # - etter ankomst Australia (før hjemreise)
    # Vi identifiserer "milepæler" basert på leg-rekkefølgen.
    # Milepæl 1: første gang vi har landet i Asia-depart-byen (asia_depart) og neste leg går til Australia/NAN.
    # Milepæl 2: første gang vi har landet i aus_depart og neste leg går til OSL.
    for idx, (frm, to, legtype, airline_hint, flight_hint) in enumerate(route_legs):
        # hvis ikke første leg, legg til transfer
        if idx == 0:
            dep = current_dt
        else:
            dep = prev_arrival + timedelta(minutes=pick_transfer_minutes())

        # flytid
        dur = duration_hours(frm, to)
        arr = dep + timedelta(minutes=int(dur * 60))

        offer_leg = {
            "from": frm,
            "to": to,
            "airline": airline_hint,
            "flight": flight_hint,
            "depart": fmt_dt(dep),
            "arrive": fmt_dt(arr),
            "link": google_link(frm, to, dep.date()),
        }
        offer_legs.append(offer_leg)
        prev_arrival = arr

        # milepæl-hopp: etter at vi er ferdig med "Asia-delen" før vi starter longhaul til AUS/NAN
        # Det vil si: når vi har landet i asia_depart, og neste leg (hvis finnes) starter fra asia_depart til NAN/AUS.
        if idx < len(route_legs) - 1:
            next_from, next_to, *_ = route_legs[idx + 1]
            # dersom neste leg er Asia->AUS (eller Asia->NAN) og vi nå nettopp landet i asia_depart:
            if to == asia_depart and next_from == asia_depart and (next_to in ["NAN", aus_arrival]):
                prev_arrival = prev_arrival + timedelta(days=asia_stay_days)

            # etter at vi har landet i aus_depart og neste er til OSL
            if to == aus_depart and next_from == aus_depart and next_to == "OSL":
                prev_arrival = prev_arrival + timedelta(days=aus_stay_days)

        # litt prisstøy per leg
        price += random.uniform(-1400, 2400)

    # sluttpris
    offer = {
        "name": "Med Fiji" if include_fiji else "Uten Fiji",
        "route": route_codes_from_legs(offer_legs),
        "price": int(max(0, round(price))),
        "legs": offer_legs,
    }
    return offer

def route_codes_from_legs(legs: List[dict]) -> str:
    if not legs:
        return ""
    path = [legs[0]["from"]] + [l["to"] for l in legs]
    out = []
    for p in path:
        if not out or out[-1] != p:
            out.append(p)
    return " → ".join(out)

# ======================================================
# ANALYSE (score + flagg)
# ======================================================
def analyze(route: dict):
    score = route["price"]
    red, yellow, green = [], [], []

    prev_arr = None
    total_hours = 0.0

    for leg in route["legs"]:
        d = dt(leg["depart"])
        a = dt(leg["arrive"])

        hours = (a - d).total_seconds() / 3600
        total_hours += hours
        score += hours * COST_PER_FLIGHT_HOUR

        if prev_arr:
            t = minutes(prev_arr, d)
            if t < MIN_TRANSFER:
                red.append(f"For kort transfertid ({t} min) – krav {MIN_TRANSFER} min")
                score += PENALTY_SHORT_TRANSFER
            elif t < TIGHT_TRANSFER:
                yellow.append(f"Tight transfertid ({t} min)")
            elif t > MAX_TRANSFER_OK:
                yellow.append(f"Lang transfertid ({t} min)")
                score += PENALTY_LONG_TRANSFER
            else:
                green.append(f"God transfertid ({t} min)")
                score += BONUS_GOOD_TRANSFER

        prev_arr = a

    layovers = len(route["legs"]) - 1
    score += layovers * COST_PER_LAYOVER

    return {
        "score": int(score),
        "red": red,
        "yellow": yellow,
        "green": green,
        "layovers": layovers,
        "flight_hours": round(total_hours, 1),
    }

def status_bucket(analysis: dict) -> str:
    if analysis["red"]:
        return "RED"
    if analysis["yellow"]:
        return "YELLOW"
    return "GREEN"

# ======================================================
# UI – KJØR
# ======================================================
if not run:
    st.info("👈 Velg open-jaw (f.eks. OSL→KUL og SIN→MEL), opphold og trykk **Start scan**")
    st.stop()

# Stabil seed (samme input -> samme typer resultater)
seed_str = f"{start_date}-{end_date}-flex{flex_days}-A{adults}-C{children}-F{use_fiji}-{asia_arrival}-{asia_depart}-{aus_arrival}-{aus_depart}-{asia_days}-{aus_days}-{scan_intensity}"
random.seed(seed_str)

st.markdown("## 🧾 Valgt plan")
st.write(
    f"- **OSL → {asia_arrival}**\n"
    f"- **{asia_depart} → {aus_arrival}**\n"
    f"- **{aus_depart} → OSL**\n"
    f"- Asia-opphold: {asia_days[0]}–{asia_days[1]} dager • Australia-opphold: {aus_days[0]}–{aus_days[1]} dager"
)

if asia_arrival != asia_depart:
    st.info(f"✅ Open-jaw i Asia: ankomst **{asia_arrival}**, avreise **{asia_depart}** (f.eks. OSL→KUL og SIN→MEL).")

if aus_arrival != aus_depart:
    st.info(f"✅ Open-jaw i Australia: ankomst **{aus_arrival}**, hjem fra **{aus_depart}**.")

st.write(
    f"**Scan:** {scan_intensity} tilbud per alternativ • "
    f"**Min transfertid:** {MIN_TRANSFER} min • "
    f"**Tight:** <{TIGHT_TRANSFER} min • "
    f"**Flex:** ±{flex_days} dager"
)

# Progress bar – føles som "markedsscan"
progress = st.progress(0)
status = st.empty()

offers_a = []
offers_b = []

total_work = scan_intensity + (max(10, scan_intensity // 2) if use_fiji else 0)
done = 0

for _ in range(scan_intensity):
    offers_a.append(generate_offer(include_fiji=False))
    done += 1
    progress.progress(min(1.0, done / max(1, total_work)))
    status.write(f"Scanner marked (uten Fiji)… {done}/{total_work}")

if use_fiji:
    for _ in range(max(10, scan_intensity // 2)):
        offers_b.append(generate_offer(include_fiji=True))
        done += 1
        progress.progress(min(1.0, done / max(1, total_work)))
        status.write(f"Scanner marked (med Fiji)… {done}/{total_work}")

status.empty()
progress.empty()

# Analyser
scored_a = [(o, analyze(o)) for o in offers_a]
scored_b = [(o, analyze(o)) for o in offers_b]

def pick_best(scored):
    greens = [(o, a) for o, a in scored if status_bucket(a) == "GREEN"]
    yellows = [(o, a) for o, a in scored if status_bucket(a) == "YELLOW"]
    reds = [(o, a) for o, a in scored if status_bucket(a) == "RED"]

    if greens:
        return min(greens, key=lambda x: x[1]["score"]), "GREEN"
    if yellows:
        return min(yellows, key=lambda x: x[1]["score"]), "YELLOW"
    if reds:
        return min(reds, key=lambda x: x[1]["score"]), "RED"
    return None, None

(best_a, best_a_status) = pick_best(scored_a)
best_b = best_b_status = None
if use_fiji and scored_b:
    (best_b, best_b_status) = pick_best(scored_b)

def bucket_rank(analysis):
    return {"GREEN": 0, "YELLOW": 1, "RED": 2}[status_bucket(analysis)]

def render_offer_card(title, offer, analysis):
    st.subheader(title)
    st.write("**Rute:**", offer["route"])
    cols = st.columns(4)
    cols[0].metric("Pris", f"{offer['price']:,} kr")
    cols[1].metric("Score", analysis["score"])
    cols[2].metric("Flytimer", analysis["flight_hours"])
    cols[3].metric("Layovers", analysis["layovers"])

    if analysis["red"]:
        st.error("❌ Ikke familievennlig (minst én kritisk risiko)")
        for f in analysis["red"]:
            st.write("🔴", f)
    elif analysis["yellow"]:
        st.warning("⚠️ Brukbar, men med risikopunkt")
        for f in analysis["yellow"]:
            st.write("🟡", f)
    else:
        st.success("✅ Trygg og familievennlig")
        for f in analysis["green"]:
            st.write("✔️", f)

    with st.expander("✈️ Flydetaljer + transfertid + booking"):
        prev = None
        for leg in offer["legs"]:
            st.markdown(
                f"""
**{leg['from']} → {leg['to']}**  
{leg['airline']} – {leg['flight']}  
🕒 {leg['depart']} → {leg['arrive']}  
[🔗 Google Flights (denne etappen)]({leg['link']})
"""
            )
            if prev:
                t = minutes(prev, dt(leg["depart"]))
                if t < MIN_TRANSFER:
                    st.write(f"⏱️ Transfertid: **{t} min** 🔴")
                elif t < TIGHT_TRANSFER:
                    st.write(f"⏱️ Transfertid: **{t} min** 🟡")
                else:
                    st.write(f"⏱️ Transfertid: **{t} min** 🟢")
            prev = dt(leg["arrive"])

# Velg anbefalt mellom A og B
candidates = []
if best_a and best_a[0]:
    candidates.append((best_a[0], best_a[1], "A"))
if best_b and best_b[0]:
    candidates.append((best_b[0], best_b[1], "B"))

st.markdown("## 🏆 Anbefalt rute (beste kombinasjon av pris + transfertid)")

if not candidates:
    st.error("Ingen tilbud generert (uventet). Prøv å endre parametere og scanne igjen.")
    st.stop()

recommended = min(candidates, key=lambda x: (bucket_rank(x[1]), x[1]["score"]))
tag = "Uten Fiji" if recommended[2] == "A" else "Med Fiji"
render_offer_card(f"Anbefalt: {tag}", recommended[0], recommended[1])

# Beste per system
st.divider()
st.markdown("## 📌 Beste funn per alternativ")

col1, col2 = st.columns(2)
with col1:
    if best_a and best_a[0]:
        render_offer_card("Beste uten Fiji (System A)", best_a[0], best_a[1])
    else:
        st.info("Ingen treff uten Fiji (uventet i simulering).")

with col2:
    if use_fiji and best_b and best_b[0]:
        render_offer_card("Beste med Fiji (System B)", best_b[0], best_b[1])
    else:
        st.info("Fiji er ikke valgt eller ingen tilbud generert.")

# Topplister
st.divider()
st.markdown("## 📋 Topplister (lavest score først)")

def top_table(scored, n=8):
    rows = []
    for offer, analysis in scored:
        rows.append({
            "Status": "🟢" if status_bucket(analysis) == "GREEN" else ("🟡" if status_bucket(analysis) == "YELLOW" else "🔴"),
            "Pris (kr)": offer["price"],
            "Score": analysis["score"],
            "Flytimer": analysis["flight_hours"],
            "Layovers": analysis["layovers"],
            "Rute": offer["route"],
        })
    rows.sort(key=lambda r: r["Score"])
    return rows[:n]

tab1, tab2 = st.columns(2)
with tab1:
    st.markdown("### Uten Fiji – topp 8")
    st.dataframe(top_table(scored_a, 8), use_container_width=True)

with tab2:
    st.markdown("### Med Fiji – topp 8")
    if scored_b:
        st.dataframe(top_table(scored_b, 8), use_container_width=True)
    else:
        st.info("Ikke aktivert / ingen data.")
