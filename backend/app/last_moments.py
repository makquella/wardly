"""
last_moments.py - the last seconds before each death, from live GSI.

The match timeline keeps a sample every 15 s, too coarse to say how a death
happened. MatchTracker feeds every GSI tick here; a ring buffer keeps one entry
per second of match clock for the last WINDOW seconds: HP and mana percent,
whether the hero was disabled (stunned, hexed or muted: no items then), and
which saving items were ready (SAVERS: castable, off cooldown; a Magic Wand
from WAND_CHARGES charges).

At a death, summarize() turns the buffer into a small record kept with the
death on the timeline:
- hp: the HP curve (seconds before the death, percent), at most WINDOW points;
- ready: the saving items that were ready at the last alive tick;
- usable: the saving items that were ready on USABLE_SECONDS (2) seconds of
  the last FREE_WINDOW when the hero was not disabled — readiness and the chance to
  press it on the same sample — and still ready at the last alive tick (one
  pressed in those seconds went on cooldown), so only these count as "not used";
- free_s: seconds of the last FREE_WINDOW the hero was not disabled;
- held_s: seconds of the last FREE_WINDOW the hero was stunned or hexed (not
  just muted: a muted hero still moves and casts);
- hexed_s: the seconds of them the hero was hexed (situational_items: Linken's
  against a Hex, Black King Bar against the stuns);
- burst_s: seconds from BURST_FROM % HP or more to the death (a burst kill),
  when that is BURST_SECONDS or less.

GSI only: OpenDota matches have no such record, and a missing value stays out.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

WINDOW = 20
FREE_WINDOW = 5
# Seconds a saver must be ready while the hero is free to count as "not used".
USABLE_SECONDS = 2
BURST_FROM = 70
BURST_SECONDS = 3
WAND_CHARGES = 10

# Items that save a life when pressed in time (escape, dispel, spell immunity,
# a big heal or a save). Names as Dota's GSI reports them.
SAVERS: dict[str, dict[str, str]] = {
    "item_black_king_bar": {"uk": "Black King Bar", "en": "Black King Bar"},
    "item_blink": {"uk": "Blink Dagger", "en": "Blink Dagger"},
    "item_overwhelming_blink": {"uk": "Overwhelming Blink", "en": "Overwhelming Blink"},
    "item_swift_blink": {"uk": "Swift Blink", "en": "Swift Blink"},
    "item_arcane_blink": {"uk": "Arcane Blink", "en": "Arcane Blink"},
    "item_force_staff": {"uk": "Force Staff", "en": "Force Staff"},
    "item_hurricane_pike": {"uk": "Hurricane Pike", "en": "Hurricane Pike"},
    "item_glimmer_cape": {"uk": "Glimmer Cape", "en": "Glimmer Cape"},
    "item_ghost": {"uk": "Ghost Scepter", "en": "Ghost Scepter"},
    "item_ethereal_blade": {"uk": "Ethereal Blade", "en": "Ethereal Blade"},
    "item_cyclone": {"uk": "Eul's Scepter", "en": "Eul's Scepter"},
    "item_wind_waker": {"uk": "Wind Waker", "en": "Wind Waker"},
    "item_manta": {"uk": "Manta Style", "en": "Manta Style"},
    "item_satanic": {"uk": "Satanic", "en": "Satanic"},
    "item_lotus_orb": {"uk": "Lotus Orb", "en": "Lotus Orb"},
    "item_invis_sword": {"uk": "Shadow Blade", "en": "Shadow Blade"},
    "item_silver_edge": {"uk": "Silver Edge", "en": "Silver Edge"},
    "item_sphere": {"uk": "Linken's Sphere", "en": "Linken's Sphere"},
    "item_bloodstone": {"uk": "Bloodstone", "en": "Bloodstone"},
    "item_guardian_greaves": {"uk": "Guardian Greaves", "en": "Guardian Greaves"},
    "item_disperser": {"uk": "Disperser", "en": "Disperser"},
    "item_magic_wand": {"uk": "Magic Wand", "en": "Magic Wand"},
}
# The hero's own safety abilities in `ready` (live_tools.ready_abilities):
# "ability:Blade Fury". Labels are the ability names.
ABILITY_PREFIX = "ability:"
# A rune kept in the Bottle that gets the hero out: "rune:Haste" in `ready`.
RUNE_PREFIX = "rune:"
# Runes a Bottle can hold (GSI items.slot*.contains_rune) → their name.
BOTTLE_RUNES = {
    "haste": "Haste",
    "double_damage": "Double Damage",
    "arcane": "Arcane",
    "invis": "Invisibility",
    "invisibility": "Invisibility",
    "illusion": "Illusion",
    "shield": "Shield",
    "regen": "Regeneration",
    "regeneration": "Regeneration",
    "water": "Water",
    "bounty": "Bounty",
}
# Bottled runes that get a hero out at low HP, best first.
RUNE_ESCAPES = ("Haste", "Invisibility", "Shield", "Illusion")
# Rune names in the genitive: «руна прискорення».
RUNES_UK = {
    "Haste": "прискорення",
    "Invisibility": "невидимості",
    "Shield": "щита",
    "Illusion": "ілюзій",
    "Double Damage": "подвійної шкоди",
    "Arcane": "чарів",
    "Regeneration": "регенерації",
    "Water": "води",
    "Bounty": "багатства",
}
# Passive or needing a target: never "not used" from GSI alone.
_NOT_PRESSED = {"item_sphere"}
# slot0-5 are the inventory; slot6-8 the backpack, whose items real GSI still
# reports with can_cast true although they cannot be pressed.
ACTIVE_SLOTS = {f"slot{index}" for index in range(6)}


def active_slot(slot: Any) -> bool:
    return str(slot) in ACTIVE_SLOTS


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or abs(value) > 10_000_000:  # NaN or broken GSI
        return None
    return float(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def held_rune(item: dict[str, Any]) -> str | None:
    """The rune in a Bottle (BOTTLE_RUNES name); None: empty, unknown or no Bottle."""
    rune = item.get("contains_rune") if item.get("name") == "item_bottle" else None
    return BOTTLE_RUNES.get(rune.lower()) if isinstance(rune, str) else None


def ready_savers(items: dict[str, Any]) -> list[str]:
    """Saving items in the inventory that could be used right now (an escape
    rune in the Bottle as "rune:Haste")."""
    ready: list[str] = []
    for slot, value in items.items():
        if not active_slot(slot):
            continue
        item = _dict(value)
        rune = held_rune(item)
        if rune in RUNE_ESCAPES and item.get("can_cast") is not False:
            if f"{RUNE_PREFIX}{rune}" not in ready:
                ready.append(f"{RUNE_PREFIX}{rune}")
            continue
        name = item.get("name")
        # Broken GSI can put a list or a dict there (unhashable for the checks below).
        if not isinstance(name, str) or name not in SAVERS or name in _NOT_PRESSED or name in ready:
            continue
        if item.get("passive") is True:
            continue
        can_cast = item.get("can_cast")
        cooldown = _number(item.get("cooldown"))
        # Only what GSI says: castable, or at least off cooldown when the field
        # is missing; an item without either field is not claimed ready.
        if can_cast is False or (can_cast is None and cooldown != 0):
            continue
        if cooldown is not None and cooldown > 0:
            continue
        if name == "item_magic_wand" and (_number(item.get("charges")) or 0) < WAND_CHARGES:
            continue
        ready.append(name)
    return ready


def is_disabled(hero: dict[str, Any]) -> bool:
    return any(hero.get(flag) is True for flag in ("stunned", "hexed", "muted"))


def is_held(hero: dict[str, Any]) -> bool:
    """Stunned or hexed: no moving, no spells, no items."""
    return any(hero.get(flag) is True for flag in ("stunned", "hexed"))


class LastSeconds:
    """One entry per second of match clock, the last WINDOW seconds."""

    def __init__(self) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=WINDOW + 1)

    def reset(self) -> None:
        self._entries.clear()

    def observe(
        self,
        clock: int,
        hero: dict[str, Any],
        items: dict[str, Any],
        abilities: list[str] | tuple[str, ...] = (),
    ) -> None:
        """`abilities`: the hero's safety abilities ready on this tick."""
        if hero.get("alive") is not True:
            return
        hp = _number(hero.get("health_percent"))
        if hp is None:
            return
        entry = {
            "t": clock,
            "hp": round(hp),
            "mp": round(_number(hero.get("mana_percent")) or 0),
            "disabled": is_disabled(hero),
            "held": is_held(hero),
            "hexed": hero.get("hexed") is True,
            "ready": ready_savers(items) + [f"{ABILITY_PREFIX}{name}" for name in abilities],
        }
        if self._entries and self._entries[-1]["t"] == clock:
            self._entries[-1] = entry  # the latest tick of that second
        elif self._entries and clock < self._entries[-1]["t"]:
            self._entries.clear()  # the clock went back (a reconnect, a replay)
            self._entries.append(entry)
        else:
            self._entries.append(entry)

    def summarize(self, death_clock: int) -> dict[str, Any] | None:
        entries = [e for e in self._entries if 0 <= death_clock - e["t"] <= WINDOW]
        if not entries:
            return None
        last = entries[-1]
        recent = [e for e in entries if death_clock - e["t"] <= FREE_WINDOW]
        # Ready on USABLE_SECONDS free seconds or more: an escape that came off
        # cooldown a second before the death was no real chance to press it.
        free_ready: Counter[str] = Counter()
        for entry in recent:
            if not entry["disabled"]:
                free_ready.update(entry["ready"])
        usable = [name for name, seconds in free_ready.items() if seconds >= USABLE_SECONDS]
        # Still ready at the last alive tick: an item pressed in those seconds
        # went on cooldown (or a wand lost its charges) and was not left unused.
        usable = [name for name in usable if name in last["ready"]]
        result: dict[str, Any] = {
            "hp": [[e["t"] - death_clock, e["hp"]] for e in entries],
            "ready": list(last["ready"]),
            "usable": usable,
            "free_s": sum(1 for e in recent if not e["disabled"]),
            "held_s": sum(1 for e in recent if e.get("held")),
            "hexed_s": sum(1 for e in recent if e.get("hexed")),
        }
        high = [e for e in entries if e["hp"] >= BURST_FROM]
        if high:
            burst = death_clock - high[-1]["t"]
            if burst <= BURST_SECONDS:
                result["burst_s"] = max(burst, 1)
        self._entries.clear()
        return result


def is_saver(name: Any) -> bool:
    """An item of SAVERS, the hero's ability or a bottled escape rune."""
    return isinstance(name, str) and (
        name in SAVERS or name.startswith((ABILITY_PREFIX, RUNE_PREFIX))
    )


def saver_label(name: str, lang: str) -> str:
    if name.startswith(ABILITY_PREFIX):
        return name[len(ABILITY_PREFIX) :]
    if name.startswith(RUNE_PREFIX):
        rune = name[len(RUNE_PREFIX) :]
        if lang == "uk":
            return f"Bottle (руна {RUNES_UK.get(rune, rune)})"
        return f"Bottle ({rune} rune)"
    names = SAVERS.get(name)
    return names["uk" if lang == "uk" else "en"] if names else name
