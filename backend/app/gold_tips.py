"""
gold_tips.py - gold the player is not spending, for every role (live GSI only).

A player who walked to the lane with an empty bag and 600 gold, or ran for
minutes with 2500 in the pocket, heard nothing: the purchase tips were a core's
advice and a support's map tip (off with «Map timers»). These two cards go out
on the map line for any role and with the map timers switched off:

- the start: from strategy time (at once there: the shop opens with the pick,
  `pre_spawn`), else an empty inventory (no item in the inventory,
  backpack or stash; the TP slot is not counted) for START_WAIT seconds of clock
  with START_GOLD+ gold → «Buy your starting items», until START_UNTIL;
- a stall: after START_UNTIL, alive, gold over the role's threshold (from 30:00
  the buyback cost is set aside when known) and no change of the items for
  STALL_SECONDS → «N gold unspent», 20 s every STALL_EVERY while it lasts.

The start card wins over the game plan on the overlay (`over_plan`).
"""

from __future__ import annotations

from typing import Any

START_GOLD = 300
START_WAIT = 10
START_UNTIL = 3 * 60
STALL_SECONDS = 120
STALL_EVERY = 3 * 60
SHOW = 20
SUPPORT_GOLD = 900
CORE_GOLD = 1200
CORE_GOLD_LATE = 2000
LATE_FROM = 15 * 60
BUYBACK_FROM = 30 * 60

TEXTS = {
    "start": {
        "en": (
            "Buy your starting items",
            "{gold} gold and an empty bag: take regen (Tango, Healing Salve) "
            "and stat items before the lane.",
        ),
        "uk": (
            "Купіть стартові предмети",
            "{gold} золота й порожній інвентар: візьміть реген (Tango, Healing Salve) і предмети на характеристики до виходу на лінію.",
        ),
    },
    "start_items": {
        "en": (
            "Buy your starting items",
            "{gold} gold and an empty bag. The usual start on this hero: {items}.",
        ),
        "uk": (
            "Купіть стартові предмети",
            "{gold} золота й порожній інвентар. Звичайний старт на цьому герої: {items}.",
        ),
    },
    "stall_support": {
        "en": (
            "{gold} gold unspent",
            "Spend it now: wards, dust, a smoke or a save item such as Force Staff or Glimmer Cape.",
        ),
        "uk": (
            "{gold} золота не витрачено",
            "Витратьте зараз: варди, дасти, смок або рятівний предмет — Force Staff, Glimmer Cape.",
        ),
    },
    "stall": {
        "en": (
            "{gold} gold unspent",
            "Buy parts of your next item: gold in the pocket does nothing, "
            "and you lose some of it when you die.",
        ),
        "uk": (
            "{gold} золота не витрачено",
            "Купіть частини наступного предмета: золото в кишені нічого не дає, а під час смерті частина втрачається.",
        ),
    },
    "stall_part": {
        "en": (
            "{gold} gold unspent",
            "{item} is next in your build: {part} ({cost}) fits your gold now — buy it.",
        ),
        "uk": (
            "{gold} золота не витрачено",
            "Наступний за збіркою — {item}: на {part} ({cost}) золота вже вистачає, купіть зараз.",
        ),
    },
    "stall_item": {
        "en": (
            "{gold} gold unspent",
            "{item} is next in your build: buy its parts now, gold in the pocket does nothing.",
        ),
        "uk": (
            "{gold} золота не витрачено",
            "Наступний за збіркою — {item}: купіть частини зараз, золото в кишені нічого не дає.",
        ),
    },
}


