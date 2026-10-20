"""
situational_items.py - the next item picked by how the player dies in this
match, before the hero's usual build (next_item.py).

The live recording already knows the last seconds of every death
(last_moments.py): how many of the last 5 seconds the hero was free to act
(`free_s`) and whether it went from 70 %+ health to dead in 3 seconds or less
(`burst_s`). Two such deaths in one match are a pattern with a known answer:

- disabled to death (stunned or hexed on all but at most 1 recorded second of
  the last 5, with at least 3 seconds recorded; a mute alone does not count —
  the hero still moves and casts, and BKB cannot be pressed muted): Black King
  Bar — magic immunity, no stun holds you — or, "by the situation", Linken's
  Sphere when those deaths were mostly in a Hex (last_moments `hexed_s`) and a
  hexer is in the enemy team; the other one is named as the alternative;
- burst down: Aeon Disk — the next burst triggers it instead of killing.

`draft_item` is the same counter to the enemy lineup, read early (DRAFT_MIN_ENEMIES
heroes seen) as an item to plan for, without the minute gates.

The player's own hero can have a plan (hero_items.py, data/heroes/item_plans):
its counters come right after the death patterns and replace the generic ones
of the same family (Terrorblade: Bloodthorn or Monkey King Bar against
evasion, his Eye of Skadi earlier against healing, no Maelstrom).

Cores only (the carry advisor): a support's item advice is the save item tip.
Nothing when the item (or something built from it) is already owned.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.hero_items import TEMPO_WHY, format_reason
from app.hero_meta import item_key, item_name
from app.next_item import _contains, _cost, gold_left, has_components

MIN_DEATHS = 2
FREE_WINDOW = 5
MIN_RECORDED = 3
MAX_FREE = 1

RULES = (
    # (why, item key, English name when the item constants are not cached)
    ("disabled", "black_king_bar", "Black King Bar"),
    ("burst", "aeon_disk", "Aeon Disk"),
)


def disable_kind(last: Any) -> str | None:
    """For a death held by disables: 'hex' when the hero was hexed for at least
    half of the held seconds, 'stun' when never hexed; None for older records."""
    if not isinstance(last, dict):
        return None
    held, hexed = last.get("held_s"), last.get("hexed_s")
    if not isinstance(held, int) or not isinstance(hexed, int) or held <= 0:
        return None
    return "hex" if hexed * 2 >= held else "stun"


def death_kind(last: Any) -> str | None:
    """'disabled', 'burst' or None for one death's last-moments summary."""
    if not isinstance(last, dict):
        return None
    hp = last.get("hp") if isinstance(last.get("hp"), list) else []
    recorded = [p for p in hp if isinstance(p, list) and len(p) == 2 and -FREE_WINDOW <= p[0] <= 0]
    held = last.get("held_s")  # older records have none: say nothing
    if len(recorded) >= MIN_RECORDED and isinstance(held, int) and len(recorded) - held <= MAX_FREE:
        return "disabled"
    if isinstance(last.get("burst_s"), int):
        return "burst"
    return None


# Counters to the enemy heroes seen in the match (enemy_heroes.py), by the
# player's usual position: a right-click carry against evasion or illusions;
# from these minutes on, when the build usually has room. Heavy healing gets no
# generic item: Spirit Vessel is a support's in high-rank games (none of the 10
# offlaners builds it; the player's review, 2026-10-20), a carry's or mid's own
# plan names Eye of Skadi or Spirit Vessel from the build.
EVASION_MINUTE = 15
ILLUSION_MINUTE = 12
# A lineup of magic damage (draft_analysis.MAGIC_DAMAGE, 3+ seen): Pipe of
# Insight for an offlaner, Black King Bar for a carry or a mid.
MAGIC_MINUTE = 14
# Heroes whose strength is a passive that break (Silver Edge) turns off; for a
# carry or a mid from this minute on.
BREAK_PASSIVES = {
    "Bristleback": "Bristleback",
    "Spectre": "Dispersion",
    "Huskar": "Berserker's Blood",
}
BREAK_MINUTE = 18
CORE_POSITIONS = {"carry", "mid", "offlane"}
# The early read of the enemy draft: once this many enemy heroes are seen.
DRAFT_MIN_ENEMIES = 4
# Past every minute gate above: the draft read names the item to plan for.
_ANY_MINUTE = 60


Candidate = tuple[str, str, str, int, str | None, str | None, dict[str, Any]]


