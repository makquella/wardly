"""The lane minute by minute against its enemy core (lane_duel.py)."""

from __future__ import annotations

from app.analysis_texts import render_finding
from app.focus_goal import match_result
from app.lane_duel import analyze_lane, lane_series
from app.opendota import trim_match


def _curve(per_minute: int, minutes: int = 12) -> list[int]:
    return [per_minute * m for m in range(minutes + 1)]


HERO_IDS = {
    "Juggernaut": 8,
    "Crystal Maiden": 5,
    "Axe": 2,
    "Rubick": 86,
    "Riki": 32,
    "Lina": 25,
}


def _player(hero, *, radiant, lane, lh, gold, roaming=False, account=None):
    return {
        "account_id": account,
        "hero_id": HERO_IDS[hero],
        "isRadiant": radiant,
        "lane": lane,
        "is_roaming": roaming,
        "lh_t": _curve(lh),
        "dn_t": _curve(1),
        "gold_t": _curve(gold),
        "xp_t": _curve(400),
    }


def _match(my_gold=300, enemy_gold=400):
    raw = {
        "match_id": 1,
        "version": 22,  # parsed
        "duration": 2400,
        "players": [
            _player("Juggernaut", radiant=True, lane=1, lh=5, gold=my_gold, account=11),
            _player("Crystal Maiden", radiant=True, lane=1, lh=1, gold=200, account=12),
            _player("Axe", radiant=False, lane=1, lh=3, gold=enemy_gold, account=13),
            _player("Rubick", radiant=False, lane=1, lh=0, gold=220, account=14),
            _player("Riki", radiant=False, lane=1, lh=4, gold=900, roaming=True, account=15),
            _player("Lina", radiant=False, lane=2, lh=6, gold=500, account=16),
        ],
    }
    return trim_match(raw, 11)


def test_trim_match_keeps_ten_minutes_of_everyone():
    trimmed = _match()
    axe = next(p for p in trimmed["players"] if p["hero"] == "Axe")
    assert len(axe["lane_t"]["gold"]) == 11 and "gold_t" not in axe
    assert lane_series(axe, "lh")[10] == 30
    me = next(p for p in trimmed["players"] if p.get("me"))
    assert lane_series(me, "gold")[10] == 3000


def test_a_lost_lane_names_the_enemy_core_and_when_it_turned():
    block, findings = analyze_lane(_match(), "carry")
    assert block["enemy"] == "Axe"  # the core of the lane, not the roaming Riki
    assert block["enemies"] == ["Axe", "Rubick"]
    assert block["gold_diff"] == -1000 and block["result"] == "lost"
    assert block["turn"] == 3  # 100 gold a minute: 300 behind from minute 3
    assert block["total_diff"] == (3000 + 2000) - (4000 + 2200)
    assert [p["minute"] for p in block["points"]] == [3, 5, 7, 10]
    assert block["points"][-1]["lh"] == 50 and block["points"][-1]["enemy_lh"] == 30
    (finding,) = findings
    assert finding["id"] == "lane_lost" and finding["params"]["gold"] == 1000
    uk = render_finding(finding, "uk")
    assert uk["title"] == "Лінію проти Axe програно"
    assert "50 добивань у вас проти 30 у Axe" in uk["text"]
    assert "розрив з'явився з 3-ї хвилини" in uk["text"]
    en = render_finding(finding, "en")
    assert "1000 gold behind; the gap opened at minute 3" in en["text"]


def test_won_even_and_support_lanes():
    block, findings = analyze_lane(_match(my_gold=500), "offlane")
    assert block["result"] == "won" and findings[0]["id"] == "lane_won"
    assert findings[0]["kind"] == "strength"
    block, findings = analyze_lane(_match(my_gold=380), "carry")
    assert block["result"] == "even" and block["turn"] is None and findings == []
    # A support's lane is shown, never judged.
    block, findings = analyze_lane(_match(), "support")
    assert block["result"] == "lost" and not block["judged"] and findings == []


def test_no_lane_without_a_parsed_replay_or_a_lane():
    trimmed = _match()
    assert analyze_lane({**trimmed, "parsed": False}, "carry") == (None, [])
    me = next(p for p in trimmed["players"] if p.get("me"))
    me["is_roaming"] = True
    assert analyze_lane(trimmed, "carry") == (None, [])
    assert analyze_lane(None, "carry") == (None, [])


