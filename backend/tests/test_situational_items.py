"""The next item picked by how the player dies in this match
(app/situational_items.py): BKB after deaths under stuns, Aeon Disk after
burst deaths — before the hero's usual build."""

from __future__ import annotations

from test_next_item import CONSTANTS, META

from app.advice_i18n import translate_uk
from app.death_screen import build_death_screen
from app.player_api import PLAYER_SERVICE
from app.post_laning_coach import build_post_laning_advice
from app.situational_items import death_kind, situational_item


def _stunned(t):
    # Five recorded seconds, only one of them free.
    return {
        "t": t,
        "last": {"hp": [[-4, 60], [-3, 50], [-2, 40], [-1, 20], [0, 5]], "free_s": 1, "held_s": 4},
    }


def _burst(t):
    return {"t": t, "last": {"hp": [[-3, 90], [-1, 30], [0, 0]], "free_s": 5, "burst_s": 2}}


def _plain(t):
    return {"t": t, "last": {"hp": [[-4, 40], [-2, 30], [0, 0]], "free_s": 5}}


def test_how_a_death_went():
    assert death_kind(_stunned(1)["last"]) == "disabled"
    assert death_kind(_burst(1)["last"]) == "burst"
    assert death_kind(_plain(1)["last"]) is None
    # Too few seconds recorded to say it was a stun.
    assert death_kind({"hp": [[0, 5]], "free_s": 0}) is None
    assert death_kind(None) is None


def _record(flag):
    from app.last_moments import LastSeconds

    seconds = LastSeconds()
    for clock in range(595, 601):
        hero = {"alive": True, "health_percent": 100 - (clock - 595) * 18, flag: True}
        seconds.observe(clock, hero, {})
    return seconds.summarize(601)


def test_a_mute_is_not_a_stun():
    # Muted: no items, but the hero still walks and casts — not a BKB pattern.
    assert death_kind(_record("muted")) is None
    assert death_kind(_record("stunned")) == "disabled"
    assert death_kind(_record("hexed")) == "disabled"
    muted = [{"t": 600, "last": _record("muted")}, {"t": 900, "last": _record("muted")}]
    assert situational_item(muted, [], META) is None
    # A record from before held_s was kept: nothing claimed.
    assert death_kind({"hp": [[-3, 50], [-2, 40], [-1, 20], [0, 5]], "free_s": 0}) is None


def test_two_deaths_under_stuns_ask_for_black_king_bar():
    assert situational_item([_stunned(600)], [], META) is None  # one is not a pattern
    item = situational_item([_stunned(600), _plain(900), _stunned(1300)], ["ogre_axe"], META)
    assert item == {
        "key": "black_king_bar",
        "name": "Black King Bar",
        "cost": 4050,
        "gold_left": 3050,
        "why": "disabled",
        "count": 2,
        "enemy": None,
        "spell": None,
    }
    # Already owned → nothing to say.
    assert situational_item([_stunned(600), _stunned(900)], ["black_king_bar"], META) is None


def test_burst_deaths_ask_for_aeon_disk_even_without_prices():
    item = situational_item([_burst(600), _burst(900)], ["power_treads"], None)
    assert item["name"] == "Aeon Disk" and item["why"] == "burst"
    assert item["gold_left"] is None and item["cost"] is None
    assert situational_item([_burst(600)], [], None) is None
    assert situational_item([_burst(600), _burst(700)], None, None) is None


def _advice(item, gold=900, minute=18):
    state = {
        "hero": "Juggernaut",
        "minute": minute,
        "gold": gold,
        "hp_percent": 100,
        "extra_context": {"next_item": item, "gpm": 520, "farm_quality": "good"},
    }
    return build_post_laning_advice(state, "SAFE_FARMING")


def test_the_farm_advice_says_why_this_item():
    item = situational_item([_stunned(600), _stunned(900)], [], META)
    advice = _advice(item, gold=900)
    assert advice.action == "Keep farming toward Black King Bar on the safest waves and camps."
    assert advice.reason == (
        "2 deaths under stuns with no free second, and Black King Bar stops that: "
        "3150 gold to go, about 7 minutes at your 520 gold per minute."
    )
    assert translate_uk(advice.reason).startswith(
        "2 смерті під контролем без жодної вільної секунди — Black King Bar це виправить"
    )
    now = _advice(item, gold=4500)
    assert now.action == "Use your gold: Black King Bar can be bought now."
    assert now.reason.endswith("; its missing parts cost 4050 gold and you have 4500.")
    assert translate_uk(now.reason).endswith("відсутні частини коштують 4050 золота, у вас 4500.")
    unpriced = _advice(situational_item([_burst(1), _burst(2)], [], None))
    assert unpriced.reason == (
        "2 deaths, each from high health in 3 seconds or less, and Aeon Disk gives you time against that."
    )
    assert translate_uk(unpriced.reason) == (
        "2 рази вас убили з високого здоров'я швидше, ніж за 3 секунди — Aeon Disk дасть час це пережити."
    )


def test_the_death_screen_says_why(monkeypatch):
    item = situational_item([_stunned(600), _stunned(900)], [], META)
    card = build_death_screen(
        death=None,
        place=None,
        respawn=20,
        gold=1500,
        buyback_cost=None,
        minute=18,
        next_item=item,
        lang="uk",
    )
    assert any(line.startswith("Купіть частини Black King Bar") for line in card["lines"])
    assert "Чому Black King Bar: смертей під контролем — 2" in card["lines"][-1]


def test_the_service_puts_the_situational_item_first(monkeypatch):
    monkeypatch.setattr(PLAYER_SERVICE, "_live_meta", lambda hero_id: META)
    # A hero without an item plan (data/heroes/item_plans): the popular build.
    assert PLAYER_SERVICE.next_item("Ursa", [])["key"] == "black_king_bar"  # the build
    monkeypatch.setattr(PLAYER_SERVICE.tracker, "death_moments", lambda: [_burst(600), _burst(900)])
    assert PLAYER_SERVICE.next_item("Ursa", [])["key"] == "aeon_disk"
    assert CONSTANTS["items"].get("aeon_disk") is None  # named without a price
