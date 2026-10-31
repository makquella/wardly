"""The GSI census: which fields the game really sends, for the problem report."""

from __future__ import annotations

import copy
import json

from app.gsi_census import GSI_CENSUS, GsiCensus


def _real(repo_root):
    path = repo_root / "data" / "gsi_samples" / "real_player_hero_demo.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _status(census):
    return {row["key"]: row["status"] for row in census.features()}


def test_a_real_player_payload_has_the_core_fields_and_no_minimap_or_events(repo_root):
    census = GsiCensus()
    census.observe(_real(repo_root))
    status = _status(census)
    for key in ("hp_mana", "disables", "item_ready", "abilities", "ultimate", "talents"):
        assert status[key] == "ok", key
    assert status["tp_slot"] == "ok" and status["position"] == "ok"
    # The sample's config did not ask for them: the census says so.
    assert status["minimap"] == "missing" and status["events"] == "missing"
    summary = census.summary()
    assert summary["in_game_payloads"] == 1
    assert "items.slot*.can_cast" in summary["paths"]
    assert "abilities.ability*.ultimate" in summary["paths"]


def test_values_never_leave_only_field_names(repo_root):
    census = GsiCensus()
    payload = _real(repo_root)
    census.observe(payload)
    text = json.dumps(census.summary())
    assert payload["player"]["steamid"] not in text
    assert "player.steamid" in text  # the field name is fine


def test_flags_minimap_heroes_and_events_are_counted(repo_root):
    census = GsiCensus()
    payload = _real(repo_root)
    payload["hero"]["stunned"] = True
    payload["minimap"] = {
        "o1": {"unitname": "npc_dota_hero_beastmaster", "team": 3, "xpos": 1, "ypos": 2},
        "o2": {"unitname": "npc_dota_hero_skeleton_king", "team": 2},
        "o3": {"unitname": "npc_dota_creep_badguys_melee", "team": 3},
    }
    payload["events"] = [{"event_type": "roshan_killed", "game_time": 900}]
    census.observe(payload)
    census.observe(copy.deepcopy(_real(repo_root)))
    summary = census.summary()
    assert summary["hero_flags_true"]["hero.stunned"] == 1
    assert summary["event_types"] == {"roshan_killed": 1}
    assert summary["minimap"]["enemy_heroes_seen"] == ["beastmaster"]
    assert summary["minimap"]["own_heroes_max"] == 1
    assert summary["minimap"]["payloads_with_enemy_heroes"] == 1
    # Half of the in-game payloads had a minimap: it counts as sent.
    assert _status(census)["minimap"] == "ok"


def test_menu_payloads_are_counted_but_not_walked():
    census = GsiCensus()
    census.observe({"map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"}})
    census.observe("broken")
    summary = census.summary()
    assert summary["payloads"] == 1 and summary["in_game_payloads"] == 0
    assert {row["status"] for row in summary["features"]} == {"no_data"}


def test_gsi_feeds_the_census_and_diagnostics_carry_it(client, repo_root):
    client.post("/gsi", json=_real(repo_root))
    assert GSI_CENSUS.in_game == 1
    body = client.get("/diagnostics").json()
    assert body["gsi_census"]["in_game_payloads"] == 1


def test_the_dota_plus_wheel_is_not_a_hero_ability(repo_root):
    """Real GSI lists plus_high_five and plus_guild_banner at level 1."""
    from app.gsi_state import normalize_gsi_payload
    from app.skill_tips import read_skills

    payload = _real(repo_root)
    payload["hero"]["level"] = 3
    payload["abilities"]["ability0"]["level"] = 2
    skills = read_skills(payload)
    assert skills["spent"] == 2  # the wheel's two levels are not skill points
    names = [a["raw_name"] for a in normalize_gsi_payload(payload)["extra_context"]["abilities"]]
    assert not any(name.startswith("plus_") for name in names)


def test_backpack_items_are_not_ready_to_press(repo_root):
    """Real GSI reports slot6-8 (the backpack) with can_cast true."""
    from app.gsi_state import normalize_gsi_payload

    path = repo_root / "data" / "gsi_samples" / "real_player_ranked.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"]["slot7"] = {
        "name": "item_force_staff",
        "purchaser": 0,
        "can_cast": True,
        "cooldown": 0,
        "passive": False,
    }
    extra = normalize_gsi_payload(payload)["extra_context"]
    assert "item_force_staff" not in extra["ready_savers"]
    # The Bottle sits in slot8 of that real payload: in the backpack, not usable.
    assert extra["regen_items"] == []
    payload["items"]["slot2"] = payload["items"].pop("slot7")
    assert "item_force_staff" in normalize_gsi_payload(payload)["extra_context"]["ready_savers"]


