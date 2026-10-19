"""The overlay's "plan for this game" (app/game_plan.py) from pick to 1:30."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

from match_fixtures import ME, FakeOpenDota, gsi_match_stream, opendota_match, recent_matches

from app.game_plan import build_game_plan
from app.player_api import PLAYER_SERVICE


def _synced(client, tmp_path, count=12):
    recent = recent_matches(count)
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
    return PLAYER_SERVICE


def _gsi_at(clock, *, game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
    payload = copy.deepcopy(gsi_match_stream(minutes=1)[0])
    payload["map"]["clock_time"] = clock
    payload["map"]["game_time"] = clock + 90
    payload["map"]["game_state"] = game_state
    return payload


def test_plan_names_the_farm_target_key_item_and_recurring_mistake(client, tmp_path, monkeypatch):
    # The OpenDota path: no high-rank build (with one, its icons replace the item line).
    from app import stratz_builds

    monkeypatch.setattr(stratz_builds, "build", lambda *args, **kwargs: [])
    service = _synced(client, tmp_path)
    plan = service.game_plan("Juggernaut", "uk")
    assert plan is not None
    assert plan["title"] == "План на гру" and plan["hero"] == "Juggernaut"
    assert plan["role"] == "core"
    lh, item, *rest = plan["lines"]
    assert lh.startswith("До 10:00 — 55 добивань (ваш середній: ")
    # The key item comes from the cached OpenDota build with its typical timing.
    assert " до " in item and "перемог" in item and "%" in item
    # Juggernaut's item plan (data/heroes/item_plans) brings its own skill order, by name.
    skills, *mistakes = rest
    assert skills == "Прокачка в про: спершу Blade Fury, потім Blade Dance"
    assert all(line.startswith("Часта помилка: ") for line in mistakes)

    english = service.game_plan("Juggernaut", "en")
    assert english["lines"][0].startswith("55 last hits by 10:00 (your average: ")
    # The record on the hero next to its name: every fixture match is on Juggernaut.
    rows = service.store.matches_for_career(ME, limit=20)
    wins = sum(1 for row in rows if row["win"])
    assert plan["record"] == f"{wins}–{len(rows) - wins}"


def test_plan_is_cached_and_needs_a_linked_account_and_known_hero(client, tmp_path):
    PLAYER_SERVICE.configure(tmp_path / "empty", client=None, auto_start=False)
    assert PLAYER_SERVICE.game_plan("Juggernaut", "en") is None

    service = _synced(client, tmp_path)
    assert service.game_plan("Not A Hero", "en") is None
    first = service.game_plan("Juggernaut", "en")
    assert service.game_plan("Juggernaut", "en") is first


def test_a_hero_never_played_still_gets_the_target_and_overall_reminder(client, tmp_path):
    service = _synced(client, tmp_path)
    plan = service.game_plan("Anti-Mage", "en")
    assert plan is not None
    # No own average and no cached build for Anti-Mage: the plain target only.
    assert plan["lines"][0] == "55 last hits by 10:00"
    assert not any("wins" in line for line in plan["lines"])
    assert "record" not in plan


def test_an_unplayed_hero_without_a_profile_gets_no_guessed_target(client, tmp_path):
    service = _synced(client, tmp_path)
    for hero in ("Windranger", "Nature's Prophet"):
        plan = service.game_plan(hero, "en")
        assert plan is not None and plan["role"] is None
        assert not any("last hits" in line for line in plan["lines"])


def test_an_unplayed_profiled_support_is_a_support_without_a_last_hit_target(client, tmp_path):
    service = _synced(client, tmp_path)
    for hero in ("Lion", "Crystal Maiden"):
        plan = service.game_plan(hero, "en")
        assert plan is not None and plan["role"] == "support"
        assert not any("last hits" in line for line in plan["lines"])


def test_an_unplayed_profiled_core_gets_its_position_target(client, tmp_path):
    service = _synced(client, tmp_path)
    axe = service.game_plan("Axe", "en")
    assert axe["role"] == "offlane" and axe["lines"][0] == "38 last hits by 10:00"
    storm = service.game_plan("Storm Spirit", "en")
    assert storm["role"] == "core" and storm["lines"][0] == "55 last hits by 10:00"


def test_supports_get_no_last_hit_target():
    history = [{"analysis": {"role": "support", "findings": []}, "lh_10": 4}] * 3
    assert build_game_plan(hero="Lion", history=history, all_recent=[], meta=None, lang="en") is (
        None
    )


def test_overlay_shows_the_plan_only_early_and_while_the_card_is_free(client, tmp_path):
    _synced(client, tmp_path)

    # Before -0:20 the card is the first skill point's, not the plan's.
    client.post("/gsi", json=_gsi_at(-40, game_state="DOTA_GAMERULES_STATE_PRE_GAME"))
    assert "game_plan" not in client.get("/overlay/recommendation?lang=uk").json()

    client.post("/gsi", json=_gsi_at(-20, game_state="DOTA_GAMERULES_STATE_PRE_GAME"))
    early = client.get("/overlay/recommendation?lang=uk").json()
    assert early["recommendation"] is None
    assert early["game_plan"]["title"] == "План на гру"
    # Read in English on a Windows without a Ukrainian voice.
    english = client.get("/overlay/recommendation?lang=en").json()["game_plan"]
    assert early["game_plan"]["lines_en"] == english["lines"] and "lines_en" not in english

    client.post("/gsi", json=_gsi_at(80))
    assert "game_plan" in client.get("/overlay/recommendation").json()

    client.post("/gsi", json=_gsi_at(95))
    assert "game_plan" not in client.get("/overlay/recommendation").json()


def test_overlay_has_no_plan_without_a_linked_account(client, tmp_path):
    PLAYER_SERVICE.configure(tmp_path / "svc", client=None, auto_start=False)
    payload = _gsi_at(-30)
    payload.pop("player")
    client.post("/gsi", json=payload)
    assert "game_plan" not in client.get("/overlay/recommendation").json()


def test_recurring_problems_keep_one_order_across_processes():
    """Ties used to follow a set's order, which changes with the hash seed."""
    script = (
        "from app.career_analysis import analyze_career\n"
        "ids = ['lh10_low', 'lane_eff_low', 'lane_deaths', 'gpm_low', 'deaths_high']\n"
        "match = {'analysis': {'score': 50, 'improvements': "
        "[{'id': i, 'kind': 'improve', 'params': {}} for i in ids], 'strengths': []}}\n"
        "print([r['id'] for r in analyze_career([dict(match), dict(match)], 'en')['recurring']])\n"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
        ).stdout
        for seed in range(4)
    }
    assert len(outputs) == 1
    assert outputs.pop().startswith("['lh10_low', 'lane_eff_low', 'lane_deaths'")


