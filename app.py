import json
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple, Dict

import pandas as pd
import streamlit as st
import plotly.express as px

# ---------------------------
# Hypercare Pet Dashboard
# Business + Cyber Pet Combo
# ---------------------------

STATE_FILE = Path('.hypercare_pet_state.json')

TARGETS = {
    "adoption_rate": 0.80,  # from your adoption legend (>=80% = on track)
    "interface_success": 0.99,
    "max_open_tickets": 25,
    "max_overdue_tasks": 25,
}

EMOJI = {
    "happy": "😄",
    "ok": "🙂",
    "worry": "😟",
    "sad": "😢",
    "sleep": "😴",
    "celebrate": "🎉",
    "alert": "🚨",
    "ticket": "🎫",
    "task": "✅",
    "adopt": "📈",
    "interface": "🔌",
}

@dataclass
class PetState:
    name: str = "HyperPup"
    hunger: int = 30      # 0-100 (higher = needs help)
    energy: int = 70      # 0-100
    happiness: int = 70   # 0-100
    last_checkin: str = ""  # ISO date
    xp: int = 0
    level: int = 1

    def clamp(self):
        self.hunger = max(0, min(100, int(self.hunger)))
        self.energy = max(0, min(100, int(self.energy)))
        self.happiness = max(0, min(100, int(self.happiness)))
        self.level = max(1, int(self.level))
        self.xp = max(0, int(self.xp))


def load_state() -> PetState:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            s = PetState(**data)
            s.clamp()
            return s
        except Exception:
            pass
    return PetState()


def save_state(state: PetState):
    state.clamp()
    STATE_FILE.write_text(json.dumps(asdict(state), indent=2))


def level_up(state: PetState):
    # Simple XP ladder
    needed = 100 + (state.level - 1) * 75
    while state.xp >= needed:
        state.xp -= needed
        state.level += 1
        needed = 100 + (state.level - 1) * 75


def pet_face(state: PetState) -> str:
    # Mood based on combined health
    stress = (state.hunger * 0.5) + ((100 - state.energy) * 0.25) + ((100 - state.happiness) * 0.25)
    if state.energy < 25:
        return EMOJI["sleep"]
    if stress < 25:
        return EMOJI["happy"]
    if stress < 45:
        return EMOJI["ok"]
    if stress < 65:
        return EMOJI["worry"]
    return EMOJI["sad"]


def score_from_metrics(adoption_rate: Optional[float], interface_success: Optional[float], open_tickets: Optional[int], overdue_tasks: Optional[int]) -> Dict[str, int]:
    """Convert business metrics into pet stats (0-100). Higher hunger = worse."""
    # Happiness: adoption and interface health
    h = 70
    if adoption_rate is not None:
        # Scale around target 0.80
        h = int(50 + 50 * min(1.0, max(0.0, adoption_rate / TARGETS["adoption_rate"])))
    if interface_success is not None:
        h = int((h + (50 + 50 * min(1.0, max(0.0, interface_success / TARGETS["interface_success"])))) / 2)

    # Hunger: tickets + overdue tasks
    hunger = 25
    if open_tickets is not None:
        hunger += int(60 * min(1.0, open_tickets / max(1, TARGETS["max_open_tickets"])))
    if overdue_tasks is not None:
        hunger += int(40 * min(1.0, overdue_tasks / max(1, TARGETS["max_overdue_tasks"])))
    hunger = max(0, min(100, hunger))

    # Energy: tasks progress proxy
    energy = 70
    if overdue_tasks is not None:
        energy = int(85 - 60 * min(1.0, overdue_tasks / max(1, TARGETS["max_overdue_tasks"])))
    energy = max(0, min(100, energy))

    return {"happiness": h, "hunger": hunger, "energy": energy}


# ---------------------------
# Data loaders
# ---------------------------

def try_read_excel(upload, sheet_name: str) -> Optional[pd.DataFrame]:
    try:
        return pd.read_excel(upload, sheet_name=sheet_name, engine='openpyxl')
    except Exception:
        return None


