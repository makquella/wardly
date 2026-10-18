"""
fight_summary.py - «a fight at your T2: 3 allies, 2 enemies; TP ready», as a
fact, never a call.

Whether to teleport into a fight depends on the team's plan, its cooldowns and
the heroes, none of which a player's GSI shows (signal_capabilities: no team
readiness). What it does show: the allied heroes and the visible enemies on the
minimap (minimap_units.py, enemy_heroes.py), the towers standing, the kill score
and the player's own TP and abilities. A fight is MIN_ALLIES+ allies and
MIN_ENEMIES+ visible enemies within FIGHT_RADIUS of an enemy hero, with
BIG_FIGHT heroes there or a kill in the last KILL_WINDOW seconds (a quiet 2v2
lane is not a fight), FIGHT_FAR or more from the player, from FIGHT_FROM on.
The card (map_hints.RoleTips.fight) names where it is (the nearest tower within
TOWER_NEAR, else the zone and the map half), how many heroes are there, and the
player's TP and fight abilities (the hero plan's `fight`, else the ultimate);
the decision stays the player's.
"""

from __future__ import annotations

import math
from typing import Any

FIGHT_FROM = 10 * 60
FIGHT_RADIUS = 1600
FIGHT_FAR = 3500
MIN_ALLIES = 2
MIN_ENEMIES = 2
BIG_FIGHT = 5
KILL_WINDOW = 20
TOWER_NEAR = 2000


class FightWatch:
    """Per match (MatchMemory): the kill score over the last minute, to tell a
    fight from heroes standing near each other."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._scores: list[tuple[int, int]] = []

    def observe(self, clock: Any, radiant: Any, dire: Any) -> None:
        values = (clock, radiant, dire)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
            return
        total = radiant + dire
        if self._scores and clock < self._scores[-1][0]:
            self._scores.clear()  # the clock went back: a reconnect or a replay
        if not self._scores or self._scores[-1][1] != total:
            self._scores.append((clock, total))
        # Keep the last minute and the score just before it.
        old = [s for s in self._scores if clock - s[0] > 60]
        self._scores = old[-1:] + [s for s in self._scores if clock - s[0] <= 60]

    def kills_since(self, clock: int, window: int = KILL_WINDOW) -> int:
        """Heroes killed (both teams) in the last `window` seconds."""
        if not self._scores:
            return 0
        before = [total for at, total in self._scores if at <= clock - window]
        base = before[-1] if before else self._scores[0][1]
        return max(0, self._scores[-1][1] - base)


def _points(units: Any, skip: set[str] | None = None) -> list[tuple[str, float, float]]:
    skip = skip or set()
    return [
        (str(u["hero"]), float(u["x"]), float(u["y"]))
        for u in units or []
        if isinstance(u, dict)
        and isinstance(u.get("x"), (int, float))
        and isinstance(u.get("y"), (int, float))
        and u.get("hero") not in skip
    ]


def find_fight(
    allies: Any,
    enemies: Any,
    x: Any,
    y: Any,
    *,
    clock: int | None,
    recent_kills: int,
    known_enemies: list[str] | None = None,
) -> dict[str, Any] | None:
    """{allies, enemies, x, y} of the biggest fight on the map that the player
    is not in; None otherwise. `known_enemies`: heroes seen as enemies this
    match, never counted as allies."""
    if clock is None or clock < FIGHT_FROM:
        return None
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    ally_points = _points(allies, set(known_enemies or []))
    enemy_points = _points(enemies)
    best: tuple[list[tuple[str, float, float]], list[tuple[str, float, float]]] | None = None
    for _, ex, ey in enemy_points:
        near_allies = [p for p in ally_points if math.hypot(p[1] - ex, p[2] - ey) <= FIGHT_RADIUS]
        near_enemies = [p for p in enemy_points if math.hypot(p[1] - ex, p[2] - ey) <= FIGHT_RADIUS]
        if len(near_allies) < MIN_ALLIES or len(near_enemies) < MIN_ENEMIES:
            continue
        if best is None or len(near_allies) + len(near_enemies) > len(best[0]) + len(best[1]):
            best = (near_allies, near_enemies)
    if best is None:
        return None
    if len(best[0]) + len(best[1]) < BIG_FIGHT and recent_kills <= 0:
        return None
    heroes = best[0] + best[1]
    cx = sum(p[1] for p in heroes) / len(heroes)
    cy = sum(p[2] for p in heroes) / len(heroes)
    if math.hypot(cx - x, cy - y) < FIGHT_FAR:
        return None
    return {
        "allies": [p[0] for p in best[0]],
        "enemies": [p[0] for p in best[1]],
        "x": cx,
        "y": cy,
        "kills": recent_kills,
    }


def nearest_tower(fight: dict[str, Any], towers: Any) -> dict[str, Any] | None:
    """The tower standing nearest the fight, within TOWER_NEAR."""
    best: tuple[float, dict[str, Any]] | None = None
    for tower in towers or []:
        if not isinstance(tower, dict):
            continue
        tx, ty = tower.get("x"), tower.get("y")
        if not isinstance(tx, (int, float)) or not isinstance(ty, (int, float)):
            continue
        distance = math.hypot(tx - fight["x"], ty - fight["y"])
        if distance <= TOWER_NEAR and (best is None or distance < best[0]):
            best = (distance, tower)
    return best[1] if best else None


def ability_states(
    abilities: Any, names: list[str], labels: dict[str, str]
) -> list[dict[str, Any]]:
    """[{name, ready, cooldown}] for the learned `names` among the normalized
    abilities (gsi_state.normalize_abilities): ready when off cooldown and
    castable; `cooldown` its seconds (0 with no mana or not castable)."""
    found: list[dict[str, Any]] = []
    by_raw = {
        str(a.get("raw_name")): a
        for a in abilities or []
        if isinstance(a, dict) and a.get("raw_name")
    }
    for raw in names:
        ability = by_raw.get(raw)
        if not ability or not isinstance(ability.get("level"), int) or ability["level"] <= 0:
            continue
        cooldown = ability.get("cooldown")
        cooldown = int(cooldown) if isinstance(cooldown, (int, float)) and cooldown > 0 else 0
        found.append(
            {
                "name": labels.get(raw) or raw,
                "ready": cooldown == 0 and ability.get("can_cast") is True,
                "cooldown": cooldown,
            }
        )
    return found
