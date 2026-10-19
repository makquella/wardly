"""
enemy_heroes.py - the enemy heroes of the live match, for counter items.

A player's GSI has no draft (that block is for spectators), but its `minimap`
block lists the units on the player's minimap — the enemy heroes the team can
see among them (`unitname` npc_dota_hero_*, `team` 2 Radiant / 3 Dire, `image`
minimap_enemyicon). Only that icon counts: from the strategy time on, GSI also
sends `minimap_plaincircle` heroes at (0, 0) for both teams' picks and heroes
not in the match at all, with an enemy team number; read as enemies, they
named the player's own allies and the player's hero. Every enemy hero seen once
is remembered for the match (MatchMemory resets it), so the list fills up as
the enemies show themselves. No minimap block (an older
GSI config, or a client that does not send it) → nothing is known and no
counter advice is given.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

TEAMS = {"radiant": 2, "dire": 3}
MAX_ENEMIES = 5
HERO_PREFIX = "npc_dota_hero_"
ENEMY_ICON = "minimap_enemyicon"
# World coordinates run about ±8200; anything far outside is a broken value.
MAX_COORDINATE = 12000


def _enemy_hero(unit: Any, own: int, normalize: Callable[[Any], str]) -> str:
    """The hero's name when `unit` is a visible enemy hero, else ""."""
    if not isinstance(unit, dict) or unit.get("image") != ENEMY_ICON:
        return ""
    raw = unit.get("unitname")
    team = unit.get("team")
    if not isinstance(raw, str) or not raw.lower().startswith(HERO_PREFIX):
        return ""
    if isinstance(team, bool) or team not in (2, 3) or team == own:
        return ""
    return normalize(raw) or ""


def visible_enemy_units(
    minimap: Any, team_name: Any, normalize: Callable[[Any], str]
) -> list[dict[str, Any]] | None:
    """[{hero, x, y}] of the enemy heroes on this tick's minimap, x/y in absolute
    replay units (centre MAP_CENTER) or None when the unit has no position;
    None without a minimap block or a known team."""
    from app.advice_context import MAP_CENTER

    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    units: list[dict[str, Any]] = []
    for unit in minimap.values():
        name = _enemy_hero(unit, own, normalize)
        if not name or any(u["hero"] == name for u in units):
            continue
        x, y = _coordinate(unit.get("xpos")), _coordinate(unit.get("ypos"))
        if x == 0 and y == 0:  # an icon not placed on the map yet: says nothing
            continue
        units.append(
            {
                "hero": name,
                "x": x + MAP_CENTER if x is not None and y is not None else None,
                "y": y + MAP_CENTER if x is not None and y is not None else None,
            }
        )
    return units


def _coordinate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and abs(number) <= MAX_COORDINATE else None


def visible_enemy_heroes(
    minimap: Any, team_name: Any, normalize: Callable[[Any], str]
) -> list[str] | None:
    """Enemy hero names on this tick's minimap; None without a minimap block
    or a known team."""
    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    names: list[str] = []
    for unit in minimap.values():
        name = _enemy_hero(unit, own, normalize)
        if not name or name in names:
            continue
        x, y = _coordinate(unit.get("xpos")), _coordinate(unit.get("ypos"))
        if x == 0 and y == 0:  # an icon not placed on the map yet: says nothing
            continue
        names.append(name)
    return names


class EnemyHeroes:
    """The enemy heroes seen so far in the match (first seen first, at most 5)."""

    def __init__(self) -> None:
        self._seen: list[str] = []

    def observe(self, names: Any) -> None:
        if not isinstance(names, list):
            return
        for name in names:
            if isinstance(name, str) and name not in self._seen and len(self._seen) < MAX_ENEMIES:
                self._seen.append(name)

    def heroes(self) -> list[str]:
        return list(self._seen)