def parse_adoption(df: pd.DataFrame) -> Tuple[Optional[float], pd.DataFrame]:
    """Expect columns like Workstream, Total Users, Trained, Active in SAP, Adoption %"""
    if df is None or df.empty:
        return None, pd.DataFrame()

    # Normalize columns
    cols = {c: c.strip() for c in df.columns}
    df = df.rename(columns=cols)

    # Keep only plausible rows
    needed = ["Workstream", "Total Users", "Trained", "Active in SAP"]
    if not all(c in df.columns for c in needed):
        return None, pd.DataFrame()

    clean = df[needed + (["Adoption %"] if "Adoption %" in df.columns else [])].copy()
    # Drop totals row if present
    clean = clean[clean["Workstream"].astype(str).str.upper() != "TOTAL"]

    # Compute adoption if missing
    if "Adoption %" not in clean.columns:
        clean["Adoption %"] = clean["Active in SAP"] / clean["Total Users"].replace(0, pd.NA)

    # Overall adoption weighted by total users
    try:
        overall = (clean["Active in SAP"].sum() / clean["Total Users"].sum())
    except Exception:
        overall = None

    return overall, clean


def parse_tasks(df: pd.DataFrame) -> Tuple[int, pd.DataFrame]:
    """Expect columns like Task Name, Finish, % Complete, Status, Owner Email (Lookup)"""
    if df is None or df.empty:
        return 0, pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Try to find common columns
    finish_col = None
    for c in df.columns:
        if str(c).lower() in ["finish", "due", "due date", "end", "end date"]:
            finish_col = c
            break

    pct_col = None
    for c in df.columns:
        if "%" in str(c) and "complete" in str(c).lower():
            pct_col = c
            break
        if str(c).lower() in ["% complete", "percent complete", "complete"]:
            pct_col = c
            break

    name_col = None
    for c in df.columns:
        if str(c).lower() in ["task name", "name", "task"]:
            name_col = c
            break

    if finish_col is None or pct_col is None:
        return 0, pd.DataFrame()

    # Parse % complete
    pct = df[pct_col]
    def to_float(x):
        if pd.isna(x):
            return 0.0
        s = str(x).strip()
        if s.endswith('%'):
            try:
                return float(s[:-1]) / 100
            except Exception:
                return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0

    df["_pct"] = pct.apply(to_float)

    # Parse dates
    df["_finish"] = pd.to_datetime(df[finish_col], errors='coerce')

    today = pd.Timestamp(date.today())
    overdue = df[(df["_finish"].notna()) & (df["_finish"] < today) & (df["_pct"] < 0.999)]

    # Prep a clean table
    keep = []
    if name_col: keep.append(name_col)
    keep += [finish_col, pct_col]
    for c in ["Status", "Task Owner (from MMP)", "Owner Email (Lookup)", "Notes"]:
        if c in df.columns:
            keep.append(c)
    clean = overdue[keep].copy()
    clean = clean.sort_values(by=finish_col)

    return int(len(overdue)), clean


def parse_interface(df: pd.DataFrame) -> Tuple[Optional[float], Optional[int], Optional[int], pd.DataFrame]:
    """Expect columns including Status with ✅/⚠️/🔴 and Workstream / Interface Name"""
    if df is None or df.empty:
        return None, None, None, pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "Status" not in df.columns:
        return None, None, None, pd.DataFrame()

    status = df["Status"].astype(str)
    ok = status.str.contains('✅')
    warn = status.str.contains('⚠️')
    fail = status.str.contains('🔴')

    total = int(len(df))
    ok_count = int(ok.sum())
    warn_count = int(warn.sum())
    fail_count = int(fail.sum())

    success = (ok_count / total) if total else None

    # Minimal table
    keep = [c for c in ["Workstream", "Interface Name", "Source System", "Target System", "Frequency", "Status"] if c in df.columns]
    table = df[keep].copy() if keep else df.head(25)

    return success, warn_count, fail_count, table


def parse_servicenow(df: pd.DataFrame) -> Tuple[Optional[int], Optional[int], pd.DataFrame]:
    """Very forgiving: tries to find state/status and priority."""
    if df is None or df.empty:
        return None, None, pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Find a state/status column
    state_col = None
    for c in df.columns:
        if str(c).lower() in ["state", "status", "incident state", "ticket state"]:
            state_col = c
            break

    # If no state column, we can't compute open/closed reliably
    if state_col is None:
        return None, None, df.head(50)

    states = df[state_col].astype(str).str.lower()
    closed_mask = states.str.contains('closed') | states.str.contains('resolved') | states.str.contains('complete')
    open_mask = ~closed_mask

    open_count = int(open_mask.sum())
    closed_count = int(closed_mask.sum())

    # Display table (top open)
    keep_cols = []
    for c in ["Snow Number", "Number", "Short description", "Short Description", "Module", "Priority", state_col, "Assignment group", "Assigned to", "Created", "Opened", "Updated"]:
        if c in df.columns and c not in keep_cols:
            keep_cols.append(c)
    table = df.loc[open_mask, keep_cols].head(50) if keep_cols else df.loc[open_mask].head(50)

    return open_count, closed_count, table


