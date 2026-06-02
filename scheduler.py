"""
Bus Charging Scheduler — Core Engine

Design philosophy:
- Rules are data: each rule is a callable (bus, state) -> score
- Weights live in scenario config, never scattered in rule logic
- Adding a rule = one new function + one registry entry; engine unchanged
- Scaling: more buses/stations/operators/routes = just more data
"""

from __future__ import annotations
import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    from_node: str
    to_node: str
    distance: int  # km


@dataclass
class Station:
    id: str
    distance_from_origin: int  # km from first node in route
    chargers: int = 1          # supports multiple chargers per station


@dataclass
class Route:
    nodes: list[str]
    segments: list[Segment]

    def _node_index(self, node: str) -> int:
        return self.nodes.index(node)

    def distance_along(self, a: str, b: str) -> int:
        """
        Distance from a to b travelling in the direction a→b.
        Works for both forward and reverse travel.
        """
        ia, ib = self._node_index(a), self._node_index(b)
        if ia <= ib:
            return sum(s.distance for s in self.segments[ia:ib])
        else:
            return sum(s.distance for s in self.segments[ib:ia])

    def ordered_stops(self, origin: str, destination: str) -> list[str]:
        """All route nodes from origin to destination inclusive."""
        io, id_ = self._node_index(origin), self._node_index(destination)
        if io <= id_:
            return self.nodes[io: id_ + 1]
        else:
            return list(reversed(self.nodes[id_: io + 1]))


@dataclass
class Bus:
    id: str
    operator: str
    origin: str
    destination: str
    departure_min: int
    battery_range: int

    @property
    def direction(self) -> str:
        return f"{self.origin}→{self.destination}"


@dataclass
class ChargeStop:
    station_id: str
    arrive_min: float
    wait_min: float
    charge_start_min: float
    charge_end_min: float


@dataclass
class BusTimeline:
    bus: Bus
    charge_stops: list[ChargeStop]
    depart_min: int
    arrive_min: float

    @property
    def total_wait(self) -> float:
        return sum(s.wait_min for s in self.charge_stops)

    @property
    def total_duration(self) -> float:
        return self.arrive_min - self.depart_min


# ---------------------------------------------------------------------------
# Scenario config
# ---------------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    id: str
    name: str
    description: str
    speed_kmh: int
    battery_range_km: int
    charge_time_min: int
    route: Route
    stations: list[Station]
    buses: list[Bus]
    weights: dict[str, float]

    @staticmethod
    def from_file(path: str | Path) -> "ScenarioConfig":
        data = json.loads(Path(path).read_text())
        segments = [Segment(**s) for s in data["route"]["segments"]]
        route = Route(nodes=data["route"]["nodes"], segments=segments)
        stations = [Station(**s) for s in data["stations"]]
        buses = [
            Bus(
                id=b["id"],
                operator=b["operator"],
                origin=b["origin"],
                destination=b["destination"],
                departure_min=_hhmm_to_min(b["departure"]),
                battery_range=data["battery_range_km"],
            )
            for b in data["buses"]
        ]
        return ScenarioConfig(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            speed_kmh=data["speed_kmh"],
            battery_range_km=data["battery_range_km"],
            charge_time_min=data["charge_time_min"],
            route=route,
            stations=stations,
            buses=buses,
            weights=data["weights"],
        )


# ---------------------------------------------------------------------------
# Rule registry  (add new rules here — nothing else changes)
# ---------------------------------------------------------------------------

# Rule: (bus, accumulated_wait_so_far, same_op_count_at_station) -> priority_score
# Higher score = served sooner
Rule = Callable[["Bus", float, int], float]


def rule_individual(bus: Bus, wait_so_far: float, same_op_count: int) -> float:
    """Prefer buses that have already waited longer."""
    return wait_so_far


def rule_operator(bus: Bus, wait_so_far: float, same_op_count: int) -> float:
    """Prefer buses whose operator has fewer buses in the queue (fairness)."""
    return 1.0 / (same_op_count + 1)


def rule_overall(bus: Bus, wait_so_far: float, same_op_count: int) -> float:
    """Prefer earlier-departing buses (FCFS baseline for throughput)."""
    return 1.0 / (bus.departure_min + 1)


