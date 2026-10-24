"""Pure ability names/fields; importing it never loads GSI or skill trackers."""

from __future__ import annotations

from typing import Any

from app.gsi_values import (
    first_value,
    optional_bool,
    optional_int,
    optional_number,
    optional_str,
    title_from_token,
)

# Dota Plus wheel/banner entries are not the hero's skills.
NOT_HERO_ABILITY_PREFIXES = ("plus_",)


def not_hero_ability(name: Any) -> bool:
    return isinstance(name, str) and name.startswith(NOT_HERO_ABILITY_PREFIXES)


_ABILITY_NAME_MAP = {
    "antimage_blink": "Blink",
    "anti_mage_blink": "Blink",
    "juggernaut_blade_fury": "Blade Fury",
    "life_stealer_rage": "Rage",
    "lifestealer_rage": "Rage",
    "medusa_mana_shield": "Mana Shield",
    "slark_dark_pact": "Dark Pact",
    "slark_pounce": "Pounce",
    "morphling_morph_agi": "Attribute Shift",
    "morphling_morph_str": "Attribute Shift",
    "morphling_attribute_shift": "Attribute Shift",
    "phantom_assassin_blur": "Blur",
    "drow_ranger_wave_of_silence": "Gust",
    "drow_ranger_gust": "Gust",
    "luna_lucent_beam": "Lucent Beam",
    "sven_warcry": "Warcry",
    "kez_grappling_claw": "Grappling Claw",
    "kez_raptor_dance": "Raptor Dance",
    "kez_echo_slash": "Echo Slash",
    "kez_talon_toss": "Talon Toss",
    "kez_falcon_rush": "Falcon Rush",
    "kez_ravens_veil": "Raven's Veil",
    "kez_kazurai_katana": "Kazurai Katana",
    "kez_switch_weapons": "Switch Weapons",
    "slardar_sprint": "Guardian Sprint",
    "bounty_hunter_wind_walk": "Shadow Walk",
    # Internal names that share no word with the in-game one: without these the
    # profiles' key abilities were never found (Phantom Lancer's escape was
    # invisible to every escape rule).
    "phantom_lancer_doppelwalk": "Doppelganger",
    "obsidian_destroyer_sanity_eclipse": "Sanity's Eclipse",
    "nevermore_requiem": "Requiem of Souls",
    "pangolier_gyroshell": "Rolling Thunder",
}


def normalize_abilities(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw_abilities = value
    elif isinstance(value, dict):
        raw_abilities = [value[key] for key in sorted(value)]
    else:
        raw_abilities = []

    abilities: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw_ability in raw_abilities:
        if isinstance(raw_ability, dict) and not_hero_ability(raw_ability.get("name")):
            continue
        ability = _normalize_ability(raw_ability)
        if not ability:
            continue
        dedupe_key = str(ability.get("name") or ability.get("raw_name") or "").lower()
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)
        abilities.append(ability)
    return abilities


def _normalize_ability(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        raw_name = optional_str(value.get("name"))
        raw_level = optional_number(value.get("level"))
        level = optional_int(raw_level) if raw_level is not None and raw_level % 1 == 0 else None
        cooldown = optional_number(
            first_value(
                value.get("cooldown"), value.get("cooldown_remaining"), value.get("cooldown_time")
            )
        )
        can_cast = optional_bool(value.get("can_cast"))
        if can_cast is None:
            can_cast = optional_bool(value.get("ability_active"))
        observed_cast = value.get("can_cast")
        observed_cast = observed_cast if isinstance(observed_cast, bool) else None
        active = value.get("ability_active")
        active = active if isinstance(active, bool) else None
    else:
        raw_name = optional_str(value)
        level = None
        cooldown = None
        can_cast = None
        observed_cast = None
        active = None

    if not raw_name:
        return None

    return {
        "name": _normalize_ability_name(raw_name),
        "raw_name": raw_name,
        "level": level,
        "cooldown": cooldown,
        "can_cast": can_cast,
        # ability_active only describes the HUD slot, not actual castability.
        "can_cast_observed": observed_cast,
        "ability_active": active,
    }


def _normalize_ability_name(value: Any) -> str:
    raw_name = str(value or "").strip()
    key = raw_name.lower().removeprefix("ability_")
    if key in _ABILITY_NAME_MAP:
        return _ABILITY_NAME_MAP[key]
    return title_from_token(key)
