"""
post_laning_coach.py - conservative farming advice after the lane phase.

This helper only combines signals already present in GSI-like state. It does
not infer enemy positions, team readiness, Roshan state, or exact fight context.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.team_context import grouped_with_team

POST_LANING_REPEAT_WINDOW_SECONDS = 120
POST_LANING_SAME_ACTION_WINDOW_SECONDS = 330
POST_LANING_RECENT_SAFETY_WINDOW_SECONDS = 150
POST_LANING_DEATH_ROUTE_WINDOW_SECONDS = 180
OBJECTIVE_REPEAT_WINDOW_SECONDS = 180


@dataclass(frozen=True)
class PostLaningAdvice:
    category: str
    action: str
    reason: str
    risk: str
    repeat_key: str
    farm_quality: str
    hp_pressure_state: str
    pressure_active: bool
    position_risk: str
    position_zone: str
    objective_context_missing: bool
    clear_pressure_context: bool
    death_context: bool


def build_post_laning_advice(
    game_state: Mapping[str, Any] | Any,
    decision_point: str,
) -> PostLaningAdvice | None:
    state = _as_mapping(game_state)
    extra = _extra_context(state)
    minute = _to_int(state.get("minute"), 0)
    if minute < 10:
        return None

    hp_percent = _to_int(state.get("hp_percent"), 100)
    farm_quality = str(extra.get("farm_quality") or "").strip().lower()
    hp_pressure = str(extra.get("hp_pressure_state") or "").strip().lower()
    position_risk = str(extra.get("position_risk") or "").strip().lower()
    position_zone = str(extra.get("position_zone") or "").strip().lower()
    pressure_active = _pressure_active(state, extra, hp_pressure)
    death_context = _death_context(state, extra)
    objective_missing = objective_context_is_missing(extra)
    clear_context = _clear_pressure_context(state, extra)
    farm_stall = extra.get("farm_stall") if isinstance(extra.get("farm_stall"), Mapping) else None
    buyback_spent = (
        extra.get("buyback_spent") if isinstance(extra.get("buyback_spent"), Mapping) else None
    )
    # Holding the Aegis, the next death revives on the spot: the buyback is
    # not the first thing a purchase risks (and the card would block an item
    # bought for the push the Aegis is for). Only while the Aegis is known to
    # last (its pickup seen) and the base is not on the line; an Aegis of
    # unknown age may run out any second, so the card stays.
    if buyback_spent is not None and _aegis_covers_buyback(extra):
        buyback_spent = None
    tp_missing = extra.get("tp_missing") if isinstance(extra.get("tp_missing"), Mapping) else None
    if tp_missing is not None and _has_global_travel(extra):
        # A learned global teleport of the hero's own is the TP's job done.
        tp_missing = None

    category = _category_for_state(
        decision_point=decision_point,
        hp_percent=hp_percent,
        farm_quality=_effective_farm_quality(state, extra, farm_quality),
        hp_pressure=hp_pressure,
        pressure_active=pressure_active,
        position_risk=position_risk,
        position_zone=position_zone,
        death_context=death_context,
        farm_stall=farm_stall is not None,
        buyback_spent=buyback_spent is not None,
        buyback_danger=bool((buyback_spent or {}).get("danger")),
        tp_missing=tp_missing is not None,
        grouped=grouped_with_team(extra),
    )
    if category is None:
        return None

    action, reason, risk = _copy_for_category(category, objective_missing)
    if category == "post_laning_farm_stall" and farm_stall:
        reason = _farm_stall_reason(farm_stall)
    elif category == "post_laning_buyback_reserve" and buyback_spent:
        reason = _buyback_reason(buyback_spent, extra)
    elif category == "post_laning_carry_tp" and tp_missing:
        reason = _tp_reason(tp_missing)
        if extra.get("tp_in_stash") is True:
            # Bought already: the missing step is the delivery, not a purchase.
            action = "Have the courier bring the TP scroll from your stash."
            reason = (
                "It is bought but not in a slot: a fight or a tower across the map needs it there."
            )
    elif category == "post_laning_farm_recovery":
        # The numbers in the action: it is the line the card shows large.
        action, reason = _farm_pace_copy(state, extra) or (action, reason)
    elif category == "post_laning_safe_farm_route":
        # A core with a known build: name the next item and the gold it needs;
        # else what this game looks like (a kill streak, the kill score, the pace).
        action, reason = (
            _next_item_copy(state, extra)
            or _situational_farm_copy(state, extra)
            or (action, reason)
        )
    elif category == "post_laning_death_route_reset":
        # Same category (one death review per death in the scheduler), but with
        # gold to spend the first thing to do while dead is to buy.
        spend = _spend_while_dead(state, extra)
        if spend is not None:
            action, reason = _spend_copy(spend)
    repeat_key = ":".join(
        [
            category,
            farm_quality or "unknown",
            hp_pressure or "unknown",
            position_risk or "unknown",
            "pressure" if pressure_active else "stable",
        ]
    )
    return PostLaningAdvice(
        category=category,
        action=action,
        reason=reason,
        risk=risk,
        repeat_key=repeat_key,
        farm_quality=farm_quality or "unknown",
        hp_pressure_state=hp_pressure or ("pressure" if pressure_active else "healthy"),
        pressure_active=pressure_active,
        position_risk=position_risk or "unknown",
        position_zone=position_zone or "unknown",
        objective_context_missing=objective_missing,
        clear_pressure_context=clear_context,
        death_context=death_context,
    )


def post_laning_context_for_review(
    game_state: Mapping[str, Any] | Any,
    decision_point: str,
) -> dict[str, Any]:
    advice = build_post_laning_advice(game_state, decision_point)
    if advice is None:
        return {
            "post_laning_category": "",
            "post_laning_reason": "",
            "post_laning_repeat_key": "",
        }
    return {
        "post_laning_category": advice.category,
        "post_laning_reason": advice.reason,
        "post_laning_repeat_key": advice.repeat_key,
    }


def important_post_laning_context_changed(
    previous: dict[str, Any] | None,
    current: PostLaningAdvice,
) -> bool:
    if not previous:
        return True

    if current.category == "post_laning_low_hp_reset":
        return True
    if current.death_context:
        return True

    previous_pressure = str(previous.get("hp_pressure_state") or "")
    if previous_pressure != current.hp_pressure_state:
        return True

    previous_pressure_active = bool(previous.get("pressure_active"))
    if previous_pressure_active != current.pressure_active:
        return True

    previous_position_risk = str(previous.get("position_risk") or "")
    if previous_position_risk != "high" and current.position_risk == "high":
        return True

    return False


def objective_context_is_missing(extra: Mapping[str, Any]) -> bool:
    missing = set(extra.get("missing_signals") or [])
    return bool(
        {
            "nearby_allies_enemies",
            "enemy_positions",
            "exact_teamfight_context",
            "objective_context",
            "exact_roshan_context",
        }
        & missing
    )


# The Aegis must last at least this long for a purchase below the buyback
# cost to wait for the card: a fight started now ends within it.
AEGIS_COVERS_SECONDS = 60


def _aegis_covers_buyback(extra: Mapping[str, Any]) -> bool:
    left = extra.get("own_aegis_left")
    return (
        extra.get("has_aegis") is True
        and isinstance(left, int)
        and not isinstance(left, bool)
        and left >= AEGIS_COVERS_SECONDS
        and not extra.get("base_danger")
    )


def _category_for_state(
    *,
    decision_point: str,
    hp_percent: int,
    farm_quality: str,
    hp_pressure: str,
    pressure_active: bool,
    position_risk: str,
    position_zone: str,
    death_context: bool,
    farm_stall: bool = False,
    buyback_spent: bool = False,
    buyback_danger: bool = False,
    tp_missing: bool = False,
    grouped: bool = False,
) -> str | None:
    # Phase 3 fix: death_route_reset is gated by the factual death_context (derived
    # from GSI state: alive/respawn_seconds/near_player_death/death_count_changed),
    # NOT by the decision_point. Previously the disjunction `death_context OR
    # decision_point in DEATH-set` let a DEATH_REVIEW decision_point select this
    # category even when state carried no sign of death, desyncing category from
    # the public `death_context` field. Per the main principle, GSI state is the
    # single source of truth for live advice; decision_point is secondary. A
    # death decision_point without factual death signs degrades conservatively to
    # a safe category (or None) rather than a death-route reset.
    if death_context:
        return "post_laning_death_route_reset"

    if decision_point == "LOW_HP" or hp_percent < 35 or hp_pressure == "critical":
        return "post_laning_low_hp_reset"

    if decision_point == "OBJECTIVE_FIGHT_CHECK":
        return "post_laning_objective_caution"

    # Deep with allies next to you (minimap) is a push or a fight with the
    # team, not a lone deep showing: «don't show deep» does not fit it.
    if (position_risk == "high" or position_zone == "deep_enemy_side") and not grouped:
        return "post_laning_risky_showing"

    # A purchase just took the gold below the buyback cost late in the game
    # (buyback_tracker.py). Under pressure the safety-first advice wins, unless
    # the game is on the line (the enemy's Aegis, an own base building down).
    if buyback_spent and (not pressure_active or buyback_danger):
        return "post_laning_buyback_reserve"

    # Almost no last hits for minutes while alive (farm_tracker.py): get back
    # to farming. Under pressure the safety-first pressure advice wins.
    if farm_stall and not pressure_active:
        return "post_laning_farm_stall"

    # No way to teleport for a minute or more (tp_tracker.py). Under pressure the
    # safety-first advice wins; a farm stall matters more.
    if tp_missing and not pressure_active:
        return "post_laning_carry_tp"

    farm_low = farm_quality in {"very_low", "low"}
    if farm_low and pressure_active:
        return "post_laning_pressure_avoidance"
    if farm_low:
        return "post_laning_farm_recovery"
    if pressure_active:
        return "post_laning_pressure_avoidance"
    if decision_point in {"SAFE_FARMING", "LANING_FARM_CHECK", "FARMING_PHASE_PRESSURE"}:
        return "post_laning_safe_farm_route"
    return None


def _copy_for_category(category: str, objective_missing: bool) -> tuple[str, str, str]:
    if category == "post_laning_low_hp_reset":
        return (
            "Reset HP before showing on another lane.",
            "At this HP, one more spell or rotation can turn into a death.",
            "High risk if you show again before resetting HP.",
        )
    if category == "post_laning_death_route_reset":
        return (
            "Use the respawn time to choose a safer farming route.",
            "Returning to the same pressured area can repeat the same death pattern.",
            "Medium risk if you respawn and run back into the same area.",
        )
    if category == "post_laning_farm_recovery":
        return (
            "Recover farm through the safest wave-and-camp route.",
            "You are behind on farm, so forcing fights before stabilizing can delay your next timing.",
            "Medium risk if you chase fights before rebuilding farm pace.",
        )
    if category == "post_laning_farm_stall":
        return (
            "Go back to farming: take the nearest safe wave or camp now.",
            "You have taken almost no last hits lately; every minute without farm delays your next item.",
            "Medium risk if you keep walking around without farming.",
        )
    if category == "post_laning_carry_tp":
        return (
            "Keep a TP scroll in its slot: buy one now, the courier can bring it.",
            "Without a TP scroll you cannot join a fight or save a tower in time.",
            "Medium risk if a fight starts across the map while you have no TP.",
        )
    if category == "post_laning_buyback_reserve":
        return (
            "Farm back your buyback gold before the next purchase.",
            "After minute 30 one death without buyback can decide the game.",
            "High risk if you die before the buyback gold is back.",
        )
    if category == "post_laning_pressure_avoidance":
        return (
            "Avoid the pressured lane and farm a safer wave or nearby camp.",
            "Staying in pressure can cost HP and slow your recovery.",
            "High risk if you stay in pressure without confirmed support.",
        )
    if category == "post_laning_risky_showing":
        return (
            "Do not show deep until enemy positions are clearer.",
            "Your position is exposed and the replay does not confirm where enemies are.",
            "High risk if you show in a deep area with missing enemy context.",
        )
    if category == "post_laning_objective_caution":
        reason = (
            "Objective fights can be valuable, but the replay does not confirm team readiness."
            if objective_missing
            else "Objective fights can be valuable, but avoid forcing them without team support."
        )
        return (
            "Only consider the objective if your team is already grouped nearby.",
            reason,
            "Medium risk if the objective fight starts without confirmed support.",
        )
    return (
        "Keep farming the safest wave-and-camp route and reassess soon.",
        "Your farm pace is stable now, so keep using safe routes instead of forcing uncertain fights.",
        "Low risk if you keep farming without showing in exposed areas.",
    )


# Gold left over (after the buyback reserve late in the game) worth a component.
SPEND_WHILE_DEAD_MIN_GOLD = 1000
BUYBACK_RESERVE_MINUTE = 30


def _spend_while_dead(state: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, int] | None:
    alive = extra.get("alive", state.get("alive", True))
    dead = (
        alive is False or _to_int(extra.get("respawn_seconds", state.get("respawn_seconds")), 0) > 0
    )
    if not dead:
        return None
    gold = extra.get("available_gold", state.get("gold"))
    if gold is None:
        return None
    gold = _to_int(gold, 0)
    reserve = 0
    # The buyback stays aside after minute 30, and earlier with the game on the
    # line (match_memory.base_danger: the enemy's Aegis, an own base building down).
    if _to_int(state.get("minute"), 0) >= BUYBACK_RESERVE_MINUTE or extra.get("base_danger"):
        cost = extra.get("buyback_cost")
        if cost is None:
            return None  # can't tell what to keep for buyback
        reserve = _to_int(cost, 0)
    spare = gold - reserve
    if spare < SPEND_WHILE_DEAD_MIN_GOLD:
        return None
    return {"gold": gold, "spare": spare, "reserve": reserve}


def spend_while_dead_sentence(game_state: Mapping[str, Any] | Any) -> str | None:
    """ "Buy parts of your next item now..." when a dead hero has gold to spare, for the
    other death reviews (repeated deaths, escape on cooldown...) to use as their reason."""
    state = _as_mapping(game_state)
    spend = _spend_while_dead(state, _extra_context(state))
    return _spend_copy(spend)[0] if spend is not None else None


def _spend_copy(spend: Mapping[str, int]) -> tuple[str, str]:
    if spend["reserve"]:
        action = (
            f"Buy parts of your next item with {spend['spare']} gold "
            f"and keep {spend['reserve']} for buyback."
        )
    else:
        action = (
            f"Buy parts of your next item now with your {spend['gold']} gold: "
            "they wait for you at the fountain."
        )
    reason = (
        "Unspent gold is partly lost on the next death; "
        "then choose a safer route than the one you died on."
    )
    return action, reason


# Below this the pace is too uncertain to turn gold into minutes.
NEXT_ITEM_MIN_GPM = 150


def _next_item_copy(state: Mapping[str, Any], extra: Mapping[str, Any]) -> tuple[str, str] | None:
    """ "Keep farming toward Black King Bar" with the gold still missing and the
    minutes at the player's pace, or "it can be bought now" when the gold is there
    (after minute 30 the buyback cost stays aside). `extra.next_item` comes from
    app/next_item.py. The actions start with "Use" / "Keep" so that the UX policy
    leaves them as they are ("Buy …" would read as autopilot)."""
    item = extra.get("next_item")
    if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
        return None
    name = item["name"]
    # A situational item (situational_items.py) says why it comes first.
    because = _situational_because(item)
    if because is not None and item.get("gold_left") is None:
        return f"Keep farming toward {name} on the safest waves and camps.", because + "."
    left = _to_int(item.get("gold_left"), 0)
    gold = extra.get("available_gold", state.get("gold"))
    if left <= 0 or gold is None:
        return None
    reserve = 0
    # The buyback stays aside after minute 30, and earlier with the game on the
    # line (match_memory.base_danger: the enemy's Aegis, an own base building down).
    if _to_int(state.get("minute"), 0) >= BUYBACK_RESERVE_MINUTE or extra.get("base_danger"):
        cost = extra.get("buyback_cost")
        if cost is None:
            return None  # can't tell what to keep for buyback
        reserve = _to_int(cost, 0)
    spare = max(0, _to_int(gold, 0) - reserve)
    if spare >= left:
        extra_gold = f"you have {spare} beyond your buyback" if reserve else f"you have {spare}"
        if because is not None:
            parts = f"its missing parts cost {left} gold and {extra_gold}"
            return f"Use your gold: {name} can be bought now.", f"{because}; {parts}."
        return (
            f"Use your gold: {name} can be bought now.",
            f"Its missing parts cost {left} gold and {extra_gold}.",
        )
    need = left - spare
    reason = (
        f"{because}: {need} gold to go"
        if because is not None
        else f"{name} is next in most builds: {need} gold to go"
    )
    gpm = _to_int(extra.get("gpm"), 0)
    if gpm >= NEXT_ITEM_MIN_GPM:
        minutes = max(1, -(-need // gpm))
        noun = "minute" if minutes == 1 else "minutes"
        reason += f", about {minutes} {noun} at your {gpm} gold per minute"
    return f"Keep farming toward {name} on the safest waves and camps.", reason + "."


# A kill score gap this big (after SCORE_GAP_MINUTE) changes how to farm.
SCORE_GAP = 8
SCORE_GAP_MINUTE = 12


def _situational_farm_copy(
    state: Mapping[str, Any], extra: Mapping[str, Any]
) -> tuple[str, str] | None:
    """The safe-farm card with this game's facts instead of the same generic
    line every time: the kill score gap, which changes how to play. A core's
    card only. «Stay alive: you are on a streak» and «Keep farming: N gold per
    minute» were dropped: a statistic or a moral is no decision, and neither
    says what to do differently now."""
    coverage = extra.get("advisor_coverage")
    if coverage is not None and coverage != "full":
        return None
    minute = _to_int(state.get("minute"), 0)
    team = str(extra.get("team_name") or "").strip().lower()
    radiant, dire = extra.get("radiant_score"), extra.get("dire_score")
    if (
        minute >= SCORE_GAP_MINUTE
        and team in ("radiant", "dire")
        and isinstance(radiant, int)
        and isinstance(dire, int)
    ):
        ours, theirs = (radiant, dire) if team == "radiant" else (dire, radiant)
        gap = ours - theirs
        if gap <= -SCORE_GAP:
            return (
                f"Your team is {-gap} kills behind: farm your own half and fight near your towers.",
                "The enemy has items first now; trade risky farm for safe farm until your "
                "key item.",
            )
        if gap >= SCORE_GAP:
            return (
                f"Your team is {gap} kills ahead: group up and take a tower instead of "
                "farming alone.",
                "A kill lead fades unless it turns into towers and map control.",
            )
    return None


SITUATIONAL_BECAUSE = {
    "disabled": "{count} deaths under stuns with no free second, and {name} stops that",
    "burst": "{count} deaths, each from high health in 3 seconds or less, and {name} gives you time against that",
    "targeted": "{count} deaths under stuns against {enemy}, and {name} blocks {spell}",
    "evasion": "{enemy} dodges your attacks, and {name} pierces it on most attacks",
    "healing": "{enemy} heals a lot, and {name} cuts the healing",
    "illusions": "{enemy} fights with illusions, and {name} hits them all",
    "magic": "{count} enemy heroes deal magic damage, and {name} protects you from it",
    "break": "{enemy} relies on {spell}, and {name} turns it off",
}
# Counters to an enemy hero seen: no death count, the enemy says why.
ENEMY_WHYS = {"evasion", "healing", "illusions", "magic", "break"}


def _situational_because(item: Mapping[str, Any]) -> str | None:
    reason = item.get("reason")
    if isinstance(reason, Mapping) and isinstance(reason.get("en"), str) and reason["en"]:
        return reason["en"]  # a hero plan's own reason (advice_i18n has its Ukrainian)
    why = str(item.get("why") or "")
    template = SITUATIONAL_BECAUSE.get(why)
    count = _to_int(item.get("count"), 0)
    enemy = item.get("enemy") if isinstance(item.get("enemy"), str) else None
    if template is None:
        return None
    if why in ENEMY_WHYS:
        if not enemy or (why == "break" and not item.get("spell")):
            return None
    elif count < 1 or (why == "targeted" and not (enemy and item.get("spell"))):
        return None
    return template.format(count=count, name=item["name"], enemy=enemy, spell=item.get("spell"))


BUYBACK_DANGER = {
    "enemy_aegis": "the enemy holds the Aegis",
    "base": "your base is open",
}


def _buyback_reason(signal: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> str:
    """The numbers of this snapshot (the card can come long after the purchase);
    the signal's own only when the snapshot has none."""
    extra = extra or {}
    gold = _to_int(extra.get("available_gold", signal.get("gold")), 0)
    cost = _to_int(extra.get("buyback_cost", signal.get("cost")), 0)
    danger = BUYBACK_DANGER.get(str(signal.get("danger")))
    if danger:
        return (
            f"You have {gold} gold and buyback costs {cost}; {danger}: "
            "one death without buyback can decide the game."
        )
    return (
        f"You have {gold} gold and buyback costs {cost}; "
        "after minute 30 one death without buyback can decide the game."
    )


