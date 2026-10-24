"""
advice_text.py - small wording cleanup for visible recommendation text.
"""

from __future__ import annotations

import re

from app.live_tools import INSURANCE_COPY
from app.schemas import RecommendationResponse

ACTION_REPLACEMENTS = {
    "consider farm jungle camps": "Avoid this fight and move to safer farm.",
    "consider farm safely": "Avoid the fight and keep farming safely.",
    "consider farm last hits": "Focus on safe last hits.",
    "consider farm safely in lane": "Keep farming safely in lane.",
    "consider farm safely in lane focus last hits": "Keep farming safely in lane and focus on last hits.",
    "consider farm safely until next wave": "Keep farming safely until the next wave.",
    "consider farm the safer part of the lane and avoid long trades": "Farm the safer part of the lane and avoid long trades.",
    "consider farm the safest wave and camp route and reassess soon": "Keep farming the safest wave-and-camp route and reassess soon.",
    "consider farm the safest wave-and-camp route and reassess soon": "Keep farming the safest wave-and-camp route and reassess soon.",
    "focus last hitting on the next wave": "Focus on safe last hits in the next wave.",
    "focus safe last hits on the lane jungle camps": "Focus on safe last hits before moving to nearby camps.",
    "focus safe last hits on lane jungle camps": "Focus on safe last hits before moving to nearby camps.",
    "focus on safe last hits on the lane jungle camps": "Focus on safe last hits before moving to nearby camps.",
    "maintain lane gold": "Maintain steady farm.",
    "consider join objective fight": "Consider joining only if the fight is near the objective.",
    "consider join the objective fight": "Consider joining only if your team is ready around the objective.",
    "prioritize keep_farming": "Keep farming safely.",
    "prioritize keep farming": "Keep farming safely.",
    "prioritize keep farming efficiently and reassess in 60 seconds.": "Keep farming safely and reassess in 60 seconds.",
    "play around timing": "You reached a timing; reassess whether to pressure or keep farming safely.",
    "consider play around timing": "You reached a timing; reassess whether to pressure or keep farming safely.",
    "keep_farming": "Keep farming safely and reassess in 60 seconds.",
    "switch_to_safe_farm": "Avoid contesting pressure and move to safer farm.",
    "play_back_and_regen": "Use regen or play back until your HP is safer.",
    "stabilize_after_recent_damage": "Back up and stabilize before trading again.",
    "stop_overstay_low_hp": "Do not overstay on low HP; reset or play behind creeps.",
    "stabilize_lane_farm": "Focus on safe last hits before forcing trades.",
    "respect_defensive_ability_cooldown": "Avoid risky trades until your defensive tool is ready.",
    "retreat_reset": "Leave the wave now and reset HP before rejoining.",
    "avoid_bad_fight": "Avoid this fight and reset to safer farm.",
    "join_only_if_objective_value": "Consider joining only if your team is ready and the fight is near the objective.",
    "play_around_timing": "You reached a timing; reassess whether to pressure or keep farming safely.",
    "conserve_mana_or_reset": "Conserve mana or reset before taking a fight.",
    "wait_out_disable": "Wait out the disable and avoid forcing actions.",
    "check_buyback_value": "Buyback is available. Only consider it for critical defense.",
    "prepare_next_move": "Use the respawn time to plan your next safe farming route.",
    "stay_hidden_until_team_ready": "Stay hidden until your team is ready to make a move.",
    "respect_hero_safety_window": "Respect your hero's safety window before forcing a fight.",
    "soft_status": "Monitoring lane - no urgent advice.",
    "plan_safer_respawn_route": "Use the respawn time to plan a safer next route.",
    "break_repeated_death_pattern": "After respawn, reset your route and avoid repeating the same risky path.",
    "respect_escape_cooldown_after_respawn": "After respawn, avoid committing forward until your escape is ready.",
    "reset_before_resources_collapse": "After respawn, reset earlier when HP or key resources get low.",
}

