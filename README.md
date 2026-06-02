# Bus Charging Scheduler

A Streamlit app that schedules electric bus charging along the Bengaluru → Kochi route.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Change a weight

Open `scenarios/scenario_N.json` and edit the `weights` object:

```json
"weights": {
  "individual": 1.0,
  "operator":   2.0,
  "overall":    1.0
}
```

That's it. No code changes needed. The scheduler reads weights at runtime.

## Add a new rule

Open `scheduler.py`. Add a function and register it:

```python
def rule_priority_bus(bus: Bus, wait_so_far: float, same_op_count: int) -> float:
    """Express buses get a 5× priority boost."""
    return 5.0 if getattr(bus, "priority", False) else 1.0

RULE_REGISTRY["priority"] = rule_priority_bus
```

Then add `"priority": 1.0` to the `weights` block in any scenario JSON where you want it active.
The engine loops over `RULE_REGISTRY` — no other changes needed.

## Add a new scenario

Create `scenarios/scenario_6.json` following the same schema as the existing files.
Drop it in the folder; the app auto-discovers it on next load.

## Project structure

```
bus_scheduler/
├── app.py            # Streamlit UI
├── scheduler.py      # Engine + domain types + rule registry
├── requirements.txt
├── README.md
├── ARCHITECTURE.md
└── scenarios/
    ├── scenario_1.json   # Even spacing (baseline)
    ├── scenario_2.json   # Bunched start
    ├── scenario_3.json   # Asymmetric load
    ├── scenario_4.json   # Operator-heavy (operator weight = 2.0)
    └── scenario_5.json   # Worst-case convergence
```