def _candidates(
    kinds: Counter[str | None],
    enemies: list[str],
    position: str | None,
    minute: int | None,
    hero: str | None = None,
    net_worth: int | None = None,
    disables: Counter[str | None] | None = None,
) -> list[Candidate]:
    """(why, item key, fallback name, deaths, enemy, spell, extra), in priority
    order; `extra` carries a hero plan's escape hero and family items."""
    from app.draft_analysis import (
        COUNTERS,
        MAGIC_DAMAGE,
        MAGIC_LINEUP_MIN,
        TARGETED_DISABLES,
        TARGETED_ITEM,
        TARGETED_NAME,
    )
    from app.hero_items import hero_rows, plan_for, replaced, tempo_rows

    rows: list[Candidate] = []
    held = kinds.get("disabled", 0)
    targeted = next((e for e in enemies if e in TARGETED_DISABLES), None)
    hexer = next((e for e in enemies if TARGETED_DISABLES.get(e) == "Hex"), None)
    hexes, stuns = (disables or Counter()).get("hex", 0), (disables or Counter()).get("stun", 0)
    linken: Candidate | None = None
    if targeted and position in CORE_POSITIONS and held >= MIN_DEATHS:
        # Held to death with a single-target disable in the enemy team: Linken's
        # blocks it (Primal Roar, Duel and Doom go through BKB).
        enemy = hexer if hexer and hexes else targeted
        linken = (
            "targeted",
            TARGETED_ITEM,
            TARGETED_NAME,
            held,
            enemy,
            TARGETED_DISABLES[enemy],
            {},
        )
    bkb: Candidate | None = None
    if held >= MIN_DEATHS:
        bkb = ("disabled", "black_king_bar", "Black King Bar", held, None, None, {})
    if linken is not None and bkb is not None and hexes + stuns:
        # By the situation: the Hex deaths ask for Linken's, the stuns for BKB;
        # the other item is named as the alternative.
        if hexer and hexes >= stuns:
            linken[6]["alternative"] = _alternative(bkb) if stuns else None
            rows += [linken, bkb]
        else:
            bkb[6]["alternative"] = _alternative(linken)
            rows += [bkb, linken]
    else:
        rows += [row for row in (linken, bkb) if row is not None]
    for why, key, fallback in RULES:
        if why != "disabled" and kinds.get(why, 0) >= MIN_DEATHS:
            rows.append((why, key, fallback, kinds[why], None, None, {}))
    plan = plan_for(hero, position)
    skip: set[str] = set()
    if plan is not None:
        tempo = tempo_rows(plan, net_worth, minute)
        if tempo is not None:
            # Farmed far ahead of the curve: the counters wait, the tempo build
            # goes on (owned
            # items are passed over below).
            return rows + [
                (
                    TEMPO_WHY,
                    row["key"],
                    row["name"],
                    net_worth or 0,
                    None,
                    None,
                    {"reason": row["reason"]},
                )
                for row in tempo
            ]
        skip = replaced(plan)
        for row in hero_rows(plan, enemies, minute):
            extra = {
                "escape": row["escape"],
                "family_items": row["family_items"],
                "reason": row["reason"],
            }
            rows.append((row["why"], row["key"], row["name"], 0, row["enemy"], row["spell"], extra))
    generic: list[Candidate] = []
    evasive = next((e for e in enemies if e in COUNTERS["evasion"][0]), None)
    if evasive and position == "carry" and (minute or 0) >= EVASION_MINUTE:
        generic.append(("evasion", "monkey_king_bar", "Monkey King Bar", 0, evasive, None, {}))
    illusionist = next((e for e in enemies if e in COUNTERS["illusions"][0]), None)
    if illusionist and position == "carry" and (minute or 0) >= ILLUSION_MINUTE:
        generic.append(("illusions", "maelstrom", "Maelstrom", 0, illusionist, None, {}))
    passive = next((e for e in enemies if e in BREAK_PASSIVES), None)
    if passive and position in ("carry", "mid") and (minute or 0) >= BREAK_MINUTE:
        generic.append(
            ("break", "silver_edge", "Silver Edge", 0, passive, BREAK_PASSIVES[passive], {})
        )
    magic = [e for e in enemies if e in MAGIC_DAMAGE]
    if len(magic) >= MAGIC_LINEUP_MIN and (minute or 0) >= MAGIC_MINUTE:
        if position == "offlane":
            generic.append(("magic", "pipe", "Pipe of Insight", len(magic), magic[0], None, {}))
        elif position in ("carry", "mid"):
            generic.append(
                ("magic", "black_king_bar", "Black King Bar", len(magic), magic[0], None, {})
            )
    return rows + [row for row in generic if row[0] not in skip]


def _alternative(row: Candidate) -> dict[str, Any]:
    return {"why": row[0], "key": row[1], "name": row[2], "enemy": row[4], "spell": row[5]}


