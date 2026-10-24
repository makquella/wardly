"""
scheduler.text - stateless recommendation-text normalization helpers.

Pure functions, no scheduler state, no ``self``. Extracted verbatim from
advice_scheduler.py as part of the Phase 2 split (no behavior change).

The MAX_ACTION_LENGTH / MAX_REASON_LENGTH constants live here because they
are coupled to truncation; advice_scheduler.py imports them back so that
_is_safe_recommendation (still local there until step 5) keeps compiling.
"""

from __future__ import annotations

from app.advice_text import clean_recommendation_text
from app.schemas import RecommendationResponse

MAX_ACTION_LENGTH = 100
MAX_REASON_LENGTH = 180


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _naturalize_action(action: str, decision_point: str | None = None) -> str:
    replacements = {
        "keep_farming": "Keep farming safely and reassess in 60 seconds.",
        "switch_to_safe_farm": "Avoid contesting pressure and move to safer farm.",
        "play_back_and_regen": "Use regen or play back until your HP is safer.",
        "stabilize_after_recent_damage": "Back up and stabilize before trading again.",
        "stop_overstay_low_hp": "Do not overstay on low HP; reset or play behind creeps.",
        "stabilize_lane_farm": "Focus on safe last hits before forcing trades.",
        "respect_defensive_ability_cooldown": "Avoid risky trades until your defensive tool is ready.",
        "retreat_reset": "Retreat and reset before rejoining.",
        "avoid_bad_fight": "Avoid this fight and reset to safer farm.",
        "join_only_if_objective_value": "Consider joining only if your team is ready and the fight is near the objective.",
        "play_around_timing": "You reached a timing; reassess whether to pressure or keep farming safely.",
        "conserve_mana_or_reset": "Conserve mana or reset before taking a fight.",
        "wait_out_disable": "Wait out the disable and avoid forcing actions.",
        "check_buyback_value": "Check buyback value only for base defense or a major objective.",
        "prepare_next_move": "Use the respawn time to plan your next safe farming route.",
        "stay_hidden_until_team_ready": "Stay hidden until your team is ready to make a move.",
        "respect_hero_safety_window": "Respect your hero's safety window before forcing a fight.",
        "plan_safer_respawn_route": "Use the respawn time to plan a safer next route.",
        "break_repeated_death_pattern": "After respawn, reset your route and avoid repeating the same risky path.",
        "respect_escape_cooldown_after_respawn": "After respawn, avoid committing forward until your escape is ready.",
        "reset_before_resources_collapse": "After respawn, reset earlier when HP or key resources get low.",
        "soft_status": "Monitoring lane - no urgent advice.",
    }
    key = action.strip().lower()
    canonical_key = key.replace(" ", "_").replace("-", "_")
    if canonical_key in replacements:
        return replacements[canonical_key]
    if "_" in key and len(action.strip().split()) == 1:
        return key.replace("_", " ").capitalize() + "."
    return clean_recommendation_text(
        RecommendationResponse(
            action=action,
            reason="ok",
            risk="ok",
            priority="low",
            time_window="reassess in 60 seconds",
        ),
        decision_point,
    ).action


def _compact_recommendation(
    recommendation: RecommendationResponse,
    decision_point: str | None = None,
) -> RecommendationResponse:
    recommendation = clean_recommendation_text(recommendation, decision_point)
    return RecommendationResponse(
        action=_truncate(
            _naturalize_action(recommendation.action, decision_point), MAX_ACTION_LENGTH
        ),
        reason=_truncate(recommendation.reason, MAX_REASON_LENGTH),
        risk=recommendation.risk,
        priority=recommendation.priority,
        time_window=recommendation.time_window,
        source=recommendation.source,
        tool=recommendation.tool,
    )