VISIBLE_PHRASE_REPLACEMENTS = {
    "keep_farming": "keep farming",
    "switch_to_safe_farm": "move to safer farm",
    "play_back_and_regen": "play back and regen",
    "stabilize_after_recent_damage": "stabilize after recent damage",
    "stop_overstay_low_hp": "stop overstaying on low HP",
    "stabilize_lane_farm": "stabilize lane farm",
    "respect_defensive_ability_cooldown": "respect defensive ability cooldown",
    "avoid_bad_fight": "avoid this fight",
    "join_only_if_objective_value": "join only for objective value",
    "play_around_timing": "play around this timing",
    "conserve_mana_or_reset": "conserve mana or reset",
    "wait_out_disable": "wait out the disable",
    "check_buyback_value": "check buyback value",
    "prepare_next_move": "prepare your next move",
    "stay_hidden_until_team_ready": "stay hidden until your team is ready",
    "respect_hero_safety_window": "respect your hero safety window",
    "soft_status": "monitoring lane",
    "plan_safer_respawn_route": "plan a safer respawn route",
    "break_repeated_death_pattern": "break the repeated death pattern",
    "respect_escape_cooldown_after_respawn": "respect escape cooldown after respawn",
    "reset_before_resources_collapse": "reset before resources collapse",
    "Maintain lane gold": "Maintain steady farm",
    "maintain lane gold": "maintain steady farm",
}

OBJECTIVE_OVERCONFIDENCE = (
    "safe to join",
    "objective value clear",
    "clear objective nearby",
    "offers clear value",
    "clear value",
    "joining maximizes",
    "maximizes pressure",
    "safe to fight",
)


def clean_recommendation_text(
    recommendation: RecommendationResponse,
    decision_point: str | None = None,
) -> RecommendationResponse:
    action = clean_action_text(recommendation.action, decision_point)
    reason = clean_reason_text(recommendation.reason, decision_point)
    risk = clean_risk_text(recommendation.risk, decision_point)
    return RecommendationResponse(
        action=action,
        reason=reason,
        risk=risk,
        priority=recommendation.priority,
        time_window=recommendation.time_window,
        source=recommendation.source,
    )


# live_tools.low_hp_copy actions ("Use Magic Wand now, then step back."); under
# a stun or hex, the tool to press once it ends (live_tools.disabled_copy).
LOW_HP_TOOL_PREFIXES = (
    "use ",
    "step out of enemy range and use ",
    "the moment the disable ends use ",
)
# The rule texts a LOW_HP reason may keep (live_tools.py: the tool that is ready,
# HP falling fast, the repeat count); anything else becomes the standard line.
LOW_HP_REASON_PATTERNS = (
    re.compile(r"^You lost \d+% HP in 5 seconds and it is still dropping\.$"),
    re.compile(r"^A death now revives you on the spot; "),
    re.compile(r"^Your HP has dropped this low \d+ times this game: "),
    re.compile(r"^Your HP is low and [^:]+ is ready: use it before the next hit"),
    re.compile(r"^[^:]+ is ready: it buys you the seconds to get away\.$"),
    re.compile(r"^[^:]+ is ready: the second after a disable is when most kills finish\.$"),
    re.compile(r"^Magic Wand (?:has \d+ charges|is charged): that HP is yours right now\.$"),
    re.compile(r"^[^:]+ (?:is ready and heals you at once|heals you at once)\.$"),
    re.compile(r"^[^:]+ heals over time: use it where enemies cannot hit you\.$"),
    re.compile(r"^The [A-Za-z ]+ rune in your Bottle (?:is ready: |heals you at once\.$)"),
    re.compile(r"^The Regeneration rune heals fast but stops at the first hit: "),
)
# Critical HP with an Aegis, a revive or a hero save ready (live_tools.insurance_copy).
LOW_HP_INSURANCE_ACTIONS = frozenset(action for action, _ in INSURANCE_COPY.values())
LOW_HP_INSURANCE_REASONS = frozenset(reason for _, reason in INSURANCE_COPY.values())


