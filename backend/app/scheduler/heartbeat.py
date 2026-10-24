"""
scheduler.heartbeat - stateless heartbeat-nudge helpers.

Pure functions, no scheduler state, no ``self``. Extracted verbatim from
advice_scheduler.py as part of the Phase 2 split (no behavior change).
"""

from __future__ import annotations

from typing import Any

from app.scheduler.safety_predicates import _hp_pressure_state
from app.scheduler.state_utils import _ctx_int, _ctx_value, _is_dead_or_respawning, _to_int
from app.schemas import RecommendationResponse
from app.team_context import nearby_allies


def _extra(state: dict[str, Any]) -> dict[str, Any]:
    extra = state.get("extra_context")
    return extra if isinstance(extra, dict) else {}


def _low_hp_pattern_recommendation() -> RecommendationResponse:
    return RecommendationResponse(
        action="Stop re-contesting the pressured lane until you reset HP.",
        reason="Repeated low-HP returns can cost more than missing one wave.",
        risk="High risk if you keep returning to pressure without resetting.",
        priority="high",
        time_window="next 60-90 seconds",
        source="fallback",
    )


def _heartbeat_context_is_confident(state: dict[str, Any]) -> bool:
    confidence = str(_ctx_value(state, "context_confidence", "high") or "high").strip().lower()
    return confidence in {"high", "medium"}


def _heartbeat_safe_category_available(state: dict[str, Any]) -> bool:
    if _ctx_int(state, "hp_percent", _to_int(state.get("hp_percent"), 100)) < 35:
        return False
    if _hp_pressure_state(state) == "critical":
        return False
    if _is_dead_or_respawning(state):
        return False
    return True


def _heartbeat_copy(state: dict[str, Any]) -> tuple[str, str, str]:
    hp_percent = _ctx_int(state, "hp_percent", _to_int(state.get("hp_percent"), 100))
    mana_percent = _ctx_int(state, "mana_percent", 100)
    hp_pressure = _hp_pressure_state(state)
    position_risk = str(_ctx_value(state, "position_risk", "") or "").strip().lower()
    position_zone = str(_ctx_value(state, "position_zone", "") or "").strip().lower()
    pressure_active = hp_pressure in {"pressured_but_stable", "risky"}
    pressure_active = pressure_active or any(
        token in str(state.get("game_state") or "").lower()
        for token in ("pressure", "risk", "damage")
    )

    if hp_percent <= 55 or mana_percent <= 25:
        return (
            "Reset resources before showing on another lane.",
            "A short reset keeps the next farming route safer without forcing a fight.",
            "Medium risk if you keep showing while resources are low.",
        )
    if (position_risk == "high" or position_zone == "deep_enemy_side") and not nearby_allies(
        _extra(state)
    ):
        return (
            "Farm closer to a safer zone until enemy positions are clearer.",
            "Enemy locations are not confirmed, so exposed farming is unnecessary risk.",
            "Medium risk if you stay visible in an exposed area.",
        )
    if pressure_active:
        return (
            "Avoid the pressured lane and farm a safer wave or nearby camp.",
            "Staying in pressure can cost HP and slow your recovery.",
            "Medium risk if you keep farming the pressured area.",
        )
    # Nothing pressing: say what this game looks like (a kill streak, the kill
    # score, the pace) instead of the same line every minute.
    from app.post_laning_coach import _situational_farm_copy  # avoid an import cycle

    raw_extra = state.get("extra_context")
    situational = _situational_farm_copy(state, raw_extra if isinstance(raw_extra, dict) else {})
    if situational is not None:
        return (*situational, "Low risk if you keep farming without forcing uncertain fights.")
    return (
        "Keep farming the safest wave-and-camp route and reassess soon.",
        "Your farm route is the safest low-risk choice while enemy locations are uncertain.",
        "Low risk if you keep farming without forcing uncertain fights.",
    )


def _is_heartbeat_recommendation(recommendation: RecommendationResponse) -> bool:
    return (
        recommendation.priority == "low"
        and recommendation.time_window == "reassess in 60-90 seconds"
    )
