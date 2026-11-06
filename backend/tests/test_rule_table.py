"""scripts/rule_table.py: counting per rule, the compare/gate and input discovery.

The rows are hand-made audit rows (replay_recording.py --audit), cards-file rows
and a few seconds of a synthetic recording; no network."""

from __future__ import annotations

import copy
import gzip
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import rule_table as rt  # noqa: E402


def advice(point: str, w: float, outcome: str | None = None, delay: float = 3.0) -> dict[str, Any]:
    row: dict[str, Any] = {"kind": "advice", "decision_point": point, "w": w, "clock": int(w)}
    if outcome:
        historical: dict[str, Any] = {"outcome": outcome}
        if outcome in {"after_show", "around_show", "already_done"}:
            historical["delay_from_shown"] = [delay - 0.5, delay]
        row["historical"] = historical
    return row


def test_repeats_are_cards_within_the_window_of_the_previous_card():
    assert rt.count_repeats([0, 30, 90, 200]) == 2  # 30 after 0; 90 is 60 after 30
    assert rt.count_repeats([0, 61]) == 0
    assert rt.count_repeats([150, 0, 40]) == 1  # unsorted input
    assert rt.count_repeats([]) == 0


def test_advice_counts_outcomes_per_decision_point():
    audit = [
        advice("DISABLED_STATUS", 10, "after_show", 2.0),
        advice("DISABLED_STATUS", 40, "around_show", 4.0),
        advice("DISABLED_STATUS", 400, "already_done"),
        advice("DISABLED_STATUS", 500, "not_used_in_episode"),
        advice("DISABLED_STATUS", 900, "died_before_use"),
        advice("DISABLED_STATUS", 1100, "no_tool"),
        advice("LOW_HP", 20),  # no historical block at all
        {"kind": "plan", "decision_point": "LOW_HP", "w": 1},  # not a card
    ]
    rules = rt.advice_counts(audit)
    status = rules["DISABLED_STATUS"]
    assert (status["cards"], status["repeats"]) == (6, 1)
    assert status["checkable"] == 5  # no_tool is not checkable
    assert (status["used_after"], status["already_done"]) == (2, 1)
    assert (status["not_used"], status["died"]) == (1, 1)
    assert rt.finalize(rules)["DISABLED_STATUS"]["median_delay_s"] == 3.0
    assert rules["LOW_HP"]["cards"] == 1 and rules["LOW_HP"]["checkable"] == 0
    assert "delays" not in rt.finalize(rules)["LOW_HP"]


def test_withdrawn_rows_are_matched_by_their_decision_point():
    audit = [
        advice("LOW_HP", 5),
        {"kind": "withdrawn", "decision_point": "LOW_HP", "action": "Heal", "reason": "healed"},
        {"kind": "withdrawn", "decision_point": None, "action": "?", "reason": "gone"},
    ]
    rules = rt.advice_counts(audit)
    assert rules["LOW_HP"]["withdrawn"] == 1 and rules["LOW_HP"]["cards"] == 1
    assert rules[rt.UNMATCHED]["withdrawn"] == 1 and rules[rt.UNMATCHED]["cards"] == 0


def recording_rows(*, arrive_at: int | None) -> list[dict[str, Any]]:
    """One row per game second; the hero is at the target from `arrive_at`."""
    rows = []
    for clock in range(0, 200):
        far = arrive_at is None or clock < arrive_at
        rows.append(
            {
                "clock": clock,
                "x": 0 if far else 5000,
                "y": 0 if far else 5000,
                "enemy": [],
                "neutral": [],
                "gold": 0,
                "src": dict.fromkeys(
                    ("creep_kills", "hero_kills", "income", "shared", "summon_kills"), 0
                ),
                "items": [],
            }
        )
    return rows


def farm(since: int, target: str = "wave") -> dict[str, Any]:
    return {"kind": "farm", "since": since, "x": 5000, "y": 5000, "target": target, "travel_s": 20}


def test_farm_counts_use_farm_outcomes_went():
    audit = [farm(10), farm(50), farm(120, "camp"), {"kind": "farm", "since": 1}]
    went = rt.farm_counts(audit, recording_rows(arrive_at=30))
    # the hero arrives at 30: the cards at 10 and 50... 10 looks ahead 60 s -> went
    assert went["FARM:wave"]["cards"] == 2 and went["FARM:wave"]["used_after"] == 2
    assert went["FARM:wave"]["repeats"] == 1  # 50 is 40 s after 10
    assert went["FARM:camp"]["cards"] == 1 and went["FARM:camp"]["used_after"] == 1
    stayed = rt.farm_counts(audit, recording_rows(arrive_at=None))
    assert stayed["FARM:wave"]["used_after"] == 0 and stayed["FARM:wave"]["not_used"] == 2
    assert stayed["FARM:wave"]["checkable"] == 2