def _vs(win: bool, enemies: list[int]) -> dict:
    return {"win": win, "analysis": {"role": "core", "enemy_heroes": enemies, "improvements": []}}


def test_the_plan_names_the_enemy_heroes_the_player_loses_to():
    # Lina (25) 0–3, Axe (2) 1–3, Pudge (14) 2–3: the two worst are shown.
    on_hero = (
        [_vs(False, [2, 25, 14])] * 3 + [_vs(True, [2, 14])] + [_vs(True, [14]), _vs(True, [8])]
    )
    plan = build_game_plan(hero="Juggernaut", history=on_hero, all_recent=[], meta=None, lang="uk")
    assert "Важко проти: Lina 0–3, Axe 1–3" in plan["lines"]
    # Too few meetings on this hero: the record over every hero is used.
    everywhere = [_vs(False, [2])] * 3
    plan = build_game_plan(hero="Lina", history=[], all_recent=everywhere, meta=None, lang="en")
    assert "Hard matchups: Axe 0–3" in plan["lines"]
    # No lineups at all (GSI-only matches): no line.
    plan = build_game_plan(
        hero="Juggernaut", history=[_vs(False, [])] * 4, all_recent=[], meta=None, lang="en"
    )
    assert not any(line.startswith("Hard matchups") for line in plan["lines"])


def test_the_record_skips_matches_without_a_result():
    rows = [{"win": None}] * 5 + [{"win": True}] * 15 + [{"win": False}] * 10
    plan = build_game_plan(
        hero="Juggernaut",
        history=rows[:20],
        record_history=rows,
        all_recent=[],
        meta=None,
        lang="en",
    )
    assert plan["record"] == "15–5"  # the last 20 finished games, not 15 of 20 rows


def test_the_key_item_for_the_live_timing_tip(client, tmp_path):
    service = _synced(client, tmp_path)
    item = service.key_item("Juggernaut")
    assert item is not None and item["key"] and item["name"] and item["typical_t"] > 0
    assert service.key_item("Juggernaut") is item  # cached
    assert service.key_item("not a hero") is None


def test_the_focus_comes_before_the_matchups():
    """The overlay clamps the lines under the first one: the matchups go last."""
    history = [_vs(False, [2, 25])] * 3
    plan = build_game_plan(
        hero="Juggernaut", history=history, all_recent=[], meta=None, lang="en", focus="Die less"
    )
    focus_line, matchups = plan["lines"][-2:]
    assert focus_line == "Your focus: die less"
    assert (
        matchups.startswith("Hard matchups: ") and "Axe 0–3" in matchups and "Lina 0–3" in matchups
    )


def test_the_high_rank_icons_replace_the_build_line():
    """Drawn as icons with their minutes, the build needs no text line: the two
    lines the card shows under the first keep the skills and the focus."""
    meta = {
        "popularity": {"mid_game_items": {"145": 40}},
        "constants": {
            "by_id": {"145": "bfury"},
            "items": {"bfury": {"name": "Battle Fury", "assembled": True, "cost": 4100}},
        },
        "timings": None,
    }
    high = [{"key": "bfury", "name": "Battle Fury", "minute": 14, "share": 80, "win": 55}]
    with_icons = build_game_plan(
        hero="Juggernaut",
        history=[],
        all_recent=[],
        meta=meta,
        lang="en",
        focus="Die less",
        high_build=high,
    )
    assert with_icons["items"] == [{"key": "bfury", "name": "Battle Fury", "minute": 14}]
    assert not any("Battle Fury" in line for line in with_icons["lines"])
    # Without the high-rank build the popular item keeps its line (no minutes on the icons).
    plain = build_game_plan(
        hero="Juggernaut", history=[], all_recent=[], meta=meta, lang="en", focus="Die less"
    )
    assert any("Battle Fury" in line for line in plain["lines"])
