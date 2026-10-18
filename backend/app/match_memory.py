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

from app.buyback_tracker import BuybackTracker
from app.enemy_heroes import EnemyHeroes
from app.enemy_lanes import EnemyLanes
from app.farm_tracker import FarmTracker
from app.gold_tips import GoldTips
from app.hero_gameplay import HeroGameplay
from app.live_hints import LiveHintInputs, render_live_hints
from app.live_role import LiveRoleTracker
from app.map_hints import RoleTips, timers
from app.roshan_timer import RoshanTimer
from app.skill_tips import SkillTips
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
        self.last_states: deque[dict[str, Any]] = deque(maxlen=20)
        self.previous_alive_state: dict[str, Any] | None = None
        self.death_count = 0
        self.death_events: list[dict[str, Any]] = []
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
        self.gameplay = HeroGameplay()

    def observe_state(self, state: dict[str, Any]) -> dict[str, Any]:
        # Roshan/Aegis can need timer settings on the first observed event.
        # Warm that file cache before core ownership, including demo/direct use.
        timers()
        return self._observe_state(state)

    @_owned
    def _observe_state(self, state: dict[str, Any]) -> dict[str, Any]:
        self._generation += 1
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
        death_delta = (
            current_deaths is not None
            and self._last_player_deaths is not None
            and current_deaths > self._last_player_deaths
        )

        track_deaths = not current_demo or self.allow_demo_history
        alive_transition_death = (
            previous_alive is True and current_alive is False and previous_alive_state is not None
        )
        if track_deaths and (alive_transition_death or death_delta):
            pre_death_state = previous_alive_state or self._best_previous_alive_state() or state
            self._record_death_event(pre_death_state, state)

        if track_deaths and current_alive is True:
            self.previous_alive_state = _copy_state(state)
        elif (
            track_deaths and current_alive is False or current_demo and not self.allow_demo_history
        ):
            self.previous_alive_state = None

        self._annotate_recent_damage(state, now_ts)
        self._last_player_deaths = current_deaths
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

    def _annotate_recent_damage(self, state: dict[str, Any], now_ts: float) -> None:
        extra_context = state.setdefault("extra_context", {})
        if not isinstance(extra_context, dict):
            extra_context = {}
            state["extra_context"] = extra_context

        hp_percent = _to_int(state.get("hp_percent"), 100)
        hp_delta_5s = _hp_delta_from_recent_peak(self.last_states, hp_percent, now_ts, 5)
        hp_delta_10s = _hp_delta_from_recent_peak(self.last_states, hp_percent, now_ts, 10)
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
    ) -> None:
        self.death_count += 1
        minute = _to_int(current_state.get("minute"), _to_int(previous_state.get("minute"), 0))
        patterns = self._classify_death(previous_state, minute)
        context = _death_context(patterns)
        event = {
            "id": self.death_count,
            "minute": minute,
            "hero": str(previous_state.get("hero") or current_state.get("hero") or ""),
            "pre_death_hp_percent": _to_int(previous_state.get("hp_percent"), 100),
            "pre_death_mana_percent": _ctx_int(previous_state, "mana_percent", 100),
            "items": list(previous_state.get("items") or []),
            "position": {
                "x": _ctx_value(previous_state, "xpos"),
                "y": _ctx_value(previous_state, "ypos"),
            },
            "gpm": _ctx_value(previous_state, "gpm"),
            "last_hits": _ctx_value(previous_state, "last_hits"),
            "ability_risks": _ctx_list(previous_state, "hero_safety_flags"),
            "hero_risk_level": str(_ctx_value(previous_state, "hero_risk_level", "low")),
            "previous_decision_point": _infer_previous_decision_point(previous_state),
            "team_status": str(previous_state.get("team_status") or "unknown"),
            "status_effects": _ctx_list(previous_state, "status_effects"),
            "context": context,
            "patterns": patterns,
        }
        self.death_events.append(event)
        self.last_death_minute = minute
        self.last_death_context = context
        self.repeated_death_patterns = self._recent_death_patterns()

    def _classify_death(self, previous_state: Mapping[str, Any], minute: int) -> list[str]:
        patterns: list[str] = []
        recent_deaths = [
            event for event in self.death_events if minute - _to_int(event.get("minute"), -999) <= 8
        ]
        if self.death_count >= 2 or recent_deaths:
            patterns.append("REPEATED_DEATHS")

        if _had_escape_or_defensive_risk(previous_state):
            patterns.append("ESCAPE_ON_COOLDOWN_DEATH")

        hp_percent = _to_int(previous_state.get("hp_percent"), 100)
        mana_percent = _ctx_int(previous_state, "mana_percent", 100)
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
                "death_review_decision": self.death_review_decision(),
                "farm_stall": self.farm.stall(),
                "buyback_spent": self.buyback.signal(),
                "base_danger": self.danger,
                "tp_missing": self.tp.signal(),
            }
        )

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


def _death_context(patterns: list[str]) -> str:
    if "REPEATED_DEATHS" in patterns:
        return "Multiple recent deaths detected; reset the next route after respawn."
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


def _hp_delta_from_recent_peak(
    states: deque[dict[str, Any]],
    current_hp: int,
    now_ts: float,
    seconds: int,
) -> int:
    recent_hp_values = [
        _to_int(state.get("hp_percent"), current_hp)
        for state in states
        if _recent_state_age(now_ts, state) <= seconds
    ]
    if not recent_hp_values:
        return 0
    return current_hp - max(recent_hp_values)


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
