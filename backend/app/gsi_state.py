"""
gsi_state.py — in-memory Dota 2 Game State Integration state for MVP overlay use.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.ability_normalization import normalize_abilities as _normalize_abilities
from app.advice_context import MAP_CENTER, build_advice_context
from app.config import GSI_DEBUG_LOG, GSI_DEBUG_SAMPLES_DIR
from app.domain_contracts import NormalizedState
from app.dota_constants import hero_id_from_any, hero_name
from app.enemy_heroes import visible_enemy_heroes, visible_enemy_units
from app.gsi_snapshot import GSIRegister, GSISnapshot
from app.gsi_values import MAX_GSI_NUMBER as MAX_GSI_NUMBER
from app.gsi_values import first_value as _first_value
from app.gsi_values import optional_bool as _optional_bool
from app.gsi_values import optional_int as _optional_int
from app.gsi_values import optional_number as _optional_number
from app.gsi_values import optional_str as _optional_str
from app.gsi_values import title_from_token as _title_from_token
from app.hero_profiles import evaluate_laning_context, load_hero_profile
from app.hero_safety import evaluate_hero_safety
from app.item_timing import normalize_item_name
from app.last_moments import active_slot, ready_savers
from app.live_tools import bottle_rune, regen_items, wand_charges
from app.map_hints import has_observer_ward, item_names, observer_charges, timers
from app.minimap_units import towers, visible_ally_units
from app.signal_capabilities import capability_summary, live_gsi_observed_capabilities
from app.skill_tips import read_skills
from app.tp_tracker import has_teleport, teleport_cooldown, teleport_in_stash

_GSI = GSIRegister()

_DEBUG_TOP_LEVEL_FIELDS = (
    "map",
    "player",
    "hero",
    "items",
    "abilities",
    "buildings",
    "draft",
    "provider",
)

_ITEM_NAME_MAP = {
    "item_bfury": "Battle Fury",
    "item_power_treads": "Power Treads",
    "item_phase_boots": "Phase Boots",
    "item_ring_of_health": "Ring of Health",
    "item_claymore": "Claymore",
    "item_magic_wand": "Magic Wand",
    "item_manta": "Manta Style",
    "item_maelstrom": "Maelstrom",
    "item_helm_of_the_dominator": "Helm of the Dominator",
    "item_tango": "Tango",
    "item_branches": "Iron Branch",
}

_EMPTY_ITEM_NAMES = {"", "empty", "item_empty", "item_unknown", "item_none"}


def update_latest_gsi(
    payload: dict[str, Any], *, enrich: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    # Warm the lazy profile file/alias cache before acquiring writer ownership.
    # The normalizer and live-memory callback subsequently use in-memory data.
    load_hero_profile("")
    timers()
    snapshot = _GSI.update(payload, normalize_gsi_payload, enrich=enrich)
    _write_debug_payload_sample(snapshot.raw, snapshot.timestamp)
    return _current(snapshot)


def reset_latest_gsi(reset_context: Callable[[], None] | None = None) -> None:
    _GSI.reset(reset_context)


def hero_from_gsi(payload: dict[str, Any]) -> str:
    """Select the canonical hero before any register ownership or metadata I/O."""
    hero_block = _dict_value(payload.get("hero"))
    return _normalize_hero_name(
        _first_value(
            payload.get("hero_name"),
            payload.get("hero") if isinstance(payload.get("hero"), str) else None,
            hero_block.get("name"),
        )
    )


# Game rules states before the heroes are on the map.
_PRE_SPAWN_STATES = frozenset(
    {
        "DOTA_GAMERULES_STATE_HERO_SELECTION",
        "DOTA_GAMERULES_STATE_STRATEGY_TIME",
        "DOTA_GAMERULES_STATE_TEAM_SHOWCASE",
        "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD",
        "DOTA_GAMERULES_STATE_WAIT_FOR_PLAYERS_TO_LOAD",
    }
)
PRE_SPAWN_STATES = _PRE_SPAWN_STATES

# Dota game rules states in which a hero is picked and the match is on.
_IN_MATCH_GAME_STATES = frozenset(
    {
        "DOTA_GAMERULES_STATE_STRATEGY_TIME",
        "DOTA_GAMERULES_STATE_TEAM_SHOWCASE",
        "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD",
        "DOTA_GAMERULES_STATE_PRE_GAME",
        "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
    }
)


def is_in_match() -> bool:
    """True when the latest GSI payload comes from a running match with a picked hero.

    Main-menu heartbeats and hero selection also post to /gsi, so freshness alone
    does not mean the player is in a game.
    """
    return _is_in_match(_GSI.capture())


def _is_in_match(snapshot: GSISnapshot | None) -> bool:
    if snapshot is None:
        return False
    hero = str(snapshot.state.get("hero") or "")
    if not hero or hero == "Unknown":
        return False
    map_block = snapshot.raw.get("map")
    game_state = map_block.get("game_state") if isinstance(map_block, dict) else None
    # The GSI config enables "map", so real match payloads always carry it.
    return str(game_state) in _IN_MATCH_GAME_STATES


def post_game_match_id() -> int | None:
    """The match id while Dota shows the score screen after a match (POST_GAME)."""
    snapshot = _GSI.capture()
    if snapshot is None:
        return None
    map_block = snapshot.raw.get("map")
    if not isinstance(map_block, dict):
        return None
    if map_block.get("game_state") != "DOTA_GAMERULES_STATE_POST_GAME":
        return None
    try:
        return int(str(map_block.get("matchid")))
    except (TypeError, ValueError):
        return None


def get_current_state() -> dict[str, Any]:
    return _current(_GSI.capture())


def _current(snapshot: GSISnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "status": "waiting_for_gsi",
            "timestamp": None,
            "state": None,
        }

    return {
        "status": "ok",
        "timestamp": snapshot.timestamp,
        "state": snapshot.state,
    }


def get_gsi_debug_latest() -> dict[str, Any]:
    snapshot = _GSI.capture()
    fields = _debug_fields(snapshot.raw if snapshot else {})
    if snapshot is None:
        return {
            "status": "waiting_for_gsi",
            "timestamp": None,
            "latest_raw_payload": None,
            "latest_normalized_state": None,
            "top_level_keys": [],
            "detected_available_fields": _detected_available_fields(None),
            "fields_summary": fields,
        }

    return {
        "status": "ok",
        "timestamp": snapshot.timestamp,
        "latest_raw_payload": snapshot.raw,
        "latest_normalized_state": snapshot.state,
        "top_level_keys": sorted(snapshot.raw.keys()),
        "detected_available_fields": _detected_available_fields(snapshot.raw),
        "fields_summary": fields,
    }


def get_gsi_debug_fields() -> dict[str, Any]:
    snapshot = _GSI.capture()
    return _debug_fields(snapshot.raw if snapshot else {})


def get_gsi_status_snapshot() -> dict[str, Any]:
    snapshot = _GSI.capture()
    return {
        **_current(snapshot),
        "fields_summary": _debug_fields(snapshot.raw if snapshot else {}),
        "in_match": _is_in_match(snapshot),
    }


def _debug_fields(payload: dict[str, Any]) -> dict[str, Any]:
    hero_block = _dict_value(payload.get("hero"))
    player_block = _dict_value(payload.get("player"))
    map_block = _dict_value(payload.get("map"))
    return {
        "has_map": _has_payload_field(payload, "map"),
        "has_player": _has_payload_field(payload, "player"),
        "has_hero": _has_payload_field(payload, "hero"),
        "has_items": _has_payload_field(payload, "items"),
        "has_abilities": _has_payload_field(payload, "abilities"),
        "has_buildings": _has_payload_field(payload, "buildings"),
        "has_draft": _has_payload_field(payload, "draft"),
        "available_hero_fields": sorted(hero_block.keys()),
        "available_player_fields": sorted(player_block.keys()),
        "available_map_fields": sorted(map_block.keys()),
    }


def _detected_available_fields(payload: dict[str, Any] | None) -> dict[str, bool]:
    payload = payload or {}
    return {field: _has_payload_field(payload, field) for field in _DEBUG_TOP_LEVEL_FIELDS}


def _has_payload_field(payload: dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if value is None:
        return False
    if isinstance(value, (dict, list, str)):
        return bool(value)
    return True


def _write_debug_payload_sample(payload: dict[str, Any], timestamp: str) -> None:
    if not GSI_DEBUG_LOG:
        return

    safe_timestamp = timestamp.replace(":", "").replace("-", "").replace("+", "_").replace(".", "_")
    GSI_DEBUG_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    path = GSI_DEBUG_SAMPLES_DIR / f"gsi_payload_{safe_timestamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_gsi_payload(
    payload: dict[str, Any],
    previous_extra_context: dict[str, Any] | None = None,
) -> NormalizedState:
    hero_block = _dict_value(payload.get("hero"))
    player_block = _dict_value(payload.get("player"))
    map_block = _dict_value(payload.get("map"))
    phase = map_block.get("game_state")
    pre_spawn = isinstance(phase, str) and phase in _PRE_SPAWN_STATES
    # Before the heroes spawn (strategy time, the showcase, loading) GSI reports the
    # picked hero as not alive: that is no death (a «respawn» card came at 00:00).
    # Nor is the first second of the pre-game, when the hero is being placed on the
    # map: not alive with no death counted yet (a «plan a safer route» card at -1:28).
    if hero_block.get("alive") is False and (pre_spawn or player_block.get("deaths") == 0):
        hero_block = {**hero_block, "alive": True}
        payload = {**payload, "hero": hero_block}

    hero = hero_from_gsi(payload)
    if payload.get("minute") is not None:
        minute = _clamp_int(payload.get("minute"), 0, 90, default=0)
    else:
        minute = _normalize_minute(
            _first_value(map_block.get("clock_time"), map_block.get("game_time"))
        )
    level = _clamp_int(
        _first_value(payload.get("level"), hero_block.get("level")), 1, 30, default=1
    )
    gold = _clamp_int(
        _first_value(payload.get("gold"), player_block.get("gold")), 0, None, default=0
    )
    hp_percent = _normalize_hp_percent(payload, hero_block)
    game_state = _normalize_game_state(payload, map_block)
    team_status = _normalize_team_status(payload, hero_block)
    items = _normalize_items(payload.get("items"))
    extra_context = _normalize_extra_context(
        payload,
        map_block=map_block,
        player_block=player_block,
        hero_block=hero_block,
        previous_extra_context=previous_extra_context,
    )

    state: NormalizedState = {
        "hero": hero,
        "role": "carry",
        "minute": minute,
        "level": level,
        "gold": gold,
        "items": items,
        "hp_percent": hp_percent,
        "game_state": game_state,
        "team_status": team_status,
        "extra_context": extra_context,
    }
    state["extra_context"].update(evaluate_hero_safety(state))
    state["extra_context"]["laning_context"] = evaluate_laning_context(state)
    state["extra_context"].update(build_advice_context(state))
    return state


def _map_coordinate(value: Any) -> float | int | None:
    """Live GSI reports world coordinates (map centre 0, about ±8000); the replay-derived
    states and advice_context.py use the replay's absolute ones (centre MAP_CENTER)."""
    number = _optional_number(value)
    return None if number is None else number + MAP_CENTER


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _observed_level(payload: dict[str, Any], hero_block: dict[str, Any]) -> int | None:
    level = _optional_int(_first_value(payload.get("level"), hero_block.get("level")))
    return level if level is not None and 1 <= level <= 30 else None


