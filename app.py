import json
import re
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.express as px
from PyPDF2 import PdfReader

# =============================
# Inventory Hound Dashboard 🐶
# One dog per product
# Reads: BOTF PI Daily PDF (and similar)
# =============================

STATE_FILE = Path('.inventory_hounds_state.json')

DOG = {
    "happy": "🐶✨",
    "ok": "🐶",
    "worry": "🐶⚠️",
    "sad": "🐶💧",
    "sleep": "🐶💤",
    "treat": "🦴",
    "walk": "🦮",
    "fetch": "🎾",
    "bark": "🗣️",
    "alert": "🚨",
    "celebrate": "🎉",
}

DEFAULT_BREED = "Lab (steady & friendly)"
BREEDS = [
    "Lab (steady & friendly)",
    "Shepherd (focused & protective)",
    "Corgi (high energy)",
    "Husky (dramatic communicator)",
    "Mutt (scrappy problem-solver)",
]

BARKS = {
    "Lab (steady & friendly)": ["Woof! Inventory looks manageable.", "Tail wagging—keep supply steady!"],
    "Shepherd (focused & protective)": ["Alert: watch DOI and tank space.", "Protect the system—avoid stockouts."],
    "Corgi (high energy)": ["Zoomies! Let’s build inventory buffer!", "Treats for stable DOI!"],
    "Husky (dramatic communicator)": ["Awoooo… capacity is tight.", "Awooo! DOI needs attention."],
    "Mutt (scrappy problem-solver)": ["I’ll sniff out the constraint.", "We’ll improvise and stabilize."],
}

TARGETS = {
    "doi_good": 10.0,     # >10 days
    "doi_ok": 5.0,        # 5-10 days
    "doi_risk": 3.0,      # 3-5 days
    "cap_low": 40.0,      # <40% = too low
    "cap_high": 70.0,     # >70% = too high (tight)
}


# -----------------------------
# State
# -----------------------------

@dataclass
class DogState:
    display_name: str
    breed: str = DEFAULT_BREED
    hunger: int = 40
    energy: int = 70
    happiness: int = 70
    last_checkin: str = ""
    xp: int = 0
    level: int = 1

    def clamp(self):
        self.hunger = max(0, min(100, int(self.hunger)))
        self.energy = max(0, min(100, int(self.energy)))
        self.happiness = max(0, min(100, int(self.happiness)))
        self.level = max(1, int(self.level))
        self.xp = max(0, int(self.xp))


def _safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def load_all_states() -> Dict[str, dict]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_all_states(states: Dict[str, dict]):
    STATE_FILE.write_text(json.dumps(states, indent=2))


def get_state(states: Dict[str, dict], key: str, display_name: str) -> DogState:
    if key in states:
        s = DogState(**states[key])
        return s
    return DogState(display_name=display_name)


def put_state(states: Dict[str, dict], key: str, state: DogState):
    # clamp
    state.hunger = max(0, min(100, int(state.hunger)))
    state.energy = max(0, min(100, int(state.energy)))
    state.happiness = max(0, min(100, int(state.happiness)))
    state.level = max(1, int(state.level))
    state.xp = max(0, int(state.xp))
    states[key] = asdict(state)


def level_up(state: DogState):
    needed = 100 + (state.level - 1) * 75
    while state.xp >= needed:
        state.xp -= needed
        state.level += 1
        needed = 100 + (state.level - 1) * 75


def mood_face(hunger: int, energy: int, happiness: int) -> str:
    stress = (hunger * 0.5) + ((100 - energy) * 0.25) + ((100 - happiness) * 0.25)
    if energy < 25:
        return DOG["sleep"]
    if stress < 25:
        return DOG["happy"]
    if stress < 45:
        return DOG["ok"]
    if stress < 65:
        return DOG["worry"]
    return DOG["sad"]


# -----------------------------
# PDF parsing
# -----------------------------

def extract_text_from_pdf(upload) -> str:
    reader = PdfReader(upload)
    chunks = []
    for page in reader.pages:
        t = page.extract_text() or ""
        chunks.append(t)
    return "\n".join(chunks)


def _to_float(token: str) -> Optional[float]:
    if token is None:
        return None
    token = token.strip()
    if token in ["#DIV/0!", "DIV/0", "-"]:
        return None
    token = token.replace(",", "")
    try:
        return float(token)
    except Exception:
        return None


