"""scripts/lane_matchups.py: Explorer rows → a lane_matchup file (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from lane_matchups import build_file, summarize  # noqa: E402

from app.lane_duel import GOLD_MARGIN  # noqa: E402
from app.lane_matchup import MIN_LANES, classify, validate  # noqa: E402

JUGG = 8


def mine(match_id, gold, slot=0, lane=1, roaming=False):
    return {
        "match_id": match_id,
        "player_slot": slot,
        "lane": lane,
        "is_roaming": roaming,
        "gold": gold,
    }


def other(match_id, hero_id, slot, gold, lh, lane=1, roaming=False):
    return {
        "match_id": match_id,
        "player_slot": slot,
        "hero_id": hero_id,
        "lane": lane,
        "is_roaming": roaming,
        "gold": gold,
        "lh": lh,
    }


def test_core_is_most_last_hits_and_support_counted():
    heroes = [mine(1, 4000)]
    others = [
        other(1, 11, 128, 3000, 60),  # enemy core, diff +1000 -> won
        other(1, 5, 129, 1500, 10),  # enemy support in the lane
        other(1, 14, 130, 2000, 30, lane=2),  # other lane
        other(1, 20, 1, 9999, 90),  # ally
    ]
    baseline, table = summarize(heroes, others)
    assert baseline == {"won": 1, "even": 0, "lost": 0}
    assert set(table) == {11, 5}
    assert table[11]["diff"] == table[5]["diff"] == 1000
    assert table[5]["won"] == 1


def test_dire_hero_and_margins():
    heroes = [
        mine(1, 3000, slot=128),
        mine(2, 3000 - GOLD_MARGIN, slot=130),
        mine(3, 3000 - GOLD_MARGIN + 1, slot=130),
    ]
    # exactly -margin is lost, one gold less behind is even
    others = [
        other(1, 11, 0, 3000 + GOLD_MARGIN, 50),  # hero -margin: lost
        other(2, 11, 0, 3000, 50),  # hero -margin: lost
        other(3, 11, 0, 3000, 50),  # hero -margin+1: even
    ]
    baseline, _ = summarize(heroes, others)
    assert baseline == {"won": 0, "even": 1, "lost": 2}


def test_roaming_and_bad_lanes_skipped():
    heroes = [mine(1, 4000, roaming=True), mine(2, 4000, lane=0), mine(3, 4000), mine(4, 4000)]
    others = [
        other(2, 11, 128, 3000, 50, lane=0),
        other(3, 11, 128, 3000, 50, roaming=True),  # roaming enemy: no laner
        other(4, 11, 128, None, 50),  # no gold
        other(1, 11, 128, 3000, 50),
    ]
    baseline, table = summarize(heroes, others)
    assert sum(baseline.values()) == 0 and table == {}


def test_build_file_cuts_min_lanes_and_validates():
    heroes, others = [], []
    for i in range(MIN_LANES):
        heroes.append(mine(i, 2000))
        others.append(other(i, 11, 128, 3500, 60))  # always lost
    heroes.append(mine(1000, 3000))
    others.append(other(1000, 5, 128, 3000, 60))  # one lane only
    data = build_file("Juggernaut", JUGG, "carry", heroes, others, generated="2026-11-08")
    validate(data)
    assert data["lanes"] == MIN_LANES + 1
    assert data["baseline"] == {"won": 0, "even": 1, "lost": MIN_LANES}
    assert [o["hero_id"] for o in data["opponents"]] == [11]
    row = data["opponents"][0]
    assert row["lost"] == MIN_LANES and row["gold_diff"] == -1500
    assert data["lane_role"] == 1 and data["window_days"] == 365
    assert classify(row, data["baseline"]) is None  # same as the baseline: no call