def test_the_focus_on_a_lost_lane_needs_a_lane():
    focus = {"id": "lane_lost", "family": "lane_lost", "section": "laning"}
    assert match_result({"problems": [], "sections": {"laning": {}}, "lane": None}, focus) is None
    assert match_result({"problems": [], "sections": {"laning": {}}, "lane": {"x": 1}}, focus)


def test_the_career_counts_the_judged_lanes():
    from app.lane_duel import career_lanes

    def match(mid, result, enemy, diff, judged=True):
        lane = {
            "judged": judged,
            "result": result,
            "enemy": enemy,
            "gold_diff": diff,
            "hero": "Juggernaut",
            "hero_id": 8,
        }
        return {"match_id": mid, "analysis": {"lane": lane}}

    newest_first = [
        match(5, "lost", "Axe", -1200),
        match(4, "won", "Mars", 900),
        match(3, "lost", "Axe", -900),
        match(2, "even", "Lina", 100, judged=False),  # a support's lane: not counted
        match(1, "even", "Lina", 0),
        {"match_id": 0, "analysis": {"lane": None}},
    ]
    lanes = career_lanes(newest_first)
    assert (lanes["games"], lanes["won"], lanes["even"], lanes["lost"]) == (4, 1, 1, 2)
    assert lanes["gold_diff"] == -300
    assert [g["match_id"] for g in lanes["games_list"]] == [1, 3, 4, 5]  # oldest first
    assert lanes["hard"] == [{"hero": "Axe", "lost": 2}]
    assert career_lanes(newest_first[:2]) is None


def test_past_lanes_per_enemy_and_the_live_record():
    from app.lane_duel import lane_record_for, lane_records

    def match(result, enemy, judged=True):
        return {"analysis": {"lane": {"judged": judged, "result": result, "enemy": enemy}}}

    records = lane_records(
        [
            match("lost", "Axe"),
            match("lost", "Axe"),
            match("won", "Axe"),
            match("won", "Mars"),
            match("won", "Mars"),
            match("lost", "Lina", judged=False),  # a support's lane: not counted
            {"analysis": None},
        ]
    )
    assert records["Axe"] == {"won": 1, "even": 0, "lost": 2, "games": 3}
    assert "Lina" not in records
    assert lane_record_for(["Rubick", "Axe"], records) == {
        "hero": "Axe",
        "kind": "hard",
        "won": 1,
        "even": 0,
        "lost": 2,
        "games": 3,
    }
    assert lane_record_for(["Mars"], records)["kind"] == "easy"
    assert lane_record_for(["Rubick"], records) is None
    assert lane_record_for([], records) is None


def test_the_lane_record_tip_shows_once():
    from app.map_hints import LANE_RECORD_SHOW, RoleTips

    record = {"hero": "Axe", "kind": "hard", "won": 1, "even": 0, "lost": 2, "games": 3}
    tips = RoleTips()
    base = {"alive": True, "has_ward": None}
    tip = tips.tip(100, "carry", lang="uk", lane_record=record, **base)
    assert tip["title"] == "Важка лінія: Axe"
    assert "програли лінію 2 з 3 разів" in tip["hint"]
    assert (
        tips.tip(100 + LANE_RECORD_SHOW + 1, "carry", lang="uk", lane_record=record, **base) is None
    )
    # A support's lane is not judged, so no record tip for it.
    assert RoleTips().tip(100, "support", lang="en", lane_record=record, **base) is None
    easy = {**record, "kind": "easy", "won": 3, "lost": 0}
    assert (
        RoleTips().tip(100, "mid", lang="en", lane_record=easy, **base)["title"] == "Your lane: Axe"
    )


