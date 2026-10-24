"""
team_context.py - the allies and enemies GSI shows around the player's hero.

GSI's minimap block lists allied heroes every tick (shared vision) and enemy
heroes only while they are visible; it says nothing about the health, mana or
cooldowns of either. So this reads only positions of the current tick:
"next to you" is a distance, never readiness, and an enemy absent from the
minimap is unknown, not gone. Coordinates are the absolute replay units of
gsi_state._map_coordinate (centre MAP_CENTER).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Close enough to fight together (a little over a typical cast range).
NEARBY_RADIUS = 1200


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _units_near(extra: Mapping[str, Any], key: str, radius: float) -> list[dict[str, Any]]:
    x, y = _number(extra.get("xpos")), _number(extra.get("ypos"))
    units = extra.get(key)
    if x is None or y is None or not isinstance(units, list):
        return []
    near = []
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        ux, uy = _number(unit.get("x")), _number(unit.get("y"))
        if ux is None or uy is None:
            continue
        distance = ((ux - x) ** 2 + (uy - y) ** 2) ** 0.5
        if distance <= radius:
            near.append({"hero": unit.get("hero"), "distance": round(distance)})
    return sorted(near, key=lambda unit: unit["distance"])


def nearby_allies(extra: Mapping[str, Any], radius: float = NEARBY_RADIUS) -> list[dict[str, Any]]:
    """Allied heroes on this tick's minimap within `radius` of the hero."""
    return _units_near(extra, "ally_units", radius)


def visible_enemies_near(
    extra: Mapping[str, Any], radius: float = NEARBY_RADIUS
) -> list[dict[str, Any]]:
    """Enemy heroes visible on this tick's minimap within `radius`."""
    return _units_near(extra, "enemy_units", radius)
