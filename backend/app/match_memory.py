"""
match_memory.py - in-memory live match history for GSI overlay advice.

This module stores only a compact session summary. It does not persist data and
does not depend on external match APIs.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from app.action_feedback import ActionWatch
from app.buyback_tracker import BuybackTracker
from app.enemy_heroes import EnemyHeroes
from app.enemy_lanes import EnemyLanes
from app.farm_map import FarmMap
from app.farm_tracker import FarmTracker
from app.fight_summary import FightWatch
from app.gold_tips import GoldTips
from app.gsi_snapshot import TRANSIENT_KEYS
from app.hero_gameplay import HeroGameplay
from app.live_hints import LiveHintInputs, render_live_hints
from app.live_plan import LivePlan
from app.live_role import LiveRoleTracker
from app.map_hints import RoleTips, timers
from app.roshan_timer import RoshanTimer
from app.skill_tips import SkillTips
from app.status_source import StatusWatch
from app.team_context import TeamSupport
from app.tp_tracker import TpTracker

DEATH_DECISION_POINTS = {
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
}

PRE_GAME_STATES = {
    "dota_gamerules_state_init",
    "dota_gamerules_state_wait_for_players_to_load",
    "dota_gamerules_state_hero_selection",
    "dota_gamerules_state_strategy_time",
    "dota_gamerules_state_pre_game",
    "dota_gamestate_init",
    "dota_gamestate_wait_for_players_to_load",
    "dota_gamestate_hero_selection",
    "dota_gamestate_strategy_time",
    "dota_gamestate_pre_game",
    "pre_game",
    "hero_selection",
    "strategy_time",
    "disconnected",
}

# HP falling this many points (of max HP) within 5 s while still above the
# critical line is the moment to leave, not the moment HP is already critical:
# the low-HP card came 1-6 s before a death. Live GSI only (wall-clock deltas).
HP_FALL_FAST_POINTS = 30
HP_FALL_CEILING = 70
# ...and still falling over the last seconds: a burst that already ended (an
# own phase, a finished combo, an HP-cost cast) is not projected forward.
HP_STILL_FALLING_SECONDS = 2
HP_STILL_FALLING_POINTS = 5

# A previous death this close (world units) and this recent (minutes) makes a
# repeated place: two deaths across the map are two events, not one mistake.
# About a third of a lane (a camp and its approaches): one area/route, not the
# same named zone. Eight minutes is a few respawn cycles in the mid game
# (respawn 30-60 s): the same trip taken again, not the next phase of the game.
DEATH_PATTERN_RADIUS = 2500
DEATH_PATTERN_MINUTES = 8
# ...or this many deaths at one spot over the whole match, however spread out
# (player_service.MATCH_PLACE_MIN: the same count names the place). Two at a
# contested spot (a tier-2 tower, the Roshan side of the river) are common in
# any game; three is a habit worth naming.
DEATH_PATTERN_MATCH_COUNT = 3
# A repeated place is a repeated mistake (REPEATED_DEATHS, «reset your route»)
# only for deaths taken alone, away from an objective: dying at the same spot
# in team fights or at an objective (REPEATED_PLACE) is where the game was, not
# a route to change. Alone = the minimap showed no ally staying next to the
# hero (team_context.TeamSupport); unknown (no minimap) claims no mistake.
# The HP the hero entered the fatal fight with: the highest of these last
# seconds before the death (the last tick before a death is always low).
DEATH_ENTRY_SECONDS = 15
# A life lost with the death counter unchanged is unresolved until an
# observation settles it (_observe_life). The game's own revive delays are
# Aegis 5 s and Reincarnation 3 s: with a revive expected (Aegis held,
# Reincarnation ready) the hero must be back within REVIVE_WAIT_SECONDS of game
# time; without one the counter normally rises in the same snapshot, so a dead
# hero still uncounted after COUNTER_WAIT_SECONDS is a death the counter is
# late on. A respawn timer longer than any revive delay is a death at once.
REVIVE_WAIT_SECONDS = 8
COUNTER_WAIT_SECONDS = 3
REVIVE_DELAY_MAX = 5
# A revive stands the hero up where it fell (measured: 42 units after an Aegis
# revive); coming back farther than this is a respawn at the fountain.
REVIVE_RADIUS = 600
# A death inferred without the counter is confirmed (not counted again) by a
# counter rise within this many game seconds.
RECONCILE_SECONDS = 120
# Game seconds between two snapshots that make a gap: a death counted across
# it has no known place (the last alive position is from before the gap).
SNAPSHOT_GAP_SECONDS = 10
# The next life after a revive: how long its readiness is offered.
REVIVE_READY_SECONDS = 20
# An own kill this recent: the fight was won, the next step is re-engage or not.
RECENT_KILL_SECONDS = 15

ESCAPE_OR_DEFENSIVE_FLAG_HINTS = (
    "escape",
    "blink",
    "rage",
    "blade_fury",
    "dark_pact",
    "pounce",
    "attribute_shift",
    "blur",
    "gust",
    "warcry",
    "grappling",
    "raptor",
    "unavailable",
)

P = ParamSpec("P")
R = TypeVar("R")

# Own tier-3 towers and barracks at the start (GSI drops a destroyed building).
OWN_TOWER3, OWN_BARRACKS = 3, 6


def base_danger(enemy_aegis: bool, own_base: dict[str, Any] | None) -> str | None:
    """The game on the line: "enemy_aegis" while an enemy can hold the Aegis,
    "base" once an own tier-3 tower or barracks is down; None otherwise."""
    if enemy_aegis:
        return "enemy_aegis"
    if own_base and (
        int(own_base.get("tower3", OWN_TOWER3)) < OWN_TOWER3
        or int(own_base.get("barracks", OWN_BARRACKS)) < OWN_BARRACKS
    ):
        return "base"
    return None


@dataclass(frozen=True)
class LiveTrackerSnapshot:
    """Detached child-tracker reads captured under one memory owner."""

    match_id: str | None
    hero: str | None
    generation: int
    enemies: list[str]
    opponents: list[str]
    missing: dict[str, Any] | None
    skill_bar: int | None
    tp_missing: bool
    roshan_open: bool
    objective: dict[str, Any] | None
    roshan_strip: list[dict[str, Any]]


def _owned(
    method: Callable[Concatenate[MatchMemory, P], R],
) -> Callable[Concatenate[MatchMemory, P], R]:
    """Serialize a core memory operation; never hold this lock across I/O."""

    @wraps(method)
    def guarded(self: MatchMemory, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return guarded


class MatchMemory:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self.allow_demo_history = False
        self.reset("init")

    @_owned
    def reset(self, reason: str = "manual") -> None:
        self._generation += 1
        now = _now()
        self.match_id: str | None = None
        self.hero: str | None = None
        self.is_demo_or_lobby = False
        self.started_at: str | None = None
        # ~20 s of live GSI (about 2 payloads a second): the HP windows (5/10 s)
        # and the fight entry before a death (DEATH_ENTRY_SECONDS).
        self.last_states: deque[dict[str, Any]] = deque(maxlen=40)
        self.previous_alive_state: dict[str, Any] | None = None
        self.death_count = 0
        self.death_events: list[dict[str, Any]] = []
        # Lives lost without a death counted (Aegis, Reincarnation) and other
        # life-cycle events; never part of the death statistics.
        self.life_events: list[dict[str, Any]] = []
        self._pending_life_loss: dict[str, Any] | None = None
        self._inferred_death_at: int | None = None
        self._last_revive: dict[str, Any] | None = None
        self._had_aegis: bool | None = None
        self._last_kills: int | None = None
        self._kill_at: int | None = None
        self.last_death_minute: int | None = None
        self.last_death_context = ""
        self.repeated_death_patterns: list[str] = []
        self.last_advice_type: str | None = None
        self.reset_reason = reason
        self.created_at = now
        self.updated_at = now
        self._local_session_seed: str | None = None
        self._last_player_deaths: int | None = None
        self.farm = FarmTracker()
        self.buyback = BuybackTracker()
        self.danger: str | None = None  # base_danger: the game on the line
        self.tp = TpTracker()
        self.role = LiveRoleTracker()
        self.tips = RoleTips()
        self.skills = SkillTips()
        self.gold = GoldTips()
        self.roshan = RoshanTimer()
        self.enemies = EnemyHeroes()
        self.enemy_lanes = EnemyLanes()
        self.fights = FightWatch()
        self.gameplay = HeroGameplay()
        self.status = StatusWatch()
        self.actions = ActionWatch()
        self.team = TeamSupport()
        self.plan = LivePlan()
        self.farm_map = FarmMap()

    def observe_state(self, state: dict[str, Any]) -> dict[str, Any]:
        # Roshan/Aegis can need timer settings on the first observed event.
        # Warm that file cache before core ownership, including demo/direct use.
        timers()
        return self._observe_state(state)

    @_owned
    def _observe_state(self, state: dict[str, Any]) -> dict[str, Any]:
        self._generation += 1
        # The minimap creep lists feed the farm tip only: out of every stored
        # and published copy of the state (up to ~176 entries a payload).
        farm_view = _pop_farm_view(state)
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        now_ts = now_dt.timestamp()
        hero = str(state.get("hero") or "Unknown").strip() or "Unknown"
        game_state = str(state.get("game_state") or "").strip().lower()
        current_demo = _ctx_bool(state, "is_demo_or_lobby")

        reset_reason = self._reset_reason_for_state(state, hero, game_state, current_demo)
        if reset_reason:
            self.reset(reset_reason)

        session_id = self._session_id_for_state(state, hero, now)
        if self.match_id and self.match_id != session_id:
            self.reset("match_id_changed")
        if self.hero and self.hero != hero:
            self.reset("demo_hero_changed" if current_demo else "hero_changed")

        self.match_id = session_id
        self.hero = hero
        self.is_demo_or_lobby = current_demo
        if self.started_at is None:
            self.started_at = now
            self.created_at = now
        self.updated_at = now

        previous_alive_state = self.previous_alive_state
        previous_alive = _alive(previous_alive_state) if previous_alive_state is not None else None
        current_alive = _alive(state)
        current_deaths = _ctx_int_or_none(state, "deaths")
        # The last counter seen, kept across payloads without it (a reconnect,
        # a partial payload): a rise is measured against it when it returns.
        deaths_added = (
            current_deaths - self._last_player_deaths
            if current_deaths is not None
            and self._last_player_deaths is not None
            and current_deaths > self._last_player_deaths
            else 0
        )
        last_clock = _game_clock(self.last_states[-1]) if self.last_states else None
        clock_now = _game_clock(state)
        gap = (
            last_clock is not None
            and clock_now is not None
            and clock_now - last_clock > SNAPSHOT_GAP_SECONDS
        )

        track_deaths = not current_demo or self.allow_demo_history
        alive_transition_death = (
            previous_alive is True and current_alive is False and previous_alive_state is not None
        )
        counter_known = current_deaths is not None and self._last_player_deaths is not None
        if track_deaths:
            self._observe_life(
                state,
                previous_alive_state,
                alive_drop=alive_transition_death,
                deaths_added=deaths_added,
                counter_known=counter_known,
                current_alive=current_alive,
                gap=gap,
            )

        if track_deaths and current_alive is True:
            self.previous_alive_state = _copy_state(state)
        elif (
            track_deaths and current_alive is False or current_demo and not self.allow_demo_history
        ):
            self.previous_alive_state = None

        self._annotate_recent_damage(state, now_ts)
        if current_deaths is not None:
            self._last_player_deaths = current_deaths
        self._annotate_status_and_actions(state)
        kills = _ctx_int_or_none(state, "kills")
        if kills is not None and self._last_kills is not None and kills > self._last_kills:
            self._kill_at = _game_clock(state)
        self._last_kills = kills
        self.farm.observe(
            _game_clock(state),
            _ctx_int_or_none(state, "last_hits"),
            current_alive,
            paused=_ctx_bool(state, "paused"),
        )
        own_base = _ctx_value(state, "own_base")
        self.danger = base_danger(
            self.roshan.enemy_aegis(_game_clock(state)),
            own_base if isinstance(own_base, dict) else None,
        )
        self.buyback.observe(
            _game_clock(state),
            _ctx_int_or_none(state, "gold"),
            _ctx_int_or_none(state, "buyback_cost"),
            _ctx_int_or_none(state, "buyback_cooldown"),
            current_alive,
            self.danger,
        )
        has_tp = _ctx_value(state, "has_tp")
        self.tp.observe(
            _game_clock(state),
            has_tp if isinstance(has_tp, bool) else None,
            current_alive,
            paused=_ctx_bool(state, "paused"),
        )
        raw_extra = state.get("extra_context")
        extra = raw_extra if isinstance(raw_extra, dict) else {}
        if extra.get("source_type") == "live_gsi":
            self.roshan.observe(extra)
            self.enemies.observe(extra.get("visible_enemies"))
            self.enemy_lanes.observe(_game_clock(state), extra.get("enemy_units"))
            self.fights.observe(
                _game_clock(state), extra.get("radiant_score"), extra.get("dire_score")
            )
            skills = extra.get("skills")
            self.skills.observe(_game_clock(state), skills if isinstance(skills, dict) else None)
            names = extra.get("item_names")
            self.gold.observe(_game_clock(state), names if isinstance(names, list) else None)
            self.role.observe(
                _game_clock(state),
                x=_number_or_none(extra.get("xpos")),
                y=_number_or_none(extra.get("ypos")),
                last_hits=_ctx_int_or_none(state, "last_hits"),
                team=extra.get("team_name"),
                alive=current_alive,
            )
        self.last_states.append(_copy_state(state))
        self._annotate_state(state)
        if extra.get("source_type") == "live_gsi" and isinstance(state.get("extra_context"), dict):
            role = self.role.role()
            role_name = role.get("role") if role else None
            state["extra_context"]["live_plan"] = self.plan.observe(
                state["extra_context"], role_name
            )
            state["extra_context"]["farm_target"] = self.farm_map.observe(
                {**state["extra_context"], **farm_view}, role_name
            )
        self.gameplay.observe(state)
        return state

    @_owned
    def death_review_decision(self) -> str | None:
        if not self.death_events:
            return None
        patterns = self.death_events[-1].get("patterns")
        if not isinstance(patterns, list):
            patterns = []
        if "REPEATED_DEATHS" in patterns:
            return "REPEATED_DEATH_PATTERN"
        if "ESCAPE_ON_COOLDOWN_DEATH" in patterns:
            return "DEATH_WITH_ESCAPE_ON_COOLDOWN"
        if "LOW_RESOURCE_DEATH" in patterns:
            return "DEATH_LOW_RESOURCE"
        return "DEATH_REVIEW"

    @_owned
    def death_review_for_state(self, state_session: object, *, available: bool) -> str | None:
        """Keep the existing fallback's session check and decision one read."""
        if available or state_session == self.match_id:
            return self.death_review_decision()
        return None

    @_owned
    def note_advice(self, decision_point: str) -> None:
        self.last_advice_type = decision_point

    @_owned
    def gameplay_context(self, state: Mapping[str, Any]) -> dict[str, Any] | None:
        if _ctx_value(state, "match_session_id") != self.match_id or state.get("hero") != self.hero:
            return None
        return self.gameplay.context(state)

    @_owned
    def note_gameplay_advice(self, state: Mapping[str, Any], context: Mapping[str, Any]) -> None:
        clock = _game_clock(state)
        if clock is not None and _ctx_value(state, "match_session_id") == self.match_id:
            self.gameplay.shown(context, clock)

    @_owned
    def role_snapshot(self, prior: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Read the observed/selected role with an already prepared prior."""
        return self.role.role(prior)

    @_owned
    def enemy_heroes(self) -> list[str]:
        return self.enemies.heroes()

    def tracker_snapshot(
        self, *, clock: int | None, lane: str | None, alive: bool, lang: str
    ) -> LiveTrackerSnapshot:
        # Roshan reads the same settings as observation; prepare outside ownership.
        timers()
        return self._tracker_snapshot(clock=clock, lane=lane, alive=alive, lang=lang)

    @_owned
    def _tracker_snapshot(
        self, *, clock: int | None, lane: str | None, alive: bool, lang: str
    ) -> LiveTrackerSnapshot:
        return LiveTrackerSnapshot(
            match_id=self.match_id,
            hero=self.hero,
            generation=self._generation,
            enemies=self.enemies.heroes(),
            opponents=self.enemy_lanes.opponents(lane),
            missing=self.enemy_lanes.missing(clock, lane) if alive else None,
            skill_bar=self.skills.bar_size(),
            tp_missing=self.tp.signal() is not None,
            roshan_open=self.roshan.maybe_up(clock),
            objective=self.roshan.hint(clock, lang),
            roshan_strip=self.roshan.strip(clock, lang),
        )

    def live_hints(
        self,
        state: Mapping[str, Any],
        extra: Mapping[str, Any],
        trackers: LiveTrackerSnapshot,
        inputs: LiveHintInputs,
        lang: str,
    ) -> dict[str, object]:
        timers()
        return self._live_hints(state, extra, trackers, inputs, lang)

    @_owned
    def _live_hints(
        self,
        state: Mapping[str, Any],
        extra: Mapping[str, Any],
        trackers: LiveTrackerSnapshot,
        inputs: LiveHintInputs,
        lang: str,
    ) -> dict[str, object]:
        if trackers.generation != self._generation:
            # Observation/reset ran while metadata was being prepared. Leave
            # new-session tip memory untouched; the next overlay poll retries.
            return {}
        return render_live_hints(self, state, extra, trackers, inputs, lang)

    @_owned
    def summary(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "hero": self.hero,
            "is_demo_or_lobby": self.is_demo_or_lobby,
            "reset_reason": self.reset_reason,
            "started_at": self.started_at,
            "death_count": self.death_count,
            "last_death_minute": self.last_death_minute,
            "recent_death_patterns": self._recent_death_patterns(),
            "last_death_context": self.last_death_context,
            "last_states_count": len(self.last_states),
            "last_advice_type": self.last_advice_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @_owned
    def overlay_context(self) -> dict[str, Any]:
        recent_patterns = self._recent_death_patterns()
        return {
            "match_death_count": self.death_count,
            "recent_death_pattern": recent_patterns[0] if recent_patterns else None,
            "recent_death_patterns": recent_patterns,
            "last_death_minute": self.last_death_minute,
            "last_death_context": self.last_death_context,
            "death_review_available": bool(self.death_events),
            "match_session_id": self.match_id,
        }

    def _best_previous_alive_state(self) -> dict[str, Any] | None:
        for state in reversed(self.last_states):
            if _alive(state) is True:
                return _copy_state(state)
        return None

    def _observe_life(
        self,
        state: dict[str, Any],
        previous_alive_state: dict[str, Any] | None,
        *,
        alive_drop: bool,
        deaths_added: int,
        counter_known: bool,
        current_alive: bool | None,
        gap: bool = False,
    ) -> None:
        """Ordinary deaths vs lives lost with no death counted, reconciled over
        snapshots. GSI usually reports an ordinary death's counter in the same
        snapshot as alive=false and an Aegis revive leaves it unchanged, but the
        counter can be late, missing for a while (a reconnect) or jump across a
        gap. An alive drop without a counter rise is unresolved (life_state)
        until an observation settles it:
        - the counter rises: a death (from the last alive state before the drop);
        - the hero stands up where it fell: an Aegis revive (the Aegis is gone),
          Reincarnation (its cooldown started), or an unconfirmed revive (no
          second-life claim);
        - a respawn timer longer than any revive, the waiting time over, or a
          return at the fountain: a death the counter has not shown, recorded
          as inferred and confirmed (not counted again) by a later rise.
        Never a revive without the hero coming back on the spot."""
        clock = _game_clock(state)
        pending = self._pending_life_loss
        if deaths_added > 0:
            pre_death_state = (
                previous_alive_state
                or (pending or {}).get("pre_state")
                or self._best_previous_alive_state()
                or state
            )
            self._pending_life_loss = None
            inferred = self._unconfirmed_death(clock)
            if inferred is not None:
                inferred["counter"] = "confirmed_late"
                deaths_added -= 1
            for index in range(deaths_added):
                # Deaths across a gap, or several in one jump, happened where
                # and when no snapshot shows: counted, with no place.
                unseen = gap and pending is None or index > 0
                self._record_death_event(
                    pre_death_state,
                    state,
                    confidence="low" if unseen else "high",
                    counter="gap" if unseen else ("late" if pending else "same_snapshot"),
                    place_known=not unseen,
                )
            return
        if alive_drop:
            before = previous_alive_state or {}
            had_aegis = _ctx_value(before, "has_aegis") is True
            reincarnation_ready = _reincarnation_ready(before)
            if not counter_known and not had_aegis and not reincarnation_ready:
                # No death counter in the payload and no revive possible: the
                # alive drop is the only sign; an inferred death.
                self._record_death_event(
                    before or state, state, confidence="low", counter="missing"
                )
                self._inferred_death_at = clock
                return
            self._pending_life_loss = {
                "clock": clock,
                "had_aegis": had_aegis,
                "reincarnation_ready": reincarnation_ready,
                "revive_expected": had_aegis or reincarnation_ready,
                "pre_state": _copy_state(before) if before else None,
                "position": {"x": _ctx_value(before, "xpos"), "y": _ctx_value(before, "ypos")},
            }
        pending = self._pending_life_loss
        if pending is not None:
            self._settle_life_loss(pending, state, clock, current_alive)
        has_aegis = _ctx_value(state, "has_aegis")
        if (
            self._had_aegis is True
            and has_aegis is False
            and current_alive is True
            and self._pending_life_loss is None
            and not (self._last_revive and self._last_revive.get("revived_at") == clock)
        ):
            # Gone while alive: expired (or the payload lost it); never a death.
            self.life_events.append({"type": "aegis_gone_alive", "at": clock})
        if isinstance(has_aegis, bool):
            self._had_aegis = has_aegis

    def _settle_life_loss(
        self,
        pending: dict[str, Any],
        state: dict[str, Any],
        clock: int | None,
        current_alive: bool | None,
    ) -> None:
        """Settle an unresolved life loss on this snapshot, or leave it pending."""
        position = pending["position"]
        here = (_ctx_value(state, "xpos"), _ctx_value(state, "ypos"))
        pre_state = pending.get("pre_state") or state
        if current_alive is True:
            on_spot = _near(here, position, REVIVE_RADIUS)
            far = _distance(here, position)
            if on_spot and pending["had_aegis"] and _ctx_value(state, "has_aegis") is not True:
                kind = "aegis_revive"
            elif on_spot and pending["reincarnation_ready"] and _reincarnation_started(state):
                kind = "reincarnation"
            elif on_spot:
                kind = "revive_unconfirmed"
            elif far is not None:
                # Back somewhere else (the fountain) with no death counted.
                self._pending_life_loss = None
                self._record_death_event(
                    pre_state, state, confidence="low", counter="not_seen", minute_state=pre_state
                )
                self._inferred_death_at = pending["clock"]
                return
            else:
                kind = "life_lost_unresolved"
            event = {
                "type": kind,
                "lost_at": pending["clock"],
                "revived_at": clock,
                "position": position,
            }
            self.life_events.append(event)
            if kind in {"aegis_revive", "reincarnation"}:
                self._last_revive = event
            self._pending_life_loss = None
            return
        waited = (
            clock - pending["clock"] if clock is not None and pending["clock"] is not None else None
        )
        respawn = _ctx_int_or_none(state, "respawn_seconds")
        limit = REVIVE_WAIT_SECONDS if pending["revive_expected"] else COUNTER_WAIT_SECONDS
        if (respawn is not None and respawn > REVIVE_DELAY_MAX + 1) or (
            waited is not None and waited > limit
        ):
            # Dead for longer than any revive takes: a death the counter has
            # not shown yet (late or missing). Counted once; a later counter
            # rise confirms it instead of adding another.
            self._pending_life_loss = None
            self._record_death_event(pre_state, state, confidence="medium", counter="not_seen")
            self._inferred_death_at = pending["clock"]

    def _unconfirmed_death(self, clock: int | None) -> dict[str, Any] | None:
        """The last death inferred without a counter rise, while a rise can
        still be its own late counter (RECONCILE_SECONDS)."""
        at = self._inferred_death_at
        if at is None or not self.death_events:
            return None
        self._inferred_death_at = None
        event = self.death_events[-1]
        if event.get("counter") not in {"not_seen", "missing"}:
            return None
        if clock is not None and clock - at > RECONCILE_SECONDS:
            return None
        return event

    def _recent_kill_seconds(self, clock: int | None) -> int | None:
        """Seconds since the player's own last kill, within RECENT_KILL_SECONDS."""
        if clock is None or self._kill_at is None:
            return None
        ago = clock - self._kill_at
        return ago if 0 <= ago <= RECENT_KILL_SECONDS else None

    def _own_aegis_left(self, clock: int | None) -> int | None:
        """Seconds the player's Aegis still lasts, only when its pickup time is
        known (roshan_timer: the pickup event, or first seen with it after being
        seen without); None otherwise (a late recording start)."""
        expires = self.roshan.aegis_expires()
        if expires is None or clock is None:
            return None
        left = expires - clock
        return left if left > 0 else None

    def _recent_revive(self, clock: int | None) -> dict[str, Any] | None:
        revive = self._last_revive
        if not revive or clock is None or not isinstance(revive.get("revived_at"), int):
            return None
        ago = clock - revive["revived_at"]
        if not 0 <= ago <= REVIVE_READY_SECONDS:
            return None
        return {"type": revive["type"], "seconds_ago": ago}

    def _annotate_status_and_actions(self, state: dict[str, Any]) -> None:
        extra_context = state.setdefault("extra_context", {})
        if not isinstance(extra_context, dict):
            return
        at = _ctx_int_or_none(state, "game_time")
        if at is None:
            at = _game_clock(state)
        moment = None if at is None else float(at)
        # A one-second phase needs a finer clock than game time's whole seconds:
        # the snapshot's observation time (wall clock, MatchMemory's own).
        observed = _number_or_none(extra_context.get("observed_at_epoch"))
        extra_context["status_source"] = self.status.observe(
            extra_context, observed if observed is not None else moment
        )
        extra_context.update(self.actions.observe(extra_context, moment))
        if extra_context.get("source_type") == "live_gsi":
            extra_context["team_support"] = self.team.observe(
                extra_context, observed if observed is not None else moment
            )

    def _annotate_recent_damage(self, state: dict[str, Any], now_ts: float) -> None:
        extra_context = state.setdefault("extra_context", {})
        if not isinstance(extra_context, dict):
            extra_context = {}
            state["extra_context"] = extra_context

        hp_percent = _to_int(state.get("hp_percent"), 100)
        hp_delta_5s = _hp_delta_from_recent_peak(self.last_states, state, now_ts, 5)
        hp_delta_10s = _hp_delta_from_recent_peak(self.last_states, state, now_ts, 10)
        hp_delta_recent = _hp_delta_from_recent_peak(
            self.last_states, state, now_ts, HP_STILL_FALLING_SECONDS
        )
        hp_rise_3s = _hp_rise_from_recent_low(self.last_states, state, now_ts, 3)
        raw_laning = extra_context.get("laning_context")
        laning_context = raw_laning if isinstance(raw_laning, Mapping) else {}
        low_hp_threshold = _to_int(laning_context.get("low_hp_warning_threshold"), 50)
        critical_hp_threshold = _to_int(laning_context.get("critical_hp_threshold"), 35)
        recent_damage_taken = hp_delta_10s <= -20
        hp_falling_fast = (
            -hp_delta_5s
            if extra_context.get("source_type") == "live_gsi"
            and _alive(state) is True
            and hp_delta_5s <= -HP_FALL_FAST_POINTS
            and hp_percent <= HP_FALL_CEILING
            and hp_delta_recent <= -HP_STILL_FALLING_POINTS
            else None
        )
        overstay_warning = (
            hp_percent <= 55
            and _alive(state) is True
            and _has_recent_low_hp_or_damage(self.last_states, now_ts, seconds=15)
        )

        extra_context.update(
            {
                "observed_at_epoch": now_ts,
                "hp_delta_5s": hp_delta_5s,
                "hp_delta_10s": hp_delta_10s,
                # HP points regained over the last 3 s (0 while not recovering).
                "hp_rise_3s": hp_rise_3s,
                "recent_damage_taken": recent_damage_taken,
                "hp_falling_fast": hp_falling_fast,
                "recent_hp_low": hp_percent <= low_hp_threshold,
                "recent_critical_hp": hp_percent <= critical_hp_threshold,
                "recent_pressure_context": "took heavy damage recently"
                if recent_damage_taken
                else "",
                "overstay_warning": overstay_warning,
            }
        )

    def _record_death_event(
        self,
        previous_state: Mapping[str, Any],
        current_state: Mapping[str, Any],
        *,
        confidence: str = "high",
        counter: str = "same_snapshot",
        place_known: bool = True,
        minute_state: Mapping[str, Any] | None = None,
    ) -> None:
        """One death the game counted (or, with `counter` not_seen/missing, one
        inferred without its counter). Without a known place (a death across a
        snapshot gap) no position is stored and no place pattern is claimed."""
        self.death_count += 1
        timing = minute_state if minute_state is not None else current_state
        minute = _to_int(timing.get("minute"), _to_int(previous_state.get("minute"), 0))
        entry = self._fight_entry_state(previous_state) if place_known else previous_state
        circumstance = self._death_circumstance() if place_known else {}
        patterns = (
            self._classify_death(previous_state, minute, entry, circumstance)
            if place_known
            else ["UNKNOWN_DEATH"]
        )
        context = _death_context(patterns)
        event = {
            "id": self.death_count,
            "minute": minute,
            "hero": str(previous_state.get("hero") or current_state.get("hero") or ""),
            "pre_death_hp_percent": _to_int(previous_state.get("hp_percent"), 100),
            "pre_death_mana_percent": _ctx_int(previous_state, "mana_percent", 100),
            # What the hero entered the fatal fight with (DEATH_ENTRY_SECONDS).
            "entry_hp_percent": _to_int(entry.get("hp_percent"), 100),
            "entry_mana_percent": _ctx_int(entry, "mana_percent", 100),
            "clock": _game_clock(timing),
            "confidence": confidence,
            # How the game's counter showed it: same_snapshot, late, gap (the
            # death fell in a gap), not_seen/missing (inferred), confirmed_late.
            "counter": counter,
            "items": list(previous_state.get("items") or []),
            "position": {
                "x": _ctx_value(previous_state, "xpos"),
                "y": _ctx_value(previous_state, "ypos"),
            }
            if place_known
            else None,
            "gpm": _ctx_value(previous_state, "gpm"),
            "last_hits": _ctx_value(previous_state, "last_hits"),
            "ability_risks": _ctx_list(previous_state, "hero_safety_flags"),
            "hero_risk_level": str(_ctx_value(previous_state, "hero_risk_level", "low")),
            "previous_decision_point": _infer_previous_decision_point(previous_state),
            "team_status": str(previous_state.get("team_status") or "unknown"),
            "status_effects": _ctx_list(previous_state, "status_effects"),
            "context": context,
            "patterns": patterns,
            # Allies that stayed next to the hero just before (None: no
            # minimap) and the enemies visible around.
            "with_team": circumstance.get("with_team"),
            "enemies_near": circumstance.get("enemies_near"),
        }
        self.death_events.append(event)
        self.last_death_minute = minute
        self.last_death_context = context
        self.repeated_death_patterns = self._recent_death_patterns()

    def _death_circumstance(self) -> dict[str, Any]:
        """Who was around in the last annotated alive snapshot (TeamSupport):
        with_team True/False, None when the minimap was not there."""
        for state in reversed(self.last_states):
            if _alive(state) is not True:
                continue
            support = _ctx_value(state, "team_support")
            if not isinstance(support, Mapping) or support.get("known") is not True:
                return {"with_team": None, "enemies_near": None}
            steady = support.get("steady")
            return {
                "with_team": bool(steady),
                "enemies_near": support.get("enemies_near"),
            }
        return {"with_team": None, "enemies_near": None}

    def _fight_entry_state(self, previous_state: Mapping[str, Any]) -> Mapping[str, Any]:
        """The alive state with the most HP in the DEATH_ENTRY_SECONDS before the
        last alive one: what the hero entered the fight with. The reference time
        is the last annotated alive state (the pre-death copy is taken before
        its own annotation)."""
        best: Mapping[str, Any] = previous_state
        stamps = [
            _number_or_none(_ctx_value(state, "observed_at_epoch"))
            for state in self.last_states
            if _alive(state) is True
        ]
        known = [stamp for stamp in stamps if stamp is not None]
        if not known:
            return best
        last_ts = max(known)
        for state in self.last_states:
            if _alive(state) is not True:
                continue
            age = last_ts - _number_or_zero(_ctx_value(state, "observed_at_epoch"))
            if 0 <= age <= DEATH_ENTRY_SECONDS and _to_int(state.get("hp_percent"), 0) > _to_int(
                best.get("hp_percent"), 0
            ):
                best = state
        return best

    def _classify_death(
        self,
        previous_state: Mapping[str, Any],
        minute: int,
        entry: Mapping[str, Any] | None = None,
        circumstance: Mapping[str, Any] | None = None,
    ) -> list[str]:
        patterns: list[str] = []
        here = (_ctx_value(previous_state, "xpos"), _ctx_value(previous_state, "ypos"))
        recent_deaths = [
            event
            for event in self.death_events
            if minute - _to_int(event.get("minute"), -999) <= DEATH_PATTERN_MINUTES
        ]
        # The same area (and recent), or the same spot again and again over the
        # match: one repeated mistake. Deaths far apart, or with no position,
        # are only several deaths: no route claim from them.
        same_spot = [e for e in self.death_events if _near(here, e.get("position"))]
        near_recent = [e for e in recent_deaths if _near(here, e.get("position"))]
        repeated_place = bool(near_recent) or len(same_spot) + 1 >= DEATH_PATTERN_MATCH_COUNT
        objective = _to_bool(previous_state.get("near_objective")) or _objective_context(
            previous_state
        )
        circumstance = circumstance or {}
        lone = circumstance.get("with_team") is False and not objective
        earlier = near_recent or same_spot
        if repeated_place and lone and not any(e.get("with_team") is True for e in earlier):
            patterns.append("REPEATED_DEATHS")
        elif repeated_place:
            patterns.append("REPEATED_PLACE")
        elif recent_deaths:
            patterns.append("MULTIPLE_DEATHS")

        if _had_escape_or_defensive_risk(previous_state):
            patterns.append("ESCAPE_ON_COOLDOWN_DEATH")

        # Low HP at the last tick before a death proves nothing (it is always
        # low): the fight entry decides whether the hero went in short.
        start = entry if entry is not None else previous_state
        hp_percent = _to_int(start.get("hp_percent"), 100)
        mana_percent = _ctx_int(start, "mana_percent", 100)
        if hp_percent <= 40 or mana_percent <= 25:
            patterns.append("LOW_RESOURCE_DEATH")

        if _to_bool(previous_state.get("near_objective")) or _objective_context(previous_state):
            patterns.append("OBJECTIVE_DEATH")

        if _looks_like_deep_farming_risk(previous_state):
            patterns.append("FARMING_DEEP_RISK")

        if not patterns:
            patterns.append("UNKNOWN_DEATH")
        return patterns

    def _annotate_state(self, state: dict[str, Any]) -> None:
        extra_context = state.setdefault("extra_context", {})
        if not isinstance(extra_context, dict):
            extra_context = {}
            state["extra_context"] = extra_context

        recent_patterns = self._recent_death_patterns()
        extra_context.update(
            {
                "match_session_id": self.match_id,
                "match_death_count": self.death_count,
                "recent_death_pattern": recent_patterns[0] if recent_patterns else None,
                "recent_death_patterns": recent_patterns,
                "last_death_minute": self.last_death_minute,
                "last_death_context": self.last_death_context,
                "death_review_available": bool(self.death_events),
                "last_death_event_id": self.death_events[-1]["id"] if self.death_events else None,
                "last_death_with_team": self.death_events[-1].get("with_team")
                if self.death_events
                else None,
                "death_review_decision": self.death_review_decision(),
                "farm_stall": self.farm.stall(),
                "buyback_spent": self.buyback.signal(),
                "base_danger": self.danger,
                "tp_missing": self.tp.signal(),
                "life_state": self._life_state(),
                "own_aegis_left": self._own_aegis_left(_game_clock(state)),
                "recent_kill_seconds": self._recent_kill_seconds(_game_clock(state)),
                "recent_revive": self._recent_revive(_game_clock(state)),
            }
        )

    def _life_state(self) -> str | None:
        """reviving: a life lost with a revive expected (Aegis, Reincarnation);
        unresolved: lost with no counter rise yet and no revive possible (a
        late counter); None otherwise."""
        pending = self._pending_life_loss
        if pending is None:
            return None
        return "reviving" if pending["revive_expected"] else "unresolved"

    def _recent_death_patterns(self) -> list[str]:
        if not self.death_events:
            return []
        patterns = self.death_events[-1].get("patterns")
        if not isinstance(patterns, list):
            return []
        return [str(pattern) for pattern in patterns]

    def _reset_reason_for_state(
        self,
        state: Mapping[str, Any],
        hero: str,
        game_state: str,
        current_demo: bool,
    ) -> str | None:
        if not self.match_id:
            return None
        if current_demo and not self.is_demo_or_lobby:
            return "entered_demo_or_lobby"
        if hero and self.hero and hero != self.hero:
            return "demo_hero_changed" if current_demo else "hero_changed"
        normalized_game_state = game_state.replace(" ", "_")
        if normalized_game_state in PRE_GAME_STATES:
            return "pre_game_or_disconnected"
        return None

    def _session_id_for_state(self, state: Mapping[str, Any], hero: str, now: str) -> str:
        explicit_match_id = _ctx_value(state, "match_id")
        if explicit_match_id not in {None, ""}:
            return str(explicit_match_id)

        if self._local_session_seed is None:
            game_time = _ctx_value(state, "game_time", 0)
            raw = f"{hero}|{now}|{game_time}"
            self._local_session_seed = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"local_{self._local_session_seed}"


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _game_clock(state: Mapping[str, Any]) -> int | None:
    clock = _ctx_int_or_none(state, "clock_time")
    if clock is None:
        clock = _ctx_int_or_none(state, "game_time")
    return clock


def _number_or_zero(value: Any) -> float:
    number = _number_or_none(value)
    return 0.0 if number is None else number


def _distance(here: tuple[Any, Any], position: Any) -> float | None:
    if not isinstance(position, Mapping):
        return None
    x0, y0 = _number_or_none(here[0]), _number_or_none(here[1])
    x1, y1 = _number_or_none(position.get("x")), _number_or_none(position.get("y"))
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return None
    return float(((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5)


def _near(here: tuple[Any, Any], position: Any, radius: float = DEATH_PATTERN_RADIUS) -> bool:
    distance = _distance(here, position)
    return distance is not None and distance <= radius


def _reincarnation_ready(state: Mapping[str, Any]) -> bool:
    """A learned, ready passive revive (Wraith King's Reincarnation) before the
    life was lost: its cooldown starting afterwards is the revive."""
    abilities = _ctx_value(state, "abilities")
    if not isinstance(abilities, list):
        return False
    for ability in abilities:
        if (
            isinstance(ability, Mapping)
            and ability.get("raw_name") == "skeleton_king_reincarnation"
            and _to_int(ability.get("level"), 0) > 0
            and ability.get("cooldown") == 0
        ):
            return True
    return False


def _reincarnation_started(state: Mapping[str, Any]) -> bool:
    """Reincarnation's cooldown is running: the revive just used it."""
    abilities = _ctx_value(state, "abilities")
    if not isinstance(abilities, list):
        return False
    return any(
        isinstance(ability, Mapping)
        and ability.get("raw_name") == "skeleton_king_reincarnation"
        and _to_int(ability.get("cooldown"), 0) > 0
        for ability in abilities
    )


def _death_context(patterns: list[str]) -> str:
    if "REPEATED_DEATHS" in patterns:
        return "Multiple recent deaths detected; reset the next route after respawn."
    if "REPEATED_PLACE" in patterns:
        return "Several deaths at this spot, with the team or at an objective."
    if "ESCAPE_ON_COOLDOWN_DEATH" in patterns:
        return "Death followed a state where a key escape or defensive tool was unavailable."
    if "LOW_RESOURCE_DEATH" in patterns:
        return "Death followed a low HP or key resource state."
    if "OBJECTIVE_DEATH" in patterns:
        return "Death happened around an objective context."
    if "FARMING_DEEP_RISK" in patterns:
        return "Death followed farming with limited team context; avoid repeating the same route."
    return "Death detected, but context is limited."


def _infer_previous_decision_point(state: Mapping[str, Any]) -> str:
    if _to_int(state.get("hp_percent"), 100) <= 35:
        return "LOW_HP"
    if _had_escape_or_defensive_risk(state):
        return "HERO_SURVIVABILITY_RISK"
    if _ctx_int(state, "mana_percent", 100) <= 20:
        return "LOW_MANA"
    if _to_bool(state.get("near_objective")) or _objective_context(state):
        return "OBJECTIVE_FIGHT_CHECK"
    game_state = str(state.get("game_state") or "").lower()
    if "fight" in game_state or "pressure" in game_state:
        return "BAD_FIGHT_RISK"
    if "farm" in game_state:
        return "SAFE_FARMING"
    return "UNKNOWN"


def _had_escape_or_defensive_risk(state: Mapping[str, Any]) -> bool:
    flags = [flag.lower() for flag in _ctx_list(state, "hero_safety_flags")]
    return any(any(hint in flag for hint in ESCAPE_OR_DEFENSIVE_FLAG_HINTS) for flag in flags)


def _looks_like_deep_farming_risk(state: Mapping[str, Any]) -> bool:
    if _ctx_value(state, "xpos") is None or _ctx_value(state, "ypos") is None:
        return False
    game_state = str(state.get("game_state") or "").lower()
    team_status = str(state.get("team_status") or "unknown").lower()
    return ("farm" in game_state or "calm" in game_state) and team_status in {"unknown", "even", ""}


def _objective_context(state: Mapping[str, Any]) -> bool:
    context = str(state.get("objective_context") or "").strip().lower()
    return bool(context and context != "unknown")


def _pop_farm_view(state: Mapping[str, Any]) -> dict[str, Any]:
    extra = state.get("extra_context")
    if not isinstance(extra, dict):
        return {}
    return {key: extra.pop(key) for key in TRANSIENT_KEYS if key in extra}


def _copy_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(state, default=str))


def _extra_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra_context = state.get("extra_context")
    return extra_context if isinstance(extra_context, Mapping) else {}


def _ctx_value(state: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if key in state:
        return state.get(key)
    return _extra_context(state).get(key, default)


def _ctx_int(state: Mapping[str, Any], key: str, default: int = 0) -> int:
    return _to_int(_ctx_value(state, key), default)


def _ctx_int_or_none(state: Mapping[str, Any], key: str) -> int | None:
    value = _ctx_value(state, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ctx_bool(state: Mapping[str, Any], key: str) -> bool:
    return _to_bool(_ctx_value(state, key))


def _ctx_list(state: Mapping[str, Any], key: str) -> list[str]:
    value = _ctx_value(state, key, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _alive(state: Mapping[str, Any] | None) -> bool | None:
    if state is None:
        return None
    value = _ctx_value(state, "alive")
    if value is None:
        return True
    return _to_bool(value)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _health_points(state: Mapping[str, Any]) -> tuple[float, float] | None:
    health = _number_or_none(_ctx_value(state, "health"))
    max_health = _number_or_none(_ctx_value(state, "max_health"))
    if health is None or not max_health or max_health <= 0:
        return None
    return health, max_health


def _hp_change(before: Mapping[str, Any], now: Mapping[str, Any]) -> int:
    """HP change from `before` to `now` in points of the current max HP (%).

    With absolute health known, a max-HP change is taken out: Armlet toggled
    off, Treads switched or an attribute shift moves health together with max
    HP, which is no damage, and a max-HP rise alone is no heal. Without it the
    reported percent is compared, as before."""
    a, b = _health_points(before), _health_points(now)
    if a is None or b is None:
        return _to_int(now.get("hp_percent"), 100) - _to_int(before.get("hp_percent"), 100)
    (hp0, max0), (hp1, max1) = a, b
    delta = hp1 - hp0
    max_delta = max1 - max0
    if max_delta < 0 and delta < 0:
        delta = min(0.0, delta - max_delta)  # the part the lower max explains
    elif max_delta > 0 and delta > 0:
        delta = max(0.0, delta - max_delta)  # the part the higher max explains
    return round(delta / max1 * 100)


def _hp_delta_from_recent_peak(
    states: deque[dict[str, Any]],
    current: Mapping[str, Any],
    now_ts: float,
    seconds: int,
) -> int:
    """The largest HP loss (negative) from any state of the last `seconds` to
    now; 0 when HP did not go down."""
    changes = [
        _hp_change(state, current)
        for state in states
        if _recent_state_age(now_ts, state) <= seconds and _alive(state) is not False
    ]
    return min([0, *changes])


def _hp_rise_from_recent_low(
    states: deque[dict[str, Any]],
    current: Mapping[str, Any],
    now_ts: float,
    seconds: int,
) -> int:
    """HP regained (points of max) from the lowest state of the last `seconds`."""
    changes = [
        _hp_change(state, current)
        for state in states
        if _recent_state_age(now_ts, state) <= seconds and _alive(state) is not False
    ]
    return max([0, *changes])


def _has_recent_low_hp_or_damage(
    states: deque[dict[str, Any]],
    now_ts: float,
    *,
    seconds: int,
) -> bool:
    for state in reversed(states):
        if _recent_state_age(now_ts, state) > seconds:
            continue
        if _alive(state) is not True:
            continue
        extra_context = _extra_context(state)
        if (
            _to_bool(extra_context.get("recent_damage_taken"))
            or _to_int(state.get("hp_percent"), 100) <= 55
        ):
            return True
    return False


def _recent_state_age(now_ts: float, state: Mapping[str, Any]) -> float:
    timestamp = _ctx_value(state, "observed_at_epoch")
    try:
        return max(0.0, now_ts - float(timestamp))
    except (TypeError, ValueError):
        return 999999.0


def _now() -> str:
    return datetime.now(UTC).isoformat()


MATCH_MEMORY = MatchMemory()