def _normalize_extra_context(
    payload: dict[str, Any],
    *,
    map_block: dict[str, Any],
    player_block: dict[str, Any],
    hero_block: dict[str, Any],
    previous_extra_context: dict[str, Any] | None,
) -> dict[str, Any]:
    reliable_gold = _optional_int(player_block.get("gold_reliable"))
    unreliable_gold = _optional_int(player_block.get("gold_unreliable"))
    gold = _optional_int(_first_value(player_block.get("gold"), payload.get("gold")))
    available_gold = _available_gold(
        reliable_gold=reliable_gold,
        unreliable_gold=unreliable_gold,
        gold=gold,
    )
    buyback_cost = _optional_int(hero_block.get("buyback_cost"))
    buyback_cooldown = _optional_int(hero_block.get("buyback_cooldown"))
    status_effects = _status_effects(hero_block)
    abilities = _normalize_abilities(payload.get("abilities"))
    minute = _normalize_minute(
        _first_value(map_block.get("clock_time"), map_block.get("game_time"))
    )
    match_id, is_demo_or_lobby = _normalize_match_id(
        _first_value(map_block.get("matchid"), map_block.get("match_id"))
    )
    demo_values_detected = _demo_values_detected(
        gold=gold, gpm=_optional_int(player_block.get("gpm")), minute=minute
    )
    has_abilities = _has_payload_field(payload, "abilities")
    has_buildings = _has_payload_field(payload, "buildings")
    has_position = hero_block.get("xpos") is not None and hero_block.get("ypos") is not None
    previous_for_deltas = (
        previous_extra_context
        if previous_extra_context and previous_extra_context.get("match_id") == match_id
        else None
    )
    capabilities = capability_summary(
        "live_gsi",
        observed=live_gsi_observed_capabilities(
            has_abilities=has_abilities,
            has_buildings=has_buildings,
            has_position=has_position,
        ),
    )

    context: dict[str, Any] = {
        "source_type": "live_gsi",
        "context_confidence": "high",
        **capabilities,
        "mana_percent": _normalize_mana_percent(hero_block),
        "mana": _optional_int(hero_block.get("mana")),
        "max_mana": _optional_int(hero_block.get("max_mana")),
        "health": _optional_int(hero_block.get("health")),
        "max_health": _optional_int(hero_block.get("max_health")),
        "alive": _optional_bool(hero_block.get("alive")),
        "respawn_seconds": _optional_int(hero_block.get("respawn_seconds")),
        "xpos": _map_coordinate(hero_block.get("xpos")),
        "ypos": _map_coordinate(hero_block.get("ypos")),
        "stunned": _optional_bool(hero_block.get("stunned")) or False,
        "silenced": _optional_bool(hero_block.get("silenced")) or False,
        "hexed": _optional_bool(hero_block.get("hexed")) or False,
        "disarmed": _optional_bool(hero_block.get("disarmed")) or False,
        "muted": _optional_bool(hero_block.get("muted")) or False,
        "break_status": _optional_bool(hero_block.get("break")) or False,
        "magicimmune": _optional_bool(hero_block.get("magicimmune")) or False,
        # Any debuff on the hero (None when the payload has no such field):
        # status_source.py tells an own hidden phase from an enemy stun with it.
        "has_debuff": hero_block.get("has_debuff")
        if isinstance(hero_block.get("has_debuff"), bool)
        else None,
        "smoked": _optional_bool(hero_block.get("smoked")) or False,
        "buyback_cost": buyback_cost,
        "buyback_cooldown": buyback_cooldown,
        "gold_reliable": reliable_gold,
        "gold_unreliable": unreliable_gold,
        "available_gold": available_gold,
        "buyback_available": _buyback_available(
            available_gold=available_gold,
            buyback_cost=buyback_cost,
            buyback_cooldown=buyback_cooldown,
        ),
        "kills": _optional_int(player_block.get("kills")),
        "kill_streak": _optional_int(player_block.get("kill_streak")),
        "deaths": _optional_int(player_block.get("deaths")),
        "assists": _optional_int(player_block.get("assists")),
        "last_hits": _optional_int(player_block.get("last_hits")),
        "denies": _optional_int(player_block.get("denies")),
        "gpm": _optional_int(player_block.get("gpm")),
        "xpm": _optional_int(player_block.get("xpm")),
        "player_slot": _optional_int(player_block.get("player_slot")),
        "team_name": _optional_str(player_block.get("team_name")),
        "team_slot": _optional_int(player_block.get("team_slot")),
        "radiant_score": _optional_int(map_block.get("radiant_score")),
        "dire_score": _optional_int(map_block.get("dire_score")),
        "match_id": match_id,
        "is_demo_or_lobby": is_demo_or_lobby,
        "demo_values_detected": demo_values_detected,
        "game_time": _optional_int(map_block.get("game_time")),
        "clock_time": _optional_int(map_block.get("clock_time")),
        "daytime": _optional_bool(map_block.get("daytime")),
        "paused": _optional_bool(map_block.get("paused")) or False,
        "paused_observed": map_block.get("paused")
        if isinstance(map_block.get("paused"), bool)
        else None,
        # Preserve unknown separately from the legacy false defaults. Hero
        # preparation never treats a missing disable flag as confirmed clear.
        "observed_status": {
            flag: hero_block.get(flag) if isinstance(hero_block.get(flag), bool) else None
            for flag in ("stunned", "hexed", "silenced", "muted", "disarmed", "smoked")
        },
        "aghanims_scepter": hero_block.get("aghanims_scepter")
        if isinstance(hero_block.get("aghanims_scepter"), bool)
        else None,
        "aghanims_shard": hero_block.get("aghanims_shard")
        if isinstance(hero_block.get("aghanims_shard"), bool)
        else None,
        "has_abilities": has_abilities,
        "has_buildings": has_buildings,
        # TP scroll in its slot or Boots of Travel (None: no items block).
        "has_tp": has_teleport(payload.get("items")),
        # A TP scroll bought but still in the stash (None: no items block).
        "tp_in_stash": teleport_in_stash(payload.get("items")),
        # Seconds until it can be used (0 ready; None: none or unknown).
        "tp_cooldown": teleport_cooldown(payload.get("items")),
        # Observer ward in the inventory (support tip; None: no items block).
        "has_observer": has_observer_ward(payload.get("items")),
        # How many observer wards are carried (a ward kept in the bag: support tip).
        "observer_charges": observer_charges(payload.get("items")),
        "skills": read_skills(payload),
        # Item names in the inventory and stash (role tips such as the mid's Bottle).
        "item_names": item_names(payload.get("items")),
        # Where each item is: the six active slots (pressable), the stash
        # (bought, not delivered). None without an items block.
        "active_items": _slot_names(payload.get("items"), stash=False),
        "stash_items": _slot_names(payload.get("items"), stash=True),
        # Roshan kills and Aegis pickups (roshan_timer.py), and the player's Aegis.
        "gsi_events": _objective_events(payload.get("events")),
        # Enemy heroes on the player's minimap (enemy_heroes.py; None: no block).
        "visible_enemies": visible_enemy_heroes(
            payload.get("minimap"), player_block.get("team_name"), _normalize_hero_name
        ),
        # The same with their positions (enemy_lanes.py: who laned where, who is missing).
        "enemy_units": visible_enemy_units(
            payload.get("minimap"), player_block.get("team_name"), _normalize_hero_name
        ),
        # Allied heroes and the towers on the minimap (fight_summary.py). The
        # player's own hero is left out: GSI sometimes draws it with the plain
        # ally circle instead of `_self` (seen in 150 snapshots of one match),
        # and the player is no ally of themselves. Own illusions use another icon.
        "ally_units": _without_own_hero(
            visible_ally_units(
                payload.get("minimap"), player_block.get("team_name"), _normalize_hero_name
            ),
            hero_from_gsi(payload),
        ),
        "towers": towers(payload.get("minimap")),
        "has_aegis": _has_aegis(hero_block, payload.get("items")),
        # The player's tier-3 towers and barracks still standing (None: no block).
        "own_base": _own_base(payload.get("buildings"), player_block.get("team_name")),
        # What can be pressed right now (live_tools.py: the survival advice names it).
        "ready_savers": _ready_savers(payload.get("items")),
        "own_castable_items": _own_castable_items(payload.get("items")),
        # Cooldown and charges per active-slot item (None without an items
        # block): an own cast (status_source.py), a consumable used
        # (action_feedback.py).
        "item_cooldowns": _active_item_numbers(payload.get("items"), "cooldown"),
        "item_charges": _active_item_numbers(payload.get("items"), "charges", total=True),
        "wand_charges": wand_charges(payload.get("items")),
        "regen_items": regen_items(payload.get("items")),
        # The rune kept in the Bottle (an escape at low HP, a kill for the mid).
        "bottle_rune": bottle_rune(payload.get("items")),
        # The hero level as sent (None when missing; the state's "level" falls
        # back to 1, which role tips must not read as "behind in levels").
        "hero_level": _observed_level(payload, hero_block),
        "status_effects": status_effects,
        "abilities": abilities,
    }

    # Deaths and team scores only grow within a match: a drop (reconnect, replay
    # seek, a new match reusing the id) is not an event.
    context["death_count_changed"] = _value_increased(previous_for_deltas, context, "deaths")
    context["score_changed"] = _value_increased(
        previous_for_deltas, context, "radiant_score"
    ) or _value_increased(previous_for_deltas, context, "dire_score")
    context["farm_rate_state"] = _farm_rate_state(
        minute=minute,
        last_hits=context.get("last_hits"),
        gpm=context.get("gpm"),
        demo_values_detected=demo_values_detected,
    )
    return {key: value for key, value in context.items() if value is not None}


