"""
signal_capabilities.py - source-specific signal availability matrix.

The assistant should not treat replay or public-match imports as equivalent to
live Dota GSI. This helper keeps that distinction explicit in extra_context.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CORE_SIGNALS = (
    "hp",
    "mana",
    "gold",
    "last_hits",
    "level",
    "items",
    "ability_cooldowns",
    "position",
    "alive_respawn",
    "buildings",
    "score_changes",
    "nearby_allies_enemies",
    "enemy_positions",
    "exact_teamfight_context",
    "objective_context",
    "exact_roshan_context",
)

EXTRA_REPLAY_SIGNALS = (
    "event_timing",
    "purchases",
    "ability_item_use",
    "damage_heal_windows",
    "lane_pressure_from_damage_windows",
)

CAPABILITY_MATRIX: dict[str, dict[str, list[str]]] = {
    "live_gsi": {
        "available": [
            "hp",
            "mana",
            "gold",
            "last_hits",
            "level",
            "items",
            "ability_cooldowns",
            "position",
            "alive_respawn",
            "buildings",
            "score_changes",
        ],
        "partial": [
            "objective_context",
            # Minimap creeps (farm_map.py): own lane creeps always, enemy lane
            # creeps and neutrals only while the team sees them.
            "lane_creeps_in_vision",
            "camps_in_vision",
        ],
        "missing": [
            "nearby_allies_enemies",
            "enemy_positions",
            "exact_teamfight_context",
            "exact_roshan_context",
        ],
    },
    "replay_gsi_like": {
        "available": [
            "event_timing",
            "purchases",
            "ability_item_use",
            "damage_heal_windows",
        ],
        "partial": [
            "items",
            "objective_context",
            "lane_pressure_from_damage_windows",
        ],
        "missing": [
            "hp",
            "mana",
            "gold",
            "last_hits",
            "level",
            "ability_cooldowns",
            "position",
            "alive_respawn",
            "buildings",
            "score_changes",
            "nearby_allies_enemies",
            "enemy_positions",
            "exact_teamfight_context",
            "exact_roshan_context",
        ],
    },
    "opendota_import": {
        "available": [
            "gold",
            "last_hits",
            "level",
            "items",
            "event_timing",
            "purchases",
        ],
        "partial": [
            "alive_respawn",
            "score_changes",
            "objective_context",
            "exact_teamfight_context",
        ],
        "missing": [
            "hp",
            "mana",
            "ability_cooldowns",
            "position",
            "buildings",
            "nearby_allies_enemies",
            "enemy_positions",
            "exact_roshan_context",
        ],
    },
    "synthetic_sample": {
        "available": [
            "hp",
            "mana",
            "gold",
            "last_hits",
            "level",
            "items",
            "ability_cooldowns",
            "position",
            "alive_respawn",
            "event_timing",
            "purchases",
            "ability_item_use",
            "damage_heal_windows",
        ],
        "partial": [
            "objective_context",
            "exact_teamfight_context",
        ],
        "missing": [
            "buildings",
            "score_changes",
            "nearby_allies_enemies",
            "enemy_positions",
            "exact_roshan_context",
        ],
    },
}


def capability_summary(
    source_type: str, *, observed: dict[str, bool] | None = None
) -> dict[str, Any]:
    source = normalize_source_type(source_type)
    summary = deepcopy(CAPABILITY_MATRIX[source])
    observed = observed or {}

    for signal, available in observed.items():
        if available:
            _move_signal(summary, signal, "available")
        else:
            _move_signal(summary, signal, "missing")

    _sort_summary(summary)
    return {
        "capability_source": source,
        "available_signals": summary["available"],
        "partial_signals": summary["partial"],
        "missing_signals": summary["missing"],
    }


def normalize_source_type(source_type: str | None) -> str:
    source = str(source_type or "").strip().lower()
    if source in CAPABILITY_MATRIX:
        return source
    if source in {"gsi", "gsi_live"}:
        return "live_gsi"
    if source in {"opendota", "public_match"}:
        return "opendota_import"
    if source in {"synthetic", "sample"}:
        return "synthetic_sample"
    return "synthetic_sample"


def live_gsi_observed_capabilities(
    *,
    has_abilities: bool,
    has_buildings: bool,
    has_position: bool,
) -> dict[str, bool]:
    return {
        "ability_cooldowns": has_abilities,
        "buildings": has_buildings,
        "position": has_position,
    }


def _move_signal(summary: dict[str, list[str]], signal: str, target: str) -> None:
    if not signal:
        return
    for bucket in ("available", "partial", "missing"):
        summary[bucket] = [item for item in summary[bucket] if item != signal]
    summary[target].append(signal)


def _sort_summary(summary: dict[str, list[str]]) -> None:
    known_order = list(CORE_SIGNALS) + list(EXTRA_REPLAY_SIGNALS)
    order = {signal: index for index, signal in enumerate(known_order)}
    for bucket in ("available", "partial", "missing"):
        summary[bucket] = sorted(
            set(summary[bucket]), key=lambda item: (order.get(item, 999), item)
        )
