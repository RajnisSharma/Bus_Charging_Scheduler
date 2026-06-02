"""
Bus Charging Scheduler — Streamlit UI
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from scheduler import ScenarioConfig, Scheduler, format_timeline, _min_to_hhmm

st.set_page_config(
    page_title="Bus Charging Scheduler",
    page_icon="⚡",
    layout="wide",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

h1, h2, h3 { font-family: 'Space Mono', monospace; }

.stApp { background-color: #0f1117; color: #e8eaf0; }

.metric-card {
    background: #1a1d2e;
    border: 1px solid #2d3154;
    border-radius: 8px;
    padding: 16px 20px;
    text-align: center;
}
.metric-card .value {
    font-family: 'Space Mono', monospace;
    font-size: 1.8rem;
    font-weight: 700;
    color: #7c83ff;
}
.metric-card .label {
    font-size: 0.75rem;
    color: #8890b0;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 4px;
}

.stop-pill {
    display: inline-block;
    background: #1e2235;
    border: 1px solid #3a3f6e;
    border-radius: 4px;
    padding: 2px 8px;
    font-family: 'Space Mono', monospace;
    font-size: 0.75rem;
    margin: 2px;
    color: #a0a8d8;
}
.wait-pill {
    display: inline-block;
    border-radius: 4px;
    padding: 2px 8px;
    font-family: 'Space Mono', monospace;
    font-size: 0.72rem;
    margin: 2px;
}

.op-kpn      { color: #7c83ff; border-left: 3px solid #7c83ff; padding-left: 6px; }
.op-freshbus { color: #56e39f; border-left: 3px solid #56e39f; padding-left: 6px; }
.op-flixbus  { color: #f7b731; border-left: 3px solid #f7b731; padding-left: 6px; }

.section-header {
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #5a6080;
    border-bottom: 1px solid #1e2235;
    padding-bottom: 8px;
    margin-bottom: 16px;
    margin-top: 32px;
}

div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Load scenarios ───────────────────────────────────────────────────────────
SCENARIO_DIR = Path(__file__).parent / "scenarios"

@st.cache_data
def load_scenario(path: str):
    cfg = ScenarioConfig.from_file(path)
    timelines = Scheduler(cfg).run()
    return cfg, timelines

scenario_files = sorted(SCENARIO_DIR.glob("scenario_*.json"))
scenario_options = {}
for f in scenario_files:
    import json
    meta = json.loads(f.read_text())
    scenario_options[meta["name"]] = str(f)


# ── Header ───────────────────────────────────────────────────────────────────
st.markdown("# ⚡ Bus Charging Scheduler")
st.markdown("<p style='color:#5a6080;font-size:0.9rem;margin-top:-8px;'>Bengaluru → A → B → C → D → Kochi · 540 km · 240 km range</p>", unsafe_allow_html=True)

col_sel, col_spacer = st.columns([2, 3])
with col_sel:
    selected_name = st.selectbox("Select Scenario", list(scenario_options.keys()), label_visibility="collapsed")

cfg, timelines = load_scenario(scenario_options[selected_name])

st.markdown(f"<p style='color:#8890b0;font-size:0.88rem;'>{cfg.description}</p>", unsafe_allow_html=True)


# ── Summary metrics ──────────────────────────────────────────────────────────
waits = [t.total_wait for t in timelines]
durations = [t.total_duration for t in timelines]
weights = cfg.weights

cols = st.columns(6)
metrics = [
    (len(timelines),                       "Buses"),
    (f"{sum(waits)/len(waits):.0f} min",   "Avg Wait"),
    (f"{max(waits):.0f} min",              "Max Wait"),
    (f"{sum(durations)/len(durations):.0f} min", "Avg Trip"),
    (f"w={weights.get('individual',1):.1f}", "Individual Weight"),
    (f"w={weights.get('operator',1):.1f}",   "Operator Weight"),
]
for col, (val, label) in zip(cols, metrics):
    with col:
        st.markdown(f"""
        <div class="metric-card">
            <div class="value">{val}</div>
            <div class="label">{label}</div>
        </div>
        """, unsafe_allow_html=True)


# ── Section 1: Scenario Input ────────────────────────────────────────────────
st.markdown('<div class="section-header">① Scenario Input</div>', unsafe_allow_html=True)

OP_COLORS = {"kpn": "🟣", "freshbus": "🟢", "flixbus": "🟡"}

input_rows = []
for b in cfg.buses:
    input_rows.append({
        "Bus ID": b.id,
        "Operator": f"{OP_COLORS.get(b.operator,'')} {b.operator}",
        "Direction": b.direction,
        "Departure": _min_to_hhmm(b.departure_min),
    })

input_df = pd.DataFrame(input_rows)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**BK — Bengaluru → Kochi**")
    bk = input_df[input_df["Direction"].str.startswith("Bengaluru")]
    st.dataframe(bk.reset_index(drop=True), use_container_width=True, hide_index=True)
with c2:
    st.markdown("**KB — Kochi → Bengaluru**")
    kb = input_df[input_df["Direction"].str.startswith("Kochi")]
    st.dataframe(kb.reset_index(drop=True), use_container_width=True, hide_index=True)

# Weights display
st.markdown(f"""
<div style='background:#1a1d2e;border:1px solid #2d3154;border-radius:8px;padding:12px 20px;margin-top:12px;font-size:0.85rem;'>
  <span style='color:#5a6080;font-family:Space Mono,monospace;font-size:0.7rem;text-transform:uppercase;letter-spacing:0.1em;'>Weights</span><br>
  Individual <b style='color:#7c83ff'>{weights.get("individual",1)}</b> &nbsp;·&nbsp;
  Operator <b style='color:#56e39f'>{weights.get("operator",1)}</b> &nbsp;·&nbsp;
  Overall <b style='color:#f7b731'>{weights.get("overall",1)}</b>