OBJECTIVE_EVENTS = {"roshan_killed", "aegis_picked_up", "aegis_denied"}


def _objective_events(value: Any) -> list[dict[str, Any]] | None:
    """GSI `events` of Roshan and the Aegis: [{type, game_time}, with the
    killer's `team` and the picker's `player_id` when given] (None without any)."""
    if not isinstance(value, list):
        return None
    events = []
    # Real GSI mixes chat_message, tip and generic_event into the list: read
    # enough of it that a Roshan kill among them is not cut off.
    for event in value[-100:]:
        if not isinstance(event, dict) or event.get("event_type") not in OBJECTIVE_EVENTS:
            continue
        game_time = _optional_int(event.get("game_time"))
        if game_time is None:
            continue
        row: dict[str, Any] = {"type": event["event_type"], "game_time": game_time}
        team = event.get("killed_by_team")
        if team in ("radiant", "dire"):
            row["team"] = team
        player_id = _optional_int(event.get("player_id"))
        if player_id is not None:
            row["player_id"] = player_id
        events.append(row)
    return events or None


def _own_base(buildings: Any, team: Any) -> dict[str, int] | None:
    """How many of the player's own tier-3 towers (of 3) and barracks (of 6)
    still stand: GSI lists the team's buildings and drops a destroyed one."""
    block = (
        buildings.get(team) if isinstance(buildings, dict) and team in ("radiant", "dire") else None
    )
    if not isinstance(block, dict) or not block:
        return None
    names = [name for name in block if isinstance(name, str)]
    return {
        "tower3": sum(1 for name in names if "_tower3_" in name),
        "barracks": sum(1 for name in names if "_rax_" in name),
    }


