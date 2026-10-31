"""
farm_map.py - the farm that pays most right now: a lane wave or a neutral camp
the player can take, with its gold, how far it is and why (a map hint card,
map_hints.farm_params). Cores only, after the laning phase, text only.

What it stands on (minimap_units.py; checked on real recordings):
- waves: the enemy lane creeps the team sees right now. A wave in the fog is
  not a candidate and its size is never assumed;
- camps: the spots of data/live/farm_map.json (built from the player's own
  recordings, scripts/build_farm_map.py; a camp missing there is unknown) and
  what the minimap shows at them. A camp is
  - `seen_full`: neutrals at it now or within CAMP_SEEN_FRESH seconds;
  - `expected`: the player cleared it, or it was seen empty, before the last
    minute boundary and it was not seen since (Valve: a camp respawns on the
    minute if its spawn box is empty; whether someone took it since, or stood
    in the box, is unknown, so it is ranked below a camp seen full);
  - `cleared` / `empty`: taken by the player or seen empty (an own unit
    within VISION_SHARE of its vision range) this minute: no candidate;
  - `unknown` otherwise: never a candidate;
- this match's own numbers, never another hero's: move speed (the player's
  own displacement), the gold of a lane creep (gold_from_creep_kills, which
  counts lane creeps only, per lane last hit) and of a neutral (the rest of
  the gold change: total minus income, hero kills, shared, summons and lane
  creeps; purchases skipped), and how fast the player clears a camp (seconds
  per 1000 HP from their own clears). Before the player has cleared a camp,
  no camp is a candidate (whether the hero can clear one is unknown); a camp
  with more HP than CLEARED_HP_MARGIN of the biggest cleared one is not
  either, and ancients only after an ancient clear.

The card names the best option only when it beats what the player is doing
(their farm gold of the last RATE_WINDOW seconds) by BETTER_SHARE and
GAIN_MIN gold a minute, and never while the player is at a wave or a camp
already; one new target per TARGET_GAP seconds and at most TARGETS_MAX per
TARGETS_WINDOW; a wave more than WAVE_TRAVEL_MAX seconds away is no target.
GSI sends up to 10 payloads a second live and recordings keep 2: the full
run is once per game second (the first payload of it), the others only
re-check the gates, so a replay decides as live does. Minimap keys are no
unit identity (minimap_units.py): a neutral is followed by name and position. Nothing when
dead, at or under HP_MIN, stunned, teleporting, in a fight (contest_near),
during an after-fight or Aegis plan, with an enemy hero visible near the hero
or the target, for a camp on the enemy half or a wave next to an enemy tower.
Path length (trees, cliffs) is a straight line times PATH_FACTOR: an estimate,
named in `unknown`. It reads only the current snapshot and its own past.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import deque
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR
from app.map_analysis import map_side, zone
from app.team_context import contest_near, visible_enemies_near

CORE_ROLES = {"carry", "mid", "offlane"}
# After the laning phase (live_plan.LANE_UNTIL): the lane has its own tips.
FROM_CLOCK = 10 * 60
HP_MIN = 0.5
WAVE_RADIUS = 600
WAVE_MIN = 2
CAMP_RADIUS = 500
CAMP_REACH = 650
KILL_REACH = 700
# A clear: neutrals within CLEAR_NEAR of the hero belong to it; walking
# CLEAR_ABORT away from a camp still standing drops it.
CLEAR_NEAR = 900
CLEAR_ABORT = 1300
AT_TARGET = 700
# A candidate this close is where the player already is (busy, no card): a
# card for a wave 900 units away said what the player was doing anyway
# (replays of 9061316351 and 9061396945: arrival 1 s after such cards).
HERE_RADIUS = 1200
# Visible enemy heroes this close to the hero or the target: no farm card
# (live_plan.FIGHT_RADIUS).
ENEMY_HERO_NEAR = 2500
# A neutral is the same unit a second later: same name, this close.
SAME_UNIT = 250
# A wave further than this moves on before the hero gets there.
WAVE_TRAVEL_MAX = 15
ENEMY_TOWER_NEAR = 1100
CAMP_SEEN_FRESH = 45
VISION_SHARE = 0.6
EXPECTED_SHARE = 0.8
CLEARED_HP_MARGIN = 1.2
PATH_FACTOR = 1.25
SPEED_DEFAULT = 300.0
SPEED_WINDOW = 60
SPEED_SAMPLES = 10
SPEED_SPAN = 3
WAVE_CLEAR_PER_CREEP = 2.0
RATE_WINDOW = 30
GOLD_WINDOW = 180
LANE_LH_MIN = 5
BETTER_SHARE = 1.4
GAIN_MIN = 60
TARGET_GAP = 45
TARGETS_MAX = 4
TARGETS_WINDOW = 300
THEN_RADIUS = 1500
# Valve's lane creep names by kind (the enemy's are valued as these).
LANE_UNIT = {
    "melee": "npc_dota_creep_goodguys_melee",
    "flag": "npc_dota_creep_goodguys_flagbearer",
    "ranged": "npc_dota_creep_goodguys_ranged",
    "siege": "npc_dota_goodguys_siege",
}
UNKNOWN = ["creeps_in_fog", "camps_out_of_vision", "path_length", "enemies_not_seen"]


@lru_cache(maxsize=1)
def farm_data() -> dict[str, Any]:
    try:
        data = json.loads((DATA_DIR / "live" / "farm_map.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {"camps": [], "units": {}}
    camps = data.get("camps") if isinstance(data, Mapping) else None
    units = data.get("units") if isinstance(data, Mapping) else None
    return {
        "camps": [c for c in camps if isinstance(c, Mapping)] if isinstance(camps, list) else [],
        "units": dict(units) if isinstance(units, Mapping) else {},
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _bounty(unit: str) -> float | None:
    info = farm_data()["units"].get(unit)
    bounty = info.get("bounty") if isinstance(info, Mapping) else None
    return sum(bounty) / 2 if isinstance(bounty, list) and len(bounty) == 2 else None


def _hp(unit: str) -> float:
    info = farm_data()["units"].get(unit)
    return float(info.get("hp") or 0) if isinstance(info, Mapping) else 0.0


def _ancient(unit: str) -> bool:
    info = farm_data()["units"].get(unit)
    return bool(info.get("ancient")) if isinstance(info, Mapping) else False


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _clusters(units: list[dict[str, Any]], radius: float) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for unit in units:
        for group in groups:
            if any(_dist(unit["x"], unit["y"], u["x"], u["y"]) < radius for u in group):
                group.append(unit)
                break
        else:
            groups.append([unit])
    return groups


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


class FarmMap:
    """The farm target of one match (MatchMemory), see the module doc."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.target: dict[str, Any] | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=60)
        self._targets: deque[int] = deque(maxlen=TARGETS_MAX + 2)
        self._last_clock: int | None = None
        self._positions: deque[tuple[int, float, float]] = deque(maxlen=SPEED_WINDOW + 5)
        self._neutrals: list[dict[str, Any]] = []
        self._camps: dict[str, dict[str, Any]] = {}
        self._clears: deque[tuple[int, float, float, bool]] = deque(maxlen=40)
        self._clears_speed: deque[float] = deque(maxlen=40)
        self._episode: dict[str, Any] | None = None
        self._wave_clears: deque[float] = deque(maxlen=20)
        self._wave_episode: dict[str, Any] | None = None
        self._prev: dict[str, Any] | None = None
        # (clock, lane last hits, neutral kills, lane gold, neutral gold), cumulative.
        self._totals: deque[tuple[int, float, float, float, float]] = deque(maxlen=GOLD_WINDOW + 5)
        self._sums: list[float] = [0, 0, 0.0, 0.0]

    # --- the snapshot ---------------------------------------------------------

    def observe(self, extra: Mapping[str, Any], role: str | None) -> dict[str, Any] | None:
        """One live snapshot (with the minimap creep lists); the current target
        (a copy, `new` on the snapshot it started) or None."""
        clock = extra.get("clock_time")
        creeps, neutrals = extra.get("lane_creeps"), extra.get("neutral_units")
        if not isinstance(clock, int) or isinstance(clock, bool):
            return None
        if self._last_clock is not None and clock < self._last_clock:
            self.reset()  # a rewound replay or another match
        alive = extra.get("alive") is not False
        if clock == self._last_clock:
            # The same game second: only the gates, on this payload.
            gate = self._gate(extra, role, clock, alive)
            if gate is not None:
                self._end(gate, clock)
                return None
            return self._out(clock)
        self._last_clock = clock
        if not isinstance(creeps, list) or not isinstance(neutrals, list):
            self._end("no_minimap_creeps", clock)
            return None
        x, y = _number(extra.get("xpos")), _number(extra.get("ypos"))
        if x is None or y is None:
            self._end("no_position", clock)
            return None
        self._observe_position(clock, x, y, alive)
        kills = self._observe_neutrals(extra, neutrals, clock, x, y)
        lane_near = any(
            isinstance(c, Mapping)
            and c.get("team") == "enemy"
            and _dist(c["x"], c["y"], x, y) <= KILL_REACH
            for c in creeps
        )
        neutral_near = any(_dist(u["x"], u["y"], x, y) <= KILL_REACH for u in neutrals)
        self._observe_gold(extra, clock, kills, lane_near, neutral_near)
        self._observe_camps(extra, neutrals, clock, x, y)
        self._observe_wave_clear(creeps, clock, x, y)
        gate = self._gate(extra, role, clock, alive)
        if gate is not None:
            self._end(gate, clock)
            return None
        return self._choose(extra, creeps, clock, x, y)

    # --- what the player does: speed, kills, gold --------------------------------

    def _observe_position(self, clock: int, x: float, y: float, alive: bool) -> None:
        if not alive:
            self._positions.clear()
            return
        if not self._positions or self._positions[-1][0] != clock:
            self._positions.append((clock, x, y))

    def speed(self) -> tuple[float, bool]:
        """(units a second, measured) from the last SPEED_WINDOW seconds."""
        points = list(self._positions)
        rates = []
        for (t0, x0, y0), (t1, x1, y1) in zip(points, points[SPEED_SPAN:], strict=False):
            seconds = t1 - t0
            if seconds <= 0 or points[-1][0] - t1 > SPEED_WINDOW:
                continue
            rate = _dist(x0, y0, x1, y1) / seconds
            if 150 <= rate <= 1000:  # walking: no stops, blinks or teleports
                rates.append(rate)
        if len(rates) < SPEED_SAMPLES:
            return SPEED_DEFAULT, False
        return statistics.median(rates), True

    def _observe_neutrals(
        self,
        extra: Mapping[str, Any],
        neutrals: list[dict[str, Any]],
        clock: int,
        x: float,
        y: float,
    ) -> int:
        """Neutral kills by the player on this game second: units next to the
        hero with no unit of the same name within SAME_UNIT now, while their
        last hits rose."""
        current = [u for u in neutrals if isinstance(u, Mapping) and "x" in u and "unit" in u]
        gone = [
            u
            for u in self._neutrals
            if not any(
                c["unit"] == u["unit"] and _dist(c["x"], c["y"], u["x"], u["y"]) <= SAME_UNIT
                for c in current
            )
        ]
        self._neutrals = [dict(u) for u in current]
        last_hits = extra.get("last_hits")
        prev_lh = self._prev.get("last_hits") if self._prev else None
        rose = (
            last_hits - prev_lh
            if isinstance(last_hits, int) and isinstance(prev_lh, int) and last_hits > prev_lh
            else 0
        )
        near = [u for u in gone if _dist(u["x"], u["y"], x, y) <= KILL_REACH]
        return min(len(near), rose)

    def _observe_gold(
        self,
        extra: Mapping[str, Any],
        clock: int,
        neutral_kills: int,
        lane_near: bool,
        neutral_near: bool,
    ) -> None:
        """Lane and neutral last hits and gold. A last hit is a lane one with
        enemy lane creeps next to the hero and no neutrals, a neutral one the
        other way round (or a neutral seen dying there); with both or neither
        it counts for neither (unknown)."""
        sources = extra.get("gold_sources")
        reliable, unreliable = extra.get("gold_reliable"), extra.get("gold_unreliable")
        last_hits = extra.get("last_hits")
        items = extra.get("item_names")
        now: dict[str, Any] = {
            "sources": dict(sources) if isinstance(sources, Mapping) else None,
            "gold": reliable + unreliable
            if isinstance(reliable, int) and isinstance(unreliable, int)
            else None,
            "last_hits": last_hits if isinstance(last_hits, int) else None,
            "items": sorted(items) if isinstance(items, list) else None,
        }
        prev, self._prev = self._prev, now
        if prev is None or now["sources"] is None or prev["sources"] is None:
            return
        lh = (now["last_hits"] or 0) - (prev["last_hits"] or 0)
        lane_gold = now["sources"].get("creep_kills", 0) - prev["sources"].get("creep_kills", 0)
        if lh > 0:
            if neutral_near and not lane_near:
                neutral_kills = max(neutral_kills, lh)
            elif lane_near and not neutral_near:
                self._sums[0] += max(0, lh - neutral_kills)
        self._sums[1] += neutral_kills
        self._sums[2] += max(0, lane_gold)
        if (
            neutral_kills
            and not lane_near
            and now["gold"] is not None
            and prev["gold"] is not None
            and now["items"] == prev["items"]
        ):
            # Neutral gold is in no counter: the rise of the total on a second
            # with a neutral kill and no lane creep near, less the income and
            # the hero, shared and summon gold. Lane creep gold is left out of
            # the sum (gold_from_creep_kills catches up in batches, gold that
            # was in the total before); purchases are skipped.
            other = sum(
                now["sources"].get(k, 0) - prev["sources"].get(k, 0)
                for k in ("hero_kills", "income", "shared", "summon_kills")
            )
            self._sums[3] += max(0, now["gold"] - prev["gold"] - other)
        entry = (clock, self._sums[0], self._sums[1], self._sums[2], self._sums[3])
        if not self._totals or self._totals[-1][0] != clock:
            self._totals.append(entry)
        else:
            self._totals[-1] = entry

    def _window(self, clock: int, seconds: int) -> tuple[float, float, float, float] | None:
        """(lane last hits, neutral kills, lane gold, neutral gold) over the last
        `seconds` (or all there is when less)."""
        if not self._totals:
            return None
        base = [t for t in self._totals if t[0] <= clock - seconds] or [self._totals[0]]
        then, now = base[-1], self._totals[-1]
        return now[1] - then[1], now[2] - then[2], now[3] - then[3], now[4] - then[4]

    def lane_creep_gold(self, clock: int) -> tuple[float | None, bool]:
        """Gold a lane creep gave this player lately; (None, False) before
        LANE_LH_MIN lane last hits were seen."""
        window = self._window(clock, GOLD_WINDOW)
        if window and window[0] >= LANE_LH_MIN and window[2] > 0:
            return window[2] / window[0], True
        return None, False

    def neutral_gold_share(self) -> float | None:
        """Measured neutral gold over Valve's base bounty, from own clears
        (bounties grow during a match)."""
        return _median([c[2] for c in self._clears if c[2] > 0])

    def farm_rate(self, clock: int) -> float:
        window = self._window(clock, RATE_WINDOW)
        if window is None:
            return 0.0
        return max(0.0, window[2] + window[3]) / RATE_WINDOW

    # --- camps ----------------------------------------------------------------------

    def _observe_camps(
        self,
        extra: Mapping[str, Any],
        neutrals: list[dict[str, Any]],
        clock: int,
        x: float,
        y: float,
    ) -> None:
        vision = extra.get("vision_sources")
        sources = (
            [v for v in vision if isinstance(v, (list, tuple)) and len(v) == 3]
            if isinstance(vision, list)
            else []
        )
        at_camp: dict[str, tuple[float, float, int]] = {}
        for camp in farm_data()["camps"]:
            cid = str(camp.get("id"))
            cx, cy = _number(camp.get("x")), _number(camp.get("y"))
            if cx is None or cy is None:
                continue
            state = self._camps.setdefault(cid, {})
            here = [u for u in neutrals if _dist(u["x"], u["y"], cx, cy) <= CAMP_RADIUS]
            at_camp[cid] = (cx, cy, len(here))
            if here:
                state["full"] = clock
            elif any(_dist(sx, sy, cx, cy) <= VISION_SHARE * r for sx, sy, r in sources):
                if state.get("full") != clock:
                    state["empty"] = clock
        self._observe_clear(at_camp, neutrals, clock, x, y)

    def _observe_clear(
        self,
        at_camp: dict[str, tuple[float, float, int]],
        neutrals: list[dict[str, Any]],
        clock: int,
        x: float,
        y: float,
    ) -> None:
        """A clear by the player: from the hero reaching a camp with neutrals
        until no neutral is left near the hero or at the camp, with own kills
        in between. Followed around the hero: a pulled camp leaves its spot.
        The camp's size is the most units of each name seen at once."""
        near = [u for u in neutrals if _dist(u["x"], u["y"], x, y) <= CLEAR_NEAR]
        episode = self._episode
        if episode is None:
            start = next(
                (
                    cid
                    for cid, (cx, cy, count) in at_camp.items()
                    if count and _dist(x, y, cx, cy) <= CAMP_REACH
                ),
                None,
            )
            if start is not None:
                self._episode = {
                    "camp": start,
                    "start": clock,
                    "counts": {},
                    "kills": self._sums[1],
                    "gold": self._sums[3],
                }
                self._count_units(self._episode, near)
            return
        cx, cy, standing = at_camp.get(episode["camp"], (x, y, 0))
        self._count_units(episode, near)
        if near or standing:
            if standing and _dist(x, y, cx, cy) > CLEAR_ABORT:
                self._episode = None  # walked away from a camp still standing
            return
        self._episode = None
        if self._sums[1] <= episode["kills"]:
            return  # emptied, but not by the player's kills
        units = [name for name, count in episode["counts"].items() for _ in range(count)]
        hp = sum(_hp(u) for u in units)
        if hp <= 0:
            return
        valve = sum(_bounty(u) or 0 for u in units)
        gold = self._sums[3] - episode["gold"]
        share = gold / valve if valve > 0 and gold > 0 else 0.0
        seconds = max(1, clock - episode["start"])
        self._clears.append((clock, hp, share, any(_ancient(u) for u in units)))
        self._clears_speed.append(seconds / hp * 1000)
        self._camps.setdefault(episode["camp"], {})["cleared"] = clock

    @staticmethod
    def _count_units(episode: dict[str, Any], near: list[dict[str, Any]]) -> None:
        counts: dict[str, int] = {}
        for unit in near:
            counts[unit["unit"]] = counts.get(unit["unit"], 0) + 1
        for name, count in counts.items():
            episode["counts"][name] = max(episode["counts"].get(name, 0), count)

    def capability(self) -> dict[str, Any]:
        """What the player has shown they clear this match."""
        if not self._clears:
            return {"cleared": False}
        return {
            "cleared": True,
            "max_hp": max(c[1] for c in self._clears),
            "ancient": any(c[3] for c in self._clears),
            "sec_per_khp": _median(list(self._clears_speed)[-6:]),
        }

    def camp_state(self, cid: str, clock: int) -> str:
        state = self._camps.get(cid) or {}
        events = [
            (state[k], k) for k in ("full", "cleared", "empty") if isinstance(state.get(k), int)
        ]
        if not events:
            return "unknown"
        at, kind = max(events)
        minute = clock - clock % 60
        if kind == "full":
            return "seen_full" if clock - at <= CAMP_SEEN_FRESH else "unknown"
        if at < minute:
            return "expected"
        return "cleared" if kind == "cleared" else "empty"

    # --- waves ----------------------------------------------------------------------

    def _observe_wave_clear(
        self, creeps: list[dict[str, Any]], clock: int, x: float, y: float
    ) -> None:
        near = [
            c
            for c in creeps
            if isinstance(c, Mapping)
            and c.get("team") == "enemy"
            and _dist(c["x"], c["y"], x, y) <= AT_TARGET
        ]
        episode = self._wave_episode
        if episode is None:
            if len(near) >= WAVE_MIN:
                self._wave_episode = {"start": clock, "count": len(near), "lh": self._sums[0]}
            return
        episode["count"] = max(episode["count"], len(near))
        if not near:
            killed = self._sums[0] - episode["lh"]
            if killed >= 2:
                self._wave_clears.append((clock - episode["start"]) / max(1, episode["count"]))
            self._wave_episode = None

    def wave_clear_per_creep(self) -> tuple[float, bool]:
        values = list(self._wave_clears)[-8:]
        if len(values) >= 2:
            return max(0.5, statistics.median(values)), True
        return WAVE_CLEAR_PER_CREEP, False

    # --- choosing ---------------------------------------------------------------------

    def _gate(
        self, extra: Mapping[str, Any], role: str | None, clock: int, alive: bool
    ) -> str | None:
        if (role or "") not in CORE_ROLES:
            return "role"
        if clock < FROM_CLOCK:
            return "laning"
        if not alive:
            return "dead"
        hp, top = _number(extra.get("health")), _number(extra.get("max_health"))
        if hp is None or not top or hp / top <= HP_MIN:
            return "hp"
        if any(extra.get(flag) is True for flag in ("stunned", "hexed", "teleporting")):
            return "busy"
        if contest_near(extra):
            return "fight"
        plan = extra.get("live_plan")
        if isinstance(plan, Mapping) and plan.get("goal") in {"after_fight", "aegis_window"}:
            return "plan"
        if visible_enemies_near(extra, ENEMY_HERO_NEAR):
            return "enemy_near"
        return None

    def _candidates(
        self, extra: Mapping[str, Any], creeps: list[dict[str, Any]], clock: int
    ) -> list[dict[str, Any]]:
        team = str(extra.get("team_name") or "").lower()
        raw_towers = extra.get("towers")
        towers: list[Any] = raw_towers if isinstance(raw_towers, list) else []
        enemy_towers = [t for t in towers if isinstance(t, Mapping) and t.get("team") != team]
        raw_enemies = extra.get("enemy_units")
        enemies: list[Any] = raw_enemies if isinstance(raw_enemies, list) else []
        lane_gold, lane_measured = self.lane_creep_gold(clock)
        per_creep, wave_measured = self.wave_clear_per_creep()
        found: list[dict[str, Any]] = []
        enemy_creeps = [c for c in creeps if isinstance(c, Mapping) and c.get("team") == "enemy"]
        for group in _clusters(enemy_creeps, WAVE_RADIUS):
            if len(group) < WAVE_MIN:
                continue
            gx = sum(c["x"] for c in group) / len(group)
            gy = sum(c["y"] for c in group) / len(group)
            lane = zone(gx, gy)
            if lane not in {"top", "mid", "bot", "base"}:
                continue
            if any(_dist(gx, gy, t["x"], t["y"]) <= ENEMY_TOWER_NEAR for t in enemy_towers):
                continue
            kinds: dict[str, int] = {}
            for c in group:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
            gold = sum(
                (
                    lane_gold
                    if lane_measured and lane_gold
                    else _bounty(LANE_UNIT.get(c["kind"], "")) or 36
                )
                for c in group
            )
            found.append(
                {
                    "kind": "wave",
                    "id": None,
                    "lane": lane,
                    "x": gx,
                    "y": gy,
                    "creeps": len(group),
                    "kinds": kinds,
                    "gold": gold,
                    "clear_s": per_creep * len(group),
                    "estimated": []
                    if lane_measured and wave_measured
                    else ["wave_gold" if not lane_measured else "wave_clear_time"],
                }
            )
        able = self.capability()
        if able.get("cleared"):
            share = self.neutral_gold_share()
            for camp in farm_data()["camps"]:
                cid = str(camp.get("id"))
                state = self.camp_state(cid, clock)
                if state not in {"seen_full", "expected"}:
                    continue
                cx, cy = float(camp["x"]), float(camp["y"])
                if map_side(cx, cy, team == "radiant") == "enemy":
                    continue
                hp = float(camp.get("hp") or 0)
                ancient = bool(camp.get("ancient"))
                if (
                    hp <= 0
                    or hp > CLEARED_HP_MARGIN * able["max_hp"]
                    or (ancient and not able["ancient"])
                ):
                    continue
                gold = float(camp.get("gold") or 0) * (share or 1.0)
                if state == "expected":
                    gold *= EXPECTED_SHARE
                found.append(
                    {
                        "kind": "camp",
                        "id": cid,
                        "lane": zone(cx, cy),
                        "x": cx,
                        "y": cy,
                        "ancient": ancient,
                        "state": state,
                        "respawn": clock - clock % 60 if state == "expected" else None,
                        "gold": gold,
                        "clear_s": (able["sec_per_khp"] or 0) * hp / 1000,
                        "estimated": [] if share else ["camp_gold"],
                    }
                )
        return [
            c
            for c in found
            if not any(
                _dist(c["x"], c["y"], e["x"], e["y"]) <= ENEMY_HERO_NEAR
                for e in enemies
                if isinstance(e, Mapping) and "x" in e
            )
        ]

    def _rate(self, candidate: dict[str, Any], x: float, y: float, speed: float) -> dict[str, Any]:
        distance = _dist(candidate["x"], candidate["y"], x, y)
        travel = 0.0 if distance <= HERE_RADIUS else distance * PATH_FACTOR / speed
        seconds = max(1.0, travel + candidate["clear_s"])
        return {**candidate, "travel_s": round(travel), "rate": candidate["gold"] / seconds}

    def _choose(
        self, extra: Mapping[str, Any], creeps: list[dict[str, Any]], clock: int, x: float, y: float
    ) -> dict[str, Any] | None:
        speed, measured = self.speed()
        scored = [self._rate(c, x, y, speed) for c in self._candidates(extra, creeps, clock)]
        here = [c for c in scored if c["travel_s"] == 0]
        current = max([c["rate"] for c in here] + [self.farm_rate(clock)])
        others = [
            c
            for c in scored
            if c["travel_s"] > 0 and (c["kind"] != "wave" or c["travel_s"] <= WAVE_TRAVEL_MAX)
        ]
        best = max(others, key=lambda c: c["rate"], default=None)
        target = self.target
        if target is not None:
            follow = self._follow(target, scored)
            if follow is None:
                self._end("gone", clock)
                target = None
            elif follow["travel_s"] == 0:
                self._end("reached", clock)
                target = None
            else:
                target.update(
                    {k: follow[k] for k in ("x", "y", "gold", "rate", "travel_s", "clear_s")}
                )
                for key in ("creeps", "kinds", "state", "respawn"):
                    if key in follow:
                        target[key] = follow[key]
                target["current_rate"] = current
                if (
                    best is None
                    or best["rate"] < BETTER_SHARE * target["rate"]
                    or self._same(best, target)
                ):
                    return self._out(clock)
        if best is None or here:
            # Nothing better, or the player is at a wave or a camp already.
            return self._out(clock) if self.target is not None else None
        if best["rate"] < BETTER_SHARE * current or (best["rate"] - current) * 60 < GAIN_MIN:
            return self._out(clock) if self.target is not None else None
        if self._targets and clock - self._targets[-1] < TARGET_GAP:
            return self._out(clock) if self.target is not None else None
        if sum(1 for t in self._targets if clock - t < TARGETS_WINDOW) >= TARGETS_MAX:
            return self._out(clock) if self.target is not None else None
        if self.target is not None:
            self._end("replaced", clock)
        then = max(
            (
                c
                for c in scored
                if c is not best and _dist(c["x"], c["y"], best["x"], best["y"]) <= THEN_RADIUS
            ),
            key=lambda c: c["rate"],
            default=None,
        )
        self._targets.append(clock)
        self.target = {
            **best,
            "since": clock,
            "current_rate": current,
            "speed_measured": measured,
            "where": self._where(extra, best),
            "then": {"kind": then["kind"], "ancient": then.get("ancient", False)} if then else None,
            "unknown": UNKNOWN
            + list(best.get("estimated") or [])
            + ([] if measured else ["move_speed"]),
        }
        return self._out(clock)

    @staticmethod
    def _same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        if a["kind"] == "camp" or b["kind"] == "camp":
            return a.get("id") == b.get("id")
        return a.get("lane") == b.get("lane") and _dist(a["x"], a["y"], b["x"], b["y"]) <= 900

    def _follow(
        self, target: Mapping[str, Any], scored: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        same = [c for c in scored if c["kind"] == target["kind"] and self._same(c, target)]
        return min(
            same, key=lambda c: _dist(c["x"], c["y"], target["x"], target["y"]), default=None
        )

    def _where(self, extra: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
        team = str(extra.get("team_name") or "").lower()
        raw_towers = extra.get("towers")
        towers: list[Any] = raw_towers if isinstance(raw_towers, list) else []
        near = min(
            (t for t in towers if isinstance(t, Mapping) and t.get("lane")),
            key=lambda t: _dist(t["x"], t["y"], candidate["x"], candidate["y"]),
            default=None,
        )
        where: dict[str, Any] = {
            "zone": zone(candidate["x"], candidate["y"]),
            "side": map_side(candidate["x"], candidate["y"], team == "radiant"),
            "team": team,
        }
        if near is not None and _dist(near["x"], near["y"], candidate["x"], candidate["y"]) <= 2200:
            where["tower"] = {
                "team": near.get("team"),
                "tier": near.get("tier"),
                "lane": near.get("lane"),
            }
        return where

    def _out(self, clock: int) -> dict[str, Any] | None:
        if self.target is None:
            return None
        out = {k: v for k, v in self.target.items() if k != "estimated"}
        out["gold"] = round(out["gold"])
        out["rate"] = round(out["rate"], 2)
        out["current_rate"] = round(out.get("current_rate") or 0, 2)
        out["new"] = out["since"] == clock
        return out

    def _end(self, reason: str, clock: int) -> None:
        if self.target is not None:
            entry = {k: v for k, v in self.target.items() if k not in {"estimated"}}
            entry.update({"ended": reason, "ended_at": clock, "gold": round(entry["gold"])})
            self.history.append(entry)
            self.target = None
        return None
