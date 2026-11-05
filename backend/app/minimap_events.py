"""
minimap_events.py - what happens at the player's buildings and lanes, as the
live minimap shows it: «your T2 bottom is attacked: Anti-Mage» and «Nature's
Prophet's summons in the bottom lane: 9, no enemy hero seen near them».

Read on a real recording (Night Stalker 9073917299, Radiant, 35 min):

- `minimap_ping_baseattacked`: the game's «building under attack» ping, no
  team or unit, at the building's own position (47 pings, each within 6 units
  of an own tower, barracks, the fillers or the Ancient), lasting
  `eventduration` 4 s. Lane creeps hitting a tower make it too (21 of the 47
  had no enemy hero or summon near): that is the lane, not news;
- `minimap_controlledcreep` with the enemy's `team`: their summons and
  dominated units (`npc_dota_furion_treant` there), in the team's vision only;
- the buildings still standing: towers, barracks (`npc_dota_goodguys_melee_rax_mid`),
  the fillers and the Ancient (`npc_dota_goodguys_fort`), with their team.

The cards say what is seen, never a call: whether to go is the team's plan,
which GSI does not show (signal_capabilities: no team readiness), and enemies
out of vision are unknown. A building attack is named only with an enemy hero
or summons seen within NEAR of it, while the player is FAR or more away; a push
by summons only on the player's half, SUMMON_MIN or more within SUMMON_SPREAD
of each other, with no enemy hero seen within NEAR, FAR or more from the player.
Both from FROM on (the lane has its own tips). Cards and their rhythm:
map_hints.RoleTips.building_attack / summon_push.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.enemy_heroes import TEAMS
from app.minimap_units import _position

FROM = 10 * 60
NEAR = 1500
FAR = 3000
SUMMON_MIN = 3
SUMMON_SPREAD = 1500
PING = "minimap_ping_baseattacked"
SUMMON_ICON = "minimap_controlledcreep"
BUILDING = re.compile(
    r"^npc_dota_(goodguys|badguys)_"
    r"(?:(tower)([1-4])(?:_(top|mid|bot))?|(melee_rax|range_rax)_(top|mid|bot)|(fort)|(fillers))$"
)
BUILDING_TEAMS = {"goodguys": "radiant", "badguys": "dire"}
# Whose summons a unit is (Valve unit names; a prefix match). A unit not here,
# a dominated neutral among them, is «enemy summons» with no hero named.
SUMMONERS = {
    "npc_dota_furion_treant": "Nature's Prophet",
    "npc_dota_lycan_wolf": "Lycan",
    "npc_dota_broodmother_spider": "Broodmother",
    "npc_dota_beastmaster_boar": "Beastmaster",
    "npc_dota_beastmaster_hawk": "Beastmaster",
    "npc_dota_invoker_forged_spirit": "Invoker",
    "npc_dota_warlock_golem": "Warlock",
    "npc_dota_visage_familiar": "Visage",
    "npc_dota_venomancer_plague_ward": "Venomancer",
    "npc_dota_shadow_shaman_ward": "Shadow Shaman",
    "npc_dota_lone_druid_bear": "Lone Druid",
    "npc_dota_eidolon": "Enigma",
    "npc_dota_unit_undying_zombie": "Undying",
    "npc_dota_clinkz_skeleton_archer": "Clinkz",
    "npc_dota_brewmaster_": "Brewmaster",
    "npc_dota_techies_": "Techies",
}


def building_pings(minimap: Any) -> list[dict[str, float]] | None:
    """[{x, y}] of the «building under attack» pings; None without a minimap."""
    if not isinstance(minimap, dict):
        return None
    found = []
    for unit in minimap.values():
        if isinstance(unit, dict) and unit.get("image") == PING:
            position = _position(unit)
            if position is not None:
                found.append({"x": position[0], "y": position[1]})
    return found


def buildings(minimap: Any) -> list[dict[str, Any]] | None:
    """[{team, kind: tower|barracks|fillers|ancient, tier, lane, x, y}] of the
    buildings on the minimap; None without a minimap block."""
    if not isinstance(minimap, dict):
        return None
    found: list[dict[str, Any]] = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or not isinstance(unit.get("unitname"), str):
            continue
        match = BUILDING.match(unit["unitname"])
        position = _position(unit)
        if match is None or position is None:
            continue
        side, tower, tier, tower_lane, rax, rax_lane, fort, fillers = match.groups()
        if tower:
            kind, lane = "tower", tower_lane
        elif rax:
            kind, lane = "barracks", rax_lane
        else:
            kind, lane = ("ancient" if fort else "fillers"), None
        entry: dict[str, Any] = {
            "team": BUILDING_TEAMS[side],
            "kind": kind,
            "lane": lane,
            "x": position[0],
            "y": position[1],
        }
        if tier:
            entry["tier"] = int(tier)
        if rax:
            entry["melee"] = rax == "melee_rax"
        found.append(entry)
    return found


def summoner(unit: str) -> str | None:
    return next((hero for prefix, hero in SUMMONERS.items() if unit.startswith(prefix)), None)


def enemy_summons(minimap: Any, team_name: Any) -> list[dict[str, Any]] | None:
    """[{unit, hero, x, y}] of the enemy's summoned and dominated units the team
    sees; None without a minimap block or a known team."""
    own = TEAMS.get(str(team_name or "").strip().lower())
    if not isinstance(minimap, dict) or own is None:
        return None
    found = []
    for unit in minimap.values():
        if not isinstance(unit, dict) or unit.get("image") != SUMMON_ICON:
            continue
        name, team = unit.get("unitname"), unit.get("team")
        if not isinstance(name, str) or team not in (2, 3) or team == own:
            continue
        position = _position(unit)
        if position is not None:
            found.append({"unit": name, "hero": summoner(name), "x": position[0], "y": position[1]})
    return found


def _near(units: Any, x: float, y: float, radius: float) -> list[dict[str, Any]]:
    return [
        u
        for u in units or []
        if isinstance(u, dict)
        and isinstance(u.get("x"), (int, float))
        and isinstance(u.get("y"), (int, float))
        and math.hypot(u["x"] - x, u["y"] - y) <= radius
    ]


def _who(summons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[{hero (None: not known), count}], most first."""
    counts: dict[str | None, int] = {}
    for unit in summons:
        counts[unit.get("hero")] = counts.get(unit.get("hero"), 0) + 1
    return [
        {"hero": hero, "count": count}
        for hero, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] or ""))
    ]