def _has_aegis(hero_block: dict[str, Any], items: Any) -> bool | None:
    """The player's hero holds the Aegis (hero flag, else the item); None if unknown."""
    flag = hero_block.get("aegis")
    if isinstance(flag, bool):
        return flag
    names = item_names(items)
    if names is None:
        return None
    return "item_aegis" in names


def _own_castable_items(items: Any) -> list[str] | None:
    """Explicit ready observations, excluding passive/backpack/stash items."""
    if not isinstance(items, dict):
        return None
    return [
        item["name"]
        for slot, item in items.items()
        if active_slot(slot)
        and isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("passive") is not True
        and item.get("can_cast") is True
        and _optional_number(item.get("cooldown")) == 0
    ]


def _without_own_hero(units: list[dict[str, Any]] | None, hero: str) -> list[dict[str, Any]] | None:
    if units is None:
        return None
    return [unit for unit in units if unit.get("hero") != hero]


def _slot_names(items: Any, *, stash: bool) -> list[str] | None:
    """Item names in the stash slots, or in the six active slots."""
    if not isinstance(items, dict) or not items:
        return None
    names = []
    for slot, item in items.items():
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or name in _EMPTY_ITEM_NAMES:
            continue
        if str(slot).startswith("stash") if stash else active_slot(slot):
            names.append(name)
    return names