# The hero's own learned ability that does a TP scroll's job across the map.
# Only Nature's Prophet's Teleportation is listed: other travel spells (Io's
# Relocate, Underlord's portal, Spirit Breaker's charge) need an ally, a
# target or a long cast, and are not a plain replacement for the scroll.
GLOBAL_TRAVEL_ABILITIES = frozenset({"furion_teleportation"})


def _has_global_travel(extra: Mapping[str, Any]) -> bool:
    abilities = extra.get("abilities")
    if not isinstance(abilities, list):
        return False
    return any(
        isinstance(a, Mapping)
        and a.get("raw_name") in GLOBAL_TRAVEL_ABILITIES
        and _to_int(a.get("level"), 0) > 0
        for a in abilities
    )


def _tp_reason(signal: Mapping[str, Any]) -> str:
    minutes = max(1, _to_int(signal.get("minutes"), 1))
    noun = "minute" if minutes == 1 else "minutes"
    return (
        f"No TP scroll for {minutes} {noun}: without it you cannot join a fight "
        "or save a tower in time."
    )


def _farm_stall_reason(stall: Mapping[str, Any]) -> str:
    last_hits = _to_int(stall.get("last_hits"), 0)
    minutes = max(1, _to_int(stall.get("minutes"), 4))
    noun = "last hit" if last_hits == 1 else "last hits"
    return (
        f"Only {last_hits} {noun} in the last {minutes} minutes; "
        "every minute without farm delays your next item."
    )


