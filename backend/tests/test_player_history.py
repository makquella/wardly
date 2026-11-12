"""Linked player, whole-match recording, OpenDota sync and post-match reviews."""

from __future__ import annotations

import re

import pytest
from match_fixtures import (
    MATCH_ID,
    ME,
    ME_STEAM64,
    FakeOpenDota,
    gsi_match_stream,
    opendota_match,
    recent_matches,
)

from app.analysis_texts import FINDINGS, render_analysis, render_finding
from app.career_analysis import analyze_career
from app.draft_analysis import analyze_draft
from app.match_facts import facts_from_opendota, facts_from_timeline, merge_facts
from app.match_tracker import MatchTracker
from app.opendota import summary_from_match, trim_match
from app.player_api import PLAYER_SERVICE
from app.player_service import PlayerService
from app.post_match_analysis import analyze_match
from app.steam_ids import SteamIdError, parse_account_id

# --- Steam ids -------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "52079950",
        ME_STEAM64,
        f"https://steamcommunity.com/profiles/{ME_STEAM64}/",
        "https://www.opendota.com/players/52079950",
        "https://www.dotabuff.com/players/52079950/matches",
        "[U:1:52079950]",
        "STEAM_0:0:26039975",
        " 52079950 ",
    ],
)
def test_parse_account_id_formats(value):
    assert parse_account_id(value) == ME


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("", "empty"),
        ("https://steamcommunity.com/id/someone", "vanity_url"),
        ("hello", "unrecognized"),
        ("0", "out_of_range"),
    ],
)
def test_parse_account_id_errors(value, code):
    with pytest.raises(SteamIdError) as error:
        parse_account_id(value)
    assert error.value.code == code


# --- live match tracker ------------------------------------------------------------


def test_tracker_records_a_whole_match(tmp_path):
    finished = []
    tracker = MatchTracker(tmp_path / "live.json", on_finished=finished.append)
    for payload in gsi_match_stream(death_minutes=(7, 18), win=True):
        tracker.observe(payload)

    assert len(finished) == 1
    timeline = finished[0]
    assert timeline["match_id"] == MATCH_ID
    assert timeline["account_id"] == ME
    assert timeline["steam_id64"] == ME_STEAM64
    assert timeline["hero"] == "Juggernaut"
    assert timeline["finished"] is True
    assert timeline["win"] is True
    assert [d["t"] for d in timeline["deaths"]] == [7 * 60, 18 * 60]
    assert timeline["deaths"][0]["gold"] == 1800
    assert [i["item"] for i in timeline["items"]][:3] == [
        "item_tango",
        "item_power_treads",
        "item_bfury",
    ]
    times = [s["t"] for s in timeline["samples"]]
    assert times[0] == 0 and all(b - a >= 15 for a, b in zip(times, times[1:], strict=False))
    assert timeline["scores"]["radiant"] > 0
    assert not (tmp_path / "live.json").exists()
    assert not any(key.startswith("_") for key in timeline)


