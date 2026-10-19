"""The game on the line: the enemy's Aegis, buyback before minute 30, Linken's
or BKB by how the deaths went, and enemies grouped far from the player
(roshan_timer, buyback_tracker, death_screen, situational_items, map_hints)."""

from __future__ import annotations

from collections import Counter

import pytest
from test_next_item import META

from app.advice_i18n import translate_uk
from app.buyback_tracker import BuybackTracker
from app.death_screen import build_death_screen
from app.gsi_state import normalize_gsi_payload
from app.last_moments import LastSeconds
from app.map_hints import GROUP_EVERY, GROUP_SHOW, RoleTips, enemy_group
from app.match_memory import base_danger
from app.post_laning_coach import _buyback_reason, _category_for_state
from app.roshan_timer import RoshanTimer
from app.situational_items import disable_kind, situational_item

OFFSET = 90
CENTER = 16384


def _extra(clock, events=None, team="dire"):
    return {
        "clock_time": clock,
        "game_time": clock + OFFSET,
        "gsi_events": events,
        "team_name": team,
    }


def _pickup(clock, player_id=None):
    event = {"type": "aegis_picked_up", "game_time": clock + OFFSET}
    if player_id is not None:
        event["player_id"] = player_id
    return event


def _kill(clock, team=None):
    event = {"type": "roshan_killed", "game_time": clock + OFFSET}
    if team:
        event["team"] = team
    return event


# --- the enemy's Aegis ------------------------------------------------------------------


def test_an_enemy_pickup_names_the_latest_the_aegis_can_last():
    timer = RoshanTimer()
    at = 25 * 60 + 3
    timer.observe(_extra(at, [_kill(at, "radiant"), _pickup(at, player_id=4)]))
    assert timer.enemy_aegis(at + 10) and not timer.enemy_aegis(at + 301)
    card = timer.hint(at + 3, "uk")
    assert card["title"] == "Аегіс у ворогів до 30:03"
    assert "байбек" in card["hint"] and card["speak"] is True
    assert card["title_en"] == "Enemy Aegis until 30:03"
    # Quiet in between; 30 s before it can expire, once more.
    assert timer.hint(at + 120, "en") is None
    ends = timer.hint(at + 280, "en")
    assert ends["title"] == "Enemy Aegis expires in 20 s"
    assert timer.hint(at + 260, "en") is None
    strip = [s for s in timer.strip(at + 100, "uk") if s["kind"] == "enemy_aegis"]
    assert [(s["label"], s["at_label"]) for s in strip] == [("Аегіс ворогів", "30:03")]
    assert all(s["kind"] != "enemy_aegis" for s in timer.strip(at + 301, "uk"))


@pytest.mark.parametrize(
    ("events", "enemy"),
    [
        # The picker's id names the team: 0-4 Radiant, 5-9 Dire.
        ([_pickup(1500, player_id=7)], False),
        ([_pickup(1500, player_id=2)], True),
        # No id: the team that killed Roshan (a snatch can fool it; nothing better).
        ([_kill(1500, "dire"), _pickup(1500)], False),
        ([_kill(1500, "radiant"), _pickup(1500)], True),
        # Neither: nothing is claimed.
        ([_pickup(1500)], False),
    ],
)
def test_whose_aegis_it_is(events, enemy):
    timer = RoshanTimer()
    timer.observe(_extra(1500, events, team="dire"))
    assert timer.enemy_aegis(1510) is enemy
    assert (timer.hint(1505, "en") is not None) is enemy