def situational_item(
    deaths: list[dict[str, Any]] | None,
    owned_names: list[str] | None,
    meta: dict[str, Any] | None,
    *,
    enemies: list[str] | None = None,
    position: str | None = None,
    minute: int | None = None,
    hero: str | None = None,
    net_worth: int | None = None,
) -> dict[str, Any] | None:
    """{key, name, cost, gold_left (None when the price is unknown), why, count,
    enemy, spell, escape} for the first rule that holds: MIN_DEATHS deaths of
    its kind (a single-target disabler among the enemies turns BKB into
    Linken's), else a counter to an enemy hero seen (the `hero`'s plan first,
    or its tempo build when the player's `net_worth` is over its curve); None
    otherwise."""
    if owned_names is None:
        return None
    kinds = Counter(
        death_kind(death.get("last")) for death in deaths or [] if isinstance(death, dict)
    )
    constants = (meta or {}).get("constants") or {}
    priced = has_components(constants)
    known = (constants.get("items") or {}) if priced else {}
    owned = [item_key(name) for name in owned_names]
    enemy_list = [e for e in enemies or [] if isinstance(e, str)]
    disables = Counter(
        disable_kind(death.get("last"))
        for death in deaths or []
        if isinstance(death, dict) and death_kind(death.get("last")) == "disabled"
    )
    candidates = _candidates(kinds, enemy_list, position, minute, hero, net_worth, disables)
    for why, key, fallback, count, enemy, spell, extra in candidates:
        # A family answered by any of its items (Monkey King Bar or Bloodthorn).
        if any(
            have_key in owned
            or (priced and any(_contains(have, have_key, constants) for have in owned))
            for have_key in extra.get("family_items") or [key]
        ):
            continue
        cost = _cost(key, constants) if priced else 0
        item: dict[str, Any] = {
            "key": key,
            "name": item_name(key, constants) if key in known else fallback,
            "cost": cost or None,
            "gold_left": gold_left(key, Counter(owned), constants) if cost else None,
            "why": why,
            "count": count,
            "enemy": enemy,
            "spell": spell,
        }
        if extra.get("escape"):
            item["escape"] = extra["escape"]
        alternative = extra.get("alternative")
        if alternative:
            alternative = dict(alternative)
            if alternative["key"] in known:
                alternative["name"] = item_name(alternative["key"], constants)
            item["alternative"] = alternative
        if extra.get("reason"):
            # A hero plan's own words, in both languages (hero_items.format_reason).
            item["reason"] = format_reason(
                extra["reason"],
                item=item["name"],
                enemy=enemy,
                escape=extra.get("escape"),
                spell=spell,
                net_worth=count if why == TEMPO_WHY else None,
            )
        return item
    return None


def draft_item(
    enemies: list[str] | None,
    owned_names: list[str] | None,
    meta: dict[str, Any] | None,
    position: str | None,
    hero: str | None = None,
) -> dict[str, Any] | None:
    """The counter item to plan for against the enemy lineup (situational_item's
    enemy counters, no deaths and no minute gates) once DRAFT_MIN_ENEMIES enemy
    heroes are seen; cores only. None otherwise or when it is already owned."""
    seen = [e for e in enemies or [] if isinstance(e, str)]
    if position not in CORE_POSITIONS or len(seen) < DRAFT_MIN_ENEMIES:
        return None
    return situational_item(
        [], owned_names, meta, enemies=seen, position=position, minute=_ANY_MINUTE, hero=hero
    )


def lineup_save_item(
    enemies: list[str] | None,
    owned_names: list[str] | None,
    meta: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The support's save item against the enemy lineup: Glimmer Cape against
    MAGIC_LINEUP_MIN heroes of magic damage, Ghost Scepter against
    PHYSICAL_LINEUP_MIN right-click carries — {key, name, cost, gold_left
    (None without priced constants), why, count, enemy}; None otherwise or when
    the player already has it (or something built from it)."""
    from app.draft_analysis import (
        MAGIC_DAMAGE,
        MAGIC_LINEUP_MIN,
        PHYSICAL_CARRIES,
        PHYSICAL_LINEUP_MIN,
    )

    if owned_names is None:
        return None
    seen = [e for e in enemies or [] if isinstance(e, str)]
    magic = [e for e in seen if e in MAGIC_DAMAGE]
    physical = [e for e in seen if e in PHYSICAL_CARRIES]
    if len(magic) >= MAGIC_LINEUP_MIN:
        why, key, fallback, heroes = "magic", "glimmer_cape", "Glimmer Cape", magic
    elif len(physical) >= PHYSICAL_LINEUP_MIN:
        why, key, fallback, heroes = "physical", "ghost", "Ghost Scepter", physical
    else:
        return None
    constants = (meta or {}).get("constants") or {}
    priced = has_components(constants)
    owned = [item_key(name) for name in owned_names]
    if key in owned or (priced and any(_contains(have, key, constants) for have in owned)):
        return None
    known = (constants.get("items") or {}) if priced else {}
    cost = _cost(key, constants) if priced else 0
    return {
        "key": key,
        "name": item_name(key, constants) if key in known else fallback,
        "cost": cost or None,
        "gold_left": gold_left(key, Counter(owned), constants) if cost else None,
        "why": why,
        "count": len(heroes),
        "enemy": heroes[0],
    }
