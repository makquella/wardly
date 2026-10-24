"""
decision_points.py — tiny event detector for GSI-driven overlay advice.
"""

from collections.abc import Mapping
from typing import Any, Literal, cast

from app.hero_gameplay import selected_rule
from app.hero_profiles import evaluate_laning_context, farm_pace
from app.hero_safety import evaluate_hero_safety
from app.item_timing import contains_meaningful_item_reference, is_meaningful_item_timing
from app.match_memory import DEATH_DECISION_POINTS, MATCH_MEMORY
from app.status_source import is_threat

DecisionPoint = Literal[
    "LOW_HP",
    "LOW_HP_WARNING",
    "RECENT_DAMAGE_WARNING",
    "OVERSTAY_WARNING",
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
    "LOW_MANA",
    "DISABLED_STATUS",
    "BUYBACK_AVAILABLE",
    "DEAD_WAIT",
    "SMOKED_STATUS",
    "HERO_SURVIVABILITY_RISK",
    "HERO_GAMEPLAY",
    "LANING_REGEN_CHECK",
    "LANING_FARM_CHECK",
    "ABILITY_SAFETY_COOLDOWN",
    "SOFT_STATUS",
    "FARMING_PHASE_PRESSURE",
    "OBJECTIVE_FIGHT_CHECK",
    "BAD_FIGHT_RISK",
    "ITEM_TIMING",
    "SAFE_FARMING",
    "NO_ADVICE",
]

PRESSURE_KEYWORDS = {
    "pressure",
    "gank",
    "ganked",
    "danger",
    "smoke",
    "enemy_push",
    "tower_pressure",
    "under_attack",
}

OBJECTIVE_FIGHT_KEYWORDS = {
    "objective",
    "roshan",
    "tower",
    "barracks",
    "push",
    "highground",
    "tormentor",
}

FIGHT_RISK_KEYWORDS = {
    "fight",
    "teamfight",
    "skirmish",
    "brawl",
    "contest",
    "engage",
    "chase",
    "dive",
}

ITEM_TIMING_KEYWORDS = {
    "power_spike",
    "power spike",
    "battle_fury",
    "battle fury",
    "manta",
    "bkb",
    "butterfly",
    "abyssal",
    "next_item",
    "next item",
}

SAFE_FARMING_KEYWORDS = {
    "calm",
    "farm",
    "farming",
    "jungle",
    "lane",
    "laning",
    "safe",
    "neutral",
    "gsi_update",
}

NO_ADVICE_KEYWORDS = {
    "paused",
    "draft",
    "strategy",
    "disconnected",
}


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


def _extra_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra_context = state.get("extra_context")
    return extra_context if isinstance(extra_context, Mapping) else {}


def _ctx_value(state: Mapping[str, Any], key: str, default: Any = None) -> Any:
    if key in state:
        return state.get(key)
    return _extra_context(state).get(key, default)


def _ctx_int(state: Mapping[str, Any], key: str, default: int = 0) -> int:
    return _to_int(_ctx_value(state, key), default=default)


def _ctx_bool(state: Mapping[str, Any], key: str) -> bool:
    return _to_bool(_ctx_value(state, key))


def _state_text(state: Mapping[str, Any]) -> str:
    return " ".join(
        str(state.get(key, ""))
        for key in (
            "game_state",
            "team_status",
            "event_context",
            "teamfight_result",
            "objective_context",
        )
    ).lower()


def has_pressure_signal(state: Mapping[str, Any]) -> bool:
    text = _state_text(state)
    return any(keyword in text for keyword in PRESSURE_KEYWORDS)


def has_objective_fight_signal(state: Mapping[str, Any]) -> bool:
    text = _state_text(state)
    return any(keyword in text for keyword in OBJECTIVE_FIGHT_KEYWORDS)


def has_bad_fight_risk_signal(state: Mapping[str, Any]) -> bool:
    text = _state_text(state)
    has_fight = any(keyword in text for keyword in FIGHT_RISK_KEYWORDS)
    has_objective = any(keyword in text for keyword in OBJECTIVE_FIGHT_KEYWORDS)
    return has_fight and not has_objective


def has_item_timing_signal(state: Mapping[str, Any]) -> bool:
    category = str(state.get("item_timing_category") or "").strip()
    if category:
        return True

    text = _state_text(state)
    items = state.get("items") if isinstance(state.get("items"), list) else []
    if (
        "item_timing" in text or "timing" in text or "power_spike" in text
    ) and contains_meaningful_item_reference(
        text,
        items,
    ):
        return True
    return any(keyword in text for keyword in ITEM_TIMING_KEYWORDS)


