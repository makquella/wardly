"""Build data/live/farm_map.json, the neutral camps the live farm tip knows
(backend/app/farm_map.py), from the player's own match recordings.

GSI has no camp list. Its minimap shows the neutral creeps the team sees
(`team` 4, `npc_dota_neutral_*`). Entry keys are no unit identity (one key
names another unit a moment later), so a unit is followed by its name and
position, one sample per game second, and a camp is found where neutrals were
seen:

- spawns: a group of 2-6 neutrals appearing at clock mm:00..mm:01 within
  SPAWN_RADIUS of each other, with no unit of the same name within
  SAME_UNIT the second before (camps respawn on the minute);
- idle groups: neutrals that stood still (same name within IDLE_MOVE) for
  IDLE_SECONDS or more with no hero within IDLE_HERO_FREE, i.e. sitting in
  their camp; sampled at most once a minute per spot.

Both are clustered into spots (SPOT_RADIUS), spots closer than MERGE_RADIUS
are merged (the busier one keeps its place), and a spot needs
MIN_OBSERVATIONS distinct (recording, minute) observations. Each observation is the group of
units seen together, valued with Valve's unit definitions
(dota/scripts/npc/npc_units.txt: bounty min/max, health, IsAncient); a camp is
random within its kind, and an observation often shows only part of the
camp (the rest out of vision), so the spot keeps the upper quartile of its
observations' gold and health (a stacked camp is the top of that range).
No tier is guessed. A recording mostly shows the player's own team's jungle:
the coverage report says how many spots each side has, and an SVG (--svg)
shows them over the map for a visual check.

    python scripts/build_farm_map.py REC.jsonl.gz [REC2 ...] [--svg spots.svg] [--write]

Recordings stay on the player's computer; only the derived camp positions and
Valve's numbers are written. Re-run on all recordings when more arrive.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "live" / "farm_map.json"
NPC_UNITS = (
    "https://raw.githubusercontent.com/dotabuff/d2vpkr/master/dota/scripts/npc/npc_units.txt"
)
MAP_CENTER = 16384
NEUTRAL_PREFIX = "npc_dota_neutral_"
SPAWN_RADIUS = 400
SPAWN_GROUP = (2, 6)
IDLE_MOVE = 60
SAME_UNIT = 250
IDLE_SECONDS = 3.0
IDLE_HERO_FREE = 1200
GROUP_RADIUS = 450
SPOT_RADIUS = 450
MIN_OBSERVATIONS = 3
# Two spots closer than this are one camp seen from two sides: merged.
MERGE_RADIUS = 900
RIVER_BAND = 1400
# Lane creeps the live tip values when no gold was measured yet.
LANE_UNITS = (
    "npc_dota_creep_goodguys_melee",
    "npc_dota_creep_goodguys_ranged",
    "npc_dota_creep_goodguys_flagbearer",
    "npc_dota_goodguys_siege",
)


def parse_kv(text: str) -> dict[str, Any]:
    """Valve KeyValues text to nested dicts (comments and #base lines dropped)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', re.sub(r"//[^\n]*", "", text))
    stack: list[dict[str, Any]] = [{}]
    key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict[str, Any] = {}
            stack[-1][key or ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted
        else:
            stack[-1][key] = quoted
            key = None
    return stack[0]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def valve_units(text: str) -> dict[str, dict[str, Any]]:
    """{unit: {bounty: [min, max], hp, ancient}} for neutral and lane creeps."""
    units = parse_kv(text).get("DOTAUnits", {})
    found: dict[str, dict[str, Any]] = {}
    for name, block in units.items():
        if not isinstance(block, dict):
            continue
        if not (name.startswith(NEUTRAL_PREFIX) or name in LANE_UNITS):
            continue
        low, high = (
            _number(block.get("BountyGoldMin")),
            _number(block.get("BountyGoldMax")),
        )
        hp = _number(block.get("StatusHealth"))
        if low is None or high is None or hp is None:
            continue
        found[name] = {
            "bounty": [int(low), int(high)],
            "hp": int(hp),
            "ancient": block.get("IsAncient") == "1",
        }
    return found


def _records(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("k") == "gsi":
                yield record


def _neutrals(payload: dict[str, Any]) -> list[tuple[str, float, float]]:
    found = []
    for unit in (payload.get("minimap") or {}).values():
        if not isinstance(unit, dict) or unit.get("team") != 4:
            continue
        name, x, y = unit.get("unitname"), unit.get("xpos"), unit.get("ypos")
        if not isinstance(name, str) or not name.startswith(NEUTRAL_PREFIX):
            continue
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or (x, y) == (0, 0):
            continue
        found.append((name, float(x), float(y)))
    return found


def _heroes(payload: dict[str, Any]) -> list[tuple[float, float]]:
    found = []
    for unit in (payload.get("minimap") or {}).values():
        if not isinstance(unit, dict) or not str(unit.get("unitname") or "").startswith(
            "npc_dota_hero_"
        ):
            continue
        x, y = unit.get("xpos"), unit.get("ypos")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and (x, y) != (0, 0):
            found.append((float(x), float(y)))
    return found


def _groups(
    points: list[tuple[str, float, float]], radius: float
) -> list[list[tuple[str, float, float]]]:
    groups: list[list[tuple[str, float, float]]] = []
    for point in points:
        for group in groups:
            if any(math.hypot(point[1] - q[1], point[2] - q[2]) < radius for q in group):
                group.append(point)
                break
        else:
            groups.append([point])
    return groups


def observations(path: Path) -> list[dict[str, Any]]:
    """Spawn and idle groups of one recording: {kind, x, y, minute, units}."""
    found: list[dict[str, Any]] = []
    previous: list[tuple[str, float, float]] = []
    # (name, x, y, standing since) of the neutrals of the last sample.
    still: list[tuple[str, float, float, float]] = []
    idle_minutes: set[tuple[int, int, int]] = set()
    last_clock: int | None = None
    match = path.name
    for record in _records(path):
        payload = record["p"]
        clock = (payload.get("map") or {}).get("clock_time")
        if not isinstance(clock, int) or clock == last_clock:
            continue  # one sample per game second
        # A unit is new only against the second just before (a gap in the
        # recording says nothing about what spawned).
        contiguous = last_clock == clock - 1
        last_clock = clock
        wall = float(record.get("w") or 0)
        current = _neutrals(payload)
        if clock >= 60:
            minute = clock // 60
            if clock % 60 <= 1 and contiguous:
                new = [
                    u
                    for u in current
                    if not any(
                        p[0] == u[0] and math.hypot(p[1] - u[1], p[2] - u[2]) <= SAME_UNIT
                        for p in previous
                    )
                ]
                for group in _groups(new, SPAWN_RADIUS):
                    if not SPAWN_GROUP[0] <= len(group) <= SPAWN_GROUP[1]:
                        continue
                    cx = sum(u[1] for u in group) / len(group)
                    cy = sum(u[2] for u in group) / len(group)
                    found.append(
                        {
                            "kind": "spawn",
                            "x": cx,
                            "y": cy,
                            "minute": (match, minute),
                            "units": [u[0] for u in group],
                        }
                    )
            heroes = _heroes(payload)
            idle = []
            next_still = []
            for unit in current:
                before = next(
                    (
                        s
                        for s in still
                        if s[0] == unit[0]
                        and math.hypot(s[1] - unit[1], s[2] - unit[2]) < IDLE_MOVE
                    ),
                    None,
                )
                since = before[3] if before else wall
                next_still.append((unit[0], unit[1], unit[2], since))
                hero_near = any(
                    math.hypot(hx - unit[1], hy - unit[2]) < IDLE_HERO_FREE for hx, hy in heroes
                )
                if before and not hero_near and wall - since >= IDLE_SECONDS:
                    idle.append(unit)
            still = next_still
            for group in _groups(idle, GROUP_RADIUS):
                cx = sum(u[1] for u in group) / len(group)
                cy = sum(u[2] for u in group) / len(group)
                cell = (round(cx / SPOT_RADIUS), round(cy / SPOT_RADIUS), minute)
                if cell in idle_minutes:
                    continue
                idle_minutes.add(cell)
                found.append(
                    {
                        "kind": "idle",
                        "x": cx,
                        "y": cy,
                        "minute": (match, minute),
                        "units": [u[0] for u in group],
                    }
                )
        previous = current
    return found


def _upper_quartile(values: list[float]) -> float:
    if len(values) < 4:
        return max(values)
    return statistics.quantiles(values, n=4)[2]


def spots(found: list[dict[str, Any]], units: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for obs in found:
        for spot in clusters:
            if math.hypot(spot["x"] - obs["x"], spot["y"] - obs["y"]) < SPOT_RADIUS:
                spot["obs"].append(obs)
                n = len(spot["obs"])
                spot["x"] += (obs["x"] - spot["x"]) / n
                spot["y"] += (obs["y"] - spot["y"]) / n
                break
        else:
            clusters.append({"x": obs["x"], "y": obs["y"], "obs": [obs]})
    clusters.sort(key=lambda spot: -len(spot["obs"]))
    merged: list[dict[str, Any]] = []
    for spot in clusters:
        host = next(
            (
                m
                for m in merged
                if math.hypot(m["x"] - spot["x"], m["y"] - spot["y"]) < MERGE_RADIUS
            ),
            None,
        )
        if host is None:
            merged.append(spot)
        else:
            host["obs"].extend(spot["obs"])
    camps = []
    for spot in merged:
        minutes = {o["minute"] for o in spot["obs"]}
        if len(minutes) < MIN_OBSERVATIONS:
            continue
        golds, hps, ancient = [], [], 0
        for obs in spot["obs"]:
            known = [units[u] for u in obs["units"] if u in units]
            if not known:
                continue
            golds.append(sum(sum(u["bounty"]) / 2 for u in known))
            hps.append(sum(u["hp"] for u in known))
            ancient += any(u["ancient"] for u in known)
        if not golds:
            continue
        x, y = spot["x"] + MAP_CENTER, spot["y"] + MAP_CENTER
        diagonal = spot["x"] + spot["y"]
        side = "river" if abs(diagonal) <= RIVER_BAND else ("radiant" if diagonal < 0 else "dire")
        camps.append(
            {
                "x": round(x),
                "y": round(y),
                "side": side,
                "ancient": ancient * 2 > len(golds),
                "gold": round(_upper_quartile(golds)),
                "hp": round(_upper_quartile(hps)),
                "spawns_seen": sum(1 for o in spot["obs"] if o["kind"] == "spawn"),
                "idle_seen": sum(1 for o in spot["obs"] if o["kind"] == "idle"),
                "minutes": len(minutes),
                "recordings": len({m[0] for m in minutes}),
            }
        )
    camps.sort(key=lambda c: (c["side"], c["x"], c["y"]))
    for index, camp in enumerate(camps, 1):
        camp["id"] = f"c{index:02d}"
    return camps


def svg(camps: list[dict[str, Any]]) -> str:
    size, low, high = 600, 7000, 25800

    def px(v: float) -> float:
        return (v - low) / (high - low) * size

    dots = "".join(
        f'<circle cx="{px(c["x"]):.0f}" cy="{size - px(c["y"]):.0f}" r="7" fill="{"#c33" if c["ancient"] else "#36c"}"/>'
        f'<text x="{px(c["x"]) + 9:.0f}" y="{size - px(c["y"]) + 4:.0f}" font-size="11">{c["id"]} {c["gold"]}g</text>'
        for c in camps
    )
    river = f'<line x1="0" y1="0" x2="{size}" y2="{size}" stroke="#9cf" stroke-width="18" opacity="0.4"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" style="background:#efe">{river}{dots}</svg>'


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument(
        "--npc-units", type=Path, help="a saved npc_units.txt instead of fetching it"
    )
    parser.add_argument("--svg", type=Path, help="write the spots over the map as SVG")
    parser.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(ROOT)}")
    args = parser.parse_args()
    if args.npc_units:
        text = args.npc_units.read_text("utf-8")
        source = f"a saved copy of dotabuff/d2vpkr master dota/scripts/npc/npc_units.txt ({args.npc_units.name})"
    else:
        with urllib.request.urlopen(NPC_UNITS, timeout=60) as response:
            text = response.read().decode("utf-8")
        source = "github.com/dotabuff/d2vpkr master dota/scripts/npc/npc_units.txt"
    units = valve_units(text)
    found: list[dict[str, Any]] = []
    for path in args.recordings:
        found.extend(observations(path))
    camps = spots(found, units)
    by_side: dict[str, int] = defaultdict(int)
    for camp in camps:
        by_side[camp["side"]] += 1
    print(
        f"{len(found)} observations in {len(args.recordings)} recordings -> {len(camps)} camps: "
        + ", ".join(f"{side} {count}" for side, count in sorted(by_side.items())),
        file=sys.stderr,
    )
    for camp in camps:
        print(
            f"  {camp['id']} {camp['side']:7} ({camp['x']}, {camp['y']}) gold {camp['gold']} hp {camp['hp']}"
            f"{' ancient' if camp['ancient'] else ''}  spawns {camp['spawns_seen']} idle {camp['idle_seen']}"
            f" minutes {camp['minutes']} recordings {camp['recordings']}",
            file=sys.stderr,
        )
    if args.svg:
        args.svg.write_text(svg(camps), encoding="utf-8")
    data = {
        "source": {
            "camps": "neutral spawns and idle groups seen on the player's own match recordings "
            "(scripts/build_farm_map.py); a camp missing here is unknown, not absent",
            "units": f"Valve unit definitions, {source}, read {datetime.now(UTC).date().isoformat()}",
        },
        "built": datetime.now(UTC).date().isoformat(),
        "recordings": len(args.recordings),
        "camps": camps,
        "units": dict(sorted(units.items())),
    }
    if args.write:
        OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}", file=sys.stderr)
    else:
        print(json.dumps({"camps": camps}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
