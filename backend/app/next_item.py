"""
next_item.py - the next build item for the live farm advice of a core.

«Black King Bar is next in most builds: 1250 gold to go, about 3 minutes at
your pace» instead of a plain «keep farming». Everything comes from data the
app already has:

- the build: the hero's most bought mid- and late-game items (OpenDota item
  popularity, cached by PlayerService like the game plan's key item);
- what the player owns: item names of the live GSI inventory, backpack and stash;
- the price: the item constants' cost and components, so parts already bought
  (Ogre Axe for Black King Bar) are not counted again.

Nothing is guessed: no cached build, no components in the cached constants
(older caches) or no items block in GSI -> no item.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.hero_meta import item_key, item_name, popular_build

# Nested recipes are a few levels deep; this only stops a broken table.
MAX_DEPTH = 6


def _info(key: str, constants: dict[str, Any]) -> dict[str, Any] | None:
    info = (constants.get("items") or {}).get(key)
    return info if isinstance(info, dict) else None


def _cost(key: str, constants: dict[str, Any]) -> int:
    info = _info(key, constants) or {}
    cost = info.get("cost")
    return int(cost) if isinstance(cost, (int, float)) and cost > 0 else 0


def _components(key: str, constants: dict[str, Any]) -> list[str]:
    parts = (_info(key, constants) or {}).get("components")
    return [item_key(p) for p in parts if isinstance(p, str)] if isinstance(parts, list) else []


def _contains(parent: str, key: str, constants: dict[str, Any], depth: int = 0) -> bool:
    """Whether `key` is a part (at any depth) of `parent`."""
    if depth > MAX_DEPTH:
        return False
    for part in _components(parent, constants):
        if part == key or _contains(part, key, constants, depth + 1):
            return True
    return False


def gold_left(key: str, owned: Counter[str], constants: dict[str, Any], depth: int = 0) -> int:
    """The gold still needed for `key` when the parts in `owned` are used
    (they are taken out of `owned`, so one part is never counted twice)."""
    if owned.get(key, 0) > 0:
        owned[key] -= 1
        return 0
    cost = _cost(key, constants)
    parts = _components(key, constants)
    if not parts or depth > MAX_DEPTH:
        return cost
    recipe = max(0, cost - sum(_cost(part, constants) for part in parts))
    return recipe + sum(gold_left(part, owned, constants, depth + 1) for part in parts)


def missing_parts(
    key: str, owned: Counter[str], constants: dict[str, Any], depth: int = 0
) -> list[tuple[str, int]]:
    """The parts of `key` still to buy with their prices, in the order the shop
    lists them: a part the player has (or has built) is taken out of `owned`; a
    part with parts of its own gives those (Mithril Hammer is never the step when
    Ogre Axe is); when only a recipe is left, the item comes with the recipe's price."""
    if owned.get(key, 0) > 0:
        owned[key] -= 1
        return []
    parts = _components(key, constants)
    if not parts or depth > MAX_DEPTH:
        return [(key, _cost(key, constants))]
    result: list[tuple[str, int]] = []
    for part in parts:
        result.extend(missing_parts(part, owned, constants, depth + 1))
    recipe = _cost(key, constants) - sum(_cost(part, constants) for part in parts)
    if recipe > 0 and not result:
        return [(key, recipe)]
    return result


def buy_now(
    key: str, owned_names: list[str], constants: dict[str, Any], gold: int
) -> dict[str, Any] | None:
    """The quick-buy step: the most expensive missing part of `key` that `gold`
    already buys ({key, name, cost}); None when no part fits the gold."""
    parts = missing_parts(key, Counter(item_key(n) for n in owned_names), constants)
    affordable = [(part, cost) for part, cost in parts if 0 < cost <= gold]
    if not affordable:
        return None
    part, cost = max(affordable, key=lambda row: row[1])
    return {"key": part, "name": item_name(part, constants), "cost": cost}


def net_worth(
    owned_names: list[str] | None, gold: Any, constants: dict[str, Any] | None
) -> int | None:
    """Gold plus the shop cost of the items carried (inventory, backpack and
    stash: map_hints.item_names), as Dota counts net worth; None without the
    gold or priced item constants."""
    if owned_names is None or isinstance(gold, bool) or not isinstance(gold, int):
        return None
    if not has_components(constants):
        return None
    return gold + sum(_cost(item_key(name), constants or {}) for name in owned_names)


