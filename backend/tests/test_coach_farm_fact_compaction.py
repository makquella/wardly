"""Malformed sample counters must stay unknown before prompt JSON compaction."""

from __future__ import annotations

import json

import pytest

from app.coach_evidence import farm_slice_evidence
from app.coach_review import FactChecker, match_facts


@pytest.mark.parametrize("source", ["lane", "peers"])
@pytest.mark.parametrize("value", [None, True, "36", -1, 36.5, float("nan"), float("inf"), 2**53])
def test_invalid_samples_cannot_crash_compaction_or_return_through_legacy_fields(
    source: str, value: object
) -> None:
    block = (
        {
            "hero": "Juggernaut",
            "enemy": "Anti-Mage",
            "points": [{"minute": 10, "lh": value, "dn": None, "enemy_lh": 65}],
        }
        if source == "lane"
        else {
            "me": {"lh_10": value},
            "peers": [{"hero": "Anti-Mage", "enemy": True, "metrics": {"lh_10": 65}}],
        }
    )
    facts = match_facts(
        {"analysis": {"headline": {"hero": "Juggernaut", "last_hits": 160}, source: block}}
    )
    assert facts is not None
    serialized = json.dumps(facts, allow_nan=False)
    refs = facts["match_farm_at_10_evidence"]
    assert all(row["subject"] != "player" for row in refs)
    assert refs == farm_slice_evidence(facts["match_farm_at_10"])
    assert FactChecker(serialized, []).problems("36 last hits at 10:00.")
    assert FactChecker(serialized, []).problems("0 last hits at 10:00.")
    if source == "lane":
        assert "last_hits_at_10" not in facts["lane"]
    else:
        assert not any(
            row["metric"] == "last_hits_at_10:00"
            for row in facts["same_role_opponent"].get("metrics", [])
        )


@pytest.mark.parametrize("source", ["lane", "peers"])
def test_zero_samples_keep_exact_source_subject_and_time_after_compaction(source: str) -> None:
    block = (
        {
            "hero": "Juggernaut",
            "enemy": "Anti-Mage",
            "points": [{"minute": 10, "lh": 0, "dn": 0, "enemy_lh": 65, "enemy_dn": 3}],
        }
        if source == "lane"
        else {
            "me": {"lh_10": 0.0},
            "peers": [{"hero": "Anti-Mage", "enemy": True, "metrics": {"lh_10": 65.0}}],
        }
    )
    facts = match_facts({"analysis": {"headline": {"hero": "Juggernaut"}, source: block}})
    assert facts is not None
    refs = facts["match_farm_at_10_evidence"]
    assert refs == farm_slice_evidence(facts["match_farm_at_10"])
    mine = next(row for row in refs if row["subject"] == "player" and row["field"] == "last_hits")
    assert mine["value"] == 0 and mine["observed_at"] == 600
    assert mine["source"] == ("analysis.lane.points" if source == "lane" else "analysis.peers.me")
    assert (
        FactChecker(json.dumps(facts, allow_nan=False), []).problems(
            "0 last hits versus 65 for Anti-Mage at 10:00."
        )
        == []
    )


def test_the_public_lane_matchup_is_told_as_public_games() -> None:
    lane = {
        "hero": "Juggernaut",
        "enemy": "Axe",
        "points": [{"minute": 10, "lh": 50, "dn": 2, "enemy_lh": 30, "enemy_dn": 1}],
        "matchup": {"enemy": "Axe", "lanes": 20, "won": 4, "even": 4, "lost": 12, "kind": "hard"},
    }
    facts = match_facts({"analysis": {"headline": {"hero": "Juggernaut"}, "lane": lane}})
    assert facts is not None
    public = facts["lane"]["public_matchup"]
    assert "public" in public["source"] and "not the player's" in public["source"]
    assert (public["enemy"], public["lanes"], public["lost"], public["kind"]) == (
        "Axe",
        20,
        12,
        "hard",
    )
    del lane["matchup"]
    facts = match_facts({"analysis": {"headline": {"hero": "Juggernaut"}, "lane": lane}})
    assert "public_matchup" not in facts["lane"]
