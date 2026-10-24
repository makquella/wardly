"""
recommender.py - rule-based fallback wording for universal carry advice.

The local advice policy owns priority and timing. This module only supplies
short, safe action/reason/risk text.
"""

from app.advice_policy import build_advice_policy
from app.hero_gameplay import selected_rule
from app.hero_gameplay_texts import GAMEPLAY_RISK
from app.hero_profiles import evaluate_laning_context
from app.laning_coach import build_laning_advice
from app.live_tools import (
    LOW_HP_ACTION_TYPES,
    death_copy,
    disabled_copy,
    hero_tools,
    hp_falling_reason,
    insurance_copy,
    low_hp_copy,
    low_hp_repeat_reason,
    low_mana_reason,
    readiness_copy,
)
from app.post_laning_coach import build_post_laning_advice, spend_while_dead_sentence
from app.schemas import GameSituationRequest, RecommendationResponse

FALLBACK_TEXT = {
    "retreat_reset": {
        "action": "Leave the wave now and reset HP before rejoining.",
        "reason": "At this HP, one more trade or spell can kill you.",
        "risk": "High risk of dying if you stay visible or keep fighting.",
    },
    "switch_to_safe_farm": {
        "action": "Avoid contesting pressure and move to safer farm.",
        "reason": "Enemy pressure is active. A low-value fight or death delays your next timing.",
        "risk": "High risk if you farm visible areas or force a fight.",
    },
    "play_back_and_regen": {
        "action": "Use regen or play back until your HP is safer.",
        "reason": "Low lane HP makes trades and last hits risky.",
        "risk": "Medium risk if you keep trading or standing exposed.",
    },
    "stabilize_after_recent_damage": {
        "action": "Back up and stabilize before trading again.",
        "reason": "You took heavy damage recently, so another trade can turn into a death.",
        "risk": "Medium risk if you keep trading before HP and position are stable.",
    },
    "stop_overstay_low_hp": {
        "action": "Do not overstay on low HP; reset or play behind creeps.",
        "reason": "Staying exposed after a bad trade often leads to a preventable death.",
        "risk": "High risk if you stay visible and take another trade.",
    },
    "stabilize_lane_farm": {
        "action": "Focus on safe last hits before forcing trades.",
        "reason": "Stabilizing farm is safer than taking low-value damage.",
        "risk": "Medium risk if you trade instead of stabilizing lane farm.",
    },
    "respect_defensive_ability_cooldown": {
        "action": "Avoid risky trades until your defensive tool is ready.",
        "reason": "Your hero is easier to punish while this safety tool is unavailable.",
        "risk": "Medium risk if you trade before your safety spell is ready.",
    },
    "improve_farm_rate": {
        "action": "Your farm pace is behind; move to safer, higher-value farm.",
        "reason": "Improving farm rate is safer than forcing a low-value fight.",
        "risk": "Medium risk if you chase fights instead of stabilizing farm.",
    },
    "conserve_mana_or_reset": {
        "action": "Conserve mana or reset before taking a fight.",
        "reason": "Low mana limits escape, spell usage, and fight impact.",
        "risk": "Medium risk if you join a fight without enough mana to leave or contribute.",
    },
    "wait_out_disable": {
        "action": "Wait out the disable and avoid forcing actions.",
        "reason": "You are controlled; surviving the next seconds matters more than dealing damage.",
        "risk": "High risk if you try to force action while disabled.",
    },
    "check_buyback_value": {
        "action": "Buyback is available. Only consider it for critical defense.",
        "reason": "Use it only if your team is defending a critical objective or the game could be decided now.",
        "risk": "High risk if buyback is spent without protecting an objective or base.",
    },
    "prepare_next_move": {
        "action": "Use the respawn time to plan your next safe farming route.",
        "reason": "Avoid rushing back into the same risky area.",
        "risk": "Low risk if you use the downtime to reset your route.",
    },
    "stay_hidden_until_team_ready": {
        "action": "Stay hidden until your team is ready to make a move.",
        "reason": "Revealing on a wave can waste the smoke timing.",
        "risk": "Medium risk if you reveal before your team can use the smoke.",
    },
    "respect_hero_safety_window": {
        "action": "Respect your hero's safety window before forcing a fight.",
        "reason": "Your key defensive resource is unavailable, so a bad fight is harder to escape.",
        "risk": "High risk if you commit before your safety resource is ready.",
    },
    "plan_safer_respawn_route": {
        "action": "Use the respawn time to plan a safer next route.",
        "reason": "Avoid returning to the same risky area without vision or team support.",
        "risk": "Medium risk if you repeat the same path after respawn.",
    },
    "break_repeated_death_pattern": {
        "action": "After respawn, reset your route and avoid repeating the same risky path.",
        "reason": "Multiple recent deaths can delay your next timing more than missing one wave or camp.",
        "risk": "High risk if the next route repeats the same death pattern.",
    },
    "respect_escape_cooldown_after_respawn": {
        "action": "After respawn, avoid committing forward until your escape is ready.",
        "reason": "You died after your key escape or defensive tool was unavailable.",
        "risk": "High risk if you commit again before your safety tool is ready.",
    },
    "reset_before_resources_collapse": {
        "action": "After respawn, reset earlier when HP or key resources get low.",
        "reason": "The previous fight became risky because your survivability resource was low.",
        "risk": "Medium risk if you stay too long after HP or mana drops.",
    },
    "join_only_if_objective_value": {
        "action": "Consider joining only if your team is ready and the fight is near the objective.",
        "reason": "Objectives can be worth joining, but random skirmishes are not.",
        "risk": "Medium risk if the fight drifts away from objective value.",
    },
    "avoid_bad_fight": {
        "action": "Avoid this fight and reset to safer farm.",
        "reason": "The fight looks risky and may delay your next timing.",
        "risk": "High risk of losing tempo if you join a low-value fight.",
    },
    "play_around_timing": {
        "action": "You reached a timing; reassess whether to pressure or keep farming safely.",
        "reason": "A meaningful item can change your next decision, but avoid forcing low-value fights.",
        "risk": "Medium risk if you force action without team or objective value.",
    },
    "keep_farming": {
        "action": "Keep farming safely and reassess in 60 seconds.",
        "reason": "No urgent threat or objective is forcing action. Build resources safely.",
        "risk": "Low risk if you avoid unnecessary fights and unsafe areas.",
    },
    "no_advice": {
        "action": "No urgent action.",
        "reason": "There is no clear threat, objective, or timing decision right now.",
        "risk": "Low risk if you keep playing safely.",
    },
    "soft_status": {
        "action": "Monitoring lane — no urgent advice.",
        "reason": "Current lane state does not need a full coaching card.",
        "risk": "Low risk if you keep playing safely.",
    },
}


