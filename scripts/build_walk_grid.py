"""Build data/live/walk_grid.json, where a unit can walk (backend/app/walk_grid.py),
from the player's own match recordings.

GSI has no map geometry: no trees, cliffs or paths. The minimap does show where
units are, once a game second each, so a cell of the map is walkable when a
ground unit was seen in it:

- heroes (allies, enemies in vision, own illusions): the straight step between
  two consecutive seconds of the same hero, when it moved at most STEP_MAX
  (walking; a blink or a teleport is skipped). A second of walking is a short
  step, so the straight line stays on the path it took, near enough for a
  CELL-sized grid;
- creeps (lane creeps, neutrals, summons, the ground courier): the cell they
  stand in. Flying couriers fly over trees and are left out.

The recorded player's own hero is left out by default (`--with-player` keeps
it), so that the player's own walks in the same recordings can check the
travel estimate (scripts/farm_outcomes.py) without having drawn the grid.
A cell nobody stood in is not walkable: the map reads «unknown», never «open».

    python scripts/build_walk_grid.py REC.jsonl.gz [REC2 ...] [--with-player] [--svg grid.svg] [--write]

Recordings stay on the player's computer; only the grid of cells is written.
Re-run on all recordings when more arrive.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "live" / "walk_grid.json"
MAP_CENTER = 16384
# The playable map: replay units 8192..24576 (map_analysis.py, OpenDota's map).
ORIGIN = 8192
SIZE = 16384
CELL = 128
CELLS = SIZE // CELL
# A hero walks at most ~550 units a second; more is a blink or a teleport.
STEP_MAX = 650
HERO_ICONS = {
    "minimap_herocircle",
    "minimap_herocircle_self",
    "minimap_enemyicon",
    "minimap_heroimage",
    "minimap_heroinvis",
}
GROUND_ICONS = {
    "minimap_creep",
    "minimap_siege",
    "minimap_controlledcreep",
    "minimap_courier",
}


def cell_of(x: float, y: float) -> tuple[int, int] | None:
    i, j = int((x - ORIGIN) // CELL), int((y - ORIGIN) // CELL)
    return (i, j) if 0 <= i < CELLS and 0 <= j < CELLS else None


def _position(unit: dict[str, Any]) -> tuple[float, float] | None:
    x, y = unit.get("xpos"), unit.get("ypos")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or (x, y) == (0, 0):
        return None
    return float(x) + MAP_CENTER, float(y) + MAP_CENTER


def _segment(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[int, int]]:
    steps = max(1, math.ceil(math.dist(a, b) / (CELL / 2)))
    cells = []
    for k in range(steps + 1):
        t = k / steps
        found = cell_of(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        if found is not None:
            cells.append(found)
    return cells


def walked(path: Path, with_player: bool) -> tuple[set[tuple[int, int]], dict[str, int]]:
    """The cells units stood in, and counts of what drew them."""
    opener = gzip.open if path.suffix == ".gz" else open
    cells: set[tuple[int, int]] = set()
    counts = {"seconds": 0, "hero_steps": 0, "skipped_jumps": 0, "ground_points": 0}
    last: dict[str, tuple[float, float]] = {}
    player = None
    prev_clock = None
    with opener(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("k") == "meta":
                player = record.get("hero")
            if record.get("k") != "gsi":
                continue
            payload = record["p"]
            clock = (payload.get("map") or {}).get("clock_time")
            if not isinstance(clock, int) or clock == prev_clock:
                continue
            if prev_clock is not None and clock != prev_clock + 1:
                last.clear()  # a gap: no step across it
            prev_clock = clock
            counts["seconds"] += 1
            player = player or (payload.get("hero") or {}).get("name")
            seen: dict[str, tuple[float, float]] = {}
            for unit in (payload.get("minimap") or {}).values():
                if not isinstance(unit, dict):
                    continue
                image, name = unit.get("image"), unit.get("unitname")
                position = _position(unit)
                if position is None:
                    continue
                if image in HERO_ICONS and isinstance(name, str) and name:
                    if not with_player and (image == "minimap_herocircle_self" or name == player):
                        continue
                    seen[f"{image}:{name}:{unit.get('team')}"] = position
                elif image in GROUND_ICONS:
                    found = cell_of(*position)
                    if found is not None:
                        cells.add(found)
                        counts["ground_points"] += 1
            for key, position in seen.items():
                before = last.get(key)
                if before is None:
                    found = cell_of(*position)
                    if found is not None:
                        cells.add(found)
                elif math.dist(before, position) <= STEP_MAX:
                    cells.update(_segment(before, position))
                    counts["hero_steps"] += 1
                else:
                    counts["skipped_jumps"] += 1
            last = seen
    return cells, counts


def rows(cells: set[tuple[int, int]]) -> list[str]:
    """One hex string per row j (y), bit i (x) of the row = cell (i, j)."""
    out = []
    for j in range(CELLS):
        value = 0
        for i in range(CELLS):
            if (i, j) in cells:
                value |= 1 << i
        out.append(f"{value:0{CELLS // 4}x}")
    return out


def svg(cells: set[tuple[int, int]]) -> str:
    rects = "".join(
        f'<rect x="{i}" y="{CELLS - 1 - j}" width="1" height="1"/>' for i, j in sorted(cells)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CELLS} {CELLS}" width="768" '
        f'height="768" style="background:#222"><g fill="#8fd18f">{rects}</g></svg>'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--with-player", action="store_true", help="also the recorded hero")
    parser.add_argument("--svg", type=Path, help="draw the walkable cells")
    parser.add_argument("--write", action="store_true", help=f"write {OUT.relative_to(ROOT)}")
    args = parser.parse_args()
    cells: set[tuple[int, int]] = set()
    for path in args.recordings:
        found, counts = walked(path, args.with_player)
        cells |= found
        print(f"{path.name}: {len(found)} cells, {counts}")
    print(f"{len(cells)} walkable cells of {CELLS * CELLS} ({len(cells) / CELLS**2:.0%})")
    if args.svg:
        args.svg.write_text(svg(cells), encoding="utf-8")
    if args.write:
        data = {
            "source": "cells where ground units were seen on the player's own match recordings "
            "(scripts/build_walk_grid.py); a cell nobody stood in is unknown, not open",
            "built": datetime.now(UTC).date().isoformat(),
            "recordings": len(args.recordings),
            "with_player": args.with_player,
            "origin": ORIGIN,
            "cell": CELL,
            "cells": CELLS,
            "rows": rows(cells),
        }
        OUT.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
