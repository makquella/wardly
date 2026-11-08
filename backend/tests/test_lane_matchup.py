"""Public lane matchups (app/lane_matchup.py): the file contract and the call."""

from __future__ import annotations

import json

import pytest

from app import lane_matchup
from app.lane_matchup import (
    MIN_LANES,
    classify,
    lane_matchup_for,
    load_matchups,
    matchup,
    safe_files,
    validate,
    wilson_lower,
)


def _file(**overrides):
    data = {
        "hero": "Juggernaut",
        "hero_id": 8,
        "position": "carry",
        "lane_role": 1,
        "window_days": 365,
        "generated": "2026-11-08",
        "source": "OpenDota Explorer",
        "lanes": 400,
        # 40 % won, 25 % even, 35 % lost
        "baseline": {"won": 160, "even": 100, "lost": 140},
        "opponents": [
            # 60 % lost: hard
            {
                "hero": "Viper",
                "hero_id": 47,
                "lanes": 20,
                "won": 4,
                "even": 4,
                "lost": 12,
                "gold_diff": -620,
            },
            # 65 % won: easy
            {
                "hero": "Lion",
                "hero_id": 26,
                "lanes": 20,
                "won": 13,
                "even": 3,
                "lost": 4,
                "gold_diff": 540,
            },
            # like the baseline: nothing to say
            {
                "hero": "Axe",
                "hero_id": 2,
                "lanes": 40,
                "won": 16,
                "even": 10,
                "lost": 14,
                "gold_diff": 30,
            },
            # hard by share, but too few lanes
            {
                "hero": "Bristleback",
                "hero_id": 99,
                "lanes": MIN_LANES - 1,
                "won": 1,
                "even": 2,
                "lost": 11,
                "gold_diff": -900,
            },
        ],
    }
    data.update(overrides)
    return data


FILES = {8: validate(_file())}


def test_classify_against_the_baseline():
    baseline = FILES[8]["baseline"]
    rows = {row["hero"]: row for row in FILES[8]["opponents"]}
    assert classify(rows["Viper"], baseline) == "hard"
    assert classify(rows["Lion"], baseline) == "easy"
    assert classify(rows["Axe"], baseline) is None
    assert classify(rows["Bristleback"], baseline) is None


def _row(won, even, lost):
    return {"won": won, "even": even, "lost": lost, "lanes": won + even + lost}


def test_classify_wants_significance_not_just_a_gap():
    baseline = {"won": 400, "even": 400, "lost": 200}  # 20 % lost, 40 % won
    # 0 won / 10 even / 5 lost: 33 % lost, a gap, but 5 lanes of noise
    assert classify(_row(0, 10, 5), baseline) is None
    assert classify(_row(5, 10, 0), baseline) is None
    # a clear row: 18 lost of 25 against 35 % lost
    usual = {"won": 400, "even": 250, "lost": 350}
    assert classify(_row(3, 4, 18), usual) == "hard"
    assert classify(_row(18, 4, 3), {"won": 350, "even": 250, "lost": 400}) == "easy"
    # symmetric: the lost side needs more lost than won too
    assert classify(_row(10, 0, 10), usual) is None


def test_wilson_lower_bound():
    assert wilson_lower(0, 0) == 0.0
    assert wilson_lower(18, 25) == pytest.approx(0.55, abs=0.02)
    assert wilson_lower(5, 15) < wilson_lower(50, 150) < 1 / 3


def test_matchup_returns_the_files_date():
    assert matchup("Juggernaut", "carry", "Viper", FILES)["generated"] == "2026-11-08"


def test_matchup_needs_the_files_position():
    assert matchup("Juggernaut", "carry", "Viper", FILES)["kind"] == "hard"
    # A mid Juggernaut: the carry numbers do not apply.
    assert matchup("Juggernaut", "mid", "Viper", FILES) is None
    assert matchup("Juggernaut", None, "Viper", FILES) is None
    # No file for the hero, no row for the enemy.
    assert matchup("Anti-Mage", "carry", "Viper", FILES) is None
    assert matchup("Juggernaut", "carry", "Pudge", FILES) is None


def test_matchup_reads_any_spelling():
    row = matchup("npc_dota_hero_juggernaut", "carry", "viper", FILES)
    assert row["hero"] == "Viper" and row["lanes"] == 20 and row["source"] == "public"
    assert row["baseline_lost"] == 0.35


def test_lane_matchup_for_names_the_hard_one_first():
    record = lane_matchup_for("Juggernaut", "carry", ["Lion", "Viper"], FILES)
    assert record == {
        "hero": "Viper",
        "kind": "hard",
        "won": 4,
        "even": 4,
        "lost": 12,
        "games": 20,
        "gold_diff": -620,
        "source": "public",
    }
    assert lane_matchup_for("Juggernaut", "carry", ["Lion", "Axe"], FILES)["hero"] == "Lion"
    assert lane_matchup_for("Juggernaut", "carry", ["Axe", "Bristleback"], FILES) is None
    assert lane_matchup_for("Juggernaut", "carry", [], FILES) is None


@pytest.mark.parametrize(
    "broken",
    [
        {"position": "support"},
        {"baseline": {"won": 1, "even": 1}},
        {
            "opponents": [
                {"hero": "Viper", "hero_id": 47, "lanes": 5, "won": 1, "even": 1, "lost": 1}
            ]
        },
        {
            "opponents": [
                {"hero": "Viper", "hero_id": 47, "lanes": 1, "won": 1, "even": 0, "lost": 0}
            ]
            * 2
        },
        {"hero_id": True},
        {"lane_role": "safe"},
        {"lane_role": 2},
        {"lanes": 399},
    ],
)
def test_validate_rejects_broken_files(broken):
    with pytest.raises(ValueError):
        validate(_file(**broken))


def test_load_matchups_reads_a_directory(tmp_path):
    (tmp_path / "juggernaut.json").write_text(json.dumps(_file()), encoding="utf-8")
    load_matchups.cache_clear()
    try:
        assert set(load_matchups(tmp_path)) == {8}
        assert load_matchups(tmp_path / "missing") == {}
    finally:
        load_matchups.cache_clear()


def test_shipped_files_are_valid():
    """Every file in data/heroes/lane_matchups loads and is for a core position."""
    load_matchups.cache_clear()
    try:
        files = load_matchups(lane_matchup.LANE_MATCHUPS_DIR)
    finally:
        load_matchups.cache_clear()
    for data in files.values():
        assert data["position"] in ("carry", "mid", "offlane")


@pytest.fixture
def fresh_safe_files():
    lane_matchup.reset_safe_files()
    yield
    lane_matchup.reset_safe_files()


def test_safe_files_survive_a_broken_file_and_report_once(fresh_safe_files, tmp_path, monkeypatch):
    from app import diagnostics

    (tmp_path / "juggernaut.json").write_text("{not json", encoding="utf-8")
    calls = []

    def strict(directory=tmp_path):
        calls.append(1)
        return load_matchups.__wrapped__(directory)

    monkeypatch.setattr(lane_matchup, "load_matchups", strict)
    before = diagnostics.recent_errors()["counts"].get("lane-matchups", 0)
    assert safe_files() == {} and safe_files() == {}
    assert len(calls) == 1
    assert diagnostics.recent_errors()["counts"]["lane-matchups"] == before + 1
    assert matchup("Juggernaut", "carry", "Viper") is None
    with pytest.raises(json.JSONDecodeError):
        load_matchups.__wrapped__(tmp_path)