def generate_recommendation(
    req: GameSituationRequest,
    rag_context: list[str],
) -> RecommendationResponse:
    """Return concise universal carry fallback advice."""

    decision_point = _decision_point_from_request(req)
    policy = build_advice_policy(req, decision_point)
    text = _fallback_text(req, policy["action_type"])

    return RecommendationResponse(
        action=text["action"],
        reason=text["reason"],
        risk=text["risk"],
        priority=policy["priority"],
        time_window=policy["time_window"],
    )


def _decision_point_from_request(req: GameSituationRequest) -> str:
    from app.decision_points import detect_decision_point

    return detect_decision_point(req.model_dump())


# Death reviews: with gold to spare, the reason says to buy while waiting.
# Death advice about the route after respawn (the others: escape, resources).
ROUTE_ACTION_TYPES = {"plan_safer_respawn_route", "break_repeated_death_pattern"}
DEATH_ACTION_TYPES = {
    "plan_safer_respawn_route",
    "break_repeated_death_pattern",
    "respect_escape_cooldown_after_respawn",
    "reset_before_resources_collapse",
    "prepare_next_move",
}


def _fallback_text(req: GameSituationRequest, action_type: str) -> dict[str, str]:
    text = _base_fallback_text(req, action_type)
    extra = req.extra_context or {}
    # Name what can be pressed right now (live_tools.py); the plain text stays
    # when GSI shows nothing ready.
    tool = None
    # Critical HP with an Aegis, a revive or a hero save ready: name it instead
    # of a plain «leave now» (live_tools.INSURANCE_COPY).
    insured = insurance_copy(extra, req.hp_percent) if action_type == "retreat_reset" else None
    if insured is not None:
        tool = insured
    elif action_type in LOW_HP_ACTION_TYPES:
        tool = low_hp_copy(extra, req.hero)
    elif action_type == "wait_out_disable":
        tool = disabled_copy(extra, req.hero)
    if tool is not None:
        text = {**text, "action": tool[0], "reason": tool[1]}
    if action_type == "conserve_mana_or_reset":
        # Name only the escape that is learned (W at 3:16 was not yet).
        text = {**text, "reason": low_mana_reason(extra, req.hero)}
    if action_type in LOW_HP_ACTION_TYPES and insured is None:
        repeat = hp_falling_reason(extra) or low_hp_repeat_reason(extra)
        if repeat is not None:
            text = {**text, "reason": repeat}
    if action_type in DEATH_ACTION_TYPES and not text["action"].startswith("Buy parts"):
        # Where the deaths keep happening, and the lesson of this one (a rescue
        # item left unpressed); else what to buy while waiting.
        # The count of deaths only replaces a route line: the escape and
        # resource cards say something more specific.
        action, reason = death_copy(extra, route=action_type in ROUTE_ACTION_TYPES)
        reason = reason or spend_while_dead_sentence(req)
        if action is not None:
            text = {**text, "action": action}
        if reason is not None:
            text = {**text, "reason": reason}
    return text