def _player(extra: dict[str, Any]) -> tuple[float, float] | None:
    x, y = extra.get("xpos"), extra.get("ypos")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(x), float(y)
    return None


def building_attack(extra: dict[str, Any]) -> dict[str, Any] | None:
    """{building, heroes, summons, x, y} of an own building pinged as attacked
    with an enemy hero or summons seen at it, the player alive and FAR away;
    the nearest such ping to the player. None otherwise."""
    clock, team, at = extra.get("clock_time"), extra.get("team_name"), _player(extra)
    if not isinstance(clock, int) or clock < FROM or at is None or extra.get("alive") is False:
        return None
    pings = extra.get("building_pings")
    own = [b for b in extra.get("buildings") or [] if isinstance(b, dict) and b.get("team") == team]
    best: tuple[float, dict[str, Any]] | None = None
    for ping in pings if isinstance(pings, list) else []:
        building = min(
            own,
            key=lambda b: math.hypot(b["x"] - ping["x"], b["y"] - ping["y"]),
            default=None,
        )
        if (
            building is None
            or math.hypot(building["x"] - ping["x"], building["y"] - ping["y"]) > 400
        ):
            continue
        far = math.hypot(building["x"] - at[0], building["y"] - at[1])
        if far < FAR:
            continue
        heroes = sorted(
            {
                u["hero"]
                for u in _near(extra.get("enemy_units"), building["x"], building["y"], NEAR)
                if u.get("hero")
            }
        )
        summons = _near(extra.get("enemy_summons"), building["x"], building["y"], NEAR)
        if not heroes and not summons:
            continue  # lane creeps at a tower: the lane, not news
        if best is None or far < best[0]:
            best = (
                far,
                {
                    "building": {k: building.get(k) for k in ("kind", "tier", "lane", "melee")},
                    "heroes": heroes,
                    "summons": _who(summons),
                    "x": building["x"],
                    "y": building["y"],
                    "team": team,
                },
            )
    return best[1] if best else None


def summon_push(extra: dict[str, Any]) -> dict[str, Any] | None:
    """{summons, count, zone, side, x, y} of the biggest group of enemy summons
    on the player's half with no enemy hero seen near, FAR from the player."""
    from app.map_analysis import map_side, zone

    clock, team, at = extra.get("clock_time"), extra.get("team_name"), _player(extra)
    if (
        not isinstance(clock, int)
        or clock < FROM
        or at is None
        or extra.get("alive") is False
        or team not in ("radiant", "dire")
    ):
        return None
    units = [u for u in extra.get("enemy_summons") or [] if isinstance(u, dict)]
    best: list[dict[str, Any]] = []
    for unit in units:
        group = _near(units, unit["x"], unit["y"], SUMMON_SPREAD)
        if len(group) > len(best):
            best = group
    if len(best) < SUMMON_MIN:
        return None
    cx = sum(u["x"] for u in best) / len(best)
    cy = sum(u["y"] for u in best) / len(best)
    if map_side(cx, cy, team == "radiant") != "own":
        return None
    if math.hypot(cx - at[0], cy - at[1]) < FAR:
        return None
    if _near(extra.get("enemy_units"), cx, cy, NEAR):
        return None  # a hero with them: a push, which the fight and group cards read
    return {
        "summons": _who(best),
        "count": len(best),
        "zone": zone(cx, cy),
        "side": "own",
        "x": cx,
        "y": cy,
        "team": team,
    }