# "Behind on farm" needs a real gap: 129 last hits against a 130+ pace is on pace.
FARM_GAP_MIN_LAST_HITS = 8
FARM_GAP_MIN_SHARE = 0.08


def _effective_farm_quality(
    state: Mapping[str, Any], extra: Mapping[str, Any], farm_quality: str
) -> str:
    if farm_quality != "low":
        return farm_quality
    expected = extra.get("expected_lh_range")
    last_hits = extra.get("last_hits", state.get("last_hits"))
    if not isinstance(expected, (list, tuple)) or not expected or last_hits is None:
        return farm_quality
    low = _to_int(expected[0], 0)
    gap = low - _to_int(last_hits, 0)
    if gap < max(FARM_GAP_MIN_LAST_HITS, FARM_GAP_MIN_SHARE * low):
        return "okay"
    return farm_quality


FAR_BEHIND_MINUTE = 20


def _farm_pace_copy(state: Mapping[str, Any], extra: Mapping[str, Any]) -> tuple[str, str] | None:
    """ "Recover farm: 38 last hits at minute 14, a good pace is 64+." when the
    numbers are known."""
    expected = extra.get("expected_lh_range")
    last_hits = extra.get("last_hits", state.get("last_hits"))
    minute = _to_int(state.get("minute"), 0)
    if not isinstance(expected, (list, tuple)) or not expected or last_hits is None or minute <= 0:
        return None
    lh, low = _to_int(last_hits, 0), _to_int(expected[0], 0)
    action = f"Recover farm: {lh} last hits at minute {minute}, a good pace is {low}+."
    if minute >= FAR_BEHIND_MINUTE and lh * 2 < low:
        # Half the pace late in the game: the same «safest waves» line every four
        # minutes did not help; say how a core catches up then.
        return (
            action,
            "Take the side lanes your team leaves and a camp between waves; "
            "join fights only for a tower or Roshan.",
        )
    return (
        action,
        "Take the safest waves and camps first: fights before that delay your next item.",
    )


