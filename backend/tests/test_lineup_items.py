"""Items against the enemy lineup seen on the minimap: magic damage asks an
offlaner for Pipe, a carry or a mid for BKB, a support for Glimmer Cape;
right-click carries ask a support for Ghost Scepter."""

from __future__ import annotations

from test_situational_items import META

from app.advice_i18n import translate_uk
from app.death_screen import build_death_screen
from app.dota_constants import hero_id_from_name
from app.draft_analysis import MAGIC_DAMAGE, PHYSICAL_CARRIES
from app.map_hints import RoleTips
from app.post_laning_coach import _next_item_copy
from app.situational_items import lineup_save_item, situational_item

MAGIC = ["Lina", "Zeus", "Leshrac"]


def test_every_lineup_hero_is_a_real_hero_name():
    for name in MAGIC_DAMAGE | PHYSICAL_CARRIES:
        assert hero_id_from_name(name), name


def test_a_magic_lineup_asks_cores_for_pipe_or_bkb():
    offlane = situational_item([], [], META, enemies=MAGIC, position="offlane", minute=15)
    assert offlane["why"] == "magic" and offlane["count"] == 3
    assert offlane["key"] == "pipe"
    carry = situational_item([], [], META, enemies=MAGIC, position="carry", minute=15)
    assert carry["key"] == "black_king_bar" and carry["enemy"] == "Lina"
    # Two of them, too early, or a support: nothing.
    assert situational_item([], [], META, enemies=MAGIC[:2], position="carry", minute=20) is None
    assert situational_item([], [], META, enemies=MAGIC, position="carry", minute=10) is None
    assert situational_item([], [], META, enemies=MAGIC, position="support", minute=20) is None
    # Already owned.
    owned = ["item_black_king_bar"]
    assert situational_item([], owned, META, enemies=MAGIC, position="carry", minute=20) is None


def test_the_magic_reason_in_both_languages():
    item = {
        "key": "black_king_bar",
        "name": "Black King Bar",
        "cost": 4050,
        "gold_left": 2000,
        "why": "magic",
        "count": 3,
        "enemy": "Lina",
        "spell": None,
    }
    state = {"minute": 20, "gold": 900, "extra_context": {"next_item": item, "gpm": 520}}
    _, reason = _next_item_copy(state, state["extra_context"])
    assert reason.startswith(
        "3 enemy heroes deal magic damage, and Black King Bar protects you from it"
    )
    assert translate_uk(reason).startswith(
        "3 герої ворога б'ють магією — Black King Bar захистить від неї: бракує 1100 золота"
    )
    card = build_death_screen(
        death={"t": 1200, "usable": []},
        place=None,
        respawn=30,
        gold=900,
        buyback_cost=None,
        minute=20,
        next_item=item,
        lang="uk",
    )
    assert any("магічною шкодою — 3" in line for line in card["lines"])


def test_a_support_gets_the_save_item_against_the_lineup():
    glimmer = lineup_save_item(MAGIC, ["item_boots"], None)
    assert glimmer["key"] == "glimmer_cape" and glimmer["name"] == "Glimmer Cape"
    assert glimmer["gold_left"] is None  # no constants cached: no price claimed
    ghost = lineup_save_item(["Phantom Assassin", "Sven", "Lina"], [], None)
    assert ghost["key"] == "ghost" and ghost["enemy"] == "Phantom Assassin"
    assert lineup_save_item(["Phantom Assassin", "Lina"], [], None) is None
    assert lineup_save_item(MAGIC, ["item_glimmer_cape"], None) is None
    assert lineup_save_item(MAGIC, None, None) is None

    items = ["item_boots", "item_wind_lace"]
    tip = RoleTips().tip(
        13 * 60,
        "support",
        alive=True,
        has_ward=True,
        lang="uk",
        gold=1300,
        items=items,
        save_item=glimmer,
    )
    assert tip["title"] == "Glimmer Cape проти магії"
    assert "магічною шкодою: 3" in tip["hint"]
    tip = RoleTips().tip(
        13 * 60,
        "support",
        alive=True,
        has_ward=True,
        lang="en",
        gold=1300,
        items=items,
        save_item={**ghost, "gold_left": 1200},
    )
    assert tip["title"] == "Buy Ghost Scepter now"


def test_the_service_prefers_the_lineup_item(monkeypatch):
    from test_supports import SAVE_META

    from app.player_api import PLAYER_SERVICE

    monkeypatch.setattr(PLAYER_SERVICE, "_live_meta", lambda hero_id: SAVE_META)
    # Every support has a hero plan now (its save item comes from it): a hero
    # without a support plan, played as a support, keeps the lineup item.
    item = PLAYER_SERVICE.save_item("Mars", ["item_boots"], MAGIC)
    assert item["why"] == "magic"
    assert PLAYER_SERVICE.save_item("Mars", ["item_boots"], ["Axe"])["name"] == ("Force Staff")