def _active_item_numbers(items: Any, field: str, *, total: bool = False) -> dict[str, float] | None:
    """{item name: field} over the six active slots, only where GSI sends a
    number (`total`: summed over stacks of the same item, else the first)."""
    if not isinstance(items, dict):
        return None
    numbers: dict[str, float] = {}
    for slot, item in items.items():
        if not active_slot(slot) or not isinstance(item, dict):
            continue
        name, value = item.get("name"), _optional_number(item.get(field))
        if not isinstance(name, str) or name in _EMPTY_ITEM_NAMES or value is None:
            continue
        if total:
            numbers[name] = numbers.get(name, 0) + value
        else:
            numbers.setdefault(name, value)
    return numbers


def _ready_savers(items: Any) -> list[str] | None:
    """Rescue items that can be pressed right now (None without an items block)."""
    if not isinstance(items, dict) or not items:
        return None
    return ready_savers(items)


def _normalize_mana_percent(hero_block: dict[str, Any]) -> int | None:
    direct = hero_block.get("mana_percent")
    if direct is not None:
        return _clamp_int(direct, 0, 100, default=100)

    mana = hero_block.get("mana")
    max_mana = hero_block.get("max_mana")
    try:
        if int(max_mana) > 0:
            return _clamp_int(round((int(mana) / int(max_mana)) * 100), 0, 100, default=100)
    except (TypeError, ValueError):
        return None
    return None


