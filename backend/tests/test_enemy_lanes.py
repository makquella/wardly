"""Where the enemy heroes laned and who is missing (enemy_lanes.py)."""

from __future__ import annotations

from match_fixtures import gsi_match_stream

from app.enemy_heroes import visible_enemy_units
from app.enemy_lanes import MISSING_AFTER, EnemyLanes
from app.gsi_state import _normalize_hero_name
from app.map_hints import MISSING_GAP, MISSING_SHOW, RoleTips

C = 16384  # MAP_CENTER
ENEMY = {"image": "minimap_enemyicon"}
MID = {"hero": "Lina", "x": C, "y": C}
BOT = {"hero": "Axe", "x": C + 5000, "y": C - 6200}


def _laned(until=200, units=(MID, BOT)):
    lanes = EnemyLanes()
    for clock in range(60, until + 1, 5):
        lanes.observe(clock, [dict(u) for u in units])
    return lanes


def test_the_minimap_gives_positions_in_replay_units():
    minimap = {
        "o1": {
            "image": "minimap_enemyicon",
            "unitname": "npc_dota_hero_lina",
            "team": 3,
            "xpos": 40,
            "ypos": -40,
        },
        "o2": {
            "image": "minimap_enemyicon",
            "unitname": "npc_dota_hero_axe",
            "team": 3,
            "xpos": "x",
            "ypos": 5,
        },
        "o3": {
            "image": "minimap_enemyicon",
            "unitname": "npc_dota_hero_lion",
            "team": 2,
            "xpos": 0,
            "ypos": 0,
        },
        # An icon not placed yet, and a pick-screen phantom: no sighting.
        "o4": {
            "image": "minimap_enemyicon",
            "unitname": "npc_dota_hero_zuus",
            "team": 3,
            "xpos": 0,
            "ypos": 0,
        },
        "o5": {"image": "minimap_plaincircle", "unitname": "npc_dota_hero_pudge", "team": 3},
    }
    units = visible_enemy_units(minimap, "radiant", _normalize_hero_name)
    assert units == [
        {"hero": "Lina", "x": C + 40, "y": C - 40},
        {"hero": "Axe", "x": None, "y": None},
    ]
    assert visible_enemy_units(minimap, None, _normalize_hero_name) is None


def test_lanes_come_from_sightings_in_the_laning_stage():
    lanes = _laned()
    assert lanes.lanes() == {"Lina": "mid", "Axe": "bot"}
    # Too few sightings: no lane claimed.
    few = EnemyLanes()
    few.observe(60, [dict(MID)])
    assert few.lane("Lina") is None


def test_the_enemy_mid_and_the_lane_opponent_go_missing():
    lanes = _laned(until=200)
    # Seen until 200; at 230 both are gone for 30 s.
    call = lanes.missing(230, "bot")
    assert call["hero"] == "Axe" and call["kind"] == "lane" and call["seconds"] == 30
    call = lanes.missing(230, "top")
    assert call == {"hero": "Lina", "lane": "mid", "kind": "mid", "since": 200, "seconds": 30}
    assert lanes.missing(200 + MISSING_AFTER - 1, "bot") is None  # not yet
    assert lanes.missing(200 + 61, "bot") is None  # too long ago to be news
    assert lanes.missing(230, None) is None  # in a base / no position
    # Seen again: nothing missing.
    lanes.observe(231, [dict(MID), dict(BOT)])
    assert lanes.missing(240, "bot") is None
    # Before the laning stage settles there is no call.
    assert _laned(until=100).missing(125, "bot") is None


def test_the_call_shows_once_per_disappearance():
    tips = RoleTips()
    call = {"hero": "Lina", "lane": "mid", "kind": "mid", "since": 200, "seconds": 22}
    tip = tips.missing(222, "uk", call)
    assert tip["title"] == "Не видно міда: Lina" and "22 с" in tip["hint"] and tip["speak"]
    later = tips.missing(230, "uk", {**call, "seconds": 30})
    assert later["hint"] == tip["hint"]  # the first second's number stays
    assert tips.missing(222 + MISSING_SHOW + 1, "uk", call) is None
    # Another enemy inside the gap waits; after it, it is called.
    other = {"hero": "Axe", "lane": "bot", "kind": "lane", "since": 210, "seconds": 25}
    assert tips.missing(235, "en", other) is None
    tip = tips.missing(222 + MISSING_GAP, "en", other)
    assert tip["title"] == "Your lane opponent is missing: Axe"


def test_the_call_reaches_the_overlay(client):
    from app.live_role import set_role_setting

    set_role_setting("carry")
    for payload in gsi_match_stream(minutes=5, death_minutes=(), positions=True, step_seconds=5):
        clock = payload["map"]["clock_time"]
        if 60 <= clock <= 200:
            x, y = payload["hero"]["xpos"], payload["hero"]["ypos"]
            payload["minimap"] = {
                "o1": {
                    **ENEMY,
                    "unitname": "npc_dota_hero_axe",
                    "team": 3,
                    "xpos": x + 300,
                    "ypos": y,
                },
                "o2": {
                    **ENEMY,
                    "unitname": "npc_dota_hero_lina",
                    "team": 3,
                    "xpos": 40,
                    "ypos": -40,
                },
            }
        else:
            payload["minimap"] = {}
        client.post("/gsi", json=payload)
        if clock == 225:
            hint = client.get("/overlay/recommendation?lang=en").json()["map_hint"]
            assert hint["title"] == "Your lane opponent is missing: Axe"
            return
    raise AssertionError("the stream never reached 3:45")


def test_the_lane_opponents_are_the_enemies_of_that_lane():
    lanes = _laned()
    assert lanes.opponents("bot") == ["Axe"]
    assert lanes.opponents("mid") == ["Lina"]
    assert lanes.opponents("top") == [] and lanes.opponents(None) == []


def test_the_past_lane_record_reaches_the_overlay(client, monkeypatch):
    from app.live_role import set_role_setting
    from app.player_api import PLAYER_SERVICE

    set_role_setting("carry")
    monkeypatch.setattr(
        PLAYER_SERVICE,
        "lane_records",
        lambda: {"Axe": {"won": 0, "even": 1, "lost": 3, "games": 4}},
    )
    for payload in gsi_match_stream(minutes=3, death_minutes=(), positions=True, step_seconds=5):
        clock = payload["map"]["clock_time"]
        x, y = payload["hero"]["xpos"], payload["hero"]["ypos"]
        payload["minimap"] = {
            "o1": {**ENEMY, "unitname": "npc_dota_hero_axe", "team": 3, "xpos": x + 300, "ypos": y}
        }
        client.post("/gsi", json=payload)
        if clock == 95:
            hint = client.get("/overlay/recommendation?lang=en").json()["map_hint"]
            assert hint["title"] == "Hard lane: Axe"
            assert "3 of 4 times" in hint["hint"]
            return
    raise AssertionError("the stream never reached 1:35")
