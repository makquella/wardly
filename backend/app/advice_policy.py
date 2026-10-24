"""
advice_policy.py - universal carry advice policy for safe MVP recommendations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.hero_profiles import get_hero_archetype
from app.schemas import RecommendationResponse


def build_advice_policy(game_state: Mapping[str, Any] | Any, decision_point: str) -> dict[str, Any]:
    state = _as_mapping(game_state)
    phase = _detect_game_phase(_to_int(state.get("minute"), 0))
    archetype = _detect_hero_archetype(str(state.get("hero", "")))
    base_goal = _overlay_goal(phase, archetype)

    if decision_point == "HERO_GAMEPLAY":
        return {
            "action_type": "prepare_hero_action",
            "priority": "low",
            "time_window": "before your next planned action",
            "safety_constraints": [
                "preparation only, never a guaranteed escape or target command",
                "unknown targets, controlled units and enemy readiness stay unknown",
            ],
            "overlay_goal": "Prepare the hero's next action using observed own resources.",
        }

    if decision_point == "LOW_HP":
        return {
            "action_type": "retreat_reset",
            "priority": "high",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": ["never suggest fighting", "survive before farming or joining"],
            "overlay_goal": f"{base_goal} Stay alive first.",
        }

    if decision_point == "FARMING_PHASE_PRESSURE":
        return {
            "action_type": "switch_to_safe_farm",
            "priority": "high",
            "time_window": "next 60-90 seconds",
            "safety_constraints": ["avoid low-value fights", "farm away from visible pressure"],
            "overlay_goal": f"{base_goal} Protect farm under pressure.",
        }

    if decision_point in {"LOW_HP_WARNING", "LANING_REGEN_CHECK"}:
        return {
            "action_type": "play_back_and_regen",
            "priority": "medium",
            "time_window": "next 30-60 seconds",
            "safety_constraints": [
                "avoid low-value trades while HP is low",
                "regen or play back before contesting",
            ],
            "overlay_goal": f"{base_goal} Stabilize lane HP before trading.",
        }

    if decision_point == "RECENT_DAMAGE_WARNING":
        return {
            "action_type": "stabilize_after_recent_damage",
            "priority": "medium",
            "time_window": "next 10-30 seconds",
            "safety_constraints": [
                "back up after heavy damage",
                "avoid another trade until stabilized",
            ],
            "overlay_goal": f"{base_goal} Stabilize after recent damage.",
        }

    if decision_point == "OVERSTAY_WARNING":
        return {
            "action_type": "stop_overstay_low_hp",
            "priority": "high",
            "time_window": "next 10-30 seconds",
            "safety_constraints": ["do not stay exposed on low HP", "reset or play behind creeps"],
            "overlay_goal": f"{base_goal} Prevent an overstay death.",
        }

    if decision_point == "LANING_FARM_CHECK":
        return {
            "action_type": "stabilize_lane_farm",
            "priority": "medium",
            "time_window": "next 60 seconds",
            "safety_constraints": [
                "do not force trades to recover farm",
                "take safe last hits first",
            ],
            "overlay_goal": f"{base_goal} Recover lane farm without taking bad damage.",
        }

    if decision_point == "ABILITY_SAFETY_COOLDOWN":
        hp_percent = _to_int(state.get("hp_percent"), 100)
        return {
            "action_type": "respect_defensive_ability_cooldown",
            "priority": "high" if hp_percent <= 45 else "medium",
            "time_window": "next 10-30 seconds",
            "safety_constraints": [
                "avoid risky trades until the safety tool is ready",
                "do not fight into slows or disables",
            ],
            "overlay_goal": f"{base_goal} Wait for the safety spell before trading.",
        }

    if decision_point == "LOW_MANA":
        return {
            "action_type": "conserve_mana_or_reset",
            "priority": "medium",
            "time_window": "next 60-90 seconds",
            "safety_constraints": ["avoid forcing fights without mana", "reset before committing"],
            "overlay_goal": f"{base_goal} Preserve resources before fighting.",
        }

    if decision_point == "DISABLED_STATUS":
        hp_percent = _to_int(state.get("hp_percent"), 100)
        return {
            "action_type": "wait_out_disable",
            "priority": "high" if hp_percent <= 60 else "medium",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": [
                "do not force actions while disabled",
                "survive the control duration",
            ],
            "overlay_goal": f"{base_goal} Stay safe while controlled.",
        }

    if decision_point == "BUYBACK_AVAILABLE":
        return {
            "action_type": "check_buyback_value",
            "priority": "high" if phase == "late_game" else "medium",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": [
                "buyback only for base defense or major objective",
                "avoid low-value buybacks",
            ],
            "overlay_goal": f"{base_goal} Evaluate buyback value conservatively.",
        }

    if decision_point == "REPEATED_DEATH_PATTERN":
        return {
            "action_type": "break_repeated_death_pattern",
            "priority": "high",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": [
                "do not repeat the same risky route",
                "prioritize survival after respawn",
            ],
            "overlay_goal": f"{base_goal} Break the repeated death pattern.",
        }

    if decision_point == "DEATH_WITH_ESCAPE_ON_COOLDOWN":
        return {
            "action_type": "respect_escape_cooldown_after_respawn",
            "priority": "high",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": [
                "wait for escape or defensive tools before committing",
                "avoid forward moves after respawn",
            ],
            "overlay_goal": f"{base_goal} Respect escape cooldowns after respawn.",
        }

    if decision_point == "DEATH_LOW_RESOURCE":
        hero_risk_level = str(_extra_context(state).get("hero_risk_level") or "").strip().lower()
        return {
            "action_type": "reset_before_resources_collapse",
            "priority": "high" if hero_risk_level == "high" else "medium",
            "time_window": "immediate: next 10-15 seconds",
            "safety_constraints": [
                "reset earlier when HP or key resources are low",
                "avoid extending low-resource fights",
            ],
            "overlay_goal": f"{base_goal} Reset before survivability resources collapse.",
        }

    if decision_point == "DEATH_REVIEW":
        return {
            "action_type": "plan_safer_respawn_route",
            "priority": "medium",
            "time_window": "reassess in 60 seconds",
            "safety_constraints": [
                "avoid returning to the same risky area",
                "plan around vision and team support",
            ],
            "overlay_goal": f"{base_goal} Use respawn time to plan a safer route.",
        }

    if decision_point == "DEAD_WAIT":
        return {
            "action_type": "prepare_next_move",
            "priority": "low",
            "time_window": "reassess in 60 seconds",
            "safety_constraints": [
                "avoid rushing back to the same risky area",
                "plan the next safe route",
            ],
            "overlay_goal": f"{base_goal} Plan the next safe movement.",
        }

    if decision_point == "SMOKED_STATUS":
        return {
            "action_type": "stay_hidden_until_team_ready",
            "priority": "medium",
            "time_window": "next 60-90 seconds",
            "safety_constraints": [
                "do not reveal on waves early",
                "avoid forcing aggression alone",
            ],
            "overlay_goal": f"{base_goal} Preserve smoke value without forcing.",
        }

    if decision_point == "HERO_SURVIVABILITY_RISK":
        hero_risk_level = (
            str(_extra_context(state).get("hero_risk_level") or "medium").strip().lower()
        )
        high_risk = hero_risk_level == "high"
        return {
            "action_type": "respect_hero_safety_window",
            "priority": "high" if high_risk else "medium",
            "time_window": "immediate: next 10-15 seconds" if high_risk else "next 60-90 seconds",
            "safety_constraints": [
                "do not force fights when key defensive or escape resource is unavailable",
                "respect hero-specific survival limits",
            ],
            "overlay_goal": f"{base_goal} Respect the current hero safety window.",
        }

    if decision_point == "OBJECTIVE_FIGHT_CHECK":
        return {
            "action_type": "join_only_if_objective_value",
            "priority": "medium",
            "time_window": "next 60-90 seconds",
            "safety_constraints": [
                "do not force fight without objective",
                "avoid random skirmishes",
            ],
            "overlay_goal": f"{base_goal} Fight only for clear objective value.",
        }

    if decision_point == "BAD_FIGHT_RISK":
        return {
            "action_type": "avoid_bad_fight",
            "priority": "high",
            "time_window": "next 60-90 seconds",
            "safety_constraints": [
                "avoid fighting without team/objective",
                "prefer farming or resetting",
            ],
            "overlay_goal": f"{base_goal} Skip low-value fights.",
        }

    if decision_point == "ITEM_TIMING":
        return {
            "action_type": "play_around_timing",
            "priority": "medium",
            "time_window": "next 60-90 seconds",
            "safety_constraints": [
                "do not force fights only because a timing is near",
                "keep map risk low",
            ],
            "overlay_goal": f"{base_goal} Convert current strength without forcing.",
        }

    if decision_point == "SAFE_FARMING":
        return {
            "action_type": "keep_farming",
            "priority": "low",
            "time_window": "reassess in 60 seconds",
            "safety_constraints": ["avoid unnecessary risk", "keep farming safely"],
            "overlay_goal": f"{base_goal} Build resources and reassess soon.",
        }

    if decision_point == "SOFT_STATUS":
        return {
            "action_type": "soft_status",
            "priority": "low",
            "time_window": "reassess in 60 seconds",
            "safety_constraints": ["do not call LLM", "status only"],
            "overlay_goal": f"{base_goal} Monitoring lane with no urgent advice.",
        }

    return {
        "action_type": "no_advice",
        "priority": "low",
        "time_window": "reassess in 60 seconds",
        "safety_constraints": ["do not call LLM", "avoid noisy advice"],
        "overlay_goal": f"{base_goal} No urgent carry decision.",
    }


def apply_advice_policy(
    recommendation: RecommendationResponse,
    policy: Mapping[str, Any],
) -> RecommendationResponse:
    return RecommendationResponse(
        action=recommendation.action,
        reason=recommendation.reason,
        risk=recommendation.risk,
        priority=policy["priority"],
        time_window=policy["time_window"],
        source=recommendation.source,
        tool=recommendation.tool,
    )


def _detect_game_phase(minute: int) -> str:
    if minute < 10:
        return "laning"
    if minute < 20:
        return "early_mid"
    if minute < 35:
        return "mid_game"
    return "late_game"


def _detect_hero_archetype(hero: str) -> str:
    return get_hero_archetype(hero)


def _overlay_goal(phase: str, archetype: str) -> str:
    if phase == "laning":
        return f"{archetype}: protect lane resources and avoid deaths."
    if phase == "early_mid":
        return f"{archetype}: grow safely while pressure moves around the map."
    if phase == "mid_game":
        return f"{archetype}: balance farming with objective-value fights."
    return f"{archetype}: preserve buyback-style discipline and fight for objectives."


def _as_mapping(game_state: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(game_state, Mapping):
        return game_state
    if hasattr(game_state, "model_dump"):
        return game_state.model_dump()
    return {}


def _extra_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra_context = state.get("extra_context")
    return extra_context if isinstance(extra_context, Mapping) else {}


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
