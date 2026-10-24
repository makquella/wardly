"""HP falling fast: the low-HP card comes while there is still time to leave."""

from __future__ import annotations

import copy

from match_fixtures import gsi_match_stream

from app.decision_points import detect_decision_point
from app.live_tools import hp_falling_reason


def _feed(client, *health):
    stream = gsi_match_stream(minutes=20, death_minutes=())
    for payload in stream:
        client.post("/gsi", json=payload)
    last = stream[-1]
    for percent in health:
        payload = copy.deepcopy(last)
        payload["hero"]["health_percent"] = percent
        client.post("/gsi", json=payload)


def test_hp_falling_fast_raises_the_urgent_card_before_it_is_critical(client):
    _feed(client, 100, 90, 60)
    body = client.get("/overlay/recommendation").json()
    assert body["decision_point"] == "LOW_HP"
    assert body["advice_mode"] == "urgent"
    # What was measured, no projection: a finished combo is not a constant DPS.
    assert body["recommendation"]["reason"] == (
        "You lost 40% HP in 5 seconds and it is still dropping."
    )
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()["recommendation"]
    assert ukrainian["reason"] == "За 5 секунд пішло 40% HP, і воно далі падає."


def test_a_slow_drop_or_a_high_hp_is_not_a_fall(client):
    _feed(client, 100, 80, 75)  # 25 points: a trade, not a fall
    assert client.get("/overlay/recommendation").json()["decision_point"] != "LOW_HP"
    _feed(client, 100, 72)  # 28 points
    assert client.get("/overlay/recommendation").json()["decision_point"] != "LOW_HP"


def test_the_rule_reads_only_the_live_flag():
    state = {"hp_percent": 65, "minute": 20, "extra_context": {"hp_falling_fast": 35}}
    assert detect_decision_point(state) == "LOW_HP"
    assert detect_decision_point({**state, "extra_context": {}}) != "LOW_HP"
    assert hp_falling_reason({"hp_falling_fast": None}) is None
    assert hp_falling_reason({"hp_falling_fast": True}) is None


def test_the_low_hp_card_keeps_its_rule_reasons():
    # The LOW_HP reason used to be forced to the standard line, which hid the
    # ready tool and the repeat count on the main low-HP card.
    from app.advice_text import clean_reason_text

    kept = [
        "You lost 40% HP in 5 seconds and it is still dropping.",
        "Your HP has dropped this low 3 times this game: heal up fully before you go back.",
        "Your HP is low and Blink Dagger is ready: use it before the next hit, not after.",
        "Blade Fury is ready: it buys you the seconds to get away.",
        "Magic Wand has 14 charges: that HP is yours right now.",
        "Faerie Fire heals you at once.",
        "Healing Salve heals over time: use it where enemies cannot hit you.",
    ]
    for reason in kept:
        assert clean_reason_text(reason, "LOW_HP") == reason
    assert clean_reason_text("Go dive their tower now.", "LOW_HP") == (
        "At this HP, one more trade or spell can kill you."
    )


def test_deaths_in_one_place_spread_over_the_match_are_named(client):
    # Deaths 13 minutes apart miss the 10-minute window, but three in the same
    # place in one game are still a pattern (the fixture dies at the same spot
    # from minute 10 on, outside 17-21).
    from app.player_api import PLAYER_SERVICE

    for payload in gsi_match_stream(positions=True, death_minutes=(11, 14, 27), minutes=28):
        if payload["map"]["clock_time"] > 27 * 60 + 5:
            break
        client.post("/gsi", json=payload)
    place = PLAYER_SERVICE.recent_death(27 * 60 + 5)["place"]
    assert place["count"] == 1 and place["in_match"] == 3
    assert (place["zone"], place["side"]) == ("jungle", "own")
    body = client.get("/overlay/recommendation").json()
    assert body["recommendation"]["action"] == (
        "After respawn, stay away from the jungle on your side."
    )
    assert body["recommendation"]["reason"] == (
        "3 deaths in the jungle on your side this game: "
        "farm somewhere safer until your team is there."
    )
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()
    assert "за гру: фарміть в іншому місці" in ukrainian["recommendation"]["reason"]
    assert any(
        "3-та смерть" in line and "за гру" in line for line in ukrainian["death_screen"]["lines"]
    )