def _base_fallback_text(req: GameSituationRequest, action_type: str) -> dict[str, str]:
    if action_type == "prepare_hero_action":
        rule = selected_rule(req.model_dump())
        if rule is not None:
            return {"action": rule.action, "reason": rule.reason, "risk": GAMEPLAY_RISK}
        return FALLBACK_TEXT["no_advice"]

    post_laning_text = _post_laning_fallback_text(req, action_type)
    if post_laning_text is not None:
        return post_laning_text

    if action_type == "stabilize_lane_farm":
        return _laning_farm_fallback_text(req)

    if action_type == "switch_to_safe_farm":
        return _pressure_fallback_text(req)

    if action_type == "respect_hero_safety_window":
        return _hero_safety_fallback_text(req)

    if action_type == "respect_defensive_ability_cooldown":
        return _ability_safety_fallback_text(req)

    if action_type != "play_around_timing":
        return FALLBACK_TEXT[action_type]

    replay_item_timing = _replay_item_timing_text(req)
    if replay_item_timing is not None:
        return replay_item_timing

    text = dict(FALLBACK_TEXT["play_around_timing"])
    category_reasons = {
        "defensive_timings": "You reached a defensive timing; consider fighting only around objectives or with team support.",
        "farming_timings": "You reached a farming timing; increase farm speed and avoid unnecessary deaths.",
        "mobility_timings": "You reached a mobility timing; look for safer map movement, not random fights.",
        "damage_timings": "You reached a damage timing; consider objective fights, not low-value skirmishes.",
        "late_game_timings": "You reached a late-game timing; prioritize high-value objectives and safe positioning.",
    }
    if req.item_timing_category in category_reasons:
        text["reason"] = category_reasons[req.item_timing_category]
    return text