def test_diff_blocks_and_empty_slots_are_not_fields(repo_root):
    """A real report (0.30.2): Dota adds `added` / `previously` diff blocks, and
    an empty inventory left the item features looking "missing"."""
    census = GsiCensus()
    payload = _real(repo_root)
    payload["previously"] = {"hero": {"health": 600}}
    payload["added"] = {"minimap": {"o9": {"unitname": "x"}}}
    payload["items"] = {f"slot{i}": {"name": "empty"} for i in range(9)}
    payload["items"]["teleport0"] = {"name": "item_tpscroll", "can_cast": True, "cooldown": 0}
    census.observe(payload)
    summary = census.summary()
    assert not [p for p in summary["paths"] if p.startswith(("added", "previously"))]
    status = _status(census)
    assert status["item_ready"] == "no_data" and status["tp_slot"] == "ok"
    census.observe(_real(repo_root))  # Manta Style: a real item with can_cast
    assert summary["payloads_with_items"] == 0
    assert _status(census)["item_ready"] == "ok"


def test_minimap_hero_icons_are_counted(repo_root):
    census = GsiCensus()
    payload = _real(repo_root)
    payload["minimap"] = {
        "o1": {"unitname": "npc_dota_hero_nevermore", "team": 2, "image": "minimap_hero"},
        "o2": {"unitname": "npc_dota_hero_nevermore", "team": 2, "image": "minimap_illusion"},
    }
    census.observe(payload)
    minimap = census.summary()["minimap"]
    assert minimap["own_heroes_max"] == 2 and minimap["own_hero_names_max"] == 1
    assert minimap["hero_images"] == {"minimap_hero": 1, "minimap_illusion": 1}


def test_enemies_are_those_of_the_current_match(repo_root):
    """The second real report listed 10 enemy heroes: two matches since start."""
    census = GsiCensus()
    first = _real(repo_root)
    first["map"]["matchid"] = "1"
    first["minimap"] = {"o1": {"unitname": "npc_dota_hero_pudge", "team": 3}}
    census.observe(first)
    second = copy.deepcopy(first)
    second["map"]["matchid"] = "2"
    second["minimap"] = {"o1": {"unitname": "npc_dota_hero_axe", "team": 3}}
    census.observe(second)
    summary = census.summary()
    assert summary["matches"] == 2
    assert summary["minimap"]["enemy_heroes_seen"] == ["axe"]


def test_a_roshan_kill_among_many_chat_events_is_read():
    from app.gsi_state import _objective_events

    events = [{"event_type": "roshan_killed", "game_time": 1500}]
    events += [{"event_type": "chat_message", "game_time": 1500 + i} for i in range(40)]
    assert _objective_events(events) == [{"type": "roshan_killed", "game_time": 1500}]


def _in_game(payload, state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
    payload["map"]["game_state"] = state
    return payload


def test_the_census_is_saved_and_shown_after_a_restart(client, repo_root, tmp_path):
    """A real report (R-QXW4K6) was sent 16 s after a restart: the census was
    empty although a match had been played. The last run's census is now saved."""
    from app.gsi_census import CENSUS_FILE, SAVE_EVERY
    from app.player_api import PLAYER_SERVICE

    path = PLAYER_SERVICE.data_dir / CENSUS_FILE
    census = GsiCensus()
    census.observe(_in_game(_real(repo_root)))
    assert census.save_due(path, now=1000.0)
    census.observe(_in_game(_real(repo_root)))
    assert not census.save_due(path, now=1000.0 + SAVE_EVERY - 1)  # too soon
    assert census.save_due(path, now=1000.0 + SAVE_EVERY)
    assert not census.save_due(path, now=5000.0)  # nothing new since
    # The match ends: saved at once, whatever the time.
    census.observe(_in_game(_real(repo_root)))
    census.observe(_in_game(_real(repo_root), "DOTA_GAMERULES_STATE_POST_GAME"))
    assert census.save_due(path, now=5001.0)

    # A new run with no game yet: the report carries the saved census.
    body = client.get("/diagnostics").json()["gsi_census"]
    assert body["in_game_payloads"] == 0
    assert body["previous_run"]["in_game_payloads"] == 3
    assert body["previous_run"]["saved_at"]
    # Once this run gets in-game data, only its own census is shown.
    client.post("/gsi", json=_in_game(_real(repo_root)))
    body = client.get("/diagnostics").json()["gsi_census"]
    assert body["in_game_payloads"] == 1 and "previous_run" not in body


def test_a_broken_census_file_is_ignored(client):
    from app.gsi_census import CENSUS_FILE
    from app.player_api import PLAYER_SERVICE

    path = PLAYER_SERVICE.data_dir / CENSUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert "previous_run" not in client.get("/diagnostics").json()["gsi_census"]


def test_minimap_creeps_and_neutrals_are_counted(repo_root):
    # farm_map.py needs them; a feed without them leaves the farm tip off.
    census = GsiCensus()
    payload = _real(repo_root)
    payload["minimap"] = {
        "o1": {"image": "minimap_siege", "unitname": "npc_dota_goodguys_siege", "team": 2},
        "o2": {"image": "minimap_creep", "unitname": "npc_dota_neutral_kobold", "team": 4},
    }
    census.observe(payload)
    only_heroes = _real(repo_root)
    only_heroes["minimap"] = {"o1": {"unitname": "npc_dota_hero_beastmaster", "team": 3}}
    census.observe(only_heroes)
    minimap = census.summary()["minimap"]
    assert minimap["payloads_with_lane_creeps"] == 1
    assert minimap["payloads_with_neutrals"] == 1