@pytest.mark.parametrize(
    ("kind", "card_id", "expected"),
    [
        ("hint", "fight@1234", "HINT:fight"),
        ("hint", "missing:Axe@600", "HINT:missing"),
        ("hint", "power_rune@720", "HINT:power_rune"),
        ("hint", "note_carry_plan", "HINT:note_carry_plan"),
        ("strip", "aegis@900", "STRIP:aegis"),
        ("hint", None, "HINT:unknown"),
        ("death", None, "DEATH"),
    ],
)
def test_hint_family_drops_the_instance_part(kind, card_id, expected):
    assert rt.hint_family(kind, card_id) == expected


def test_hint_counts_count_cards_and_repeats_in_game_seconds():
    cards = [
        {"kind": "hint", "id": "fight@100", "clock": 100},
        {"kind": "hint", "id": "fight@130", "clock": 130},
        {"kind": "hint", "id": "fight@400", "clock": 400},
        {"kind": "advice", "id": "x", "clock": 1},
        {"kind": "death", "id": None, "clock": 500},
    ]
    rules = rt.hint_counts(cards)
    assert (rules["HINT:fight"]["cards"], rules["HINT:fight"]["repeats"]) == (3, 1)
    assert rules["DEATH"]["cards"] == 1 and "advice" not in rules


def test_game_minutes_and_rate():
    assert rt.game_minutes([]) == 0.0
    assert rt.game_minutes([{"clock": -90}, {"clock": 600}]) == 10.0
    counts = rt.new_counts() | {"cards": 5}
    assert rt.per_10(counts, 20.0) == 2.5
    assert rt.per_10(counts, 0.0) is None