def test_tracker_survives_a_restart_mid_match(tmp_path):
    stream = gsi_match_stream()
    first = MatchTracker(tmp_path / "live.json")
    for payload in stream[: len(stream) // 2]:
        first.observe(payload)
    first.flush()

    finished = []
    second = MatchTracker(tmp_path / "live.json", on_finished=finished.append)
    assert second.current()["match_id"] == MATCH_ID
    for payload in stream[len(stream) // 2 :]:
        second.observe(payload)
    assert len(finished) == 1
    assert finished[0]["samples"][0]["t"] == 0


def test_tracker_finishes_stale_match_and_skips_short_games(tmp_path):
    now = [0.0]
    finished = []
    tracker = MatchTracker(
        tmp_path / "live.json", on_finished=finished.append, clock=lambda: now[0]
    )
    # A 3-minute game (abandoned): no review.
    for payload in gsi_match_stream(minutes=3)[:-1]:
        tracker.observe(payload)
    now[0] += 11 * 60
    tracker.check_stale()
    assert finished == []
    assert tracker.current() is None

    for payload in gsi_match_stream(match_id=MATCH_ID + 1, minutes=20)[:-1]:
        tracker.observe(payload)
    now[0] += 11 * 60
    tracker.check_stale()
    assert len(finished) == 1
    assert finished[0]["end_reason"] == "stale"
    assert finished[0]["win"] is None


def test_tracker_ignores_demo_and_lobby_ids(tmp_path):
    tracker = MatchTracker(tmp_path / "live.json")
    payload = gsi_match_stream()[100]
    payload["map"]["matchid"] = "gsi_juggernaut_live_lane_test"
    tracker.observe(payload)
    assert tracker.current() is None


# --- analysis ------------------------------------------------------------------------


def _meta():
    fake = FakeOpenDota()
    return {
        "constants": fake.item_constants(),
        "popularity": fake.item_popularity(8),
        "timings": fake.item_timings(8),
    }


def _analysis(match, lang="en", *, with_meta=True):
    trimmed = trim_match(match, ME)
    facts = facts_from_opendota(trimmed)
    if not with_meta:
        return render_analysis(analyze_match(facts), lang)
    return render_analysis(analyze_match(facts, meta=_meta(), opendota=trimmed), lang)


def test_good_parsed_match_is_praised():
    analysis = _analysis(opendota_match(good=True))
    assert analysis["headline"]["grade"] == "A"
    assert analysis["role"] == "core"
    ids = {f["id"] for f in analysis["strengths"]}
    assert {"lh10_great", "gpm_high", "deaths_low"} <= ids
    assert not [f for f in analysis["improvements"] if f["severity"] >= 3]


def test_bad_parsed_match_names_the_problems_with_numbers():
    analysis = _analysis(opendota_match(good=False), lang="uk", with_meta=False)
    assert analysis["headline"]["grade"] == "D"
    ids = [f["id"] for f in analysis["improvements"]]
    assert "gpm_low" in ids
    assert "core_item_slow" in ids
    assert "farm_stall" in ids
    assert analysis["focus"] == ids[:3]
    gpm = next(f for f in analysis["improvements"] if f["id"] == "gpm_low")
    assert "390" in gpm["text"] and "88%" in gpm["text"] and gpm["drill"]
    stall = next(f for f in analysis["improvements"] if f["id"] == "farm_stall")
    assert "З 15 по 22-ту хвилину" in stall["text"]
    assert analysis["series"]["last_hits"][10] < analysis["series"]["last_hits_target"][10]
    # Gold and experience get a "good pace" line of the same length.
    series = analysis["series"]
    assert len(series["gold_target"]) == len(series["gold"]) and series["gold_target"][10] > 0
    assert len(series["xp_target"]) == len(series["xp"]) and series["xp_target"][10] > 0
    killers = [m["killer"] for m in analysis["moments"] if m["type"] == "death"]
    assert killers[0] == "Shadow Fiend"


def test_unparsed_match_still_gets_a_review_without_timelines():
    analysis = _analysis(opendota_match(good=False, parsed=False))
    assert analysis["parsed"] is False
    assert "laning" not in analysis["sections"]
    assert {"farm", "survival", "fights"} <= set(analysis["sections"])


def test_gsi_timeline_review_and_merge_with_opendota(tmp_path):
    finished = []
    tracker = MatchTracker(tmp_path / "live.json", on_finished=finished.append)
    for payload in gsi_match_stream(lh_per_minute=3.0, death_minutes=(3, 6, 20)):
        tracker.observe(payload)
    gsi = facts_from_timeline(finished[0])
    assert gsi["lh_t"][10] == 30
    assert gsi["kill_participation"] is not None
    analysis = analyze_match(gsi)
    ids = {f["id"] for f in analysis["improvements"]}
    assert {"lh10_low", "lane_deaths", "death_with_gold"} <= ids

    od = facts_from_opendota(trim_match(opendota_match(good=False, my_deaths=[180, 360, 1200]), ME))
    merged = merge_facts(od, gsi)
    assert merged["sources"] == ["gsi", "opendota"]
    # OpenDota knows the killer, GSI the unspent gold at that death.
    assert merged["deaths_log"][0]["killer"] == "Shadow Fiend"
    assert merged["deaths_log"][0]["gold"] == 1800


def test_every_finding_has_both_languages_and_formats_cleanly():
    produced = set()
    for match in (
        opendota_match(good=True),
        opendota_match(good=False),
        opendota_match(good=False, parsed=False),
    ):
        for lang in ("uk", "en"):
            analysis = _analysis(match, lang)
            for finding in analysis["strengths"] + analysis["improvements"]:
                produced.add(finding["id"])
                for text in (finding["title"], finding["text"], finding.get("drill") or ""):
                    assert "{" not in text and text.strip() != "—", (finding["id"], text)
                assert not re.search(r"\bNone\b", finding["text"]), finding
    assert produced
    for finding_id, langs in FINDINGS.items():
        assert set(langs) == {"uk", "en"}, finding_id
        assert set(langs["uk"]) == set(langs["en"]), finding_id


# --- career ---------------------------------------------------------------------------


def test_career_trend_heroes_and_recurring_problems():
    matches = []
    for index in range(20):
        good = index < 10  # recent 10 good, previous 10 bad -> improving
        match = opendota_match(good=good, match_id=MATCH_ID - index)
        trimmed = trim_match(match, ME)
        summary = summary_from_match(trimmed)
        summary["match_id"] = MATCH_ID - index
        summary["start_time"] = 1790000000 - index * 3600
        summary["analysis"] = analyze_match(facts_from_opendota(trimmed))
        matches.append(summary)
    career = analyze_career(matches, "uk")
    assert career["matches"] == 20 and career["winrate"] == 50
    assert career["trend"]["gpm"]["direction"] == "up" and career["trend"]["gpm"]["better"]
    assert career["trend"]["deaths"]["direction"] == "down" and career["trend"]["deaths"]["better"]
    assert career["heroes"][0]["hero"] == "Juggernaut"
    recurring = {item["id"]: item for item in career["recurring"]}
    assert recurring["gpm_low"]["count"] == 10 and recurring["gpm_low"]["of"] == 20
    assert career["focus_plan"] and all(item["drill"] for item in career["focus_plan"])
    assert career["streak"] == {"win": True, "length": 10}
    assert len(career["series"]) == 20 and career["series"][-1]["match_id"] == MATCH_ID


# --- service + API --------------------------------------------------------------------


def _service(tmp_path, client):
    PLAYER_SERVICE.configure(tmp_path / "svc", client=client, auto_start=False)
    return PLAYER_SERVICE


def test_a_broken_gsi_name_still_links_the_player(client, tmp_path):
    """A list as `player.name` used to raise in the SQLite insert after the
    account was marked as seen: it was never linked (found by the GSI fuzzer)."""
    _service(tmp_path, FakeOpenDota(matches={}))
    first, *rest = gsi_match_stream(win=False)
    first["player"]["name"] = [1, 2]
    assert client.post("/gsi", json=first).status_code == 200
    status = client.get("/player").json()
    assert status["linked"] and status["account_id"] == ME
    for payload in rest[:5]:
        client.post("/gsi", json=payload)
    assert PLAYER_SERVICE.tracker.current()["hero"]


def test_gsi_links_the_player_and_reviews_the_match(client, tmp_path):
    fake = FakeOpenDota(matches={MATCH_ID: opendota_match(good=False)})
    service = _service(tmp_path, fake)
    assert client.get("/player").json()["linked"] is False

    for payload in gsi_match_stream(win=False):
        assert client.post("/gsi", json=payload).status_code == 200

    status = client.get("/player").json()
    assert status["linked"] and status["account_id"] == ME and status["source"] == "gsi"
    assert status["last_review"]["match_id"] == MATCH_ID
    rows = client.get("/player/matches").json()["items"]
    assert rows[0]["match_id"] == MATCH_ID and rows[0]["win"] is False
    assert rows[0]["sources"] == ["gsi"] and rows[0]["has_timeline"]

    detail = client.get(f"/player/matches/{MATCH_ID}?lang=uk").json()
    assert detail["parse_status"] == "waiting_opendota"
    assert detail["analysis"]["lang"] == "uk" and detail["analysis"]["sources"] == ["gsi"]

    # After the delay the worker fetches OpenDota and rebuilds the review.
    service.jobs.run_pending(until=float("inf"))
    detail = client.get(f"/player/matches/{MATCH_ID}?lang=uk").json()
    assert detail["sources"] == ["gsi", "opendota"]
    assert detail["parse_status"] == "parsed"
    assert detail["analysis"]["parsed"] is True
    assert len(detail["scoreboard"]) == 10 and sum(r["me"] for r in detail["scoreboard"]) == 1


def test_unparsed_match_requests_a_replay_parse(tmp_path):
    fake = FakeOpenDota(matches={MATCH_ID: opendota_match(parsed=False)})
    service = PlayerService(tmp_path, client=fake, auto_start=False)
    service.link(str(ME))
    service.fetch_match(MATCH_ID, request_parse=True)
    service.jobs.run_pending()
    assert fake.parse_requests == [MATCH_ID]
    assert service.store.get_match(ME, MATCH_ID)["parse_status"] == "parsing"
    # The replay is parsed now: the next poll upgrades the review.
    fake.matches[MATCH_ID] = opendota_match(parsed=True)
    service.jobs.run_pending(until=float("inf"))
    record = service.store.get_match(ME, MATCH_ID)
    assert record["parse_status"] == "parsed" and record["analysis"]["parsed"] is True
    assert fake.parse_requests == [MATCH_ID]


def test_link_sync_and_career_endpoints(client, tmp_path):
    recent = recent_matches(15)
    fake = FakeOpenDota(
        matches={
            row["match_id"]: opendota_match(good=row["radiant_win"], match_id=row["match_id"])
            for row in recent
        },
        recent=recent,
    )
    service = _service(tmp_path, fake)

    bad = client.post("/player/link", json={"steam": "steamcommunity.com/id/me"})
    assert bad.status_code == 400 and bad.json()["code"] == "vanity_url"

    linked = client.post(
        "/player/link", json={"steam": f"https://steamcommunity.com/profiles/{ME_STEAM64}"}
    ).json()
    assert linked["linked"] and linked["account_id"] == ME and linked["source"] == "manual"
    service.jobs.run_pending(until=float("inf"))

    status = client.get("/player").json()
    assert status["sync"]["state"] == "done" and status["player"]["persona_name"] == "Me"
    table = client.get("/player/matches?limit=20").json()
    assert table["total"] == 15 and len(table["items"]) == 15
    assert table["items"][0]["match_id"] == MATCH_ID
    reviewed = [row for row in table["items"] if row["has_analysis"]]
    assert len(reviewed) == 12

    career = client.get("/player/career?lang=uk").json()
    assert career["linked"] and career["matches"] == 15 and career["analyzed"] == 12
    assert career["recurring"] and career["recurring"][0]["text"].startswith("У ")

    assert client.get("/player/matches/1").status_code == 404
    assert client.delete("/player").json()["linked"] is False


def test_other_account_in_gsi_is_offered_not_switched(client, tmp_path):
    _service(tmp_path, None)
    client.post("/player/link", json={"steam": "12345"})
    payload = gsi_match_stream()[50]
    client.post("/gsi", json=payload)
    status = client.get("/player").json()
    assert status["account_id"] == 12345
    assert status["detected"]["account_id"] == ME
    assert client.post("/player/link-detected").json()["account_id"] == ME


def _playing_as(payload, account_id):
    """The same GSI payload with another account at the keyboard."""
    import copy

    payload = copy.deepcopy(payload)
    payload["player"] = {
        **payload.get("player", {}),
        "steamid": str(76561197960265728 + account_id),
    }
    payload["player"].pop("accountid", None)
    return payload


def test_two_people_on_one_computer_switch_by_who_plays(client, tmp_path):
    service = _service(tmp_path, None)
    client.post("/player/link", json={"steam": "12345"})
    payload = gsi_match_stream()[50]
    client.post("/gsi", json=payload)
    # The second person is offered once, then kept as a profile.
    assert client.post("/player/link-detected").json()["account_id"] == ME
    status = client.get("/player").json()
    assert [(p["account_id"], p["current"]) for p in status["profiles"]] == [
        (ME, True),
        (12345, False),
    ]

    # The first one starts Dota again: the app is theirs without a click.
    client.post("/gsi", json=_playing_as(payload, 12345))
    status = client.get("/player").json()
    assert status["account_id"] == 12345 and status["source"] == "profile"
    assert status["detected"] is None
    client.post("/gsi", json=payload)
    assert client.get("/player").json()["account_id"] == ME

    # By hand too; a forgotten profile is offered again, not switched to.
    assert (
        client.post("/player/profiles/switch", json={"account_id": 12345}).json()["account_id"]
        == 12345
    )
    assert client.post("/player/profiles/switch", json={"account_id": 999}).status_code == 404
    left = client.post("/player/profiles/remove", json={"account_id": ME}).json()
    assert [p["account_id"] for p in left["profiles"]] == [12345]
    client.post("/gsi", json=_playing_as(payload, 777))
    client.post("/gsi", json=payload)
    status = client.get("/player").json()
    assert status["account_id"] == 12345 and status["detected"]["account_id"] == ME
    assert service.store.get_player(ME) is not None  # forgetting keeps the account's data


def test_change_forgets_the_profile_and_an_old_database_has_its_one_profile(client, tmp_path):
    service = _service(tmp_path, None)
    client.post("/player/link", json={"steam": "12345"})
    service.store._set_meta("profiles", None)  # a database from before profiles
    assert service.store.profiles() == [12345]
    client.post("/player/link", json={"steam": str(ME)})
    assert service.store.profiles() == [12345, ME]
    client.delete("/player")
    assert service.store.profiles() == [12345]
    service.store._set_meta("profiles", "not json")
    assert service.store.profiles() == []


def test_last_review_belongs_to_the_linked_account(client, tmp_path):
    service = _service(tmp_path, None)
    client.post("/player/link", json={"steam": "12345"})
    # Someone else plays on this PC: their match is stored under their account.
    for payload in gsi_match_stream():
        client.post("/gsi", json=payload)
    assert service.store.get_match(ME, MATCH_ID) is not None
    assert client.get("/player").json()["last_review"] is None
    client.post("/player/link-detected")
    assert client.get("/player").json()["last_review"]["match_id"] == MATCH_ID


def test_sync_skips_bot_practice_and_custom_lobbies(client, tmp_path):
    recent = recent_matches(6)
    recent[1]["lobby_type"] = 4  # bots
    recent[2]["lobby_type"] = 1  # practice
    recent[3]["lobby_type"] = 8  # 1v1 mid
    service = _service(tmp_path, FakeOpenDota(recent=recent))
    client.post("/player/link", json={"steam": str(ME)})
    service.jobs.run_pending(until=float("inf"))
    ids = {row["match_id"] for row in client.get("/player/matches").json()["items"]}
    assert ids == {recent[0]["match_id"], recent[4]["match_id"], recent[5]["match_id"]}


def test_sync_asks_opendota_to_parse_the_newest_unparsed_matches(client, tmp_path):
    import time as clock

    now = int(clock.time())
    recent = recent_matches(8)
    for index, row in enumerate(recent):
        row["start_time"] = now - 3600 * (index + 1)
    recent[6]["start_time"] = now - 10 * 24 * 3600  # replay probably gone
    matches = {
        row["match_id"]: opendota_match(
            good=row["radiant_win"], match_id=row["match_id"], parsed=index == 1
        )
        for index, row in enumerate(recent)
    }
    fake = FakeOpenDota(matches=matches, recent=recent)
    service = _service(tmp_path, fake)
    client.post("/player/link", json={"steam": str(ME)})
    service.jobs.run_pending(until=float("inf"))
    # The five newest, except the one OpenDota has already parsed; each only once.
    expected = [recent[i]["match_id"] for i in (0, 2, 3, 4)]
    assert sorted(fake.parse_requests) == sorted(expected)
    statuses = {
        row["match_id"]: row["parse_status"]
        for row in client.get("/player/matches").json()["items"]
    }
    assert statuses[recent[1]["match_id"]] == "parsed"
    assert statuses[recent[5]["match_id"]] == "basic"
    # A second sync does not ask again for matches that did not get parsed.
    client.post("/player/sync")
    service.jobs.run_pending(until=float("inf"))
    assert sorted(fake.parse_requests) == sorted(expected)


def test_empty_path_env_means_default(monkeypatch, tmp_path):
    from app.config import path_from_env

    monkeypatch.setenv("SOME_DIR", "  ")
    assert path_from_env("SOME_DIR", tmp_path / "x") == tmp_path / "x"
    monkeypatch.setenv("SOME_DIR", str(tmp_path / "y"))
    assert path_from_env("SOME_DIR", tmp_path / "x") == tmp_path / "y"


def test_player_endpoints_work_offline(client, tmp_path):
    _service(tmp_path, None)
    client.post("/player/link", json={"steam": str(ME)})
    assert client.post("/player/sync").json()["opendota"] is False
    assert client.get("/player/matches").json()["items"] == []
    assert client.get("/player/career").json()["matches"] == 0


# --- build advice and rank comparison ------------------------------------------------


def test_opendota_meta_endpoints_are_parsed():
    fake = FakeOpenDota()
    items = fake.item_constants()
    assert items["by_id"]["145"] == "bfury"
    assert items["items"]["bfury"] == {
        "name": "Battle Fury",
        "cost": 4100,
        "assembled": True,
        "components": ["quelling_blade"],
    }
    assert items["items"]["demon_edge"]["assembled"] is False
    timings = fake.item_timings(8)
    assert {"item": "bfury", "time": 900, "games": 900, "wins": 513} in timings
    popularity = fake.item_popularity(8)
    assert popularity["mid_game_items"]["145"] == 700
    stats = fake.hero_stats()
    assert stats[0]["hero_id"] == 8 and stats[0]["brackets"]["5"] == [10000, 5150]


def test_late_core_item_gets_a_winrate_backed_advice():
    analysis = _analysis(opendota_match(good=False), lang="uk")
    ids = [f["id"] for f in analysis["improvements"]]
    late = next(f for f in analysis["improvements"] if f["id"] == "build_timing_late")
    # Compared with the usual timing (20:00, 50%), not the lucky early bucket (15:00, 55%).
    assert "Maelstrom до 26:00" in late["text"] and "40%" in late["text"] and "50%" in late["text"]
    assert "до 20:00" in late["text"] and "55%" not in late["text"]
    assert "до 20:00" in late["drill"]
    # The generic "late first item" finding is replaced by the specific one.
    assert "core_item_slow" not in ids
    build = analysis["build"]
    assert [item["name"] for item in build["items"]] == ["Maelstrom"]
    assert build["items"][0]["timing"]["winrate"] == 40
    assert [row["bought"] for row in build["popular"]["mid"]][:3] == [False, False, False]


def test_standard_build_with_good_timings_is_recognised():
    analysis = _analysis(opendota_match(good=True))
    build = analysis["build"]
    assert [item["key"] for item in build["items"]] == ["bfury", "manta", "black_king_bar"]
    assert build["items"][0]["timing"] == {
        **build["items"][0]["timing"],
        "bucket": 900,
        "winrate": 57,
        "best_bucket": 600,
        "best_winrate": 60,
        "typical_bucket": 1200,
        "typical_winrate": 52,
    }
    ids = {f["id"] for f in analysis["strengths"]}
    assert "build_timing_good" in ids or "build_on_meta" in ids
    assert not [f for f in analysis["improvements"] if f["id"].startswith("build_")]


def test_rank_peers_compare_with_the_direct_opponent():
    analysis = _analysis(opendota_match(good=False), lang="uk")
    peers = analysis["peers"]
    assert peers["role"] == "carry" and peers["role_label"] == "керрі"
    assert peers["lobby_rank_label"] == "Легенда 4"
    assert [p["hero"] for p in peers["peers"]] == ["Anti-Mage"] and peers["peers"][0]["enemy"]
    assert peers["me"]["gpm"] == 390 and peers["avg"]["gpm"] == 600
    from app.peer_analysis import peer_findings

    ids = {f["id"] for f in peer_findings(peers)}
    assert {"peer_gpm_behind", "peer_lh10_behind", "peer_deaths_more"} <= ids
    # The opponent comparison replaces the generic "GPM is low" in the review.
    shown = [f["id"] for f in analysis["improvements"]]
    assert "peer_gpm_behind" in shown and "gpm_low" not in shown
    gpm = next(f for f in analysis["improvements"] if f["id"] == "peer_gpm_behind")
    assert "Anti-Mage" in gpm["text"] and "600" in gpm["text"]
    deaths = next(f for f in analysis["improvements"] if f["id"] == "peer_deaths_more")
    assert "9 смертей проти 5 у керрі" in deaths["text"]
    good = _analysis(opendota_match(good=True))
    assert "peer_gpm_ahead" in {f["id"] for f in peer_findings(good["peers"])}


def test_unparsed_match_peers_follow_the_farm_order():
    """Without lanes (an unparsed match) every non-support used to count as a
    carry, so the enemy mid was the "same-role opponent" too."""
    from app.peer_analysis import match_peers

    match = opendota_match(good=False, parsed=False)
    for player in match["players"]:
        player["lane_role"] = None
    peers = match_peers(trim_match(match, ME))
    # The enemy with the most last hits is their carry (Anti-Mage, 250).
    assert peers["role"] == "carry"
    assert [p["hero"] for p in peers["peers"]] == ["Anti-Mage"]


def test_rank_labels():
    from app.analysis_texts import rank_label

    assert rank_label(54, "uk") == "Легенда 4"
    assert rank_label(35, "en") == "Crusader 5"
    assert rank_label(80, "uk") == "Безсмертний"
    assert rank_label(None, "uk") is None


def test_career_rank_comparison_and_bracket_winrates(client, tmp_path):
    recent = recent_matches(12)
    fake = FakeOpenDota(
        matches={
            row["match_id"]: opendota_match(good=row["radiant_win"], match_id=row["match_id"])
            for row in recent
        },
        recent=recent,
    )
    service = _service(tmp_path, fake)
    client.post("/player/link", json={"steam": str(ME)})
    service.jobs.run_pending(until=float("inf"))
    career = client.get("/player/career?lang=uk").json()
    rank = career["rank"]
    assert rank["rank_label"] == "Легенда 4" and rank["role_label"] == "керрі"
    assert rank["matches"] == 12
    gpm = next(row for row in rank["metrics"] if row["key"] == "gpm")
    assert gpm["peers"] == 600.0
    heroes = {row["hero"]: row for row in career["heroes"]}
    assert heroes["Juggernaut"]["bracket_winrate"] == 51.5
    assert career["rank_bracket_label"] == "Легенда"
    # Meta data is fetched once and then served from the cache.
    assert fake.calls.count("items") == 1 and fake.calls.count("popularity:8") == 1
    assert fake.calls.count("herostats") == 1


def test_build_advice_works_offline_from_the_cache(client, tmp_path):
    fake = FakeOpenDota(matches={MATCH_ID: opendota_match(good=False)})
    service = _service(tmp_path, fake)
    client.post("/player/link", json={"steam": str(ME)})
    service.fetch_match(MATCH_ID, request_parse=False)
    service.jobs.run_pending(until=float("inf"))
    # Internet gone: a new live match of the same hero still gets build advice.
    service.client = None
    for payload in gsi_match_stream(match_id=MATCH_ID + 1, win=False):
        client.post("/gsi", json=payload)
    detail = client.get(f"/player/matches/{MATCH_ID + 1}?lang=uk").json()
    build = detail["analysis"]["build"]
    assert [item["key"] for item in build["items"]] == ["bfury", "manta"]
    assert build["items"][0]["timing"]["winrate"] == 57
    # Manta at 21:00 is the usual timing for the hero: no "late item" advice.
    ids = [f["id"] for f in detail["analysis"]["improvements"]]
    assert "build_timing_late" not in ids


# --- draft ----------------------------------------------------------------------------


def _draft_meta():
    fake = FakeOpenDota()
    return {
        "matchups": {"8": fake.hero_matchups(8), "1": fake.hero_matchups(1)},
        "pool": [1],
        # Anti-Mage is a carry by OpenDota's tags (no reviewed games on it).
        "hero_roles": {"1": ["Carry", "Escape", "Nuker"]},
        "constants": fake.item_constants(),
    }


def _draft_analysis(match, lang="uk"):
    trimmed = trim_match(match, ME)
    facts = facts_from_opendota(trimmed)
    return render_analysis(analyze_match(facts, opendota=trimmed, draft=_draft_meta()), lang)


def _with_enemy(match, index, hero_id):
    match["players"][index]["hero_id"] = hero_id
    return match


def test_draft_matchups_and_a_better_pick_from_the_pool():
    analysis = _draft_analysis(opendota_match(good=True))
    draft = analysis["draft"]
    assert [row["hero"] for row in draft["enemies"]][:2] == ["Anti-Mage", "Shadow Fiend"]
    assert draft["enemies"][0]["winrate"] == 45.0 and draft["enemies"][0]["games"] == 400
    # Juggernaut: mean(-5, -3, -1, 0, +2) = -1.4; Anti-Mage: mean(+5, +3, +2, +6) = +4.0.
    assert [(row["hero"], row["edge"], row["picked"]) for row in draft["pool"]] == [
        ("Anti-Mage", 4.0, False),
        ("Juggernaut", -1.4, True),
    ]
    assert draft["better_pick"] == "Anti-Mage"
    pick = next(f for f in analysis["improvements"] if f["id"] == "draft_better_pick")
    assert "Anti-Mage: +4,0%" in pick["text"] and "-1,4% у Juggernaut" in pick["text"]
    assert pick["section_label"] == "Драфт"


def test_the_better_pick_keeps_the_role():
    from app.draft_analysis import fits_role

    # A support hero of the pool is not offered to a carry, whatever its edge.
    meta = {**_draft_meta(), "hero_roles": {"1": ["Support", "Disabler"]}}
    trimmed = trim_match(opendota_match(good=True), ME)
    block, findings = analyze_draft(facts_from_opendota(trimmed), trimmed, meta, "core")
    assert [row["hero"] for row in block["pool"]] == ["Juggernaut"]
    assert not [f for f in findings if f["id"] == "draft_better_pick"]
    # A few "core" games on a support hero are not enough: the tags must agree...
    played = {"1": {"core": 4, "support": 1}}
    assert not fits_role(1, "core", played, {"1": ["Support", "Initiator"]})
    assert not fits_role(1, "support", played, {"1": ["Support"]})
    # ...unless the player really plays it that way.
    assert fits_role(1, "core", {"1": {"core": 6}}, {"1": ["Support"]})
    assert fits_role(1, "core", {"1": {"core": 2}}, {"1": ["Carry", "Escape"]})
    assert fits_role(1, "core", None, {"1": ["Carry"]})
    assert not fits_role(2, "core", None, None)
    # With the match lineup the position counts: a mid hero is not a carry pick.
    sf = {"11": {"mid": 5, "carry": 1}}
    assert not fits_role(11, "carry", sf, {"11": ["Carry", "Nuker"]})
    assert fits_role(11, "mid", sf, {"11": ["Carry", "Nuker"]})


def test_a_farming_support_is_a_support_in_the_review():
    from app.post_match_analysis import detect_role

    # Unparsed match: no lanes, no wards. Treant took 60 last hits in 25 min
    # (2.4/min, above the old 2.0 support cut), fourth in his team's farm.
    players = [
        {"me": True, "isRadiant": True, "last_hits": 60},
        {"isRadiant": True, "last_hits": 250},
        {"isRadiant": True, "last_hits": 180},
        {"isRadiant": True, "last_hits": 120},
        {"isRadiant": True, "last_hits": 30},
        *({"isRadiant": False, "last_hits": 100} for _ in range(5)),
    ]
    facts = {"duration": 25 * 60, "last_hits": 60}
    assert detect_role(facts) == "core"  # without the lineup: the old guess
    assert detect_role(facts, {"duration": 25 * 60, "players": players}) == "support"
    players[0]["last_hits"] = 300
    assert detect_role(facts, {"duration": 25 * 60, "players": players}) == "core"


def test_counter_item_missing_and_bought():
    match = _with_enemy(opendota_match(good=True), 6, 44)  # Shadow Fiend -> Phantom Assassin
    analysis = _draft_analysis(match)
    counter = next(c for c in analysis["draft"]["counters"] if c["reason"] == "evasion")
    assert counter["heroes"] == ["Phantom Assassin"] and counter["bought"] == []
    missing = next(f for f in analysis["improvements"] if f["id"] == "counter_item_missing")
    assert "Phantom Assassin (ухилення)" in missing["text"]
    assert "Monkey King Bar" in missing["text"]

    match = _with_enemy(opendota_match(good=True), 6, 44)
    me = next(p for p in match["players"] if p.get("account_id") == ME)
    me["purchase_log"].append({"time": 1900, "key": "monkey_king_bar"})
    trimmed = trim_match(match, ME)
    block, findings = analyze_draft(facts_from_opendota(trimmed), trimmed, _draft_meta(), "core")
    assert block["counters"][0]["bought"] == ["Monkey King Bar"]
    assert [f["id"] for f in findings if f["id"].startswith("counter")] == ["counter_item_bought"]
    bought = render_finding(next(f for f in findings if f["id"] == "counter_item_bought"), "en")
    assert bought["title"] == "Answer to Phantom Assassin: Monkey King Bar"
    # A support is not told to buy Monkey King Bar.
    _, support = analyze_draft(facts_from_opendota(trimmed), trimmed, _draft_meta(), "support")
    assert not [f for f in support if f["id"].startswith("counter")]


def test_reviews_are_rebuilt_once_the_role_history_is_known(client, tmp_path):
    """Sync reviews the newest match first, before the older matches say which
    role the player plays each pool hero in; the sync ends with a rebuild."""
    recent = recent_matches(8)
    matches = {}
    for row in recent:
        match = opendota_match(good=True, match_id=row["match_id"])
        me = next(p for p in match["players"] if p.get("account_id") == ME)
        me["hero_id"] = row["hero_id"]  # Juggernaut and Anti-Mage in turn
        matches[row["match_id"]] = match
    service = _service(tmp_path, FakeOpenDota(matches=matches, recent=recent))
    client.post("/player/link", json={"steam": str(ME)})
    service.jobs.run_pending(until=float("inf"))
    newest = client.get(f"/player/matches/{recent[0]['match_id']}?lang=en").json()
    # Anti-Mage has no role tags in the fixture: only the player's own core
    # games on it let it into the pool of this core review.
    pool = [row["hero"] for row in newest["analysis"]["draft"]["pool"]]
    assert "Anti-Mage" in pool


def test_counter_items_of_an_unparsed_match_come_from_the_inventory():
    """An unparsed match has no purchase log: the final inventory (item ids)
    decides, and with no items known there is no "missing" advice at all."""
    from app.draft_analysis import bought_items

    base = _draft_meta()
    constants = {
        **base["constants"],
        "by_id": {**base["constants"]["by_id"], "135": "monkey_king_bar"},
    }
    meta = {**base, "constants": constants}
    mkb_id = "135"
    match = _with_enemy(opendota_match(good=True, parsed=False), 6, 44)  # vs Phantom Assassin
    me = next(p for p in match["players"] if p.get("account_id") == ME)
    me["item_0"] = int(mkb_id)
    trimmed = trim_match(match, ME)
    facts = facts_from_opendota(trimmed)
    assert "monkey_king_bar" in bought_items(facts, constants)
    _, findings = analyze_draft(facts, trimmed, meta, "core")
    assert [f["id"] for f in findings if f["id"].startswith("counter")] == ["counter_item_bought"]

    me["item_0"] = None
    trimmed = trim_match(match, ME)
    facts = facts_from_opendota(trimmed)
    assert bought_items(facts, constants) is None
    block, findings = analyze_draft(facts, trimmed, meta, "core")
    assert block["counters"] and not [f for f in findings if f["id"].startswith("counter")]


def test_no_draft_without_the_enemy_lineup(tmp_path):
    finished = []
    tracker = MatchTracker(tmp_path / "live.json", on_finished=finished.append)
    for payload in gsi_match_stream():
        tracker.observe(payload)
    # GSI in player mode shows only your own hero.
    assert analyze_match(facts_from_timeline(finished[0]))["draft"] is None


def test_service_fetches_matchups_for_the_pool_and_rebuilds_old_reviews(client, tmp_path):
    recent = recent_matches(12)
    fake = FakeOpenDota(
        matches={
            row["match_id"]: opendota_match(good=row["radiant_win"], match_id=row["match_id"])
            for row in recent
        },
        recent=recent,
    )
    service = PLAYER_SERVICE
    service.configure(tmp_path / "svc", client=fake, auto_start=False)
    client.post("/player/link", json={"steam": str(ME)})
    service.jobs.run_pending(until=float("inf"))
    assert {"matchups:8", "matchups:1"} <= set(fake.calls)
    detail = client.get(f"/player/matches/{MATCH_ID}?lang=uk").json()
    assert detail["analysis"]["draft"]["pool"]

    # A review stored by an older version of the rules is rebuilt when read.
    record = service.store.get_match(ME, MATCH_ID)
    old = {**record["analysis"], "version": 1, "draft": None}
    service.store.upsert_match(ME, MATCH_ID, source="opendota", analysis=old)
    detail = client.get(f"/player/matches/{MATCH_ID}?lang=uk").json()
    assert detail["analysis"]["version"] != 1 and detail["analysis"]["draft"]


# --- best vs worst own matches -----------------------------------------------------------


def test_best_matches_are_compared_with_the_worst(client, tmp_path):
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
    compare = client.get("/player/career?lang=uk").json()["self_compare"]
    assert compare["hero"] == "Juggernaut" and compare["matches"] == 12
    assert compare["best"]["winrate"] == 100 and compare["worst"]["winrate"] == 0
    rows = {row["key"]: row for row in compare["rows"]}
    assert rows["lh_10"]["best"] == 70 and rows["lh_10"]["worst"] == 36
    assert all(row["best_is_better"] for row in compare["rows"])
    assert (
        "Перший великий предмет: Battle Fury до 12:00 у найкращих матчах, Maelstrom до 26:00 у найгірших."
        in compare["highlights"]
    )
    assert len(compare["highlights"]) == 3
    # Pick advice depends on each lineup: not a recurring problem to train.
    career = client.get("/player/career?lang=uk").json()
    assert "draft_better_pick" not in {row["id"] for row in career["recurring"]}


def test_best_vs_worst_needs_enough_matches():
    from app.self_compare import compare_best_worst

    rows = [
        {
            "hero": "Juggernaut",
            "win": True,
            "analysis": analyze_match(
                facts_from_opendota(trim_match(opendota_match(good=True), ME))
            ),
        }
        for _ in range(5)
    ]
    assert compare_best_worst(rows, "en") is None


def test_team_fight_deaths_get_a_place_on_the_map():
    from app.match_facts import facts_from_opendota

    match = opendota_match(good=False)
    me_index = next(i for i, p in enumerate(match["players"]) if p.get("account_id") == ME)
    trimmed = trim_match(match, ME)
    deaths = facts_from_opendota(trimmed)["deaths_log"]
    assert deaths and all("x" not in d for d in deaths)
    first = deaths[0]["t"]
    players = [{"deaths": 0} for _ in match["players"]]
    players[me_index] = {"deaths": 1, "deaths_pos": {"150": {"96": 1}}}
    match["teamfights"] = [{"start": first - 20, "end": first + 5, "players": players}]
    trimmed = trim_match(match, ME)
    assert trimmed["trim_version"] >= 2 and trimmed["teamfights"][0]["deaths_pos"]
    deaths = facts_from_opendota(trimmed)["deaths_log"]
    assert (deaths[0]["x"], deaths[0]["y"]) == (150 * 128, 96 * 128)
    assert all("x" not in d for d in deaths[1:])


def test_an_old_trim_is_fetched_again_when_the_review_is_opened(tmp_path, monkeypatch):
    """A match stored by an older trim_match (no skill order) is rebuilt from what
    it has and fetched again in the background — parsed or not."""
    import app.player_service as player_service

    for parsed in (True, False):
        fake = FakeOpenDota(matches={MATCH_ID: opendota_match(parsed=parsed)})
        service = _service(tmp_path / str(parsed), fake)
        service.store.set_primary(ME, source="manual")
        service.fetch_match(MATCH_ID, request_parse=False)
        service.jobs.run_pending(until=float("inf"))
        assert fake.calls.count(f"match:{MATCH_ID}") == 1
        assert service.match_detail(MATCH_ID, "en")["analysis"] is not None
        service.jobs.run_pending(until=float("inf"))
        assert fake.calls.count(f"match:{MATCH_ID}") == 1  # current: not fetched again

        monkeypatch.setattr(player_service, "TRIM_VERSION", 99)
        row = service.store.list_matches(ME, limit=1)[0]
        assert service._trim_outdated(ME, row)
        assert service.match_detail(MATCH_ID, "en")["analysis"] is not None
        service.jobs.run_pending(until=float("inf"))
        assert fake.calls.count(f"match:{MATCH_ID}") == 2
        monkeypatch.undo()


def test_a_targeted_disable_that_keeps_killing_asks_for_linkens():
    """A Queen of Pain kept dying to a farmed Beastmaster: Primal Roar goes through
    BKB, and Linken's Sphere blocks it."""
    match = _with_enemy(opendota_match(good=True), 6, 38)  # Beastmaster
    trimmed = trim_match(match, ME)
    facts = facts_from_opendota(trimmed)
    facts["deaths_log"] = [
        {"t": 600, "killer": "Beastmaster"},
        {"t": 1300, "killer": "Beastmaster"},
        {"t": 1900, "killer": "Beastmaster"},
    ]
    block, findings = analyze_draft(facts, trimmed, _draft_meta(), "core")
    counter = next(c for c in block["counters"] if c["reason"] == "targeted")
    assert counter["heroes"] == ["Beastmaster"] and counter["spell"] == "Primal Roar"
    assert counter["kills"] == 3
    missing = next(f for f in findings if f["id"] == "counter_item_missing")
    assert missing["params"]["items"] == "Linken's Sphere"
    uk = render_finding(missing, "uk")
    assert "Beastmaster (ви гинули під Primal Roar)" in uk["text"]
    # One kill: the lineup alone asks for no Linken's.
    facts["deaths_log"] = facts["deaths_log"][:1]
    block, _ = analyze_draft(facts, trimmed, _draft_meta(), "core")
    assert not [c for c in block["counters"] if c["reason"] == "targeted"]


def test_best_vs_worst_numbers_are_written_in_the_language():
    from app.self_compare import _fmt

    assert _fmt("lane_deaths", 0.5, "uk") == "0,5"
    assert _fmt("lane_deaths", 2.5, "en") == "2.5"
    assert _fmt("deaths", 3.0, "uk") == "3"