</div>
""", unsafe_allow_html=True)


# ── Section 2: Per-Bus Timetable ─────────────────────────────────────────────
st.markdown('<div class="section-header">② Per-Bus Timetable</div>', unsafe_allow_html=True)

filter_op = st.multiselect(
    "Filter by operator",
    ["kpn", "freshbus", "flixbus"],
    default=["kpn", "freshbus", "flixbus"],
    label_visibility="collapsed",
)
filter_dir = st.radio("Direction", ["All", "Bengaluru→Kochi", "Kochi→Bengaluru"],
                      horizontal=True, label_visibility="collapsed")

timetable_rows = []
for t in timelines:
    ft = format_timeline(t)
    if ft["operator"] not in filter_op:
        continue
    if filter_dir != "All" and ft["direction"] != filter_dir:
        continue

    stops_str = " → ".join(s["station"] for s in ft["charge_stops"]) or "—"
    waits_str = " / ".join(
        f"{s['wait_min']:.0f}m" for s in ft["charge_stops"]
    ) or "0"

    timetable_rows.append({
        "Bus": ft["bus_id"],
        "Op": ft["operator"],
        "Direction": ft["direction"],
        "Depart": ft["depart"],
        "Charge Stops": stops_str,
        "Wait at Each (min)": waits_str,
        "Total Wait": f"{ft['total_wait_min']:.0f} min",
        "Arrive": ft["arrive"],
        "Trip Duration": f"{ft['total_duration_min']:.0f} min",
    })

if timetable_rows:
    tbl_df = pd.DataFrame(timetable_rows)
    st.dataframe(tbl_df, use_container_width=True, hide_index=True)
else:
    st.info("No buses match the current filters.")


# ── Section 3: Per-Station View ───────────────────────────────────────────────
st.markdown('<div class="section-header">③ Per-Station Charging Order</div>', unsafe_allow_html=True)

station_ids = [s.id for s in cfg.stations]
station_tabs = st.tabs([f"Station {sid}" for sid in station_ids])

for tab, sid in zip(station_tabs, station_ids):
    with tab:
        # Collect all charge events at this station
        events = []
        for t in timelines:
            for stop in t.charge_stops:
                if stop.station_id == sid:
                    events.append({
                        "Bus": t.bus.id,
                        "Operator": t.bus.operator,
                        "Direction": t.bus.direction,
                        "Arrive": _min_to_hhmm(stop.arrive_min),
                        "Wait (min)": round(stop.wait_min, 1),
                        "Charge Start": _min_to_hhmm(stop.charge_start_min),
                        "Charge End": _min_to_hhmm(stop.charge_end_min),
                    })

        if not events:
            st.write("No buses charged here in this scenario.")
            continue

        events.sort(key=lambda e: e["Charge Start"])
        for i, ev in enumerate(events, 1):
            ev["#"] = i

        ev_df = pd.DataFrame(events)[["#","Bus","Operator","Direction","Arrive","Wait (min)","Charge Start","Charge End"]]

        # Small utilisation bar
        total_charging = len(events) * cfg.charge_time_min
        if events:
            span_start = min(e["Charge Start"] for e in events)
            span_end   = max(e["Charge End"]   for e in events)
            # compute span in minutes
            def hhmm_diff(a, b):
                def to_m(t):
                    h, m = map(int, t.split(":"))
                    return h*60 + m
                return to_m(b) - to_m(a)
            span = hhmm_diff(span_start, span_end) or 1
            utilisation = min(100, total_charging / span * 100)
        else:
            utilisation = 0

        st.markdown(f"""
        <div style='display:flex;align-items:center;gap:12px;margin-bottom:12px;'>
          <span style='font-size:0.8rem;color:#8890b0;'>{len(events)} buses charged · {utilisation:.0f}% utilisation</span>
          <div style='flex:1;background:#1e2235;border-radius:4px;height:8px;'>
            <div style='background:#7c83ff;width:{utilisation:.0f}%;height:100%;border-radius:4px;'></div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.dataframe(ev_df, use_container_width=True, hide_index=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style='margin-top:48px;padding-top:16px;border-top:1px solid #1e2235;font-size:0.75rem;color:#3a4060;text-align:center;'>
  Speed: 60 km/h · Range: 240 km · Charge time: 25 min · 1 charger/station
</div>
""", unsafe_allow_html=True)
