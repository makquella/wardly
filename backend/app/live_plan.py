"""
live_plan.py - the coach's short-term plan: one goal at a time, what it rests
on, the next step, and when it is done or called off.

A card is a moment; a plan is what the next half minute is for. LivePlan keeps
one current plan (a stronger one replaces a weaker one, never the other way)
and starts one only when the best action changes, from what GSI shows:

- lane_recover: a core in the laning phase took at most LANE_MAX_LH last hits
  in LANE_WINDOW seconds while alive the whole time, with HP down to
  LANE_LOW_HP or LANE_ENEMIES+ enemy heroes visible around. The next step is
  the tower's last hits and asking a support: not «go to the jungle», which a
  weak hero at this level may not clear (GSI shows neither the creep
  equilibrium nor whether the hero can farm camps: named in the card).
- deliver_item: an active item (last_moments.SAVERS) or its recipe waiting in
  the stash for DELIVERY_WAIT seconds while the hero is alive: until it is
  delivered (and assembled) it is not a tool. A passive or a stat item
  (Skadi, an Aghanim's that changes no press) changes no immediate action and
  starts no plan.
- after_fight: a fight is over when no enemy hero has been visible near the
  hero for FIGHT_QUIET seconds after one was (FIGHT_RECENT). Its result is the
  kill score during it (never missing markers: an enemy off the minimap is
  unknown, not dead). Won with allies staying next to the hero and an enemy
  tower within TOWER_REACH: hit it now; otherwise, low on HP: recover first.
  No result in the score: no plan.
- aegis_window: the Aegis picked up (its timer known, roshan_timer) with the
  team: group and take what it is for while it lasts; alone it buys one
  mistake. A second life after its revive is the readiness card's
  (live_tools.readiness_copy).

Every plan carries `done` and `cancel` checked on each snapshot; a finished
plan goes to `history` (for the replay audit) with how it ended. It reads
only the current snapshot and its own past; never the future.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from app.last_moments import SAVERS, saver_label
from app.team_context import steady_allies, visible_enemies_near

LANE_FROM = 3 * 60
LANE_UNTIL = 10 * 60
LANE_WINDOW = 90
LANE_MAX_LH = 1
LANE_LOW_HP = 0.5
LANE_ENEMIES = 2
LANE_ENEMY_RADIUS = 1600
# A plan that recovered the lane: this many last hits within a minute.
LANE_RECOVERED_LH = 3
DELIVERY_WAIT = 30
DELIVERY_GIVE_UP = 180
FIGHT_RADIUS = 2500
FIGHT_RECENT = 30
FIGHT_QUIET = 6
TOWER_REACH = 3000
AFTER_FIGHT_SECONDS = 45
RECOVER_HP = 0.5
RECOVERED_HP = 0.8
AEGIS_MIN_LEFT = 60
# Higher replaces lower; equal or lower waits until the current one ends.
PRIORITY = {"after_fight": 4, "aegis_window": 3, "lane_recover": 2, "deliver_item": 1}
NO_CORE = {"support", "hard_support", "pos4", "pos5"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _hp_share(extra: Mapping[str, Any]) -> float | None:
    hp, top = _number(extra.get("health")), _number(extra.get("max_health"))
    return hp / top if hp is not None and top else None


def _clock_label(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _team_scores(extra: Mapping[str, Any]) -> tuple[int, int] | None:
    """(own team kills, enemy team kills) from the map score."""
    radiant, dire = _number(extra.get("radiant_score")), _number(extra.get("dire_score"))
    team = str(extra.get("team_name") or "").lower()
    if radiant is None or dire is None or team not in {"radiant", "dire"}:
        return None
    return (int(radiant), int(dire)) if team == "radiant" else (int(dire), int(radiant))


def _enemy_tower_near(extra: Mapping[str, Any]) -> dict[str, Any] | None:
    x, y = _number(extra.get("xpos")), _number(extra.get("ypos"))
    team = str(extra.get("team_name") or "").lower()
    towers = extra.get("towers")
    if x is None or y is None or not isinstance(towers, list):
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for tower in towers:
        if not isinstance(tower, Mapping) or str(tower.get("team")) == team:
            continue
        tx, ty = _number(tower.get("x")), _number(tower.get("y"))
        if tx is None or ty is None:
            continue
        distance = ((tx - x) ** 2 + (ty - y) ** 2) ** 0.5
        if distance <= TOWER_REACH and (best is None or distance < best[0]):
            best = (distance, dict(tower))
    return best[1] if best else None


def _tower_standing(tower: Mapping[str, Any], extra: Mapping[str, Any]) -> bool | None:
    towers = extra.get("towers")
    if not isinstance(towers, list):
        return None
    return any(
        isinstance(t, Mapping)
        and t.get("team") == tower.get("team")
        and t.get("tier") == tower.get("tier")
        and t.get("lane") == tower.get("lane")
        for t in towers
    )


def _product(name: str) -> str:
    """The item a stash recipe completes (item_recipe_manta → item_manta)."""
    return "item_" + name.removeprefix("item_recipe_") if name.startswith("item_recipe_") else name


class LivePlan:
    """One short-term plan per match (MatchMemory), see the module doc."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.plan: dict[str, Any] | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=40)
        self._lane: deque[tuple[int, int, bool, float | None, int]] = deque(maxlen=240)
        self._lane_shown: int | None = None
        self._stash_since: dict[str, int] = {}
        self._delivered: set[tuple[str, int]] = set()
        self._contest_at: int | None = None
        self._fight_score: tuple[int, int] | None = None
        self._had_aegis: bool | None = None
        self._last_clock: int | None = None

    def observe(self, extra: Mapping[str, Any], role: str | None) -> dict[str, Any] | None:
        """One live snapshot; returns the current plan (a copy, `new` on the
        snapshot it started) or None."""
        clock = extra.get("clock_time")
        if not isinstance(clock, int) or isinstance(clock, bool) or clock < 0:
            return self._current(None)
        if self._last_clock is not None and clock < self._last_clock:
            self.reset()  # a rewound replay or another match
        self._last_clock = clock
        alive = extra.get("alive") is not False
        if self.plan is not None:
            ended = self._ended(self.plan, extra, clock, alive)
            if ended is not None:
                self.history.append({**self.plan, "ended": ended, "ended_at": clock})
                self.plan = None
        candidates = [
            self._lane_candidate(extra, clock, alive, role),
            self._delivery_candidate(extra, clock, alive),
            self._fight_candidate(extra, clock, alive),
            self._aegis_candidate(extra, clock, alive),
        ]
        for candidate in candidates:
            if candidate is None:
                continue
            current = self.plan
            if current is None or PRIORITY[candidate["goal"]] > PRIORITY[current["goal"]]:
                if current is not None:
                    self.history.append({**current, "ended": "replaced", "ended_at": clock})
                self.plan = {**candidate, "since": clock}
        return self._current(clock)

    def _current(self, clock: int | None) -> dict[str, Any] | None:
        if self.plan is None:
            return None
        return {**self.plan, "new": clock is not None and self.plan["since"] == clock}

    # --- when a plan is over -------------------------------------------------

    def _ended(
        self, plan: Mapping[str, Any], extra: Mapping[str, Any], clock: int, alive: bool
    ) -> str | None:
        goal, basis = plan["goal"], plan["basis"]
        age = clock - plan["since"]
        if not alive and goal != "aegis_window":
            return "cancelled:died"
        if goal == "lane_recover":
            if clock >= LANE_UNTIL:
                return "done:laning_over"
            gained = self._lh_gained(clock, 60)
            if gained is not None and gained >= LANE_RECOVERED_LH:
                return "done:last_hits_back"
            return None
        if goal == "deliver_item":
            stash = extra.get("stash_items")
            if isinstance(stash, list) and basis["stash_name"] not in stash:
                return "done:delivered"
            return "cancelled:timeout" if age > DELIVERY_GIVE_UP else None
        if goal == "after_fight":
            if basis["next"] == "recover":
                share = _hp_share(extra)
                if share is not None and share >= RECOVERED_HP:
                    return "done:recovered"
            else:
                standing = _tower_standing(basis["tower"], extra)
                if standing is False:
                    return "done:tower_down"
                if len(visible_enemies_near(extra, FIGHT_RADIUS)) > len(steady_allies(extra)) + 1:
                    return "cancelled:enemies_back"
            return "done:window_over" if age > AFTER_FIGHT_SECONDS else None
        if goal == "aegis_window":
            if extra.get("has_aegis") is False:
                return "done:aegis_gone"
            return None
        return None

    # --- what starts one -------------------------------------------------------

    def _lh_gained(self, clock: int, window: int) -> int | None:
        base = [s for s in self._lane if s[0] <= clock - window]
        if not base or not self._lane:
            return None
        return self._lane[-1][1] - base[-1][1]

    def _lane_candidate(
        self, extra: Mapping[str, Any], clock: int, alive: bool, role: str | None
    ) -> dict[str, Any] | None:
        last_hits = extra.get("last_hits")
        if isinstance(last_hits, int) and not isinstance(last_hits, bool):
            if not self._lane or self._lane[-1][0] != clock:
                enemies = len(visible_enemies_near(extra, LANE_ENEMY_RADIUS))
                self._lane.append((clock, last_hits, alive, _hp_share(extra), enemies))
        if not LANE_FROM <= clock < LANE_UNTIL or not alive or (role or "") in NO_CORE:
            return None
        if self._lane_shown is not None and clock - self._lane_shown < 3 * 60:
            return None
        window = [s for s in self._lane if clock - LANE_WINDOW <= s[0] <= clock]
        base = [s for s in self._lane if s[0] <= clock - LANE_WINDOW]
        if not window or not base or clock - base[-1][0] > LANE_WINDOW + 10:
            return None  # not enough history, or a gap
        if not all(s[2] for s in window):
            return None  # a death in the window is another story
        gained = window[-1][1] - base[-1][1]
        if gained > LANE_MAX_LH:
            return None
        lows = [s[3] for s in window if s[3] is not None]
        hp_min = min(lows) if lows else None
        enemies = max(s[4] for s in window)
        if not (hp_min is not None and hp_min <= LANE_LOW_HP or enemies >= LANE_ENEMIES):
            return None  # a quiet stretch (a pushed-out wave, a rune trip)
        self._lane_shown = clock
        start = base[-1][0]
        return {
            "goal": "lane_recover",
            "basis": {
                "last_hits": gained,
                "from": _clock_label(start),
                "to": _clock_label(clock),
                "seconds": clock - start,
                "hp_min": round(hp_min * 100) if hp_min is not None else None,
                "enemies": enemies,
                "unknown": ["creep_equilibrium", "camp_clear_speed"],
            },
            "next": "tower_last_hits_and_support",
            "done_when": f"{LANE_RECOVERED_LH}+ last hits in a minute, or laning over",
            "cancel_when": "death",
        }

    def _delivery_candidate(
        self, extra: Mapping[str, Any], clock: int, alive: bool
    ) -> dict[str, Any] | None:
        stash = extra.get("stash_items")
        if not isinstance(stash, list):
            return None
        names = {str(name) for name in stash}
        self._stash_since = {
            name: self._stash_since.get(name, clock) for name in names if _product(name) in SAVERS
        }
        if not alive:
            return None
        for name, since in sorted(self._stash_since.items(), key=lambda item: item[1]):
            if clock - since < DELIVERY_WAIT or (name, since) in self._delivered:
                continue
            self._delivered.add((name, since))
            product = _product(name)
            return {
                "goal": "deliver_item",
                "basis": {
                    "stash_name": name,
                    "item": product,
                    "label": saver_label(product, "en"),
                    "label_uk": saver_label(product, "uk"),
                    "waiting": clock - since,
                },
                "next": "courier",
                "done_when": "the stash no longer holds it",
                "cancel_when": "death or 3 minutes",
            }
        return None

    def _fight_candidate(
        self, extra: Mapping[str, Any], clock: int, alive: bool
    ) -> dict[str, Any] | None:
        score = _team_scores(extra)
        if visible_enemies_near(extra, FIGHT_RADIUS) and alive:
            if self._contest_at is None or clock - self._contest_at > FIGHT_RECENT:
                self._fight_score = score  # a new fight: the score at its start
            self._contest_at = clock
            return None
        if not alive:
            # Dead in the fight: its outcome is the death card's, not this one.
            self._contest_at = None
            return None
        if self._contest_at is None or clock - self._contest_at < FIGHT_QUIET:
            return None
        started, self._contest_at = self._fight_score, None
        if score is None or started is None:
            return None
        kills, lost = score[0] - started[0], score[1] - started[1]
        if kills <= 0 and lost <= 0:
            return None  # nothing in the score: no result to act on
        share = _hp_share(extra)
        allies = steady_allies(extra)
        tower = _enemy_tower_near(extra)
        basis: dict[str, Any] = {
            "kills": kills,
            "lost": lost,
            "hp": round(share * 100) if share is not None else None,
            "allies": len(allies),
            "tower": tower,
        }
        if kills >= 2 and kills > lost and allies and tower is not None:
            basis["next"] = "tower"
            return {
                "goal": "after_fight",
                "basis": basis,
                "next": "tower",
                "done_when": "the tower falls, or 45 s",
                "cancel_when": "enemies back in number, or death",
            }
        if share is not None and share <= RECOVER_HP:
            basis["next"] = "recover"
            return {
                "goal": "after_fight",
                "basis": basis,
                "next": "recover",
                "done_when": "HP back to 80 %, or 45 s",
                "cancel_when": "death",
            }
        return None

    def _aegis_candidate(
        self, extra: Mapping[str, Any], clock: int, alive: bool
    ) -> dict[str, Any] | None:
        has = extra.get("has_aegis")
        picked = has is True and self._had_aegis is False
        if isinstance(has, bool):
            self._had_aegis = has
        left = extra.get("own_aegis_left")
        if not picked or not alive or not isinstance(left, int) or left < AEGIS_MIN_LEFT:
            return None
        allies = steady_allies(extra)
        return {
            "goal": "aegis_window",
            "basis": {
                "left": left,
                "until": _clock_label(clock + left),
                "allies": len(allies),
            },
            "next": "push_with_team" if allies else "group_up",
            "done_when": "the Aegis is used or expires",
            "cancel_when": "",
        }
