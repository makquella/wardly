"""
team_context.py - the allies and enemies GSI shows around the player's hero.

GSI's minimap block lists allied heroes every tick (shared vision) and enemy
heroes only while they are visible; it says nothing about the health, mana or
cooldowns of either. So "next to you" is a distance, never readiness,
and an enemy absent from the minimap is unknown, not gone.

One tick of an ally nearby is a passer-by as often as a team: TeamSupport
keeps who has stayed near for STEADY_SECONDS (by name, reset by a payload gap
or a missing minimap) and how many enemies are visible around, and
grouped_with_team() asks for a steady ally and no visible enemy majority. It
never claims the allies' HP, mana or cooldowns. Coordinates are the absolute
replay units of gsi_state._map_coordinate (centre MAP_CENTER).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Close enough to fight together (a little over a typical cast range).
NEARBY_RADIUS = 1200
# An ally near the hero this long (payloads about 0.5 s apart) is moving with
# it; shorter is a crossing.
STEADY_SECONDS = 2.0
# A pause between payloads longer than this forgets who was near (stale).
STALE_SECONDS = 3.0
# A fight is still around: an enemy hero visible this close (a blink or a
# gap-closer away), or this much HP (% of max) lost in the last 10 s.
CONTEST_RADIUS = 2000
CONTEST_HP_LOST = 15


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


class TeamSupport:
    """Which allies have stayed next to the hero, from consecutive minimap
    ticks (see the module doc)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._since: dict[str, float] = {}
        self._last_at: float | None = None

    def observe(self, extra: Mapping[str, Any], at: float | None) -> dict[str, Any]:
        units = extra.get("ally_units")
        stale = at is None or self._last_at is None or at - self._last_at > STALE_SECONDS
        self._last_at = at
        if at is None or not isinstance(units, list):
            self._since = {}
            return {"known": False}
        if stale:
            self._since = {}
        near = sorted(
            {str(unit["hero"]) for unit in nearby_allies(extra) if unit.get("hero") is not None}
        )
        self._since = {hero: self._since.get(hero, at) for hero in near}
        steady = [hero for hero in near if at - self._since[hero] >= STEADY_SECONDS]
        return {
            "known": True,
            "allies": near,
            "steady": steady,
            "enemies_near": len(visible_enemies_near(extra)),
        }


def grouped_with_team(extra: Mapping[str, Any]) -> bool:
    """With the team: an ally has stayed next to the hero (TeamSupport) and
    the visible enemies around do not outnumber the group. Without the
    tracker's note (a direct call) the allies of this tick decide."""
    support = extra.get("team_support")
    if not isinstance(support, Mapping):
        return bool(nearby_allies(extra))
    steady = support.get("steady")
    if not isinstance(steady, list) or not steady:
        return False
    enemies = support.get("enemies_near")
    return len(steady) + 1 >= (enemies if isinstance(enemies, int) else 0)


def steady_allies(extra: Mapping[str, Any]) -> list[str]:
    """The allies that stayed next to the hero (this tick's ones without the
    tracker's note)."""
    support = extra.get("team_support")
    if isinstance(support, Mapping):
        steady = support.get("steady")
        return [str(hero) for hero in steady] if isinstance(steady, list) else []
    return [str(unit.get("hero")) for unit in nearby_allies(extra)]


def contest_near(extra: Mapping[str, Any]) -> bool:
    """Something to fight right now: a visible enemy close by, or damage
    being taken. Without it «when to go in again» answers no question."""
    if visible_enemies_near(extra, CONTEST_RADIUS):
        return True
    lost = extra.get("hp_delta_10s")
    return (
        isinstance(lost, (int, float)) and not isinstance(lost, bool) and lost <= -CONTEST_HP_LOST
    )