def _replay_item_timing_text(req: GameSituationRequest) -> dict[str, str] | None:
    context = req.extra_context or {}
    source_type = str(context.get("source_type") or "").strip()
    missing = set(context.get("missing_signals") or [])
    if source_type != "replay_gsi_like":
        return None
    if not {"gold", "ability_cooldowns"} & missing:
        return None

    return {
        "action": "After this item pickup, reassess whether to farm safely or pressure with your team.",
        "reason": (
            "The item improves your options, but missing cooldown and team context means "
            "the safer choice still depends on nearby pressure."
        ),
        "risk": "Medium risk if you force action without reliable cooldown or team context.",
    }


def _post_laning_fallback_text(
    req: GameSituationRequest, action_type: str
) -> dict[str, str] | None:
    decision_point = _decision_point_from_request(req)
    post_laning_advice = build_post_laning_advice(req, decision_point)
    if post_laning_advice is None:
        return None

    action_types = {
        "retreat_reset",
        "switch_to_safe_farm",
        "stabilize_lane_farm",
        "improve_farm_rate",
        "prepare_next_move",
        "plan_safer_respawn_route",
        "reset_before_resources_collapse",
        "respect_escape_cooldown_after_respawn",
        "join_only_if_objective_value",
        "avoid_bad_fight",
        "keep_farming",
    }
    if action_type not in action_types:
        return None

    return {
        "action": post_laning_advice.action,
        "reason": post_laning_advice.reason,
        "risk": post_laning_advice.risk,
    }


def _laning_farm_fallback_text(req: GameSituationRequest) -> dict[str, str]:
    laning_advice = build_laning_advice(req, "LANING_FARM_CHECK")
    if laning_advice is not None:
        return {
            "action": laning_advice.action,
            "reason": laning_advice.reason,
            "risk": laning_advice.risk,
        }
    return FALLBACK_TEXT["stabilize_lane_farm"]


def _pressure_fallback_text(req: GameSituationRequest) -> dict[str, str]:
    laning_advice = build_laning_advice(req, "FARMING_PHASE_PRESSURE")
    if laning_advice is not None:
        return {
            "action": laning_advice.action,
            "reason": laning_advice.reason,
            "risk": laning_advice.risk,
        }

    context = req.extra_context or {}
    if str(context.get("position_risk") or "").strip().lower() == "high":
        return {
            "action": "Move closer to a safer farming zone before showing on the wave.",
            "reason": "Your position is risky and enemy locations are not confirmed.",
            "risk": "High risk if you stay visible in a risky area without enemy location info.",
        }

    hp_pressure = str(context.get("hp_pressure_state") or "").strip().lower()
    if hp_pressure == "pressured_but_stable":
        return {
            "action": "Farm the safer part of the lane and avoid long trades.",
            "reason": "You are under pressure but still have enough HP to keep farming if you stay conservative.",
            "risk": "Medium risk if you take extended trades while pressure is active.",
        }
    if hp_pressure == "risky":
        return {
            "action": "Back up, stabilize HP, then return to the wave.",
            "reason": "Pressure plus reduced HP can turn the next trade into a death.",
            "risk": "High risk if you keep trading before HP is stable.",
        }

    if _has_low_farm_rate(req):
        return FALLBACK_TEXT["improve_farm_rate"]

    return FALLBACK_TEXT["switch_to_safe_farm"]


def _has_low_farm_rate(req: GameSituationRequest) -> bool:
    context = req.extra_context or {}
    if context.get("demo_values_detected"):
        return False
    if context.get("farm_rate_state") == "slow":
        return True
    try:
        last_hits = int(context.get("last_hits"))
    except (TypeError, ValueError):
        last_hits = None
    try:
        gpm = int(context.get("gpm"))
    except (TypeError, ValueError):
        gpm = None

    if gpm is not None and gpm > 2000:
        return False

    thresholds = ((25, 170), (20, 120), (15, 80), (10, 45))
    if any(
        req.minute >= minute and last_hits is not None and last_hits < target
        for minute, target in thresholds
    ):
        return True
    return req.minute >= 15 and gpm is not None and gpm < 400