# ---------------------------
# UI
# ---------------------------

st.set_page_config(page_title='Hypercare Pet Dashboard', page_icon='🐾', layout='wide')

state = load_state()

st.title('🐾 Hypercare Pet Dashboard (Business + Pet Combo)')

with st.sidebar:
    st.header('Data Inputs')
    hc_file = st.file_uploader('Upload your Hypercare workbook (Excel)', type=['xlsx', 'xlsm'])
    metric_file = st.file_uploader('Upload your Hypercare metric pack (Excel) (optional)', type=['xlsx', 'xlsm'])
    sn_file = st.file_uploader('Upload ServiceNow export (CSV) (optional)', type=['csv'])

    st.divider()
    st.header('Pet Settings')
    state.name = st.text_input('Pet name', value=state.name)

    st.caption('Pet = your Hypercare health. Better metrics → happier pet.')

    st.divider()
    st.header('Actions')
    colA, colB = st.columns(2)
    if colA.button('Feed (reduce hunger) 🍖'):
        state.hunger -= 12
        state.happiness += 4
        state.xp += 10
    if colB.button('Play (boost happiness) 🎾'):
        state.happiness += 10
        state.energy -= 10
        state.xp += 10
    if st.button('Rest (restore energy) 🛌'):
        state.energy += 18
        state.hunger += 4
        state.xp += 6

    if st.button('Daily check-in ✅'):
        today_s = date.today().isoformat()
        if state.last_checkin != today_s:
            state.last_checkin = today_s
            state.xp += 25
            state.happiness += 6
        else:
            st.info('Already checked in today.')

    level_up(state)
    save_state(state)

# --- Load data
adoption_rate = None
adoption_df = pd.DataFrame()

overdue_tasks = None
overdue_tasks_df = pd.DataFrame()

interface_success = None
interface_warn = None
interface_fail = None
interface_df = pd.DataFrame()

open_tickets = None
closed_tickets = None
sn_table = pd.DataFrame()

if hc_file is not None:
    # Sheet names based on your workbook navigation
    adoption_sheet = "Adoption Report"
    tasks_sheet = "Hypercare Tasks"

    df_adopt_raw = try_read_excel(hc_file, adoption_sheet)
    adoption_rate, adoption_df = parse_adoption(df_adopt_raw)

    df_tasks_raw = try_read_excel(hc_file, tasks_sheet)
    overdue_tasks, overdue_tasks_df = parse_tasks(df_tasks_raw)

if metric_file is not None:
    # Your metric pack uses "Hypercare Interface Report" tab
    interface_sheet = "Hypercare Interface Report"
    df_int_raw = try_read_excel(metric_file, interface_sheet)
    interface_success, interface_warn, interface_fail, interface_df = parse_interface(df_int_raw)

if sn_file is not None:
    try:
        sn_raw = pd.read_csv(sn_file)
        open_tickets, closed_tickets, sn_table = parse_servicenow(sn_raw)
    except Exception:
        pass

# If ServiceNow not provided, approximate open tickets from metric pack weekly tracker not populated; leave as None

# --- Convert metrics to pet stats
scores = score_from_metrics(adoption_rate, interface_success, open_tickets, overdue_tasks)

# Blend current pet stats toward metric-based stats (keeps the pet feeling alive)
blend = 0.35
state.happiness = int(state.happiness * (1 - blend) + scores['happiness'] * blend)
state.hunger = int(state.hunger * (1 - blend) + scores['hunger'] * blend)
state.energy = int(state.energy * (1 - blend) + scores['energy'] * blend)
level_up(state)
save_state(state)

# --- Header: pet + tiles
left, mid, right = st.columns([1.2, 2.2, 1.6])

with left:
    st.subheader(f"{pet_face(state)}  {state.name}")
    st.caption(f"Level {state.level} • XP {state.xp}")
    st.progress(max(0, min(100, 100 - state.hunger)), text=f"Hunger (needs help): {state.hunger}/100")
    st.progress(state.energy, text=f"Energy: {state.energy}/100")
    st.progress(state.happiness, text=f"Happiness: {state.happiness}/100")