def test_gsi_keeps_who_took_roshan_and_the_aegis_and_the_own_base():
    buildings = {
        "dire": {
            "dota_badguys_tower3_top": {"health": 1, "max_health": 2500},
            "dota_badguys_tower3_mid": {"health": 2500, "max_health": 2500},
            "bad_rax_melee_mid": {"health": 2200, "max_health": 2200},
            "bad_rax_range_mid": {"health": 1300, "max_health": 1300},
        },
    }
    payload = {
        "map": {"clock_time": 1600, "game_time": 1690},
        "player": {"team_name": "dire"},
        "hero": {"name": "npc_dota_hero_terrorblade"},
        "buildings": buildings,
        "events": [
            {"game_time": 1680, "event_type": "roshan_killed", "killed_by_team": "radiant"},
            {"game_time": 1680, "event_type": "aegis_picked_up", "player_id": 4, "snatched": False},
        ],
    }
    extra = normalize_gsi_payload(payload)["extra_context"]
    assert extra["gsi_events"] == [
        {"type": "roshan_killed", "game_time": 1680, "team": "radiant"},
        {"type": "aegis_picked_up", "game_time": 1680, "player_id": 4},
    ]
    assert extra["own_base"] == {"tower3": 2, "barracks": 2}
    assert (
        normalize_gsi_payload({**payload, "buildings": {}})["extra_context"].get("own_base") is None
    )


def test_the_game_is_on_the_line():
    assert base_danger(True, None) == "enemy_aegis"
    assert base_danger(False, {"tower3": 2, "barracks": 6}) == "base"
    assert base_danger(False, {"tower3": 3, "barracks": 5}) == "base"
    assert base_danger(False, {"tower3": 3, "barracks": 6}) is None
    assert base_danger(False, None) is None


# --- buyback before minute 30 -----------------------------------------------------------


def _spend(clock, danger):
    tracker = BuybackTracker()
    tracker.observe(clock, 2600, 1500, 0, True, danger)
    tracker.observe(clock + 1, 500, 1500, 0, True, danger)
    return tracker.signal()


def test_spending_the_buyback_counts_from_minute_20_with_the_game_on_the_line():
    assert _spend(26 * 60, None) is None  # before 30:00, as before
    assert _spend(19 * 60, "enemy_aegis") is None
    signal = _spend(26 * 60, "enemy_aegis")
    assert signal == {"clock": 26 * 60 + 1, "gold": 500, "cost": 1500, "danger": "enemy_aegis"}
    assert _spend(31 * 60, None) == {"clock": 31 * 60 + 1, "gold": 500, "cost": 1500}


def test_the_buyback_reason_names_the_danger_in_both_languages():
    reason = _buyback_reason({"gold": 13, "cost": 1469, "danger": "enemy_aegis"})
    assert reason == (
        "You have 13 gold and buyback costs 1469; the enemy holds the Aegis: "
        "one death without buyback can decide the game."
    )
    assert translate_uk(reason) == (
        "Золота 13, байбек коштує 1469. Аегіс у ворогів: одна смерть без байбеку може вирішити гру."
    )
    base = _buyback_reason({"gold": 13, "cost": 1469, "danger": "base"})
    assert translate_uk(base).startswith("Золота 13, байбек коштує 1469. Ваша база відкрита")
    # Under pressure the buyback card waits, unless the game is on the line.
    common = {
        "decision_point": "SAFE_FARMING",
        "hp_percent": 90,
        "farm_quality": "good",
        "hp_pressure": "",
        "pressure_active": True,
        "position_risk": "",
        "position_zone": "",
        "death_context": False,
        "buyback_spent": True,
    }
    assert _category_for_state(**common) != "post_laning_buyback_reserve"
    assert _category_for_state(**common, buyback_danger=True) == "post_laning_buyback_reserve"


# --- the death screen -------------------------------------------------------------------


def _screen(lang="uk", **over):
    inputs = {
        "death": {},
        "place": None,
        "respawn": 64,
        "gold": 1420,
        "buyback_cost": 1569,
        "buyback_cooldown": 0,
        "minute": 28,
        "next_item": None,
        "danger": None,
        **over,
    }
    return build_death_screen(**inputs, lang=lang)


def test_the_death_screen_says_how_much_the_buyback_was_short():
    card = _screen()
    assert card["lines"] == ["Байбек коштує 1569, а після смерті у вас 1420: не вистачає 149."]
    english = _screen("en")
    assert english["lines"] == ["Buyback costs 1569 and you have 1420 after the death: 149 short."]

    # Before minute 20 only with the game on the line (the gold is spent as before);
    # on cooldown or affordable: not said.
    def said(**over):
        card = _screen(**over)
        return any(line.startswith("Байбек") for line in (card or {}).get("lines", []))

    assert not said(minute=15)
    assert _screen(minute=15)["lines"][0].startswith("Витратьте 1420")
    assert said(minute=15, danger="enemy_aegis")
    assert not said(buyback_cooldown=200)
    assert not said(gold=1600)


