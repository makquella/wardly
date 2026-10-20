"""«Against <enemy>, not your usual build»: the counter-item card Wardly shows
when it reads the enemy draft, for a promo video.

Nothing is written by hand: the enemy comes from the heroes the app counters
(draft_analysis.COUNTERS, situational_items.BREAK_PASSIVES), the item from
situational_items.situational_item (the logic behind the live draft card),
and the card's title and reason from the overlay's own Ukrainian text
(map_hints.TIPS["draft_<why>"])."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
POSITIONS = ("carry", "mid", "offlane")


def _backend_path() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def enemies() -> list[str]:
    """Every enemy hero the app answers with an item, in a stable order."""
    _backend_path()
    from app.draft_analysis import COUNTERS
    from app.situational_items import BREAK_PASSIVES

    names: list[str] = []
    # Heavy healing has no generic item (a hero's own plan names one), so no
    # healer is a draft video's enemy.
    for kind in ("illusions", "evasion"):
        names += sorted(COUNTERS[kind][0])
    names += sorted(BREAK_PASSIVES)
    return list(dict.fromkeys(names))


def hero_key(name: str) -> str | None:
    _backend_path()
    from app.dota_constants import hero_id_from_name, hero_npc_name

    hero_id = hero_id_from_name(name)
    npc = hero_npc_name(hero_id) if hero_id else ""
    return npc.removeprefix("npc_dota_hero_") or None


def card(enemy: str, lang: str = "uk") -> dict[str, Any] | None:
    """{enemy, key, position, item, title, reason} or None when no position gets an item."""
    _backend_path()
    from app.map_hints import TIPS
    from app.situational_items import situational_item

    key = hero_key(enemy)
    if not key:
        return None
    for position in POSITIONS:
        item = situational_item([], [], None, enemies=[enemy], position=position, minute=60)
        if not item or f"draft_{item['why']}" not in TIPS:
            continue
        values = {
            "item": item["name"],
            "enemy": item.get("enemy") or enemy,
            "spell": item.get("spell") or "",
            "count": item.get("count") or 0,
        }
        title, reason = (text.format(**values) for text in TIPS[f"draft_{item['why']}"][lang])
        return {
            "enemy": enemy,
            "key": key,
            "position": position,
            "item": item,
            "title": title,
            "reason": reason,
        }
    return None
