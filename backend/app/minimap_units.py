"""
minimap_units.py - the player's allies and the towers on the live minimap.

A player's GSI `minimap` block (enemy_heroes.py reads the enemies from it) also
lists the allied heroes (`minimap_herocircle` of the player's team; the player
is `minimap_herocircle_self`) and the towers still standing
(`npc_dota_goodguys_tower2_bot`, `team` 2 Radiant / 3 Dire). Positions are
returned in absolute replay units (centre MAP_CENTER), as enemy_heroes does.
An icon at (0, 0) is not placed on the map yet and says nothing. Used by
fight_summary.py.

The same block also lists creeps (`minimap_creep`, siege creeps
`minimap_siege`; checked on real recordings): the player's own lane creeps
always, the enemy's lane creeps and the neutral creeps (`team` 4,
`npc_dota_neutral_*`) only while the team sees them; and every own unit
carries its `visionrange`. Entry keys (`o123`) are NOT a unit's identity: one
key names another unit a moment later (4103 of 18 000 consecutive neutral
pairs on one recording), so a unit is followed by its name and position.
Read by farm_map.py; a creep in the fog is not there, never assumed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from app.enemy_heroes import HERO_PREFIX, MAX_COORDINATE, TEAMS

ALLY_ICON = "minimap_herocircle"
TOWER = re.compile(r"^npc_dota_(goodguys|badguys)_tower([1-4])(?:_(top|mid|bot))?$")
TOWER_TEAMS = {"goodguys": "radiant", "badguys": "dire"}
CREEP_ICONS = {"minimap_creep", "minimap_siege"}
NEUTRAL_TEAM = 4
NEUTRAL_PREFIX = "npc_dota_neutral_"
LANE_CREEP = re.compile(r"^npc_dota_(?:creep_)?(goodguys|badguys)_")


def _position(unit: dict[str, Any]) -> tuple[float, float] | None:
    from app.advice_context import MAP_CENTER

    values: list[float] = []
    for value in (unit.get("xpos"), unit.get("ypos")):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or abs(value) > MAX_COORDINATE:
            return None
        values.append(float(value))
    x, y = values
    if x == 0 and y == 0:
        return None
    return x + MAP_CENTER, y + MAP_CENTER


def visible_ally_units(
    minimap: Any, team_name: Any, normalize: Callable[[Any], str]
) -> list[dict[str, Any]] | None:
    """[{hero, x, y}] of the allied heroes on the minimap (not the player);
    None without a minimap block or a known team."""
    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    units: list[dict[str, Any]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or unit.get("image") != ALLY_ICON:
            continue
        raw = unit.get("unitname")
        if not isinstance(raw, str) or not raw.lower().startswith(HERO_PREFIX):
            continue
        if unit.get("team") != own:
            continue
        name = normalize(raw) or ""
        position = _position(unit)
        if not name or position is None or any(u["hero"] == name for u in units):
            continue
        units.append({"hero": name, "x": position[0], "y": position[1]})
    return units


def towers(minimap: Any) -> list[dict[str, Any]] | None:
    """[{team, tier, lane, x, y}] of the towers on the minimap (lane None for
    the tier-4 ones); None without a minimap block."""
    if not isinstance(minimap, dict):
        return None
    found: list[dict[str, Any]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or not isinstance(unit.get("unitname"), str):
            continue
        match = TOWER.match(unit["unitname"])
        position = _position(unit)
        if match is None or position is None:
            continue
        found.append(
            {
                "team": TOWER_TEAMS[match.group(1)],
                "tier": int(match.group(2)),
                "lane": match.group(3),
                "x": position[0],
                "y": position[1],
            }
        )
    return found


def _creep_kind(name: str) -> str | None:
    for kind in ("siege", "ranged", "flag", "melee"):
        if kind in name:
            return kind
    return None


def lane_creeps(minimap: Any, team_name: Any) -> list[dict[str, Any]] | None:
    """[{team: own|enemy, kind: melee|ranged|siege|flag, x, y}] of the lane
    creeps on the minimap; None without a minimap block or a known team."""
    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    found: list[dict[str, Any]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or unit.get("image") not in CREEP_ICONS:
            continue
        name, team = unit.get("unitname"), unit.get("team")
        if not isinstance(name, str) or team not in (2, 3) or not LANE_CREEP.match(name):
            continue
        kind, position = _creep_kind(name), _position(unit)
        if kind is None or position is None:
            continue
        side = "own" if team == own else "enemy"
        found.append({"team": side, "kind": kind, "x": position[0], "y": position[1]})
    return found


def neutral_units(minimap: Any) -> list[dict[str, Any]] | None:
    """[{unit, x, y}] of the neutral creeps the team sees; None without a
    minimap block."""
    if not isinstance(minimap, dict):
        return None
    found: list[dict[str, Any]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or unit.get("team") != NEUTRAL_TEAM:
            continue
        name = unit.get("unitname")
        if not isinstance(name, str) or not name.startswith(NEUTRAL_PREFIX):
            continue
        position = _position(unit)
        if position is not None:
            found.append({"unit": name, "x": position[0], "y": position[1]})
    return found


def vision_sources(minimap: Any, team_name: Any) -> list[tuple[float, float, float]] | None:
    """(x, y, vision range) of the player's team's units that see; None without
    a minimap block or a known team. Trees and high ground are not in it."""
    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    found: list[tuple[float, float, float]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or unit.get("team") != own:
            continue
        radius = unit.get("visionrange")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or radius <= 0:
            continue
        position = _position(unit)
        if position is not None:
            found.append((position[0], position[1], float(radius)))
    return found
