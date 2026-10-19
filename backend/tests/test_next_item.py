"""A core's live farm advice names the next build item (app/next_item.py)."""

from __future__ import annotations

from collections import Counter

from match_fixtures import ME, FakeOpenDota, gsi_match_stream, opendota_match, recent_matches

from app.advice_i18n import translate_uk
from app.next_item import gold_left, has_components, next_build_item
from app.player_api import PLAYER_SERVICE
from app.post_laning_coach import build_post_laning_advice

CONSTANTS = {
    "by_id": {"1": "black_king_bar", "2": "manta", "3": "hurricane_pike", "4": "dragon_lance"},
    "items": {
        "black_king_bar": {
            "name": "Black King Bar",
            "cost": 4050,
            "assembled": True,
            "components": ["ogre_axe", "mithril_hammer"],
        },
        "ogre_axe": {"name": "Ogre Axe", "cost": 1000, "assembled": False, "components": []},
        "mithril_hammer": {
            "name": "Mithril Hammer",
            "cost": 1600,
            "assembled": False,
            "components": [],
        },
        "manta": {"name": "Manta Style", "cost": 4650, "assembled": True, "components": ["yasha"]},
        "yasha": {"name": "Yasha", "cost": 2050, "assembled": True, "components": ["blade"]},
        "blade": {"name": "Blade of Alacrity", "cost": 1000, "assembled": False, "components": []},
        "dragon_lance": {
            "name": "Dragon Lance",
            "cost": 1900,
            "assembled": True,
            "components": ["ogre_axe"],
        },
        "hurricane_pike": {
            "name": "Hurricane Pike",
            "cost": 4450,
            "assembled": True,
            "components": ["dragon_lance"],
        },
    },
}
META = {
    "constants": CONSTANTS,
    "popularity": {"mid_game_items": {"1": 90, "4": 60, "2": 50}, "late_game_items": {"3": 10}},
}


def test_owned_parts_are_not_paid_twice():
    assert gold_left("black_king_bar", Counter(), CONSTANTS) == 4050
    assert gold_left("black_king_bar", Counter({"ogre_axe": 1}), CONSTANTS) == 3050
    # Parts at any depth: a Blade of Alacrity counts toward Yasha inside Manta.
    assert gold_left("manta", Counter({"blade": 1}), CONSTANTS) == 3650
    # One Ogre Axe is used once, not for both recipes that need it.
    owned = Counter({"ogre_axe": 1})
    assert gold_left("black_king_bar", owned, CONSTANTS) == 3050
    assert gold_left("dragon_lance", owned, CONSTANTS) == 1900


def test_the_next_item_skips_what_is_owned_or_built_into_something_bigger():
    first = next_build_item(META, ["item_power_treads", "item_ogre_axe"])
    assert first == {
        "key": "black_king_bar",
        "name": "Black King Bar",
        "cost": 4050,
        "gold_left": 3050,
    }
    # BKB owned, Dragon Lance already inside a Hurricane Pike: Manta is next.
    later = next_build_item(META, ["item_black_king_bar", "item_hurricane_pike"])
    assert later is not None and later["key"] == "manta"
    everything = ["item_black_king_bar", "item_hurricane_pike", "item_manta"]
    assert next_build_item(META, everything) is None


def test_no_item_without_the_data_to_price_it():
    assert next_build_item(META, None) is None  # no items block in GSI
    assert next_build_item(None, []) is None
    old = {
        "constants": {
            "by_id": CONSTANTS["by_id"],
            "items": {
                k: {x: y for x, y in v.items() if x != "components"}
                for k, v in CONSTANTS["items"].items()
            },
        },
        "popularity": META["popularity"],
    }
    assert not has_components(old["constants"])
    assert next_build_item(old, []) is None


def _state(minute, gold, **extra):
    return {
        "hero": "Juggernaut",
        "minute": minute,
        "gold": gold,
        "hp_percent": 100,
        "extra_context": {
            "available_gold": gold,
            "gpm": 600,
            "next_item": {"key": "black_king_bar", "name": "Black King Bar", "gold_left": 3050},
            **extra,
        },
    }


def test_the_farm_route_names_the_item_the_gold_and_the_minutes():
    advice = build_post_laning_advice(_state(20, 1200), "SAFE_FARMING")
    assert advice is not None and advice.category == "post_laning_safe_farm_route"
    assert advice.action == "Keep farming toward Black King Bar on the safest waves and camps."
    assert advice.reason == (
        "Black King Bar is next in most builds: 1850 gold to go, "
        "about 4 minutes at your 600 gold per minute."
    )
    ready = build_post_laning_advice(_state(20, 3400), "SAFE_FARMING")
    assert ready.action == "Use your gold: Black King Bar can be bought now."
    assert ready.reason == "Its missing parts cost 3050 gold and you have 3400."