def parse_product_summary(text: str) -> List[dict]:
    """Parse the bottom summary table (PRIMA/ULTRA rows).

    Expected tokens per product (typical):
    Grade, Prod(KBD), Inv incl heels(KBBL), Avail Inv(KBBL), Avail Room(KBBL), Working Cap(KBBL), Cap%, Avail Inv Days, Avail Room Days, DOI label (optional)

    The PDF may place these on one line OR many lines; we handle both.
    """

    # Normalize whitespace
    t = re.sub(r"\s+", " ", text)

    # Fast path: try regex row style
    row_re = re.compile(
        r"\b((?:PRIMA|ULTRA)\s+\d+)\s+"  # name
        r"([0-9\.]+|#DIV/0!)\s+"          # prod
        r"([0-9,]+|#DIV/0!)\s+"           # inv
        r"([0-9,]+|#DIV/0!)\s+"           # avail inv
        r"([0-9,]+|#DIV/0!)\s+"           # avail room
        r"([0-9,]+|#DIV/0!)\s+"           # cap
        r"(\d+)%\s+"                      # cap%
        r"([0-9\.]+|#DIV/0!)\s+"          # avail inv days
        r"([0-9\.]+|#DIV/0!)"              # avail room days
        r"(?:\s+([<>]\s*\d+\s+days|\d+\s*-\s*\d+\s+days))?",  # optional label
        re.IGNORECASE
    )

    rows = []
    for m in row_re.finditer(t):
        name = m.group(1).upper().replace("  ", " ").strip()
        prod_kbd = _to_float(m.group(2))
        inv_kbbl = _to_float(m.group(3))
        avail_inv_kbbl = _to_float(m.group(4))
        avail_room_kbbl = _to_float(m.group(5))
        cap_kbbl = _to_float(m.group(6))
        cap_pct = _to_float(m.group(7))
        avail_inv_days = _to_float(m.group(8))
        avail_room_days = _to_float(m.group(9))
        doi_label = (m.group(10) or "").strip()

        rows.append({
            "product": name,
            "prod_kbd": prod_kbd,
            "inv_kbbl": inv_kbbl,
            "avail_inv_kbbl": avail_inv_kbbl,
            "avail_room_kbbl": avail_room_kbbl,
            "cap_kbbl": cap_kbbl,
            "cap_pct": cap_pct,
            "avail_inv_days": avail_inv_days,
            "avail_room_days": avail_room_days,
            "doi_label": doi_label,
        })

    if rows:
        # Deduplicate by product
        seen = set()
        out = []
        for r in rows:
            if r["product"] not in seen and r["product"] != "TOTAL":
                out.append(r)
                seen.add(r["product"])
        return out

    # Fallback: token state machine
    tokens = re.findall(r"PRIMA|ULTRA|\d+\.\d+|\d+%|\d+|#DIV/0!|>|<|-|days", text, flags=re.IGNORECASE)
    tokens = [tok for tok in tokens if tok.strip()]

    i = 0
    while i < len(tokens):
        tok = tokens[i].upper()
        if tok in ["PRIMA", "ULTRA"] and i + 1 < len(tokens):
            num = tokens[i+1]
            if not re.match(r"^\d+$", num):
                i += 1
                continue
            name = f"{tok} {num}"
            i += 2

            # collect until next PRIMA/ULTRA or TOTAL
            buf = []
            while i < len(tokens) and tokens[i].upper() not in ["PRIMA", "ULTRA", "TOTAL"]:
                buf.append(tokens[i])
                i += 1

            # We expect cap% token somewhere
            cap_pct = None
            for b in buf:
                if b.endswith('%'):
                    cap_pct = _to_float(b.replace('%',''))

            # Try map numeric sequence
            nums = []
            for b in buf:
                if b.lower() == 'days':
                    continue
                if b in ['>','<','-']:
                    continue
                if b.endswith('%'):
                    continue
                v = _to_float(b)
                if v is not None:
                    nums.append(v)

            # Try to find DOI label
            doi_label = ""
            if 'days' in [x.lower() for x in buf]:
                # grab tail from last '>'/'<' or numbers around '-'
                tail = " ".join(buf[-4:])
                tail = tail.replace(' - ', '-').replace('  ', ' ')
                if 'days' in tail.lower():
                    doi_label = tail

            def n(idx):
                return nums[idx] if idx < len(nums) else None

            rows.append({
                "product": name,
                "prod_kbd": n(0),
                "inv_kbbl": n(1),
                "avail_inv_kbbl": n(2),
                "avail_room_kbbl": n(3),
                "cap_kbbl": n(4),
                "cap_pct": cap_pct,
                "avail_inv_days": n(5),
                "avail_room_days": n(6),
                "doi_label": doi_label,
            })
        else:
            i += 1

    # Deduplicate
    seen = set()
    out = []
    for r in rows:
        if r["product"] and r["product"] not in seen and r["product"] != "TOTAL":
            out.append(r)
            seen.add(r["product"])
    return out


