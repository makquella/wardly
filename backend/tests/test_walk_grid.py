"""Walking distance over the walk grid (walk_grid.py): around a wall it is
longer than the straight line, nothing is assumed where no unit stood, and the
grid in data/live loads."""

from __future__ import annotations

import math

import pytest

from app import walk_grid

ORIGIN, CELL, CELLS = 0, 100, 20


def _grid(open_cells: set[tuple[int, int]]) -> dict:
    return {"origin": ORIGIN, "cell": CELL, "cells": CELLS, "open": open_cells}


def _at(i: int, j: int) -> tuple[float, float]:
    return ORIGIN + (i + 0.5) * CELL, ORIGIN + (j + 0.5) * CELL


@pytest.fixture
def walled(monkeypatch):
    """An open 20×20 field with a wall at column 10 and a gap at its top."""
    cells = {(i, j) for i in range(CELLS) for j in range(CELLS) if i != 10 or j == 19}
    monkeypatch.setattr(walk_grid, "grid", lambda: _grid(cells))


def test_open_ground_is_close_to_the_straight_line(monkeypatch):
    monkeypatch.setattr(
        walk_grid, "grid", lambda: _grid({(i, j) for i in range(CELLS) for j in range(CELLS)})
    )
    start, goal = _at(2, 3), _at(15, 9)
    (walk,) = walk_grid.distances(*start, [goal])
    assert walk is not None and 1.0 <= walk / math.dist(start, goal) <= 1.06


def test_a_wall_makes_the_walk_go_around_it(walled):
    start, goal = _at(5, 2), _at(15, 2)
    (walk,) = walk_grid.distances(*start, [goal])
    straight = math.dist(start, goal)
    # Up to the gap at the top and back down: far longer than the line.
    assert walk is not None and walk > 2.5 * straight


def test_no_walk_is_assumed_where_no_unit_stood(monkeypatch):
    cells = {(i, j) for i in range(CELLS) for j in range(CELLS) if i != 10}
    monkeypatch.setattr(walk_grid, "grid", lambda: _grid(cells))
    walks = walk_grid.distances(*_at(5, 2), [_at(15, 2), _at(6, 2), (90_000.0, 90_000.0)])
    assert walks[0] is None and walks[1] is not None and walks[2] is None
    monkeypatch.setattr(walk_grid, "grid", lambda: None)
    assert walk_grid.distances(*_at(5, 2), [_at(6, 2)]) == [None]


def test_a_diagonal_never_cuts_a_corner(monkeypatch):
    # Two open cells touching only at a corner: no way between them.
    monkeypatch.setattr(walk_grid, "grid", lambda: _grid({(0, 0), (1, 1)}))
    monkeypatch.setattr(walk_grid, "SNAP_CELLS", 0)
    assert walk_grid.distances(*_at(0, 0), [_at(1, 1)]) == [None]


def test_the_shipped_grid_loads():
    walk_grid.grid.cache_clear()
    g = walk_grid.grid()
    assert g is not None and g["cells"] * g["cell"] == 16384 and len(g["open"]) > 1000