def test_the_buyback_gold_stays_aside_after_minute_30():
    advice = build_post_laning_advice(_state(32, 5000, buyback_cost=2500), "SAFE_FARMING")
    assert advice.action.startswith("Keep farming toward Black King Bar")
    assert "550 gold to go, about 1 minute" in advice.reason
    ready = build_post_laning_advice(_state(32, 6000, buyback_cost=2500), "SAFE_FARMING")
    assert ready.reason == "Its missing parts cost 3050 gold and you have 3500 beyond your buyback."
    # No buyback cost known: the plain advice, never a guess.
    plain = build_post_laning_advice(_state(32, 6000), "SAFE_FARMING")
    assert plain.action == "Keep farming the safest wave-and-camp route and reassess soon."


def test_a_slow_or_unknown_pace_gives_no_minutes():
    advice = build_post_laning_advice(_state(20, 1200, gpm=None), "SAFE_FARMING")
    assert advice.reason == "Black King Bar is next in most builds: 1850 gold to go."


def test_every_variant_has_ukrainian():
    texts = [
        "Keep farming toward Black King Bar on the safest waves and camps.",
        "Consider: keep farming toward Black King Bar on the safest waves and camps.",
        "Black King Bar is next in most builds: 1850 gold to go, "
        "about 4 minutes at your 600 gold per minute.",
        "Black King Bar is next in most builds: 550 gold to go, "
        "about 1 minute at your 600 gold per minute.",
        "Black King Bar is next in most builds: 1850 gold to go.",
        "Use your gold: Eul's Scepter of Divinity can be bought now.",
        "Its missing parts cost 3050 gold and you have 3400.",
        "Its missing parts cost 3050 gold and you have 3500 beyond your buyback.",
    ]
    for text in texts:
        assert translate_uk(text), text


def _synced(client, tmp_path):
    recent = recent_matches(12)
    fake = FakeOpenDota(
        matches={
            row["match_id"]: opendota_match(good=row["radiant_win"], match_id=row["match_id"])
            for row in recent
        },
        recent=recent,
    )
    PLAYER_SERVICE.configure(tmp_path / "svc", client=fake, auto_start=False)
    client.post("/player/link", json={"steam": str(ME)})
    PLAYER_SERVICE.jobs.run_pending(until=float("inf"))
    return fake


def _live(client, minutes, gold):
    stream = gsi_match_stream(minutes=minutes, death_minutes=(), lh_per_minute=9)
    for payload in stream:
        payload["items"]["teleport0"] = {"name": "item_tpscroll"}
        payload["player"].update(gpm=600, gold=gold, gold_reliable=500, gold_unreliable=gold - 500)
    for payload in stream[::6]:
        client.post("/gsi", json=payload)


def test_the_live_card_names_the_next_item_of_the_heros_build(client, tmp_path):
    _synced(client, tmp_path)
    # 20:00 on the fixture Juggernaut: Power Treads and Battle Fury bought.
    _live(client, 20, 1500)
    english = client.get("/overlay/recommendation").json()["recommendation"]
    assert english["action"] == "Keep farming toward Manta Style on the safest waves and camps."
    assert english["reason"].startswith("Manta Style is next in most builds: 3150 gold to go")
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()["recommendation"]
    assert ukrainian["action"] == "Фарміть на Manta Style на найбезпечніших хвилях і таборах."


def test_a_hero_with_nothing_cached_gets_its_build_fetched(client, tmp_path):
    fake = _synced(client, tmp_path)
    fake.calls.clear()
    # A hero without an item plan (data/heroes/item_plans): nothing cached, nothing said.
    assert PLAYER_SERVICE.next_item("Wraith King", []) is None
    PLAYER_SERVICE.jobs.run_pending(until=float("inf"))
    assert "popularity:42" in fake.calls and "timings:42" in fake.calls
    # Asked once a minute at most, not on every poll.
    fake.calls.clear()
    PLAYER_SERVICE.next_item("Wraith King", [])
    PLAYER_SERVICE.jobs.run_pending(until=float("inf"))
    assert fake.calls == []


def test_constants_cached_without_components_are_fetched_again(client, tmp_path):
    fake = _synced(client, tmp_path)
    from app.player_service import ITEM_CONSTANTS_KEY

    store = PLAYER_SERVICE.store
    cached = store.cache_get(ITEM_CONSTANTS_KEY)
    for info in cached["items"].values():
        info.pop("components", None)
    store.cache_set(ITEM_CONSTANTS_KEY, cached)
    fake.calls.clear()
    PLAYER_SERVICE._ensure_hero_meta(8)
    assert "items" in fake.calls
    assert has_components(store.cache_get(ITEM_CONSTANTS_KEY))