def doi_bucket(doi: Optional[float], doi_label: str) -> Optional[float]:
    if doi is not None:
        return doi
    l = (doi_label or "").lower()
    if ">" in l and "10" in l:
        return 12.0
    if "5" in l and "10" in l:
        return 7.0
    if "<" in l and "5" in l:
        return 3.0
    return None


# -----------------------------
# Dog stats from inventory
# -----------------------------

def compute_dog_stats(cap_pct: Optional[float], doi: Optional[float], room_days: Optional[float]) -> Tuple[int, int, int]:
    # Happiness from DOI
    if doi is None:
        happiness = 60
    elif doi > TARGETS["doi_good"]:
        happiness = 90
    elif doi >= TARGETS["doi_ok"]:
        happiness = 70
    elif doi >= TARGETS["doi_risk"]:
        happiness = 40
    else:
        happiness = 20

    # Hunger from capacity%
    if cap_pct is None:
        hunger = 50
    elif cap_pct < TARGETS["cap_low"]:
        hunger = 80
    elif cap_pct <= TARGETS["cap_high"]:
        hunger = 40
    else:
        hunger = 20

    # Room score from available room days
    if room_days is None:
        room_score = 60
    elif room_days > 10:
        room_score = 85
    elif room_days >= 5:
        room_score = 65
    else:
        room_score = 35

    energy = int((happiness + (100 - hunger) + room_score) / 3)
    return happiness, hunger, energy


# -----------------------------
# UI
# -----------------------------

st.set_page_config(page_title='Inventory Hound Dashboard', page_icon='🐶', layout='wide')
st.title('🐶 Inventory Hound Dashboard (One Dog per Product)')
st.caption('Upload a BOTF PI Daily PDF. Each product gets its own dog whose mood is driven by Days of Inventory (DOI) + capacity pressure.')

with st.sidebar:
    st.header('Upload')
    pdf_file = st.file_uploader('BOTF PI Daily report (PDF)', type=['pdf'])
    st.divider()
    st.header('Dog Actions (optional)')
    st.caption('You can give treats/walk/fetch, but dogs will always drift toward the inventory-driven health score.')

states_raw = load_all_states()

report_text = ""
products = []

if pdf_file is not None:
    try:
        report_text = extract_text_from_pdf(pdf_file)
        products = parse_product_summary(report_text)
    except Exception as e:
        st.error('Could not read PDF text. Try a different export or a clearer PDF.')
        st.stop()

if not products:
    st.info('Upload a PDF to generate dogs. Tip: the app looks for the PRIMA/ULTRA summary rows near the bottom of the report.')
    st.stop()

# Build a dataframe for display
view = pd.DataFrame(products)

# Compute inventory-driven scores per product
for p in products:
    doi = doi_bucket(p.get('avail_inv_days'), p.get('doi_label',''))
    cap_pct = p.get('cap_pct')
    room_days = p.get('avail_room_days')

    inv_happiness, inv_hunger, inv_energy = compute_dog_stats(cap_pct, doi, room_days)

    key = p['product']
    display_name = f"{p['product']} Pup"
    st_dog = get_state(states_raw, key, display_name)

    # Drift toward inventory-derived state
    blend = 0.55
    st_dog.happiness = int(st_dog.happiness * (1 - blend) + inv_happiness * blend)
    st_dog.hunger = int(st_dog.hunger * (1 - blend) + inv_hunger * blend)
    st_dog.energy = int(st_dog.energy * (1 - blend) + inv_energy * blend)

    # Persist updated drift
    put_state(states_raw, key, st_dog)

save_all_states(states_raw)