def _pressure_active(state: Mapping[str, Any], extra: Mapping[str, Any], hp_pressure: str) -> bool:
    if hp_pressure in {"pressured_but_stable", "risky", "critical"}:
        return True
    game_state = str(state.get("game_state") or "").strip().lower()
    if any(token in game_state for token in ("pressure", "fight", "risk", "damage")):
        return True
    return bool(
        extra.get("replay_damage_pressure_window")
        or extra.get("lane_pressure_from_damage_windows")
        or extra.get("recent_damage_taken")
    )


def _clear_pressure_context(state: Mapping[str, Any], extra: Mapping[str, Any]) -> bool:
    if _death_context(state, extra):
        return True
    if bool(state.get("near_teamfight") or extra.get("near_teamfight")):
        return True
    if bool(extra.get("replay_damage_pressure_window") or extra.get("recent_damage_taken")):
        return True
    game_state = str(state.get("game_state") or "").strip().lower()
    return any(token in game_state for token in ("pressure", "fight", "risk", "damage"))


def _death_context(state: Mapping[str, Any], extra: Mapping[str, Any]) -> bool:
    alive = extra.get("alive", state.get("alive", True))
    if alive is False or str(alive).strip().lower() in {"false", "0", "no"}:
        return True
    if _to_int(extra.get("respawn_seconds", state.get("respawn_seconds")), 0) > 0:
        return True
    return bool(
        state.get("near_player_death")
        or state.get("selected_player_death_nearby")
        or extra.get("near_player_death")
        or extra.get("selected_player_death_nearby")
        or extra.get("death_count_changed")
    )


def _extra_context(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = state.get("extra_context")
    return extra if isinstance(extra, Mapping) else {}


def _as_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