def _status_effects(hero_block: dict[str, Any]) -> list[str]:
    effect_fields = {
        "stunned": "stunned",
        "silenced": "silenced",
        "hexed": "hexed",
        "disarmed": "disarmed",
        "muted": "muted",
        "break": "break",
    }
    return [
        label
        for field, label in effect_fields.items()
        if _optional_bool(hero_block.get(field)) is True
    ]


def _available_gold(
    *, reliable_gold: int | None, unreliable_gold: int | None, gold: int | None
) -> int | None:
    if reliable_gold is not None or unreliable_gold is not None:
        return max(0, reliable_gold or 0) + max(0, unreliable_gold or 0)
    return gold


def _buyback_available(
    *,
    available_gold: int | None,
    buyback_cost: int | None,
    buyback_cooldown: int | None,
) -> bool:
    if available_gold is None or buyback_cost is None or buyback_cooldown is None:
        return False
    return buyback_cooldown == 0 and buyback_cost > 0 and available_gold >= buyback_cost


def _normalize_match_id(value: Any) -> tuple[str, bool]:
    text = str(value or "").strip()
    if text in {"", "0", "0.0"}:
        return "local_demo", True
    return text, False


def _demo_values_detected(*, gold: int | None, gpm: int | None, minute: int) -> bool:
    return (gpm is not None and gpm > 2000) or (gold is not None and minute < 10 and gold > 30000)