def test_with_the_game_on_the_line_the_gold_is_kept_and_the_item_still_named():
    item = {
        "key": "sphere",
        "name": "Linken's Sphere",
        "gold_left": 580,
        "why": "targeted",
        "count": 2,
        "enemy": "Shadow Shaman",
        "spell": "Hex",
        "alternative": {
            "why": "disabled",
            "key": "black_king_bar",
            "name": "Black King Bar",
            "enemy": None,
            "spell": None,
        },
    }
    card = _screen(next_item=item, danger="enemy_aegis")
    assert card["lines"] == [
        "Байбек коштує 1569, а після смерті у вас 1420: не вистачає 149.",
        "Наступний предмет — Linken's Sphere, коли золото на байбек буде.",
        "Чому Linken's Sphere: смертей під контролем проти Shadow Shaman — 2, він блокує Hex.",
        "Інший варіант — Black King Bar: проти оглушень, якщо тримають ними, а не Hex.",
    ]
    # With gold to spare above the buyback the purchase line keeps the reserve.
    rich = _screen(next_item=item, danger="base", gold=2600, minute=24)
    assert (
        rich["lines"][0]
        == "Купіть Linken's Sphere зараз: золота вистачає, кур'єр принесе. Залиште 1569 на байбек."
    )


# --- Linken's or BKB, by the situation --------------------------------------------------


def _held(t, hexed):
    return {
        "t": t,
        "last": {
            "hp": [[-4, 60], [-3, 50], [-2, 40], [-1, 20], [0, 5]],
            "free_s": 0,
            "held_s": 5,
            "hexed_s": hexed,
        },
    }


def test_last_seconds_count_the_hexed_seconds():
    seconds = LastSeconds()
    for clock in range(96, 101):
        hexed = clock >= 98
        seconds.observe(
            clock,
            {"alive": True, "health_percent": 50, "stunned": not hexed, "hexed": hexed},
            {},
        )
    last = seconds.summarize(100)
    assert last["held_s"] == 5 and last["hexed_s"] == 3
    assert disable_kind(last) == "hex"
    assert disable_kind({"held_s": 5, "hexed_s": 0}) == "stun"
    assert disable_kind({"held_s": 5}) is None  # an older record


LINEUP = ["Shadow Shaman", "Tidehunter", "Pudge", "Clinkz", "Techies"]


def _after(deaths, enemies=LINEUP):
    return situational_item(
        deaths, [], META, enemies=enemies, position="carry", minute=28, hero="Wraith King"
    )


def test_deaths_in_a_hex_ask_for_linkens_with_bkb_as_the_other_option():
    item = _after([_held(849, 0), _held(1693, 3), _held(1793, 3)])
    assert (item["key"], item["why"], item["enemy"], item["spell"]) == (
        "sphere",
        "targeted",
        "Shadow Shaman",
        "Hex",
    )
    assert item["alternative"]["key"] == "black_king_bar"
    # All in a Hex: no alternative to name.
    assert "alternative" not in _after([_held(1, 4), _held(2, 5)])


def test_deaths_in_stuns_ask_for_bkb_with_linkens_as_the_other_option():
    item = _after([_held(849, 0), _held(1693, 0), _held(1793, 3)])
    assert (item["key"], item["why"]) == ("black_king_bar", "disabled")
    alternative = item["alternative"]
    assert (alternative["key"], alternative["enemy"], alternative["spell"]) == (
        "sphere",
        "Shadow Shaman",
        "Hex",
    )
    # Without a single-target disabler: BKB alone.
    assert "alternative" not in _after([_held(1, 0), _held(2, 0)], ["Tidehunter", "Techies"])