def document(
    rule: str,
    *,
    cards: int,
    repeats: int = 0,
    checkable: int = 0,
    used: int = 0,
    minutes: float = 100.0,
    shas: tuple[str, ...] = ("aaa",),
    tune: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = {k: v for k, v in rt.new_counts().items() if k != "delays"}
    counts.update(cards=cards, repeats=repeats, checkable=checkable, used_after=used)
    side = {
        "recordings": [{"name": s, "sha256_12": s, "minutes": minutes} for s in shas],
        "count": len(shas),
        "minutes": minutes,
        "rules": {rule: counts},
    }
    return {
        "version": rt.JSON_VERSION,
        "splits": {"tune": tune or copy.deepcopy(side), "holdout": side},
    }


def verdict(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return rt.compare_runs(base, new)


def test_gate_flags_a_fall_in_the_used_after_share():
    base = document("R", cards=20, checkable=20, used=10)
    worse = document("R", cards=20, checkable=20, used=8)  # 50% -> 40%
    result = verdict(base, worse)
    assert [w["rule"] for w in result["worse"]] == ["ALL", "R"]
    assert "used after" in result["worse"][1]["reasons"][0]
    assert "WORSE" in rt.render_compare(result)


def test_gate_does_not_flag_small_changes_or_improvements():
    base = document("R", cards=20, repeats=2, checkable=20, used=10)
    assert not verdict(base, document("R", cards=20, repeats=3, checkable=20, used=9))["worse"]
    assert not verdict(base, document("R", cards=20, repeats=0, checkable=20, used=15))["worse"]
    assert "did not get worse" in rt.render_compare(verdict(base, base))


def test_gate_flags_more_repeats_and_more_noise():
    base = document("R", cards=20, repeats=2, checkable=20, used=10)
    repeats = verdict(base, document("R", cards=20, repeats=4, checkable=20, used=10))
    assert "repeats" in repeats["worse"][0]["reasons"][0]  # 10% -> 20%
    noisy = verdict(base, document("R", cards=30, repeats=3, checkable=30, used=15))
    assert "cards per 10 min" in noisy["worse"][0]["reasons"][0]  # +50 %
    assert not verdict(base, document("R", cards=29, repeats=2, checkable=29, used=14))["worse"]


def test_gate_ignores_rules_with_too_few_cards():
    base = document("R", cards=4, checkable=4, used=4)
    assert not verdict(base, document("R", cards=4, checkable=4, used=0))["worse"]
    # a used-after drop needs checkable cards, noise needs cards, in BOTH runs
    big = document("R", cards=20, checkable=20, used=20)
    assert not verdict(big, document("R", cards=20, checkable=4, used=0))["worse"]
    assert not verdict(document("H", cards=0), document("H", cards=40, repeats=40))["worse"]


def test_tune_never_gates_and_different_recordings_warn():
    base = document("R", cards=20, checkable=20, used=20)
    tune = document("R", cards=20, checkable=20, used=0)["splits"]["tune"]
    new = document("R", cards=20, checkable=20, used=20, tune=tune)
    result = verdict(base, new)
    assert result["worse"] == [] and result["warnings"] == []
    other = document("R", cards=20, checkable=20, used=20, shas=("aaa", "bbb"))
    warnings = verdict(base, other)["warnings"]
    assert any(w.startswith("holdout:") for w in warnings)


def test_load_base_rejects_other_files(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(rt.InputError):
        rt.load_base(path)
    path.write_text(json.dumps(document("R", cards=1)), encoding="utf-8")
    assert rt.load_base(path)["version"] == rt.JSON_VERSION


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_discover_reads_the_cloud_folders_and_extra_paths(tmp_path):
    cloud = tmp_path / "cloud"
    tune = touch(cloud / "tune" / "S-AAAAAA.jsonl.gz")
    touch(cloud / "tune" / "notes.txt")
    hold = touch(cloud / "holdout" / "S-BBBBBB.jsonl.gz")
    local = touch(tmp_path / "mine" / "night.jsonl")
    found = rt.discover(cloud, tune=[tmp_path / "mine"], holdout=[])
    assert found["tune"] == [tune.resolve(), local.resolve()]
    assert found["holdout"] == [hold.resolve()]
    assert rt.discover(cloud, tune=[tune]) == rt.discover(cloud)  # no duplicates


def test_discover_without_a_cloud_folder_is_empty(tmp_path):
    assert rt.discover(tmp_path / "none") == {"tune": [], "holdout": []}


def test_discover_rejects_a_file_on_both_sides_and_missing_paths(tmp_path):
    shared = touch(tmp_path / "a.jsonl.gz")
    with pytest.raises(rt.InputError, match="both tune and holdout"):
        rt.discover(None, tune=[shared], holdout=[shared])
    with pytest.raises(rt.InputError, match="not found"):
        rt.discover(None, tune=[tmp_path / "missing.jsonl.gz"])


def test_work_names_are_unique():
    names = rt.work_names([Path("/a/x.jsonl.gz"), Path("/b/x.jsonl.gz"), Path("/c/y.jsonl")])
    assert names == ["x", "x-2", "y"]


def test_empty_cloud_folder_exits_with_a_message(tmp_path, capsys):
    assert rt.main(["--cloud", str(tmp_path / "empty")]) == 2
    assert "no recordings" in capsys.readouterr().err


def test_gate_needs_a_base(tmp_path, capsys):
    assert rt.main(["--cloud", str(tmp_path), "--gate"]) == 2
    assert "--compare" in capsys.readouterr().err


def synthetic_recording(path: Path) -> None:
    """A few seconds of a sample snapshot, written like match_records does."""
    sample = json.loads((ROOT / "data" / "gsi_samples" / "disabled_status.json").read_text("utf-8"))
    with gzip.open(path, "wt", encoding="utf-8") as out:
        out.write(json.dumps({"k": "meta", "anonymized": True}) + "\n")
        for i in range(120):
            payload = copy.deepcopy(sample)
            payload["map"]["clock_time"] = payload["map"]["game_time"] = 600 + i // 2
            out.write(json.dumps({"k": "gsi", "w": 1000 + i * 0.5, "p": payload}) + "\n")


def test_a_synthetic_recording_goes_through_the_subprocess_replay(tmp_path, capsys):
    """Takes a few seconds: it starts the real replay in its own process."""
    (tmp_path / "tune").mkdir()
    synthetic_recording(tmp_path / "tune" / "t.jsonl.gz")
    synthetic_recording(tmp_path / "holdout.jsonl.gz")
    bad = tmp_path / "tune" / "bad.jsonl.gz"
    bad.write_bytes(b"not gzip")
    out = tmp_path / "out.json"
    nothing = str(tmp_path / "none")
    holdout = str(tmp_path / "holdout.jsonl.gz")
    code = rt.main(
        ["--cloud", nothing, "--tune", str(tmp_path / "tune"), "--holdout", holdout]
        + ["--jobs", "2", "--json", str(out)]
    )
    captured = capsys.readouterr()
    assert code == 1  # the broken file failed, the rest is printed
    assert "FAILED tune bad" in captured.err
    assert "| rule |" in captured.out
    saved = json.loads(out.read_text("utf-8"))
    assert saved["splits"]["holdout"]["count"] == 1
    assert saved["splits"]["holdout"]["minutes"] == 10.98
    assert [r["name"] for r in saved["splits"]["tune"]["recordings"]] == ["bad", "t"]
    assert saved["splits"]["tune"]["count"] == 1
    # the same code on the same recordings is never worse than itself
    again = ["--cloud", nothing, "--tune", str(tmp_path / "tune" / "t.jsonl.gz")]
    again += ["--holdout", holdout, "--compare", str(out), "--gate"]
    assert rt.main(again) == 0


def test_each_death_screen_gets_its_own_id_from_the_death_counter():
    import replay_recording

    assert replay_recording._death_id({"player": {"deaths": 3}}) == "death@3"
    assert replay_recording._death_id({"player": {"deaths": 0}}) == "death@0"
    assert replay_recording._death_id({"player": {}}) is None
    assert replay_recording._death_id(None) is None
    cards = [
        {"kind": "death", "id": replay_recording._death_id({"player": {"deaths": n}}), "clock": c}
        for n, c in ((3, 100), (3, 110), (4, 400))
    ]
    assert rt.hint_counts(cards)["DEATH"]["cards"] == 3  # the same id is dropped by the replay


def test_gate_row_all_catches_noise_from_a_new_rule():
    base = document("R", cards=20, checkable=20, used=10)
    new = document("R", cards=20, checkable=20, used=10)
    for side in rt.SPLITS:
        new["splits"][side]["rules"]["NEW"] = {**new["splits"][side]["rules"]["R"], "cards": 30}
    result = verdict(base, new)
    by_rule = {r["rule"]: r for r in result["rows"]}
    assert by_rule["ALL"]["worse"] and "cards per 10 min" in by_rule["ALL"]["worse"][0]
    assert by_rule["NEW"]["note"] == "new" and by_rule["NEW"]["worse"] == []
    assert [w["rule"] for w in result["worse"]] == ["ALL"]
    assert "| NEW |" in rt.render_compare(result) and "new" in rt.render_compare(result)


def test_all_row_covers_used_after_and_gone_is_information():
    base = document("R", cards=20, repeats=2, checkable=20, used=10)
    base["splits"]["holdout"]["rules"]["OLD"] = {**base["splits"]["holdout"]["rules"]["R"]}
    new = document("R", cards=20, repeats=2, checkable=20, used=10)
    by_rule = {r["rule"]: r for r in verdict(base, new)["rows"]}
    assert by_rule["OLD"]["note"] == "gone" and by_rule["OLD"]["worse"] == []
    assert by_rule["ALL"]["worse"] == []  # fewer cards is not noise
    # used-after over all checkable cards: 10/20 -> 10/40
    more = document("R", cards=20, repeats=2, checkable=20, used=10)
    more["splits"]["holdout"]["rules"]["X"] = {
        **more["splits"]["holdout"]["rules"]["R"],
        "used_after": 0,
    }
    row = verdict(document("R", cards=20, repeats=2, checkable=20, used=10), more)["rows"][0]
    assert row["rule"] == "ALL" and any("used after" in r for r in row["worse"])


def test_gate_refuses_different_holdout_recordings(tmp_path, monkeypatch, capsys):
    base = document("R", cards=20, checkable=20, used=10, shas=("aaa",))
    new = document("R", cards=20, checkable=20, used=10, shas=("bbb",))
    assert verdict(base, new)["same_holdout"] is False
    # tune differences only warn
    tune = document("R", cards=20, checkable=20, used=10, shas=("zzz",))["splits"]["tune"]
    same = document("R", cards=20, checkable=20, used=10, tune=tune)
    result = verdict(base, same)
    assert result["same_holdout"] is True and result["warnings"]

    path = tmp_path / "base.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    holdout = tmp_path / "h.jsonl.gz"
    synthetic_recording(holdout)
    args = ["--cloud", str(tmp_path / "none"), "--holdout", str(holdout), "--compare", str(path)]
    assert rt.main(args) == 0  # a warning only
    capsys.readouterr()
    assert rt.main([*args, "--gate"]) == 2
    assert "same recordings" in capsys.readouterr().err
