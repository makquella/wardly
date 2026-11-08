"""The public lane data used live when the player has no record of their own."""

from __future__ import annotations

import pytest
from test_lane_duel import _match

from app import lane_matchup, main
from app.live_hints import lane_pressure
from app.map_hints import TIPS, RoleTips

PUBLIC = {
    "Axe": {"won": 2, "even": 3, "lost": 20},
    "Lina": {"won": 20, "even": 3, "lost": 2},
}
BASE = {"alive": True, "has_ward": None}
CARRY = {"role": "carry", "source": "lane", "lane": "safe"}


def _files(position="carry"):
    rows = [
        {"hero": name, "hero_id": hid, "lanes": sum(c.values()), "gold_diff": -300, **c}
        for (name, c), hid in zip(PUBLIC.items(), (2, 25), strict=True)
    ]
    return {
        8: {
            "hero": "Juggernaut",
            "hero_id": 8,
            "position": position,
            "lane_role": 1,
            "window_days": 30,
            "generated": "2026-01-01",
            "source": "test",
            "lanes": 200,
            "baseline": {"won": 70, "even": 60, "lost": 70},
            "opponents": rows,
        }
    }


@pytest.fixture
def public(monkeypatch):
    files = _files()
    monkeypatch.setattr(lane_matchup, "load_matchups", lambda *a, **k: files)
    return files


def _own(monkeypatch, records):
    monkeypatch.setattr(main.PLAYER_SERVICE, "lane_records", lambda: records)


def test_public_record_when_no_own(public, monkeypatch):
    _own(monkeypatch, {})
    record = main._lane_record(["Axe"], "Juggernaut", CARRY)
    assert record["source"] == "public" and record["kind"] == "hard"
    assert (record["lost"], record["games"], record["my_hero"]) == (20, 25, "Juggernaut")
    assert main._lane_record(["Lina"], "Juggernaut", CARRY)["kind"] == "easy"


def test_own_record_wins(public, monkeypatch):
    _own(monkeypatch, {"Axe": {"won": 3, "even": 0, "lost": 0, "games": 3}})
    record = main._lane_record(["Axe"], "Juggernaut", CARRY)
    assert record["kind"] == "easy" and "source" not in record


def test_no_public_for_support_or_other_position(public, monkeypatch):
    _own(monkeypatch, {})
    assert (
        main._lane_record(
            ["Axe"], "Juggernaut", {"role": "support", "source": "lane", "lane": "safe"}
        )
        is None
    )
    assert main._lane_record(["Axe"], "Juggernaut", None) is None
    assert (
        main._lane_record(["Axe"], "Juggernaut", {"role": "mid", "source": "lane", "lane": "mid"})
        is None
    )
    assert main._lane_record(["Axe"], "Lina", CARRY) is None
    assert main._lane_record([], "Juggernaut", CARRY) is None


@pytest.mark.parametrize(
    ("role", "card"),
    [
        ({"role": "carry", "source": "history"}, False),
        ({"role": "carry", "source": "hero"}, False),
        ({"role": "carry", "source": "setting"}, False),
        ({"role": "carry", "source": "setting", "lane": "mid"}, False),
        ({"role": "carry", "source": "setting", "lane": "safe"}, True),
        ({"role": "carry", "source": "lane", "lane": "safe"}, True),
        ({"role": "carry", "source": "lane", "lane": "safe", "mismatch": "mid"}, False),
    ],
)
def test_public_card_needs_the_lane_to_confirm_the_position(public, monkeypatch, role, card):
    _own(monkeypatch, {})
    assert (main._lane_record(["Axe"], "Juggernaut", role) is not None) is card


def test_mid_and_offlane_lanes_confirm_their_positions():
    assert main._public_position({"role": "mid", "source": "lane", "lane": "mid"}) == "mid"
    assert (
        main._public_position({"role": "offlane", "source": "setting", "lane": "off"}) == "offlane"
    )
    assert main._public_position({"role": "offlane", "source": "lane", "lane": "safe"}) is None


def test_a_broken_data_dir_leaves_the_live_card_and_review_alone(monkeypatch, tmp_path):
    from app.lane_duel import analyze_lane

    (tmp_path / "juggernaut.json").write_text("{broken", encoding="utf-8")
    lane_matchup.reset_safe_files()
    real = lane_matchup.load_matchups
    monkeypatch.setattr(lane_matchup, "load_matchups", lambda: real.__wrapped__(tmp_path))
    try:
        _own(monkeypatch, {})
        assert main._lane_record(["Axe"], "Juggernaut", CARRY) is None
        own = {"Axe": {"won": 0, "even": 0, "lost": 3, "games": 3}}
        _own(monkeypatch, own)
        assert main._lane_record(["Axe"], "Juggernaut", CARRY)["hero"] == "Axe"
        block, _ = analyze_lane(_match(), "carry")
        assert block is not None and "matchup" not in block
    finally:
        monkeypatch.undo()
        lane_matchup.reset_safe_files()


def test_own_pace_kept_with_public_kind(public, monkeypatch):
    pace = {"hero": "Axe", "games": 3, "lh": {5: 20}}
    monkeypatch.setattr(
        main,
        "lane_record_for",
        lambda opponents, records: {"hero": "Axe", "kind": None, "pace": pace},
    )
    record = main._lane_record(["Axe"], "Juggernaut", CARRY)
    assert record["kind"] == "hard" and record["source"] == "public"
    assert record["pace"] == pace


def test_texts_in_both_languages_and_once():
    for key in ("lane_public_hard", "lane_public_easy"):
        assert set(TIPS[key]) == {"en", "uk"}
    record = {
        "hero": "Axe",
        "kind": "hard",
        "won": 2,
        "even": 3,
        "lost": 20,
        "games": 25,
        "source": "public",
        "my_hero": "Juggernaut",
    }
    en = RoleTips().tip(100, "carry", lang="en", lane_record=record, **BASE)
    assert en["title"] == "Hard lane: Axe"
    assert "Juggernaut loses this lane to Axe in 20 of 25 games" in en["hint"]
    tips = RoleTips()
    uk = tips.tip(100, "carry", lang="uk", lane_record=record, **BASE)
    assert uk["title"] == "Важка лінія: Axe" and "20 з 25" in uk["hint"]
    assert uk["id"] == "lane_record@100"
    assert tips.tip(300, "carry", lang="uk", lane_record=record, **BASE) is None
    easy = {**record, "kind": "easy", "hero": "Lina"}
    tip = RoleTips().tip(100, "mid", lang="en", lane_record=easy, **BASE)
    assert (
        tip["title"] == "Your lane: Lina" and "wins this lane against Lina in 2 of" in tip["hint"]
    )
    assert RoleTips().tip(100, "support", lang="en", lane_record=record, **BASE) is None


def test_public_hard_is_lane_pressure():
    hard = {"hero": "Axe", "kind": "hard", "source": "public"}
    state, extra = {"hp_percent": 100}, {"clock_time": 120, "deaths": 0}
    assert lane_pressure(state, extra, hard)
    assert not lane_pressure(state, extra, {**hard, "kind": "easy"})