def test_the_opponents_usual_last_hits_from_past_lanes():
    from app.lane_duel import lane_pace_for, lane_record_for, lane_records

    def match(result, enemy, at5, at7):
        points = [
            {"minute": 3, "lh": 10, "enemy_lh": 12},
            {"minute": 5, "lh": 18, "enemy_lh": at5},
            {"minute": 7, "lh": 26, "enemy_lh": at7},
        ]
        return {
            "analysis": {
                "lane": {"judged": True, "result": result, "enemy": enemy, "points": points}
            }
        }

    records = lane_records(
        [
            match("won", "Axe", 20, 30),
            match("even", "Axe", 25, 35),
            match("lost", "Lina", 30, 44),
            # A review without the minute points counts for the record, not the pace.
            {"analysis": {"lane": {"judged": True, "result": "won", "enemy": "Lina"}}},
        ]
    )
    assert records["Axe"]["pace_games"] == 2 and records["Axe"]["enemy_lh_5"] == 45
    assert lane_pace_for(["Axe"], records) == {"hero": "Axe", "games": 2, "lh": {5: 22, 7: 32}}
    assert lane_pace_for(["Lina"], records) is None  # one lane with points
    # No clear win/loss record against Axe: the pace still reaches the live tips.
    assert lane_record_for(["Axe"], records) == {
        "hero": "Axe",
        "kind": None,
        "pace": {"hero": "Axe", "games": 2, "lh": {5: 22, 7: 32}},
    }


def test_the_pace_tip_names_how_far_behind_the_opponent_the_player_is():
    from app.map_hints import PACE_SHOW, RoleTips

    record = {
        "hero": "Axe",
        "kind": None,
        "pace": {"hero": "Axe", "games": 3, "lh": {5: 22, 7: 32}},
    }
    base = {"alive": True, "has_ward": None, "lane_record": record}
    tips = RoleTips()
    assert tips.tip(299, "carry", lang="uk", last_hits=10, **base) is None
    tip = tips.tip(300, "carry", lang="uk", last_hits=15, **base)
    assert tip["title"] == "Відстаєте від темпу Axe: 15 добивань"
    assert "близько 22 добивань до 5:00" in tip["hint"]
    # The number stays while the card is up, then the tip is gone.
    assert tips.tip(310, "carry", lang="uk", last_hits=17, **base)["title"].endswith(
        ": 15 добивань"
    )
    assert tips.tip(300 + PACE_SHOW + 1, "carry", lang="uk", last_hits=17, **base) is None
    # On pace at 7:00 (fewer than three behind): nothing.
    assert tips.tip(420, "carry", lang="en", last_hits=30, **base) is None
    # Offlaners and supports are not compared with the enemy carry's last hits.
    assert RoleTips().tip(300, "offlane", lang="en", last_hits=5, **base) is None
    english = RoleTips().tip(420, "mid", lang="en", last_hits=20, **base)
    assert english["title"] == "Behind Axe's pace: 20 last hits"


def _public_files(position="carry", lanes=20, lost=12):
    return {
        8: {
            "hero": "Juggernaut",
            "hero_id": 8,
            "position": position,
            "lane_role": 1,
            "window_days": 365,
            "generated": "2026-11-08",
            "source": "OpenDota Explorer",
            "lanes": 400,
            "baseline": {"won": 160, "even": 100, "lost": 140},
            "opponents": [
                {
                    "hero": "Axe",
                    "hero_id": 2,
                    "lanes": lanes,
                    "won": 4,
                    "even": lanes - 4 - lost,
                    "lost": lost,
                    "gold_diff": -620,
                }
            ],
        }
    }


def test_the_public_matchup_sits_beside_the_lane_and_changes_nothing():
    plain, plain_findings = analyze_lane(_match(), "carry", files={})
    block, findings = analyze_lane(_match(), "carry", files=_public_files())
    assert "matchup" not in plain
    assert block["matchup"] == {
        "enemy": "Axe",
        "lanes": 20,
        "won": 4,
        "even": 4,
        "lost": 12,
        "kind": "hard",
        "baseline_lost": 0.35,
        "baseline_won": 0.4,
        "generated": "2026-11-08",
    }
    assert {k: v for k, v in block.items() if k != "matchup"} == plain
    assert findings == plain_findings


def test_no_public_matchup_for_another_position_a_support_or_a_thin_row():
    files = _public_files()
    assert "matchup" not in analyze_lane(_match(), "mid", files=files)[0]
    assert "matchup" not in analyze_lane(_match(), "support", files=files)[0]
    assert "matchup" not in analyze_lane(_match(), "carry", files=_public_files("mid"))[0]
    assert (
        "matchup" not in analyze_lane(_match(), "carry", files=_public_files(lanes=10, lost=6))[0]
    )


def test_a_row_without_a_clear_call_keeps_kind_none():
    block, _ = analyze_lane(_match(), "carry", files=_public_files(lost=7))
    assert block["matchup"]["kind"] is None and block["matchup"]["lost"] == 7
