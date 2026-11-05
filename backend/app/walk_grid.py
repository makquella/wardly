"""
walk_grid.py - how far a walk is, around trees and cliffs: the walking distance
over data/live/walk_grid.json (scripts/build_walk_grid.py), the map cells where
ground units were seen on the player's own recordings.

GSI has no map geometry. A cell nobody stood in is not walkable: unknown, not
open. A walk that the grid cannot connect (an end too far from any known cell,
or no known way between them) has no length here, and the caller falls back to
its own estimate and says so. Distances are Dijkstra over the cells with
diagonal steps, from the cell of the start, so one call gives the distance to
every target; a diagonal-step path is a little longer than the walk a hero
takes (SMOOTH corrects for it, measured on straight open ground).
"""

from __future__ import annotations

import heapq
import json
import math
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR

# A start or a target this many cells from a known one snaps to it.
SNAP_CELLS = 3
# An 8-neighbour path over a line at a random angle is ~1.055 × the line.
SMOOTH = 1 / 1.055
NEIGHBOURS = [(di, dj, math.hypot(di, dj)) for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj]


@lru_cache(maxsize=1)
def grid() -> dict[str, Any] | None:
    """{origin, cell, cells, open: set of (i, j)} or None without the file."""
    try:
        data = json.loads((DATA_DIR / "live" / "walk_grid.json").read_text("utf-8"))
        origin, cell, cells = int(data["origin"]), int(data["cell"]), int(data["cells"])
        rows = data["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(rows, list) or len(rows) != cells or cell <= 0:
        return None
    walkable: set[tuple[int, int]] = set()
    for j, row in enumerate(rows):
        try:
            value = int(row, 16)
        except (TypeError, ValueError):
            return None
        i = 0
        while value:
            if value & 1:
                walkable.add((i, j))
            value >>= 1
            i += 1
    return {"origin": origin, "cell": cell, "cells": cells, "open": walkable}


def _cell(g: dict[str, Any], x: float, y: float) -> tuple[int, int]:
    return int((x - g["origin"]) // g["cell"]), int((y - g["origin"]) // g["cell"])


def _snap(g: dict[str, Any], x: float, y: float) -> tuple[int, int] | None:
    ci, cj = _cell(g, x, y)
    best = None
    for di in range(-SNAP_CELLS, SNAP_CELLS + 1):
        for dj in range(-SNAP_CELLS, SNAP_CELLS + 1):
            here = (ci + di, cj + dj)
            if here in g["open"]:
                d = math.hypot(di, dj)
                if best is None or d < best[0]:
                    best = (d, here)
    return best[1] if best else None


def distances(
    x: float, y: float, targets: list[tuple[float, float]], limit: float = 12000.0
) -> list[float | None]:
    """The walking distance (map units) from (x, y) to each target; None for a
    target the grid cannot reach (or with no grid). Search stops at `limit`."""
    g = grid()
    if g is None or not targets:
        return [None] * len(targets)
    start = _snap(g, x, y)
    goals = [_snap(g, tx, ty) for tx, ty in targets]
    if start is None:
        return [None] * len(targets)
    wanted = {goal for goal in goals if goal is not None}
    cell = g["cell"]
    walkable = g["open"]
    best: dict[tuple[int, int], float] = {start: 0.0}
    queue: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
    found: dict[tuple[int, int], float] = {}
    max_steps = limit / cell
    while queue and len(found) < len(wanted):
        d, here = heapq.heappop(queue)
        if d > best.get(here, math.inf) or d > max_steps:
            continue
        if here in wanted:
            found[here] = d
        i, j = here
        for di, dj, step in NEIGHBOURS:
            there = (i + di, j + dj)
            if there not in walkable:
                continue
            # No corner cutting: a diagonal needs both sides open.
            if di and dj and ((i + di, j) not in walkable or (i, j + dj) not in walkable):
                continue
            nd = d + step
            if nd < best.get(there, math.inf):
                best[there] = nd
                heapq.heappush(queue, (nd, there))
    out: list[float | None] = []
    for (tx, ty), goal in zip(targets, goals, strict=True):
        if goal is None or goal not in found:
            out.append(None)
            continue
        # The snapped ends: the straight bits from the real points to their cells.
        ends = math.dist((x, y), _centre(g, start)) + math.dist((tx, ty), _centre(g, goal))
        out.append(found[goal] * cell * SMOOTH + ends)
    return out


def _centre(g: dict[str, Any], c: tuple[int, int]) -> tuple[float, float]:
    return g["origin"] + (c[0] + 0.5) * g["cell"], g["origin"] + (c[1] + 0.5) * g["cell"]