def has_components(constants: dict[str, Any] | None) -> bool:
    """Whether the cached item constants carry the components (kept since 0.12)."""
    items = (constants or {}).get("items") or {}
    return any(isinstance(info, dict) and "components" in info for info in items.values())


def owned_items(extra: Any) -> list[str] | None:
    """The item names the player has (map_hints.item_names), with Aghanim's
    Shard when GSI says the hero has it: it is consumed on purchase and leaves
    the items block. None without an items block."""
    names = extra.get("item_names") if isinstance(extra, dict) else None
    if not isinstance(names, list):
        return None
    owned = list(names)
    if extra.get("aghanims_shard") is True and "item_aghanims_shard" not in owned:
        owned.append("item_aghanims_shard")
    return owned


# A listed item cheaper than this, missing while a later one of the list is owned,
# was sold for the slot (Falcon Blade, Mask of Madness): it is not named again.
EARLY_ITEM_COST = 2000


def next_listed_item(
    entries: list[dict[str, Any]], meta: dict[str, Any] | None, owned_names: list[str] | None
) -> dict[str, Any] | None:
    """{key, name, cost, gold_left} of the first of `entries` ({item or key,
    name, unless: [keys]}) the player neither owns nor has built into something
    bigger, nor answered with an `unless` item, nor an early one (under EARLY_ITEM_COST)
    sold once a later entry is owned; None when unknown."""
    if not meta or owned_names is None:
        return None
    constants = meta.get("constants") or {}
    # Without the components (constants cached by an older version) the price
    # of the missing parts cannot be told.
    if not has_components(constants):
        return None
    owned = [item_key(name) for name in owned_names]
    known = constants.get("items") or {}

    def has(key: str) -> bool:
        return key in owned or any(_contains(have, key, constants) for have in owned)

    keys = [e.get("item") or e.get("key") for e in entries]
    for index, entry in enumerate(entries):
        key = keys[index]
        if not isinstance(key, str):
            continue
        if has(key):
            continue
        if any(other in owned for other in entry.get("unless") or []):
            continue
        cost = _cost(key, constants)
        if cost <= 0:
            continue
        if cost < EARLY_ITEM_COST and any(
            isinstance(later, str) and has(later) for later in keys[index + 1 :]
        ):
            continue  # an early item sold for a slot once later ones are bought
        return {
            "key": key,
            "name": item_name(key, constants) if key in known else entry.get("name") or key,
            "cost": cost,
            "gold_left": gold_left(key, Counter(owned), constants),
        }
    return None


def next_build_item(
    meta: dict[str, Any] | None, owned_names: list[str] | None
) -> dict[str, Any] | None:
    """{key, name, cost, gold_left} of the first popular mid/late item the player
    neither owns nor has already built into something bigger; None when unknown."""
    if not meta or owned_names is None:
        return None
    build = popular_build(meta.get("popularity"), meta.get("constants") or {})
    return next_listed_item((build.get("mid") or []) + (build.get("late") or []), meta, owned_names)


# How many items per phase the save item is looked for in: a support's build
# lists boots and wards first, so the top four can miss it.
SAVE_SEARCH = 10


def save_build_item(
    meta: dict[str, Any] | None, owned_names: list[str] | None, candidates: set[str]
) -> dict[str, Any] | None:
    """{key, name, cost, gold_left} of the save item (one of `candidates`) most
    bought on the hero, mid game first; None when the build is unknown, the
    player owns one or none of them is in the build."""
    if not meta or owned_names is None:
        return None
    constants = meta.get("constants") or {}
    if not has_components(constants):
        return None
    candidates = {item_key(name) for name in candidates}
    owned = [item_key(name) for name in owned_names]
    if any(
        key in candidates or any(_contains(key, c, constants) for c in candidates) for key in owned
    ):
        return None  # a save item (or one built from it, Hurricane Pike) is there
    build = popular_build(meta.get("popularity"), constants, per_phase=SAVE_SEARCH)
    for entry in (build.get("mid") or []) + (build.get("early") or []) + (build.get("late") or []):
        key = entry["key"]
        cost = _cost(key, constants)
        if key in candidates and cost > 0:
            return {
                "key": key,
                "name": item_name(key, constants),
                "cost": cost,
                "gold_left": gold_left(key, Counter(owned), constants),
            }
    return None
