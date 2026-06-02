# Architecture

## Scheduler approach

**Discrete-event simulation with a weighted priority rule engine.**

Each bus is an event in a min-heap. When a bus arrives at a station, it competes for the charger using a score computed by summing weighted rule outputs. Higher score = served sooner. The heap advances time naturally — no fixed time-step, no polling.

Why this and not alternatives:

| Approach | Why not |
|---|---|
| FIFO / First-come-first-served | Ignores weights entirely; can't express operator fairness |
| Integer Linear Programming | Heavy dependency, hard to add soft rules incrementally |
| Constraint satisfaction (OR-Tools) | Overkill for this problem size; rule addition requires solver re-modelling |
| Fixed time-step simulation | Wastes cycles on idle periods; imprecise for 25-min charge window |

Discrete-event simulation gives exact timestamps, scales to thousands of buses with no rewrite, and adding a rule is one function — the engine doesn't change.

## Rule registry

```python
RULE_REGISTRY: dict[str, Rule] = {
    "individual": rule_individual_wait,
    "operator":   rule_operator_fairness,
    "overall":    rule_overall_throughput,
}
```

Rules are plain functions `(bus, wait_so_far, same_op_count) -> float`. The scheduler loops over the registry and sums `weight × rule(...)`. Weights come from the scenario JSON. Neither the engine nor any existing rule changes when a new rule is added.

## Data structure design

A scenario JSON carries everything the scheduler needs:

```json
{
  "id": "scenario_1",
  "name": "...",
  "description": "...",
  "speed_kmh": 60,
  "battery_range_km": 240,
  "charge_time_min": 25,
  "route": {
    "nodes": ["Bengaluru", "A", "B", "C", "D", "Kochi"],
    "segments": [{ "from_node": "Bengaluru", "to_node": "A", "distance": 100 }, ...]
  },
  "stations": [{ "id": "A", "distance_from_origin": 100, "chargers": 1 }, ...],
  "buses": [{ "id": "bus-BK-01", "operator": "kpn", "origin": "Bengaluru",
              "destination": "Kochi", "departure": "19:00" }, ...],
  "weights": { "individual": 1.0, "operator": 1.0, "overall": 1.0 }
}
```

## Anticipated future changes — and how each is handled

| Change | How the design handles it |
|---|---|
| **Add a station** (e.g. station E between D and Kochi) | Add a node to `route.nodes`, a segment to `route.segments`, and an entry to `stations`. Zero code changes. |
| **Multiple chargers per station** | `Station.chargers` field already exists. Set it to 2. The engine picks the least-busy charger automatically. Zero code changes. |
| **New operator** (e.g. RedBus) | Add buses with `"operator": "redbus"` in the scenario JSON. The rule engine is operator-agnostic. Zero code changes. |
| **New route** (e.g. Chennai → Coimbatore) | Create a new scenario JSON with different `route.nodes` and `segments`. `Route.ordered_stops` and `distance_along` work for any graph path. Zero code changes. |
| **Change a weight** | Edit one JSON field. Zero code changes. |
| **Add a new soft rule** (e.g. priority buses, time-of-day cost) | Write one function, add it to `RULE_REGISTRY`, add its weight key to scenario JSON. Engine unchanged. |
| **Add a new hard constraint** (e.g. driver shift ends) | Add a pre-simulation validation pass or filter on departure times. Engine is separate from validation. |
| **Different battery ranges per bus** | `Bus.battery_range` is already per-bus. Set it individually in the JSON. `_assign_stations` reads `bus.battery_range`, not a global. |
| **Variable charging times** (e.g. fast chargers) | Add `charge_time_min` to `Station` (override global). One `or` in the engine: `station.charge_time_min or cfg.charge_time_min`. |
| **Time-of-day electricity costs** | Add a rule `rule_electricity_cost(bus, ...)` that looks up a cost table (also in the JSON). Register it. One new function. |
| **Multiple routes sharing stations** | Each scenario has its own route. Run multiple schedulers; merge charger queues. Or add a `route_id` field to buses and extend the engine's station queue by `(station_id, route_id)`. Small, isolated change. |
| **More than 20 buses** | The heap scales as O(n log n). No structural changes. |
| **Scenario with no KB direction** (Scenario 3) | The scheduler handles it natively — it just processes whatever buses exist. Zero code changes. |

## How to change a weight

```json
// scenarios/scenario_4.json
"weights": {
  "individual": 1.0,
  "operator":   2.0,
  "overall":    1.0
}
```

One value. One file. No code.

## How to add a new rule (live example)

Say tomorrow we learn that KPN buses have SLA guarantees and must wait no more than 30 min:

```python
# scheduler.py — append to RULE_REGISTRY

def rule_sla_guarantee(bus: Bus, wait_so_far: float, same_op_count: int) -> float:
    """Operators with SLA get a large priority boost once wait exceeds threshold."""
    SLA_OPERATORS = {"kpn"}
    SLA_THRESHOLD_MIN = 30.0
    if bus.operator in SLA_OPERATORS and wait_so_far > SLA_THRESHOLD_MIN:
        return 100.0  # very high — effectively pre-empt queue
    return 0.0

RULE_REGISTRY["sla"] = rule_sla_guarantee
```

Then in any scenario JSON where this should apply:

```json
"weights": { "individual": 1.0, "operator": 1.0, "overall": 1.0, "sla": 1.0 }
```

Scenarios without the `"sla"` key are unaffected — `weights.get("sla", 0.0)` defaults to zero.

## Assumptions made

1. **Speed is uniform**: 60 km/h everywhere. No traffic, no road variation. Stated in the spec.
2. **Greedy station assignment**: each bus charges at the latest possible station before it would run out. This minimises stops, reduces congestion, and is optimal for individual trip time when no congestion exists. Under heavy load, the simulation adjusts timing via waits.
3. **FCFS within same priority score**: if two buses have identical weighted scores, the one that arrived first is served first (heap tie-breaking by sequence number).
4. **No mid-route battery top-ups**: buses only charge at scheduled stops. Partial charges are not modelled (spec says charging always fills to full).
5. **Overnight trips are fine**: arrival times like 28:50 mean 04:50 the next day. The scheduler uses absolute minutes and doesn't wrap at midnight.
6. **Endpoints (Bengaluru, Kochi) are not scheduling stations**: they have slow chargers that always top up the bus before departure. Out of scope per the spec.
