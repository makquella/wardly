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
- deliver_item: a major item (a save of last_moments.SAVERS, or a completed
  build item of item_timing; no components, consumables) or its recipe
  waiting in the stash for DELIVERY_WAIT seconds while the hero is alive:
  until it is delivered (and assembled) it is not a tool, and a passive one
  gives nothing either, so being passive does not exclude it. Delivered into
  the backpack and left there BACKPACK_WAIT seconds, the next step changes to
  swapping it into the main slots: in the backpack it neither presses nor
  gives its passive. A recipe delivered but not assembled ends the plan as
  such: which component is missing is not known.

Item stages are kept apart: bought (in the stash), delivered (backpack, or a
recipe not assembled yet), carried (the six main slots) and, for a save,
ready (its cooldown 0). Purchase itself is not observed: an item is first seen
in one of those places; `unseen` is neither on the hero nor in the stash (not
bought, on the courier, dropped or sold). An item back in its place within
RETURN_GRACE seconds is the same copy, not a receipt. Each time a major item is received (to the backpack or
the main slots) the current plan is reassessed (`reassessments`, for the
replay audit): the delivery plan of that item changes its step or ends; any
other plan stays, since no rule here knows what the item changes for it. The
item's effect is named only where the live rules know it (a save tool the
escape and dispel cards may name); otherwise it is recorded as unknown, never
guessed, and no item ever makes «go fight».
- after_fight: a fight is over when no enemy hero has been visible near the
  hero for FIGHT_QUIET seconds after one was (FIGHT_RECENT). Its local result
  is what the player's own counters say happened to them in it: the kills
  they took part in (kills + assists) and their deaths. The team's kill score
  is map-wide: kills elsewhere count in it too (two fights at once, a pick in
  another lane), so it is kept only as the team result over that interval,
  labelled as such, and is never read as this fight's result. An enemy off
  the minimap is unknown, not dead. With FIGHT_TOWER_KILLS or more kills taken
  part in, allies staying next to the hero and an enemy tower within
  TOWER_REACH (each checked on its own): the tower; at or under RECOVER_HP:
  recover first. Nothing taken part in and HP fine: no plan. A gap in the
  data during the fight drops it (its counters span unseen time).
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

from app.item_timing import classify_item_timing, normalize_item_name
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
# An item left this long in the backpack (alive) gets the swap step.
BACKPACK_WAIT = 10
# Where an item is, from least to most usable; a product seen in two places
# (a second copy, a recipe beside it) counts at the most usable one.
STAGES = {"unseen": 0, "stash": 1, "unassembled": 2, "backpack": 3, "carried": 4}
RECEIVED = {"backpack", "carried"}
# An item back where it was within this many seconds is the same copy (GSI
# shows a slot empty while the item is moved): no receipt.
RETURN_GRACE = 5
FIGHT_RADIUS = 2500
FIGHT_RECENT = 30
FIGHT_QUIET = 6
TOWER_REACH = 3000
# Kills the player took part in, in the fight, for the tower step: one is a
# pick, two is a fight their side lost around the player.
FIGHT_TOWER_KILLS = 2
# A gap longer than this between two snapshots of a fight drops it.
FIGHT_GAP = 10
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


def _own_counters(extra: Mapping[str, Any]) -> tuple[int, int] | None:
    """(kills + assists, deaths) of the player: what happened to them."""
    kills, assists, deaths = (_number(extra.get(k)) for k in ("kills", "assists", "deaths"))
    if kills is None or assists is None or deaths is None:
        return None
    return int(kills + assists), int(deaths)


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


def _major(product: str) -> bool:
    """A save, or a completed build item worth a plan (not a component, a
    consumable or a recipe)."""
    if product in SAVERS:
        return True
    if product.startswith("item_recipe_"):
        return False
    return bool(classify_item_timing(product)["is_meaningful"])


def _item_label(product: str, lang: str) -> str:
    return saver_label(product, lang) if product in SAVERS else normalize_item_name(product)


