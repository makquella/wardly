"""Roshan's respawn window and the Aegis on the map line (app/roshan_timer.py)."""

from __future__ import annotations

import copy

from match_fixtures import gsi_match_stream

from app.gsi_state import normalize_gsi_payload
from app.match_memory import MATCH_MEMORY
from app.roshan_timer import RoshanTimer

OFFSET = 90  # the fixture's game_time = clock_time + 90


def _extra(clock, events=None, aegis=None):
    return {
        "clock_time": clock,
        "game_time": clock + OFFSET,
        "gsi_events": events,
        "has_aegis": aegis,
    }


def _kill(clock):
    return {"type": "roshan_killed", "game_time": clock + OFFSET}


def test_a_kill_opens_the_respawn_window_eight_to_eleven_minutes_later():
    timer = RoshanTimer()
    timer.observe(_extra(20 * 60, [_kill(20 * 60)]))
    assert timer.hint(27 * 60, "en") is None
    hint = timer.hint(28 * 60 - 20, "uk")
    assert hint["title"] == "Рошан може з'явитися"
    assert hint["hint"] == "Вікно появи відкривається о 28:00, до 31:00."
    assert hint["in_seconds"] == 20 and hint["speak"] is True and hint["minor"] is False
    assert hint["title_en"] == "Roshan can respawn"  # spoken without a Ukrainian voice
    assert timer.hint(29 * 60, "en") is None  # inside the window: nothing to repeat
    assert timer.hint(31 * 60, "en")["title"] == "Roshan is up for sure"
    # The same event again (GSI keeps it for a while) changes nothing; a new kill does.
    timer.observe(_extra(21 * 60, [_kill(20 * 60)]))
    assert timer.killed_at == 20 * 60
    timer.observe(_extra(35 * 60, [_kill(20 * 60), _kill(34 * 60)]))
    assert timer.killed_at == 34 * 60


def test_the_aegis_warns_a_minute_before_it_expires():
    timer = RoshanTimer()
    timer.observe(_extra(20 * 60 - 1, aegis=False))
    timer.observe(_extra(20 * 60, aegis=True))
    assert timer.hint(23 * 60 + 59, "en") is None
    hint = timer.hint(24 * 60, "uk")
    assert hint["title"] == "Аегіс згорить через 60 с"
    assert "60" in hint["title_en"] and hint["title_en"].isascii()
    # Used (a death) or expired: gone.
    timer.observe(_extra(24 * 60 + 10, aegis=False))
    assert timer.hint(24 * 60 + 20, "en") is None


def test_the_aegis_expiry_follows_the_pickup_event_after_a_restart():
    # The backend starts at 22:00 while the hero already holds an Aegis taken at 20:00.
    pickup = {"type": "aegis_picked_up", "game_time": 20 * 60 + OFFSET}
    timer = RoshanTimer()
    timer.observe(_extra(22 * 60, [pickup], aegis=True))
    assert timer.aegis_at == 20 * 60
    assert timer.hint(24 * 60, "en")["title"] == "Aegis expires in 60 s"
    # No pickup event and never seen without it: the expiry is unknown, no warning.
    timer = RoshanTimer()
    timer.observe(_extra(22 * 60, aegis=True))
    assert timer.aegis_at is None
    assert timer.hint(26 * 60, "en") is None


def test_no_kill_event_no_roshan_hint():
    timer = RoshanTimer()
    timer.observe(_extra(20 * 60, [{"type": "tip", "game_time": 100}]))
    assert timer.hint(28 * 60, "en") is None


def _payload(clock, events=None, **hero):
    payload = copy.deepcopy(gsi_match_stream(minutes=30, death_minutes=())[-2])
    payload["map"]["clock_time"] = clock
    payload["map"]["game_time"] = clock + OFFSET
    if events is not None:
        payload["events"] = events
    payload["hero"].update(hero)
    return payload


def test_gsi_events_and_the_aegis_flag_are_read():
    extra = normalize_gsi_payload(
        _payload(
            1500,
            [
                {"game_time": 1400, "event_type": "roshan_killed", "killed_by_team": "dire"},
                {"game_time": 1405, "event_type": "chat_message"},
            ],
            aegis=True,
        )
    )["extra_context"]
    assert extra["gsi_events"] == [{"type": "roshan_killed", "game_time": 1400, "team": "dire"}]
    assert extra["has_aegis"] is True


def test_the_roshan_window_reaches_the_overlay(client):
    client.post("/settings/advice", json={"role": "carry"})
    kill = {"game_time": 20 * 60 + OFFSET, "event_type": "roshan_killed"}
    client.post("/gsi", json=_payload(20 * 60 + 5, [kill]))
    assert MATCH_MEMORY.roshan.killed_at == 20 * 60
    client.post("/gsi", json=_payload(28 * 60 - 15, [kill]))
    answer = client.get("/overlay/recommendation?lang=uk").json()
    assert answer["map_hint"]["id"] == "roshan_window@1680"
    assert answer["map_hint"]["title"] == "Рошан може з'явитися"