def test_older_death_records_keep_the_old_choice():
    old = [
        {"t": t, "last": {k: v for k, v in _held(t, 0)["last"].items() if k != "hexed_s"}}
        for t in (1, 2)
    ]
    item = _after(old)
    assert (item["key"], item["enemy"]) == ("sphere", "Shadow Shaman")
    assert "alternative" not in item
    assert Counter(disable_kind(d["last"]) for d in old) == Counter({None: 2})


# --- enemies grouped far away -----------------------------------------------------------


def _unit(hero, x, y):
    return {"hero": hero, "x": CENTER + x, "y": CENTER + y}


FIVE_BOT = [_unit(h, 5500 + i * 100, 1100 + i * 50) for i, h in enumerate(LINEUP)]


def test_a_group_far_from_the_player_is_found():
    group = enemy_group(FIVE_BOT, CENTER - 400, CENTER + 7500, "dire")
    assert group["count"] == 5 and group["zone"] == "bot" and group["side"] == "own"
    # Close to the player, too few, or no position: nothing.
    assert enemy_group(FIVE_BOT, CENTER + 5000, CENTER + 1000, "dire") is None
    assert enemy_group(FIVE_BOT[:3], CENTER - 400, CENTER + 7500, "dire") is None
    assert enemy_group(FIVE_BOT, None, None, "dire") is None
    spread = [_unit(h, -6000 + i * 3000, -6000 + i * 3000) for i, h in enumerate(LINEUP)]
    assert enemy_group(spread, CENTER, CENTER, "dire") is None


def test_the_group_card_shows_at_most_once_every_three_minutes():
    group = enemy_group(FIVE_BOT, CENTER - 400, CENTER + 7500, "dire")
    tips = RoleTips()

    def card(clock, lang="uk"):
        return tips.tip(clock, "carry", alive=True, has_ward=None, lang=lang, enemies=None) or (
            tips.enemy_group(clock, lang, group)
        )

    assert tips.enemy_group(9 * 60, "uk", group) is None  # the laning stage
    first = tips.enemy_group(21 * 60, "uk", group)
    assert first["title"] == "Ворогів разом — 5, на нижній лінії на своїй половині"
    assert "Туди один не йдіть" in first["hint"]
    english = tips.enemy_group(21 * 60 + 5, "en", None)
    assert english["title"] == "5 enemies together in the bottom lane on your side"
    assert tips.enemy_group(21 * 60 + GROUP_SHOW + 1, "uk", group) is None
    assert tips.enemy_group(21 * 60 + GROUP_EVERY, "uk", group) is not None


def test_the_enemy_aegis_reaches_the_overlay(client):
    from test_roshan_timer import OFFSET as FIXTURE_OFFSET
    from test_roshan_timer import _payload

    from app.match_memory import MATCH_MEMORY

    client.post("/settings/advice", json={"role": "carry"})
    at = 25 * 60
    events = [
        {"game_time": at + FIXTURE_OFFSET, "event_type": "roshan_killed", "killed_by_team": "dire"},
        {"game_time": at + FIXTURE_OFFSET, "event_type": "aegis_picked_up", "player_id": 7},
    ]
    client.post("/gsi", json=_payload(at + 2, events))  # the fixture's hero is Radiant
    assert MATCH_MEMORY.roshan.enemy_aegis(at + 2)
    answer = client.get("/overlay/recommendation?lang=uk").json()
    assert answer["map_hint"]["title"] == "Аегіс у ворогів до 30:00"
    assert any(item["kind"] == "enemy_aegis" for item in answer.get("timer_strip") or [])


def test_a_dead_hero_keeps_the_buyback_with_the_game_on_the_line():
    from app.post_laning_coach import spend_while_dead_sentence

    # The match at 28:13: 1420 gold after the death, buyback 1569.
    state = {
        "minute": 28,
        "gold": 1420,
        "extra_context": {"alive": False, "available_gold": 1420, "buyback_cost": 1569},
    }
    assert spend_while_dead_sentence(state).startswith("Buy parts of your next item now")
    state["extra_context"]["base_danger"] = "enemy_aegis"
    assert spend_while_dead_sentence(state) is None
    state["extra_context"].update(available_gold=2600)
    assert spend_while_dead_sentence(state) == (
        "Buy parts of your next item with 1031 gold and keep 1569 for buyback."
    )
