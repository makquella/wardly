"""The public lane data used live when the player has no record of their own."""

from __future__ import annotations

import pytest

from app import lane_matchup, main
from app.live_hints import lane_pressure
from app.map_hints import TIPS, RoleTips

PUBLIC = {
    "Axe": {"won": 2, "even": 3, "lost": 20},
    "Lina": {"won": 20, "even": 3, "lost": 2},
}
BASE = {"alive": True, "has_ward": None}


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
            "lane_role": "safe",
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
    record = main._lane_record(["Axe"], "Juggernaut", "carry")
    assert record["source"] == "public" and record["kind"] == "hard"
    assert (record["lost"], record["games"], record["my_hero"]) == (20, 25, "Juggernaut")
    assert main._lane_record(["Lina"], "Juggernaut", "carry")["kind"] == "easy"


def test_own_record_wins(public, monkeypatch):
    _own(monkeypatch, {"Axe": {"won": 3, "even": 0, "lost": 0, "games": 3}})
    record = main._lane_record(["Axe"], "Juggernaut", "carry")
    assert record["kind"] == "easy" and "source" not in record


def test_no_public_for_support_or_other_position(public, monkeypatch):
    _own(monkeypatch, {})
    assert main._lane_record(["Axe"], "Juggernaut", "support") is None
    assert main._lane_record(["Axe"], "Juggernaut", None) is None
    assert main._lane_record(["Axe"], "Juggernaut", "mid") is None
    assert main._lane_record(["Axe"], "Lina", "carry") is None
    assert main._lane_record([], "Juggernaut", "carry") is None


def test_own_pace_kept_with_public_kind(public, monkeypatch):
    pace = {"hero": "Axe", "games": 3, "lh": {5: 20}}
    monkeypatch.setattr(
        main,
        "lane_record_for",
        lambda opponents, records: {"hero": "Axe", "kind": None, "pace": pace},
    )
    record = main._lane_record(["Axe"], "Juggernaut", "carry")
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
    assert "Juggernaut loses this lane to Axe 20 times of 25" in en["hint"]
    tips = RoleTips()
    uk = tips.tip(100, "carry", lang="uk", lane_record=record, **BASE)
    assert uk["title"] == "Важка лінія: Axe" and "20 з 25" in uk["hint"]
    assert uk["id"] == "lane_record@100"
    assert tips.tip(300, "carry", lang="uk", lane_record=record, **BASE) is None
    easy = {**record, "kind": "easy", "hero": "Lina"}
    tip = RoleTips().tip(100, "mid", lang="en", lane_record=easy, **BASE)
    assert (
        tip["title"] == "Your lane: Lina" and "wins this lane against Lina 2 times" in tip["hint"]
    )
    assert RoleTips().tip(100, "support", lang="en", lane_record=record, **BASE) is None


def test_public_hard_is_lane_pressure():
    hard = {"hero": "Axe", "kind": "hard", "source": "public"}
    state, extra = {"hp_percent": 100}, {"clock_time": 120, "deaths": 0}
    assert lane_pressure(state, extra, hard)
    assert not lane_pressure(state, extra, {**hard, "kind": "easy"})