def _hero_safety_fallback_text(req: GameSituationRequest) -> dict[str, str]:
    context = req.extra_context or {}
    reason = str(context.get("hero_safety_reason") or "").strip()
    constraint = str(context.get("recommended_constraint") or "").strip()
    ability = str(context.get("hero_safety_ability") or "").strip()
    kind = str(context.get("hero_safety_kind") or "").strip().lower()
    raw_flags = context.get("hero_safety_flags", [])
    flags = {
        str(flag).strip().lower()
        for flag in (raw_flags if isinstance(raw_flags, list) else [])
        if str(flag).strip()
    }

    if req.hero == "Medusa" and "mana_shield_resource_low" in flags:
        return {
            "action": "Reset mana before taking an extended fight.",
            "reason": "Low mana reduces Medusa's effective survivability.",
            "risk": _risk_from_constraint(
                constraint, FALLBACK_TEXT["respect_hero_safety_window"]["risk"]
            ),
        }

    seconds = _cooldown_left(req, ability)
    if ability and ("escape_on_cooldown" in flags or kind == "escape"):
        return {
            "action": _truncate(f"Avoid committing forward until {ability} is ready.", 100),
            "reason": _truncate(
                f"{ability} is back in {seconds} s: without it, escaping a bad trade "
                "or fight is harder."
                if seconds
                else f"Without {ability}, escaping a bad trade or fight is harder.",
                180,
            ),
            "risk": _risk_from_constraint(
                constraint, FALLBACK_TEXT["respect_hero_safety_window"]["risk"]
            ),
        }

    if ability and ("defensive_ability_on_cooldown" in flags or kind == "defensive"):
        return _ability_cooldown_text(ability, constraint, seconds)

    text = dict(FALLBACK_TEXT["respect_hero_safety_window"])
    if reason:
        text["reason"] = reason
    if constraint:
        text["risk"] = _risk_from_constraint(constraint, text["risk"])
    return text


def _ability_safety_fallback_text(req: GameSituationRequest) -> dict[str, str]:
    context = req.extra_context or {}
    laning_context = context.get("laning_context")
    ability = ""
    if isinstance(laning_context, dict):
        ability = str(laning_context.get("key_safety_ability") or "").strip()

    if not ability:
        ability = str(context.get("hero_safety_ability") or "").strip()

    if not ability:
        inferred_laning_context = evaluate_laning_context(req.model_dump())
        ability = str(inferred_laning_context.get("key_safety_ability") or "").strip()

    if ability:
        seconds = _cooldown_left(req, ability)
        readiness = readiness_copy(context, ability, seconds)
        if readiness is not None:
            return {
                "action": readiness[0],
                "reason": readiness[1],
                "risk": FALLBACK_TEXT["respect_defensive_ability_cooldown"]["risk"],
            }
        return _ability_cooldown_text(ability, "", seconds)

    return FALLBACK_TEXT["respect_defensive_ability_cooldown"]


def _cooldown_left(req: GameSituationRequest, ability: str) -> int | None:
    """Seconds until the hero's safety ability is back (live GSI), when known."""
    if not ability:
        return None
    cooldowns = hero_tools(req.hero, (req.extra_context or {}).get("abilities"))["cooldowns"]
    return cooldowns.get(ability)


def _ability_cooldown_text(
    ability: str, constraint: str, seconds: int | None = None
) -> dict[str, str]:
    reason = (
        f"{ability} is back in {seconds} s: until then, disables and slows are harder to avoid."
        if seconds
        else f"Without {ability}, disables and slows are harder to avoid."
    )
    return {
        "action": _truncate(f"Avoid risky trades until {ability} is ready.", 100),
        "reason": _truncate(reason, 180),
        "risk": _risk_from_constraint(
            constraint,
            FALLBACK_TEXT["respect_defensive_ability_cooldown"]["risk"],
        ),
    }


def _risk_from_constraint(constraint: str, fallback: str) -> str:
    if not constraint:
        return fallback
    return _truncate(f"Risk increases if you ignore this constraint: {constraint}.", 140)


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."
