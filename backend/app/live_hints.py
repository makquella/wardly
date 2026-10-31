"""In-memory live hint rendering with metadata prepared by the API boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.map_hints import enemy_group, map_hint, score_gap, timer_strip

if TYPE_CHECKING:
    from app.match_memory import LiveTrackerSnapshot, MatchMemory


@dataclass(frozen=True)
class GoldHintInputs:
    next_item: dict[str, Any] | None = None
    buy_now: dict[str, Any] | None = None
    start_items: list[dict[str, Any]] | None = None
    pre_spawn: bool = False


@dataclass(frozen=True)
class LiveHintInputs:
    role: dict[str, Any] | None
    gold: GoldHintInputs
    map_enabled: bool
    carry_advisor: bool
    key_item: dict[str, Any] | None = None
    save_item: dict[str, Any] | None = None
    lane_record: dict[str, Any] | None = None
    # The counter item to plan for against the enemy draft (situational_items.draft_item).
    draft_item: dict[str, Any] | None = None
    # A hero plan's advice with no item for the lineup (hero_items.plan_note).
    plan_note: dict[str, Any] | None = None
    # The abilities a fight summary names ({names, labels}; hero_items.plan_fight).
    fight_abilities: dict[str, Any] | None = None
    skill_build: dict[str, Any] | None = None


def render_live_hints(
    memory: MatchMemory,
    state: Mapping[str, Any],
    extra: Mapping[str, Any],
    trackers: LiveTrackerSnapshot,
    inputs: LiveHintInputs,
    lang: str,
) -> dict[str, object]:
    """Caller owns memory; this function performs no provider, file or network I/O."""
    role = inputs.role
    role_name = role.get("role") if role else None
    clock_value = extra.get("clock_time")
    clock = clock_value if isinstance(clock_value, int) else None
    gold_value = state.get("gold")
    buyback = extra.get("buyback_cost")
    result: dict[str, object] = {"live_role": role}
    if trackers.skill_bar:
        result["skill_bar"] = trackers.skill_bar
    gold = memory.gold.tip(
        clock,
        lang,
        gold=gold_value if isinstance(gold_value, int) else None,
        alive=extra.get("alive") is not False,
        role=role_name,
        buyback_cost=buyback if isinstance(buyback, int) else None,
        next_item=inputs.gold.next_item,
        buy_now=inputs.gold.buy_now,
        start_items=inputs.gold.start_items,
        pre_spawn=inputs.gold.pre_spawn,
    )
    skill = memory.skills.tip(
        clock,
        lang,
        alive=extra.get("alive") is not False,
        build=inputs.skill_build,
        hero=str(state.get("hero") or "") or None,
        lane_pressure=lane_pressure(state, extra, inputs.lane_record),
    )
    if inputs.map_enabled:
        last_hits = extra.get("last_hits")
        hint = map_hint(
            clock,
            role_name,
            memory.tips,
            alive=extra.get("alive") is not False,
            has_ward=extra.get("has_observer")
            if isinstance(extra.get("has_observer"), bool)
            else None,
            ward_charges=extra.get("observer_charges")
            if isinstance(extra.get("observer_charges"), int)
            else None,
            lang=lang,
            tp_missing=trackers.tp_missing,
            carry_advisor=inputs.carry_advisor,
            last_hits=last_hits if isinstance(last_hits, int) else None,
            level=extra.get("hero_level") if isinstance(extra.get("hero_level"), int) else None,
            deaths=extra.get("deaths") if isinstance(extra.get("deaths"), int) else None,
            gold=gold_value if isinstance(gold_value, int) else None,
            lane=role.get("lane") if role else None,
            items=extra.get("item_names") if isinstance(extra.get("item_names"), list) else None,
            key_item=inputs.key_item,
            save_item=inputs.save_item,
            score_gap=score_gap(dict(extra)),
            enemies=trackers.enemies or None,
            bottle_rune=extra.get("bottle_rune")
            if isinstance(extra.get("bottle_rune"), str)
            else None,
            denies=extra.get("denies") if isinstance(extra.get("denies"), int) else None,
            hp=state.get("hp_percent") if isinstance(state.get("hp_percent"), int) else None,
            regen=extra.get("regen_items") if isinstance(extra.get("regen_items"), list) else None,
            missing=trackers.missing,
            lane_record=inputs.lane_record,
            draft_item=inputs.draft_item,
            plan_note=inputs.plan_note,
            fight=_fight(memory, extra, trackers, inputs, clock),
            plan=extra.get("live_plan") if isinstance(extra.get("live_plan"), dict) else None,
            farm=extra.get("farm_target") if isinstance(extra.get("farm_target"), dict) else None,
            enemy_group=enemy_group(
                extra.get("enemy_units") if isinstance(extra.get("enemy_units"), list) else None,
                extra.get("xpos"),
                extra.get("ypos"),
                extra.get("team_name"),
            ),
            roshan_open=trackers.roshan_open,
            objective=trackers.objective,
            skill=skill,
        )
        strip = timer_strip(clock, role_name, lang, trackers.roshan_strip)
        if strip:
            result["timer_strip"] = strip
    else:
        hint = skill
    hint = _with_gold_hint(hint, gold)
    seen = role.get("mismatch") if role else None
    if seen and clock is not None and not _keeps_hint(hint):
        hint = memory.tips.role_mismatch(clock, lang, str(role_name), str(seen)) or hint
    if hint is not None:
        result["map_hint"] = hint
    return result


# A hard lane for the skill tip: in the first LANE_PRESSURE_UNTIL seconds, a death,
# health at or under LANE_PRESSURE_HP %, or a lane opponent the player usually
# loses to (lane_duel.lane_record_for).
LANE_PRESSURE_UNTIL = 10 * 60
LANE_PRESSURE_HP = 50


def lane_pressure(
    state: Mapping[str, Any], extra: Mapping[str, Any], lane_record: dict[str, Any] | None
) -> bool:
    clock = extra.get("clock_time")
    if not isinstance(clock, int) or not 0 <= clock < LANE_PRESSURE_UNTIL:
        return False
    deaths, hp = extra.get("deaths"), state.get("hp_percent")
    return (
        (isinstance(deaths, int) and deaths >= 1)
        or (isinstance(hp, int) and hp <= LANE_PRESSURE_HP)
        or (lane_record or {}).get("kind") == "hard"
    )


def _keeps_hint(hint: dict[str, Any] | None) -> bool:
    return hint is not None and (
        bool(hint.get("over_plan"))
        or str(hint.get("id") or "").startswith(("missing", "roshan", "aegis"))
    )


def _with_gold_hint(
    hint: dict[str, Any] | None, gold: dict[str, Any] | None
) -> dict[str, Any] | None:
    if gold is None or _keeps_hint(hint):
        return hint
    return gold


def _fight(
    memory: MatchMemory,
    extra: Mapping[str, Any],
    trackers: LiveTrackerSnapshot,
    inputs: LiveHintInputs,
    clock: Any,
) -> dict[str, Any] | None:
    """A fight the player is not in (fight_summary.py), with what the card says:
    where, who is there, the player's TP and fight abilities."""
    from app.fight_summary import ability_states, find_fight, nearest_tower
    from app.skill_build import label

    if not isinstance(clock, int) or extra.get("alive") is False:
        return None
    fight = find_fight(
        extra.get("ally_units"),
        extra.get("enemy_units"),
        extra.get("xpos"),
        extra.get("ypos"),
        clock=clock,
        recent_kills=memory.fights.kills_since(clock),
        known_enemies=list(trackers.enemies or []),
    )
    if fight is None:
        return None
    wanted = inputs.fight_abilities or {}
    names = list(wanted.get("names") or [])
    labels = dict(wanted.get("labels") or {})
    if not names:
        skills = extra.get("skills") if isinstance(extra.get("skills"), dict) else {}
        ultimate = (skills or {}).get("ultimate") or {}
        if ultimate.get("raw_name") and not ultimate.get("passive"):
            names = [str(ultimate["raw_name"])]
    for name in names:
        labels.setdefault(name, label(name))
    team = extra.get("team_name")
    tower = nearest_tower(fight, extra.get("towers"))
    return {
        **fight,
        "team": team,
        "tower": tower,
        "has_tp": extra.get("has_tp"),
        "tp_cooldown": extra.get("tp_cooldown"),
        "abilities": ability_states(extra.get("abilities"), names, labels),
    }