class GoldTips:
    """Per match (MATCH_MEMORY.gold): fed every live tick, asked by the overlay."""

    def __init__(self) -> None:
        self._bag: tuple[str, ...] | None = None
        self._changed_at: int | None = None
        self._empty_since: int | None = None
        self._shown: dict[str, int] = {}

    def observe(self, clock: int | None, items: list[str] | None) -> None:
        """`items`: the names in the inventory, backpack and stash (map_hints.item_names);
        None without an items block, which changes nothing."""
        if clock is None or items is None:
            return
        bag = tuple(sorted(items))
        if bag != self._bag or self._changed_at is None or clock < self._changed_at:
            self._bag = bag
            self._changed_at = clock
        if bag:
            self._empty_since = None
        elif self._empty_since is None or clock < self._empty_since:
            self._empty_since = clock

    def tip(
        self,
        clock: int | None,
        lang: str,
        *,
        gold: int | None,
        alive: bool,
        role: str | None,
        buyback_cost: int | None = None,
        next_item: dict[str, Any] | None = None,
        buy_now: dict[str, Any] | None = None,
        start_items: list[dict[str, Any]] | None = None,
        pre_spawn: bool = False,
    ) -> dict[str, Any] | None:
        """`next_item`: {key, name} of the next build item (cores, and a support
        with a hero plan), `buy_now`: its part the gold buys now (next_item.buy_now), both drawn as icons.
        `start_items`: the hero's usual start ([{key, name}], hero_meta.start_items
        or the high-rank builds), named and drawn as icons on the start card.
        `pre_spawn`: strategy time, the hero not on the map yet — the shop is open,
        so the start card shows at once (no START_WAIT)."""
        if clock is None or gold is None or not alive or self._bag is None:
            return None
        lang = "uk" if lang == "uk" else "en"
        if clock < START_UNTIL:
            empty = self._empty_since
            if empty is None or gold < START_GOLD:
                return None
            if clock - empty < START_WAIT and not pre_spawn:
                return None
            # Shown for as long as the bag stays empty: nothing matters more then.
            if start_items:
                hint = _hint(
                    "start_items",
                    f"gold-start@{empty}",
                    lang,
                    gold=_round(gold),
                    items=", ".join(item["name"] for item in start_items),
                    over_plan=True,
                )
                # Copies (two Iron Branches) as a count on the icon.
                hint["items"] = [
                    {
                        "key": i["key"],
                        "name": i["name"],
                        **({"count": i["count"]} if i.get("count", 1) > 1 else {}),
                    }
                    for i in start_items
                ]
                return hint
            return _hint("start", f"gold-start@{empty}", lang, gold=_round(gold), over_plan=True)
        spare = gold
        if clock >= BUYBACK_FROM and buyback_cost:
            spare = gold - buyback_cost
        if spare < _threshold(role, clock) or self._changed_at is None:
            return None
        if clock - self._changed_at < STALL_SECONDS:
            return None
        start = self._every("stall", clock)
        if start is None:
            return None
        hint_id = f"gold-stall@{start}"
        if not next_item:
            # A support with no plan item has no build to name.
            key = "stall_support" if role == "support" else "stall"
            return _hint(key, hint_id, lang, gold=_round(spare))
        item = {"key": next_item["key"], "name": next_item["name"]}
        if buy_now:
            hint = _hint(
                "stall_part",
                hint_id,
                lang,
                gold=_round(spare),
                item=item["name"],
                part=buy_now["name"],
                cost=buy_now["cost"],
            )
            hint["items"] = [item, {"key": buy_now["key"], "name": buy_now["name"]}]
            return hint
        hint = _hint("stall_item", hint_id, lang, gold=_round(spare), item=item["name"])
        hint["items"] = [item]
        return hint

    def _every(self, key: str, clock: int) -> int | None:
        shown = self._shown.get(key)
        if shown is None or clock - shown >= STALL_EVERY or clock < shown:
            self._shown[key] = shown = clock
        return shown if clock - shown <= SHOW else None


def _threshold(role: str | None, clock: int) -> int:
    if role == "support":
        return SUPPORT_GOLD
    return CORE_GOLD_LATE if clock >= LATE_FROM else CORE_GOLD


def _round(gold: int) -> int:
    """Down to hundreds, as the player reads it on screen."""
    return max(0, gold) // 100 * 100


def _hint(
    key: str, hint_id: str, lang: str, *, over_plan: bool = False, **params: Any
) -> dict[str, Any]:
    title, text = TEXTS[key][lang]
    return {
        "kind": "tip",
        # The overlay card's label (instead of «Map»).
        "label": "Покупки" if lang == "uk" else "Shop",
        "id": hint_id,
        "at": None,
        "at_label": None,
        "in_seconds": None,
        "title": title.format(**params),
        "hint": text.format(**params),
        "speak": True,
        # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
        "title_en": TEXTS[key]["en"][0].format(**params),
        "over_plan": over_plan,
    }