def _farm_rate_state(
    *,
    minute: int,
    last_hits: int | None,
    gpm: int | None,
    demo_values_detected: bool = False,
) -> str:
    if minute < 10 or demo_values_detected or (gpm is not None and gpm > 2000):
        return "unknown"
    if _farm_threshold_missed(minute, last_hits) or (
        minute >= 15 and gpm is not None and gpm < 400
    ):
        return "slow"
    if last_hits is not None or gpm is not None:
        return "good"
    return "unknown"


def _farm_threshold_missed(minute: int, last_hits: int | None) -> bool:
    if last_hits is None:
        return False
    thresholds = ((25, 170), (20, 120), (15, 80), (10, 45))
    return any(
        minute >= threshold_minute and last_hits < threshold_lh
        for threshold_minute, threshold_lh in thresholds
    )


def _value_increased(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> bool:
    before, now = (previous or {}).get(key), current.get(key)
    if not isinstance(before, int) or not isinstance(now, int):
        return False
    return now > before


def _clamp_int(value: Any, minimum: int, maximum: int | None, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _normalize_minute(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 0
    if seconds < 0:
        return 0
    return min(seconds // 60, 90)


def _normalize_hp_percent(payload: dict[str, Any], hero_block: dict[str, Any]) -> int:
    direct = _first_value(payload.get("hp_percent"), hero_block.get("health_percent"))
    if direct is not None:
        return _clamp_int(direct, 0, 100, default=100)

    health = hero_block.get("health")
    max_health = hero_block.get("max_health")
    try:
        if int(max_health) > 0:
            return _clamp_int(round((int(health) / int(max_health)) * 100), 0, 100, default=100)
    except (TypeError, ValueError):
        pass
    return 100


def _normalize_hero_name(value: Any) -> str:
    """The localized name of any known hero; an unknown npc key title-cased."""
    hero_id = hero_id_from_any(value)
    if hero_id is not None:
        return hero_name(hero_id)
    key = str(value or "").strip().lower().removeprefix("npc_dota_hero_")
    return _title_from_token(key) if key else "Unknown"


def _normalize_items(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            normalized = _normalize_item_name(item)
            if normalized:
                items.append(normalized)
        return items
    if not isinstance(value, dict):
        return []

    items = []
    for slot_name in sorted(value):
        slot = value[slot_name]
        item_name = slot.get("name") if isinstance(slot, dict) else slot
        normalized = _normalize_item_name(item_name)
        if normalized:
            items.append(normalized)
    return items


def _normalize_item_name(value: Any) -> str:
    raw_name = str(value or "").strip()
    key = raw_name.lower()
    if key in _EMPTY_ITEM_NAMES:
        return ""
    if key in _ITEM_NAME_MAP:
        return _ITEM_NAME_MAP[key]
    return normalize_item_name(key)


def normalize_abilities(value: Any) -> list[dict[str, Any]]:
    """The raw GSI abilities block as a list of {name, raw_name, level, cooldown, can_cast}."""
    return _normalize_abilities(value)


def _normalize_game_state(payload: dict[str, Any], map_block: dict[str, Any]) -> str:
    candidates = (
        payload.get("game_state"),
        payload.get("event"),
        map_block.get("name"),
        map_block.get("game_state"),
    )
    # Container reprs can contain words such as "pressure"/"fight". They are
    # invalid event/phase signals, rather than advice context or hashable enums.
    state = next((value for value in candidates if isinstance(value, str)), None)
    return str(state or "gsi_update").strip() or "gsi_update"


def _normalize_team_status(payload: dict[str, Any], hero_block: dict[str, Any]) -> str:
    if payload.get("team_status"):
        return str(payload["team_status"]).strip()
    if hero_block.get("alive") is False:
        return "hero_dead"
    return "unknown"
