"""Public lane matchups (app/lane_matchup.py): the file contract and the call."""

from __future__ import annotations

import json

import pytest

from app import lane_matchup
from app.lane_matchup import MIN_LANES, classify, lane_matchup_for, load_matchups, matchup, validate


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