def clean_action_text(action: str, decision_point: str | None = None) -> str:
    text = clean_visible_text(action.strip())
    key = _canonical(text)

    if decision_point == "FARMING_PHASE_PRESSURE" and key.startswith(
        "consider farm the safer part of the lane and avoid long trades"
    ):
        return "Farm the safer part of the lane and avoid long trades."

    if decision_point == "FARMING_PHASE_PRESSURE" and key.startswith(
        "take safe creeps then rotate to safer farm if pressure continues"
    ):
        return "Take safe creeps, then rotate to safer farm if pressure continues."
    if decision_point == "FARMING_PHASE_PRESSURE" and key.startswith(
        "consider take safe creeps then rotate to safer farm if pressure continues"
    ):
        return "Take safe creeps, then rotate to safer farm if pressure continues."
    if decision_point == "FARMING_PHASE_PRESSURE" and key.startswith(
        "avoid the pressured lane and farm a safer wave or nearby camp"
    ):
        return "Avoid the pressured lane and farm a safer wave or nearby camp."

    if decision_point == "FARMING_PHASE_PRESSURE" and _is_pressure_farm_drift(text):
        return "Avoid contesting pressure and move to safer farm."

    if decision_point == "LOW_HP":
        if key.startswith("reset hp before showing on another lane"):
            return "Reset HP before showing on another lane."
        # The tool that is ready right now (live_tools.low_hp_copy) stays as it is.
        if key.startswith(LOW_HP_TOOL_PREFIXES) or text in LOW_HP_INSURANCE_ACTIONS:
            return text
        return "Leave the wave now and reset HP before rejoining."

    if key in ACTION_REPLACEMENTS:
        return ACTION_REPLACEMENTS[key]

    if decision_point == "LANING_FARM_CHECK" and _is_awkward_laning_farm_text(text):
        return "Focus on safe last hits before forcing trades."

    if decision_point == "OBJECTIVE_FIGHT_CHECK" and _is_overconfident_objective_text(text):
        return "Consider joining only if your team is ready and the fight is near the objective."

    if decision_point == "BAD_FIGHT_RISK" and _suggests_safe_farm_as_generic_command(text):
        return "Avoid this fight and reset to safer farm."

    return text


def clean_reason_text(reason: str, decision_point: str | None = None) -> str:
    text = clean_visible_text(reason.strip())

    if decision_point == "LANING_FARM_CHECK" and _is_awkward_laning_farm_text(text):
        return "Stabilizing farm is safer than taking low-value damage."

    if decision_point == "FARMING_PHASE_PRESSURE" and _is_pressure_farm_drift(text):
        if text.startswith("Your farm pace is stable now"):
            return "Your farm pace is stable now, so keep using safe routes instead of forcing uncertain fights."
        if text.startswith("You are still behind on farm, and staying in pressure"):
            return text
        if text.startswith("Staying in pressure can cost HP and slow your recovery"):
            return text
        return "Enemy pressure is active, and a low-value fight can delay your next timing."

    if decision_point == "LOW_HP":
        if text in LOW_HP_INSURANCE_REASONS:
            return text
        if any(pattern.match(text) for pattern in LOW_HP_REASON_PATTERNS):
            return text
        if text.startswith("At this HP, one more spell or rotation can turn into a death"):
            return "At this HP, one more spell or rotation can turn into a death."
        return "At this HP, one more trade or spell can kill you."

    if decision_point == "OBJECTIVE_FIGHT_CHECK" and _is_overconfident_objective_text(text):
        return "Objectives can be worth joining, but avoid forcing a fight without team support."

    if decision_point == "BAD_FIGHT_RISK" and _suggests_safe_farm_as_generic_command(text):
        return "The fight looks risky and may delay your next timing."

    return text


def clean_risk_text(risk: str, decision_point: str | None = None) -> str:
    text = clean_visible_text(risk.strip())
    if decision_point == "BAD_FIGHT_RISK" and text.lower() in {"low", "low risk", "low."}:
        return "High risk of losing tempo if you join a low-value fight."
    if decision_point == "OBJECTIVE_FIGHT_CHECK" and text.lower() in {"low", "low risk", "low."}:
        return "Medium risk if the fight drifts away from objective value."
    if decision_point == "OBJECTIVE_FIGHT_CHECK" and _is_overconfident_objective_text(text):
        return "Medium risk if the fight drifts away from objective value."
    return text


def clean_visible_text(text: str) -> str:
    cleaned = text
    for raw, replacement in VISIBLE_PHRASE_REPLACEMENTS.items():
        cleaned = cleaned.replace(raw, replacement)
    return cleaned


def _canonical(text: str) -> str:
    text = re.sub(r"[^\w\s-]", " ", text.strip().lower())
    return " ".join(text.replace("-", " ").split())


def _is_overconfident_objective_text(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in OBJECTIVE_OVERCONFIDENCE)


def _suggests_safe_farm_as_generic_command(text: str) -> bool:
    lowered = text.lower()
    return "farm jungle camps" in lowered or lowered == "consider farm safely"


def _is_awkward_laning_farm_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "last-hitting",
            "lane jungle",
            "consider farm",
            "farm safely in lane",
            "farm last hits",
            "maintain lane gold",
        )
    )


def _is_pressure_farm_drift(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "pressure",
            "safer farm",
            "safe farm",
            "farm safely",
            "avoid contesting",
            "low-value fight",
            "low value fight",
        )
    )