with mid:
    st.subheader('Today’s Hypercare Health')
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{EMOJI['adopt']} Adoption", "—" if adoption_rate is None else f"{adoption_rate:.0%}")
    c2.metric(f"{EMOJI['interface']} Interface success", "—" if interface_success is None else f"{interface_success:.0%}")
    c3.metric(f"{EMOJI['ticket']} Open tickets", "—" if open_tickets is None else f"{open_tickets}")
    c4.metric(f"{EMOJI['task']} Overdue tasks", "—" if overdue_tasks is None else f"{overdue_tasks}")

    # Quick guidance
    tips = []
    if adoption_rate is not None and adoption_rate < TARGETS['adoption_rate']:
        tips.append(f"{EMOJI['alert']} Adoption is below {TARGETS['adoption_rate']:.0%}. Consider targeting low-adoption workstreams with quick refreshers.")
    if interface_success is not None and interface_success < TARGETS['interface_success']:
        tips.append(f"{EMOJI['alert']} Interface success is below {TARGETS['interface_success']:.0%}. Review the at-risk interfaces list.")
    if open_tickets is not None and open_tickets > TARGETS['max_open_tickets']:
        tips.append(f"{EMOJI['alert']} Open tickets are high (> {TARGETS['max_open_tickets']}). Consider a triage sweep + aging review.")
    if overdue_tasks is not None and overdue_tasks > 0:
        tips.append(f"{EMOJI['alert']} You have overdue tasks. Focus on the top 5 oldest due dates first.")

    if tips:
        for t in tips[:4]:
            st.write(f"- {t}")
    else:
        st.write(f"- {EMOJI['celebrate']} Looking good — keep the rhythm (daily check-in + keep tickets moving).")

with right:
    st.subheader('Exec-ready Snapshot')
    lines = []
    if adoption_rate is not None:
        lines.append(f"Adoption: {adoption_rate:.0%} (target ≥ {TARGETS['adoption_rate']:.0%})")
    if interface_success is not None:
        lines.append(f"Interface success: {interface_success:.0%} (target ≥ {TARGETS['interface_success']:.0%})")
    if open_tickets is not None and closed_tickets is not None:
        lines.append(f"Tickets: {open_tickets} open / {closed_tickets} closed (from export)")
    elif open_tickets is not None:
        lines.append(f"Tickets: {open_tickets} open")
    if overdue_tasks is not None:
        lines.append(f"Overdue tasks: {overdue_tasks}")

    if not lines:
        st.info('Upload at least the Hypercare workbook to generate a snapshot.')
    else:
        st.code("\n".join([f"• {x}" for x in lines]), language='markdown')

# --- Tabs
st.divider()

tab1, tab2, tab3, tab4 = st.tabs(['📈 Adoption', '✅ Tasks', '🎫 Tickets', '🔌 Interfaces'])

with tab1:
    st.subheader('Adoption by workstream')
    if adoption_df.empty:
        st.warning('Upload the Hypercare workbook and ensure it has an "Adoption Report" sheet with columns: Workstream, Total Users, Trained, Active in SAP.')
    else:
        view = adoption_df.copy()
        view['Adoption %'] = (view['Adoption %']).astype(float)
        fig = px.bar(view, x='Workstream', y='Adoption %', color='Adoption %', color_continuous_scale='Blues', title='Adoption % by Workstream')
        fig.update_yaxes(tickformat='.0%')
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(view, use_container_width=True)

with tab2:
    st.subheader('Overdue tasks (if any)')
    if overdue_tasks_df.empty:
        st.info('No overdue tasks detected (or sheet/columns not found).')
    else:
        st.dataframe(overdue_tasks_df, use_container_width=True)

with tab3:
    st.subheader('ServiceNow tickets (from export)')
    if sn_file is None:
        st.info('Upload a ServiceNow CSV export to populate this tab (this app does not directly connect to ServiceNow).')
    else:
        if open_tickets is None:
            st.warning('Could not detect a State/Status column in the CSV. Try exporting a view that includes State.')
        else:
            st.write(f"Open tickets: **{open_tickets}** • Closed tickets: **{closed_tickets}**")
            st.dataframe(sn_table, use_container_width=True)

with tab4:
    st.subheader('Interface health (from metric pack)')
    if interface_df.empty:
        st.info('Upload the Hypercare metric pack and ensure it has a "Hypercare Interface Report" sheet with a Status column (✅ / ⚠️ / 🔴).')
    else:
        st.write(f"At-risk (⚠️): **{interface_warn}** • Failed (🔴): **{interface_fail}**")
        st.dataframe(interface_df, use_container_width=True)

# --- Footer: Optional link to Power BI report (manual)
st.divider()
st.caption('Tip: You can also link/launch your existing Power BI Hypercare report from this page in your SharePoint hub as a companion.')