# Alerts
alerts = []
for p in products:
    doi = doi_bucket(p.get('avail_inv_days'), p.get('doi_label',''))
    cap_pct = p.get('cap_pct')
    if doi is not None and doi < 5:
        alerts.append(f"{DOG['alert']} {p['product']}: DOI is low ({doi:.1f} days)")
    if cap_pct is not None and cap_pct > 70:
        alerts.append(f"{DOG['alert']} {p['product']}: Capacity is high ({cap_pct:.0f}%)")
    if cap_pct is not None and cap_pct < 40:
        alerts.append(f"{DOG['alert']} {p['product']}: Capacity is low ({cap_pct:.0f}%)")

st.subheader('Quick Alerts')
if alerts:
    for a in alerts[:10]:
        st.write(f"- {a}")
else:
    st.write(f"- {DOG['celebrate']} No major DOI/capacity alarms detected.")

st.divider()

# Render dogs grid
st.subheader('Dogs by Product')
cols = st.columns(3)

for idx, p in enumerate(products):
    col = cols[idx % 3]
    key = p['product']
    s = get_state(states_raw, key, f"{p['product']} Pup")

    doi = doi_bucket(p.get('avail_inv_days'), p.get('doi_label',''))
    cap_pct = p.get('cap_pct')
    room_days = p.get('avail_room_days')

    with col:
        st.markdown(f"### {mood_face(s.hunger, s.energy, s.happiness)} {p['product']}")
        st.caption(f"{s.breed} • Level {s.level} • XP {s.xp}")

        st.progress(max(0, min(100, 100 - s.hunger)), text=f"Needs inventory (hunger): {s.hunger}/100")
        st.progress(s.energy, text=f"Energy: {s.energy}/100")
        st.progress(s.happiness, text=f"Happiness: {s.happiness}/100")

        # Inventory stats
        st.write("**Inventory inputs**")
        st.write(f"- Capacity: **{'—' if cap_pct is None else f'{cap_pct:.0f}%'}**")
        st.write(f"- DOI (Avail Inv Days): **{'—' if doi is None else f'{doi:.1f}'}**")
        st.write(f"- Avail Room Days: **{'—' if room_days is None else f'{room_days:.1f}'}**")

        # Optional actions per dog
        with st.expander('Actions for this dog (optional)'):
            s.display_name = st.text_input('Dog name', value=s.display_name, key=f"name_{key}")
            s.breed = st.selectbox('Dog vibe', options=BREEDS, index=BREEDS.index(s.breed) if s.breed in BREEDS else 0, key=f"breed_{key}")

            a1, a2, a3 = st.columns(3)
            if a1.button(f"Treat {DOG['treat']}", key=f"treat_{key}"):
                s.hunger -= 10
                s.happiness += 6
                s.xp += 10
            if a2.button(f"Walk {DOG['walk']}", key=f"walk_{key}"):
                s.energy += 10
                s.hunger += 3
                s.xp += 8
            if a3.button(f"Fetch {DOG['fetch']}", key=f"fetch_{key}"):
                s.happiness += 10
                s.energy -= 6
                s.xp += 10

            if st.button('Daily check-in ✅', key=f"checkin_{key}"):
                today_s = date.today().isoformat()
                if s.last_checkin != today_s:
                    s.last_checkin = today_s
                    s.xp += 20
                    s.happiness += 4
                else:
                    st.info('Already checked in today.')

            level_up(s)
            put_state(states_raw, key, s)
            save_all_states(states_raw)

        bark_line = BARKS.get(s.breed, ["Woof!"])[(s.level + s.hunger) % 2]
        st.write(f"{DOG['bark']} **{bark_line}**")

st.divider()

# Analytics tab
st.subheader('Inventory Table (parsed)')
show_cols = [
    'product','prod_kbd','inv_kbbl','avail_inv_kbbl','avail_room_kbbl','cap_kbbl','cap_pct','avail_inv_days','avail_room_days','doi_label'
]
existing = [c for c in show_cols if c in view.columns]
st.dataframe(view[existing], use_container_width=True)

# Simple charts
if 'cap_pct' in view.columns:
    cap_df = view.dropna(subset=['cap_pct']).copy()
    if not cap_df.empty:
        fig = px.bar(cap_df, x='product', y='cap_pct', title='Capacity % by Product')
        st.plotly_chart(fig, use_container_width=True)

if 'avail_inv_days' in view.columns:
    doi_df = view.dropna(subset=['avail_inv_days']).copy()
    if not doi_df.empty:
        fig = px.bar(doi_df, x='product', y='avail_inv_days', title='Days of Inventory (Avail Inv Days) by Product')
        st.plotly_chart(fig, use_container_width=True)