def has_safe_farming_signal(state: Mapping[str, Any]) -> bool:
    text = _state_text(state)
    return any(keyword in text for keyword in SAFE_FARMING_KEYWORDS)


def has_low_farm_pressure_signal(state: Mapping[str, Any]) -> bool:
    farm_rate_state = (
        str(_ctx_value(state, "farm_rate_state", state.get("farm_rate_state", ""))).strip().lower()
    )
    gold_delta = _ctx_int(state, "gold_delta", default=0)
    lh_delta = _ctx_int(state, "lh_delta", default=0)
    low_farm = (
        farm_rate_state == "slow"
        or _is_low_farm_rate(state)
        or (gold_delta > 0 and gold_delta < 220 and lh_delta <= 1)
    )
    pressure_nearby = (
        _to_bool(state.get("near_player_death"))
        or _to_bool(state.get("near_teamfight"))
        or _to_bool(state.get("near_objective"))
        or has_pressure_signal(state)
    )
    return low_farm and pressure_nearby


def has_disabled_status(state: Mapping[str, Any]) -> bool:
    """A status that may be an enemy disable. A stun/hex/silence/mute the live
    tracker classified as the player's own phase (Manta, Doppelganger,
    Omnislash...) or as unexplained (no debuff, no HP lost) is not one
    (status_source.py); a disarm or break has no own-phase source and stays."""
    if any(_ctx_bool(state, field) for field in ("disarmed", "break_status")):
        return True
    if not any(_ctx_bool(state, field) for field in ("stunned", "silenced", "hexed", "muted")):
        return False
    source = _extra_context(state).get("status_source")
    return source is None or is_threat(source)


def has_fight_pressure(state: Mapping[str, Any]) -> bool:
    # Not `score_changed`: in live GSI that is the team score, so any kill anywhere
    # on the map. It counts only together with a sign of a fight near the player.
    return (
        _to_bool(state.get("near_player_death"))
        or _to_bool(state.get("near_teamfight"))
        or _to_bool(state.get("near_objective"))
        or _ctx_bool(state, "death_count_changed")
        or has_pressure_signal(state)
        or has_bad_fight_risk_signal(state)
        or has_objective_fight_signal(state)
    )


def hero_safety_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra_context = _extra_context(state)
    if "hero_risk_level" in extra_context:
        return extra_context
    return evaluate_hero_safety(state)


def has_hero_survivability_risk(
    state: Mapping[str, Any], *, hp_percent: int, mana_percent: int
) -> bool:
    safety_context = hero_safety_context(state)
    risk = str(safety_context.get("hero_risk_level") or "low").strip().lower()
    if risk not in {"medium", "high"}:
        return False

    contextual_risk = (
        hp_percent <= 60
        or mana_percent <= 35
        or has_fight_pressure(state)
        or has_pressure_signal(state)
        or has_bad_fight_risk_signal(state)
        or has_objective_fight_signal(state)
    )
    # An escape on cooldown alone is not a reason to talk: blink heroes use it
    # all game, and «wait for Blink» at full HP came eight times a match.
    escape_only = str(safety_context.get("hero_safety_kind") or "") == "escape"
    return (risk == "high" and not escape_only) or contextual_risk


def is_laning_or_early_game(minute: int) -> bool:
    return minute < 12


def has_low_hp_warning(
    *,
    hp_percent: int,
    minute: int,
    warning_threshold: int,
    critical_threshold: int,
) -> bool:
    return is_laning_or_early_game(minute) and critical_threshold < hp_percent <= warning_threshold


def has_ability_safety_cooldown(
    laning_context: Mapping[str, Any],
    *,
    hp_percent: int,
    fight_pressure: bool,
    readiness_moment: bool = False,
) -> bool:
    """The key escape is on cooldown and it matters: HP is down, a fight is
    around, or the next step after a won fight or a revive is being chosen."""
    if laning_context.get("key_safety_available") is not False:
        return False
    return hp_percent <= 70 or fight_pressure or readiness_moment


def has_laning_farm_check(laning_context: Mapping[str, Any], *, minute: int) -> bool:
    return is_laning_or_early_game(minute) and laning_context.get("farm_status") == "behind"