RULE_REGISTRY: dict[str, Rule] = {
    "individual": rule_individual,
    "operator":   rule_operator,
    "overall":    rule_overall,
}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """
    Two-phase:
    1. Assign charging stations per bus (greedy: go as far as possible).
    2. Simulate with a min-heap; use weighted rules to break ties at congested stations.
    """

    def __init__(self, cfg: ScenarioConfig):
        self.cfg = cfg

    def _travel_min(self, dist: int) -> float:
        return dist / self.cfg.speed_kmh * 60

    # ------------------------------------------------------------------
    # Phase 1: station assignment (greedy range-aware)
    # ------------------------------------------------------------------

    def _assign_stations(self, bus: Bus) -> list[str]:
        cfg = self.cfg
        stops = cfg.route.ordered_stops(bus.origin, bus.destination)
        station_set = {s.id for s in cfg.stations}

        chosen: list[str] = []
        last_charged = stops[0]  # origin = full battery

        for i, node in enumerate(stops[1:], 1):
            if node not in station_set:
                continue  # skip endpoints that aren't stations

            dist_here = cfg.route.distance_along(last_charged, node)

            # What's the nearest chargeable stop after this one?
            remaining = stops[i + 1:]
            next_stops = [n for n in remaining if n in station_set]
            next_node = next_stops[0] if next_stops else stops[-1]
            dist_to_next = cfg.route.distance_along(node, next_node)

            must_charge = dist_here > cfg.battery_range_km
            wont_make_next = dist_here + dist_to_next > cfg.battery_range_km

            if must_charge or wont_make_next:
                chosen.append(node)
                last_charged = node

        return chosen

    # ------------------------------------------------------------------
    # Phase 2: discrete-event simulation
    # ------------------------------------------------------------------

    def run(self) -> list[BusTimeline]:
        cfg = self.cfg
        weights = cfg.weights

        bus_plan = {b.id: self._assign_stations(b) for b in cfg.buses}

        # charger_free[station_id][charger_index] = time charger is free
        charger_free: dict[str, list[float]] = {
            s.id: [0.0] * s.chargers for s in cfg.stations
        }

        @dataclass
        class BusState:
            bus: Bus
            stops: list[str]
            stop_idx: int = 0
            current_time: float = 0.0
            current_node: str = ""
            charge_stops: list[ChargeStop] = field(default_factory=list)
            done: bool = False

        states: dict[str, BusState] = {
            b.id: BusState(
                bus=b,
                stops=bus_plan[b.id],
                current_time=float(b.departure_min),
                current_node=b.origin,
            )
            for b in cfg.buses
        }

        # heap items: (arrive_time, tie_breaker, bus_id)
        heap: list[tuple[float, int, str]] = []
        _seq = [0]

        def push(arrive: float, bus_id: str):
            _seq[0] += 1
            heapq.heappush(heap, (arrive, _seq[0], bus_id))

        for b in cfg.buses:
            bs = states[b.id]
            if bs.stops:
                dist = cfg.route.distance_along(bs.current_node, bs.stops[0])
                push(bs.current_time + self._travel_min(dist), b.id)
            else:
                dist = cfg.route.distance_along(b.origin, b.destination)
                bs.current_time += self._travel_min(dist)
                bs.done = True

        while heap:
            arrive_time, _, bus_id = heapq.heappop(heap)
            bs = states[bus_id]
            if bs.done:
                continue

            station_id = bs.stops[bs.stop_idx]

            # Priority score (higher = served sooner)
            wait_so_far = sum(s.wait_min for s in bs.charge_stops)
            same_op = sum(
                1 for other in states.values()
                if not other.done
                and other.stop_idx < len(other.stops)
                and other.stops[other.stop_idx] == station_id
                and other.bus.operator == bs.bus.operator
            )
            score = sum(
                weights.get(k, 1.0) * RULE_REGISTRY[k](bs.bus, wait_so_far, same_op)
                for k in RULE_REGISTRY
            )

            # Pick the charger that frees up soonest
            chargers = charger_free[station_id]
            best = min(range(len(chargers)), key=lambda i: chargers[i])
            charger_avail = chargers[best]

            charge_start = max(arrive_time, charger_avail)
            charge_end = charge_start + cfg.charge_time_min
            wait = charge_start - arrive_time

            bs.charge_stops.append(ChargeStop(
                station_id=station_id,
                arrive_min=arrive_time,
                wait_min=wait,
                charge_start_min=charge_start,
                charge_end_min=charge_end,
            ))

            charger_free[station_id][best] = charge_end
            bs.current_time = charge_end
            bs.current_node = station_id
            bs.stop_idx += 1

            if bs.stop_idx < len(bs.stops):
                dist = cfg.route.distance_along(bs.current_node, bs.stops[bs.stop_idx])
                push(bs.current_time + self._travel_min(dist), bus_id)
            else:
                dist = cfg.route.distance_along(bs.current_node, bs.bus.destination)
                bs.current_time += self._travel_min(dist)
                bs.done = True

        return [
            BusTimeline(
                bus=s.bus,
                charge_stops=s.charge_stops,
                depart_min=s.bus.departure_min,
                arrive_min=s.current_time,
            )
            for s in states.values()
        ]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _hhmm_to_min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _min_to_hhmm(m: float) -> str:
    total = int(round(m))
    return f"{total // 60:02d}:{total % 60:02d}"


def format_timeline(t: BusTimeline) -> dict:
    return {
        "bus_id": t.bus.id,
        "operator": t.bus.operator,
        "direction": t.bus.direction,
        "depart": _min_to_hhmm(t.depart_min),
        "arrive": _min_to_hhmm(t.arrive_min),
        "total_wait_min": round(t.total_wait, 1),
        "total_duration_min": round(t.total_duration, 1),
        "charge_stops": [
            {
                "station": s.station_id,
                "arrive": _min_to_hhmm(s.arrive_min),
                "wait_min": round(s.wait_min, 1),
                "charge_start": _min_to_hhmm(s.charge_start_min),
                "charge_end": _min_to_hhmm(s.charge_end_min),
            }
            for s in t.charge_stops
        ],
    }