def _item_stages(extra: Mapping[str, Any]) -> dict[str, str] | None:
    """{major item: stage} on this snapshot; None without an items block."""
    active, backpack, stash = (
        extra.get(key) for key in ("active_items", "backpack_items", "stash_items")
    )
    if not isinstance(active, list) or not isinstance(stash, list):
        return None
    stages: dict[str, str] = {}

    def put(name: Any, stage: str, recipe_stage: str) -> None:
        name = str(name)
        product = _product(name)
        if not _major(product):
            return
        stage = recipe_stage if name != product else stage
        if STAGES[stage] > STAGES[stages.get(product, "unseen")]:
            stages[product] = stage

    for name in stash:
        put(name, "stash", "stash")
    for name in backpack if isinstance(backpack, list) else []:
        put(name, "backpack", "unassembled")
    for name in active:
        put(name, "carried", "unassembled")
    return stages


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
        self._fight_own: tuple[int, int] | None = None
        self._fight_seen: int | None = None
        self._fight_start: int | None = None
        self._had_aegis: bool | None = None
        self._last_clock: int | None = None
        self._stages: dict[str, str] | None = None
        self._backpack_since: dict[str, int] = {}
        self._stage_seen: dict[tuple[str, str], int] = {}
        self._backpack_shown: set[tuple[str, int]] = set()
        self.reassessments: deque[dict[str, Any]] = deque(maxlen=40)

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
        self._reassess_items(extra, clock)
        if self.plan is not None:
            ended = self._ended(self.plan, extra, clock, alive)
            if ended is not None:
                self.history.append({**self.plan, "ended": ended, "ended_at": clock})
                self.plan = None
        candidates = [
            self._lane_candidate(extra, clock, alive, role),
            self._delivery_candidate(extra, clock, alive),
            self._backpack_candidate(clock, alive),
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
            stage = (self._stages or {}).get(basis["item"])
            if plan["next"] == "to_main_slots":
                if stage == "carried":
                    return "done:carried"
                if self._stages is not None and stage != "backpack":
                    return "cancelled:gone"  # sold, dropped or disassembled
                return "cancelled:timeout" if age > DELIVERY_GIVE_UP else None
            stash = extra.get("stash_items")
            if isinstance(stash, list) and basis["stash_name"] not in stash:
                if stage == "backpack":
                    # In the backpack: the swap step after BACKPACK_WAIT.
                    return "cancelled:timeout" if age > DELIVERY_GIVE_UP else None
                if stage == "unassembled":
                    return "done:delivered_not_assembled"
                return "done:carried" if stage == "carried" else "done:delivered"
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

    # --- items received: reassess the plan ---------------------------------------

    def _reassess_items(self, extra: Mapping[str, Any], clock: int) -> None:
        stages = _item_stages(extra)
        if stages is None:
            return  # no items block: the stages are unknown, kept as they were
        previous, self._stages = self._stages, stages
        self._backpack_since = {
            product: self._backpack_since.get(product, clock)
            for product, stage in stages.items()
            if stage == "backpack"
        }
        seen = self._stage_seen
        for product, stage in stages.items():
            back = seen.get((product, stage))
            seen[(product, stage)] = clock
            if previous is None:
                continue  # the first view is where things are, not what was received
            old = previous.get(product, "unseen")
            if stage == old or stage not in RECEIVED or STAGES[stage] < STAGES[old]:
                continue
            if back is not None and clock - back <= RETURN_GRACE:
                continue  # the same copy, back after a move
            self.reassessments.append(self._reassess(product, old, stage, extra, clock))

    def _reassess(
        self, product: str, old: str, new: str, extra: Mapping[str, Any], clock: int
    ) -> dict[str, Any]:
        plan = self.plan
        entry: dict[str, Any] = {
            "at": clock,
            "item": product,
            "from": old,
            "to": new,
            # Only what the live rules know the item does; the rest unknown.
            "effect": "save_tool" if product in SAVERS else "unknown",
            "ready": None,
            "plan": plan["goal"] if plan else None,
            "next": plan["next"] if plan else None,
        }
        if new == "carried" and product in SAVERS:
            cooldowns = extra.get("item_cooldowns")
            left = _number(cooldowns.get(product)) if isinstance(cooldowns, Mapping) else None
            entry["ready"] = None if left is None else left == 0
        own = (
            plan is not None and plan["goal"] == "deliver_item" and plan["basis"]["item"] == product
        )
        if plan is not None and own and new == "carried":
            self.history.append({**plan, "ended": "done:carried", "ended_at": clock})
            self.plan = None
            entry["result"] = "ended"
        elif own:
            entry["result"] = "kept:backpack_wait"  # the swap step after BACKPACK_WAIT
        else:
            # No rule here knows what the item changes for another plan.
            entry["result"] = "kept" if plan else "no_plan"
        return entry

    def _backpack_candidate(self, clock: int, alive: bool) -> dict[str, Any] | None:
        if not alive:
            return None
        for product, since in sorted(self._backpack_since.items(), key=lambda item: item[1]):
            if clock - since < BACKPACK_WAIT or (product, since) in self._backpack_shown:
                continue
            self._backpack_shown.add((product, since))
            candidate = {
                "goal": "deliver_item",
                "basis": {
                    "stash_name": None,
                    "item": product,
                    "label": _item_label(product, "en"),
                    "label_uk": _item_label(product, "uk"),
                    "save": product in SAVERS,
                    "where": "backpack",
                    "waiting": clock - since,
                },
                "next": "to_main_slots",
                "done_when": "it is in the main slots",
                "cancel_when": "death, the item gone, or 3 minutes",
            }
            plan = self.plan
            if (
                plan is not None
                and plan["goal"] == "deliver_item"
                and plan["basis"]["item"] == product
            ):
                # The delivery plan of this item: its next step changes.
                self.history.append({**plan, "ended": "changed:in_backpack", "ended_at": clock})
                self.plan = {**candidate, "since": clock}
                self.reassessments.append(
                    {"at": clock, "item": product, "to": "backpack", "result": "changed"}
                )
                return None
            return candidate
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
            name: self._stash_since.get(name, clock) for name in names if _major(_product(name))
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
                    "label": _item_label(product, "en"),
                    "label_uk": _item_label(product, "uk"),
                    "save": product in SAVERS,
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
        own = _own_counters(extra)
        seen, self._fight_seen = self._fight_seen, clock
        if self._contest_at is not None and seen is not None and clock - seen > FIGHT_GAP:
            self._contest_at = None  # the fight spans unseen time: no result
        if visible_enemies_near(extra, FIGHT_RADIUS) and alive:
            if self._contest_at is None or clock - self._contest_at > FIGHT_RECENT:
                # A new fight: the counters at its start.
                self._fight_score, self._fight_own = score, own
                self._fight_start = clock
            self._contest_at = clock
            return None
        if not alive:
            # Dead in the fight: its outcome is the death card's, not this one.
            self._contest_at = None
            return None
        if self._contest_at is None or clock - self._contest_at < FIGHT_QUIET:
            return None
        started, own_started, self._contest_at = self._fight_score, self._fight_own, None
        if own is None or own_started is None:
            return None
        took_part = own[0] - own_started[0]
        share = _hp_share(extra)
        allies = steady_allies(extra)
        tower = _enemy_tower_near(extra)
        basis: dict[str, Any] = {
            "took_part": max(0, took_part),
            "hp": round(share * 100) if share is not None else None,
            "allies": len(allies),
            "tower": tower,
        }
        if score is not None and started is not None:
            # Map-wide, over the fight's interval: never this fight's result.
            basis["team_interval"] = {
                "kills": score[0] - started[0],
                "lost": score[1] - started[1],
                "from": _clock_label(clock if self._fight_start is None else self._fight_start),
                "to": _clock_label(clock),
            }
        if took_part >= FIGHT_TOWER_KILLS and allies and tower is not None:
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