def _is_low_farm_rate(state: Mapping[str, Any]) -> bool:
    if _ctx_bool(state, "demo_values_detected"):
        return False

    minute = _to_int(state.get("minute"), default=0)
    last_hits = _ctx_value(state, "last_hits")
    gpm = _ctx_value(state, "gpm")

    try:
        last_hits_number = int(last_hits)
    except (TypeError, ValueError):
        last_hits_number = None
    try:
        gpm_number = int(gpm)
    except (TypeError, ValueError):
        gpm_number = None

    if gpm_number is not None and gpm_number > 2000:
        return False

    # A carry's thresholds, scaled by the hero's position (an offlaner: 70 %).
    pace = farm_pace(str(state.get("hero") or ""))
    thresholds = ((25, 170), (20, 120), (15, 80), (10, 45))
    if any(
        minute >= threshold_minute
        and last_hits_number is not None
        and last_hits_number < round(threshold_lh * pace)
        for threshold_minute, threshold_lh in thresholds
    ):
        return True
    return minute >= 15 and gpm_number is not None and gpm_number < round(400 * pace)


def detect_decision_point(state: Mapping[str, Any] | None) -> DecisionPoint:
    if not state:
        return "NO_ADVICE"

    hp_percent = _to_int(state.get("hp_percent"), default=100)
    minute = _to_int(state.get("minute"), default=0)
    text = _state_text(state)
    alive = _ctx_value(state, "alive", True)
    alive_bool = True if alive is None else _to_bool(alive)
    mana_percent = _ctx_int(state, "mana_percent", default=100)
    respawn_seconds = _ctx_int(state, "respawn_seconds", default=0)
    buyback_cost = _ctx_int(state, "buyback_cost", default=0)
    buyback_cooldown = _ctx_int(state, "buyback_cooldown", default=9999)
    available_gold = _ctx_int(
        state,
        "available_gold",
        default=_ctx_int(state, "gold_reliable", default=0)
        + _ctx_int(state, "gold_unreliable", default=0),
    )
    near_player_death = _to_bool(state.get("near_player_death"))
    near_objective = _to_bool(state.get("near_objective"))
    near_teamfight = _to_bool(state.get("near_teamfight"))
    team_status = str(state.get("team_status") or "unknown").strip().lower()
    teamfight_result = str(state.get("teamfight_result") or "unknown").strip().lower()
    objective_for_selected_team = state.get("objective_for_selected_team")
    recent_item_purchase = str(state.get("recent_item_purchase") or "").strip()
    laning_context = evaluate_laning_context(state)
    critical_hp_threshold = _to_int(laning_context.get("critical_hp_threshold"), default=35)
    low_hp_warning_threshold = _to_int(laning_context.get("low_hp_warning_threshold"), default=50)

    if any(keyword in text for keyword in NO_ADVICE_KEYWORDS):
        return "NO_ADVICE"

    if _ctx_bool(state, "paused"):
        return "NO_ADVICE"

    if not alive_bool and _ctx_value(state, "life_state") == "reviving":
        # The life went with no death counted (Aegis, Reincarnation): the hero
        # is coming back on the spot. No death review, no buyback; the card of
        # the life just lost is withdrawn by the scheduler.
        return "NO_ADVICE"

    if not alive_bool or respawn_seconds > 0:
        if _has_conservative_buyback_context(
            state,
            minute=minute,
            respawn_seconds=respawn_seconds,
            buyback_cost=buyback_cost,
            buyback_cooldown=buyback_cooldown,
            available_gold=available_gold,
            near_objective=near_objective,
            team_status=team_status,
            objective_for_selected_team=objective_for_selected_team,
        ):
            return "BUYBACK_AVAILABLE"
        extra_context = _extra_context(state)
        replay_death_decision = str(extra_context.get("death_review_decision") or "")
        if replay_death_decision in DEATH_DECISION_POINTS:
            return cast(DecisionPoint, replay_death_decision)
        state_session = extra_context.get("match_session_id")
        death_decision = MATCH_MEMORY.death_review_for_state(
            state_session, available=bool(extra_context.get("death_review_available"))
        )
        if death_decision in DEATH_DECISION_POINTS:
            return cast(DecisionPoint, death_decision)
        return "DEATH_REVIEW"

    # Priority order keeps urgent survival and death review first, then profile-
    # driven lane checks, fight/objective context, farm state, status heartbeat.
    if hp_percent <= critical_hp_threshold:
        return "LOW_HP"

    disabled = has_disabled_status(state)
    fight_pressure = has_fight_pressure(state)
    low_mana = mana_percent <= 20

    if disabled:
        return "DISABLED_STATUS"

    if _ctx_int(state, "hp_falling_fast", default=0) > 0:
        # Most of the HP gone in seconds: leave before it is critical.
        return "LOW_HP"

    if has_hero_survivability_risk(state, hp_percent=hp_percent, mana_percent=mana_percent):
        return "HERO_SURVIVABILITY_RISK"

    if has_ability_safety_cooldown(
        laning_context,
        hp_percent=hp_percent,
        fight_pressure=fight_pressure,
        readiness_moment=_ctx_value(state, "recent_revive") is not None,
    ):
        return "ABILITY_SAFETY_COOLDOWN"

    if (
        low_mana or _ctx_bool(state, "death_count_changed") or _ctx_bool(state, "score_changed")
    ) and fight_pressure:
        return "BAD_FIGHT_RISK"

    if team_status == "disadvantage" and near_teamfight:
        return "BAD_FIGHT_RISK"

    if objective_for_selected_team is False and team_status == "disadvantage":
        return "BAD_FIGHT_RISK"

    if near_player_death or teamfight_result == "bad":
        return "BAD_FIGHT_RISK"

    if team_status == "advantage" and near_objective:
        return "OBJECTIVE_FIGHT_CHECK"

    if objective_for_selected_team is True and team_status != "disadvantage":
        return "OBJECTIVE_FIGHT_CHECK"

    if near_teamfight or has_bad_fight_risk_signal(state):
        return "BAD_FIGHT_RISK"

    if _ctx_bool(state, "overstay_warning"):
        return "OVERSTAY_WARNING"

    if _ctx_bool(state, "recent_damage_taken") and hp_percent <= 65:
        return "RECENT_DAMAGE_WARNING"

    if has_low_hp_warning(
        hp_percent=hp_percent,
        minute=minute,
        warning_threshold=low_hp_warning_threshold,
        critical_threshold=critical_hp_threshold,
    ):
        return "LOW_HP_WARNING"

    if near_objective or has_objective_fight_signal(state):
        return "OBJECTIVE_FIGHT_CHECK"

    if recent_item_purchase and is_meaningful_item_timing(recent_item_purchase):
        return "ITEM_TIMING"

    if has_item_timing_signal(state):
        return "ITEM_TIMING"

    if low_mana:
        return "LOW_MANA"

    # A lane farm problem comes first: preparation tips can wait for calm farm.
    if has_laning_farm_check(laning_context, minute=minute):
        return "LANING_FARM_CHECK"

    if selected_rule(state) is not None:
        return "HERO_GAMEPLAY"

    if _ctx_bool(state, "smoked"):
        return "SMOKED_STATUS"

    if _is_low_farm_rate(state):
        return "FARMING_PHASE_PRESSURE"

    if has_low_farm_pressure_signal(state):
        return "FARMING_PHASE_PRESSURE"

    if minute < 18 and has_pressure_signal(state):
        return "FARMING_PHASE_PRESSURE"

    if is_laning_or_early_game(minute):
        return "SOFT_STATUS"

    if has_safe_farming_signal(state) or minute >= 0:
        return "SAFE_FARMING"

    return "NO_ADVICE"


def _has_conservative_buyback_context(
    state: Mapping[str, Any],
    *,
    minute: int,
    respawn_seconds: int,
    buyback_cost: int,
    buyback_cooldown: int,
    available_gold: int,
    near_objective: bool,
    team_status: str,
    objective_for_selected_team: Any,
) -> bool:
    buyback_available = _ctx_bool(state, "buyback_available") or (
        buyback_cost > 0 and buyback_cooldown == 0 and available_gold >= buyback_cost
    )
    if not buyback_available:
        return False

    text = _state_text(state)
    critical_context = any(
        keyword in text
        for keyword in (
            "highground",
            "base",
            "ancient",
            "barracks",
            "throne",
            "roshan",
            "objective",
            "defense",
        )
    )
    if minute >= 35 and (respawn_seconds >= 35 or critical_context):
        return True
    if critical_context and respawn_seconds >= 45:
        return True
    if near_objective and team_status == "disadvantage":
        return True
    return objective_for_selected_team is False and (near_objective or critical_context)
