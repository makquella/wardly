"""The farm tip (farm_map.py): which wave or camp it names, from what the
minimap shows and what the player did this match, and when it names nothing.
Synthetic snapshots in the shape of the normalized live state (absolute
coordinates); the camp data is a test fixture, not data/live/farm_map.json.
The tests check decisions (target, state, why none), not wording."""

from __future__ import annotations

from typing import Any

import pytest

from app import farm_map
from app.farm_map import FarmMap
from app.map_hints import TIPS, RoleTips, farm_params
from app.minimap_units import lane_creeps, neutral_units, vision_sources

C = 16384.0
# Radiant: its half is x + y < 2 * C.
OWN_CAMP = {"id": "c01", "x": C - 3000, "y": C - 1500, "side": "radiant", "ancient": False}
NEAR_CAMP = {"id": "c02", "x": C - 4500, "y": C - 3500, "side": "radiant", "ancient": False}
ENEMY_CAMP = {"id": "c03", "x": C + 3000, "y": C + 1500, "side": "dire", "ancient": False}
UNITS = {
    "npc_dota_neutral_kobold": {"bounty": [20, 24], "hp": 400, "ancient": False},
    "npc_dota_neutral_centaur_khan": {"bounty": [54, 60], "hp": 1100, "ancient": False},
    "npc_dota_creep_goodguys_melee": {"bounty": [34, 39], "hp": 550, "ancient": False},
    "npc_dota_creep_goodguys_ranged": {"bounty": [43, 52], "hp": 300, "ancient": False},
}
DATA = {
    "camps": [
        {**OWN_CAMP, "gold": 70, "hp": 1600},
        {**NEAR_CAMP, "gold": 160, "hp": 2200},
        {**ENEMY_CAMP, "gold": 160, "hp": 2200},
    ],
    "units": UNITS,
}
# The bottom lane on Radiant's side (map_analysis.zone: v < -5000).
WAVE_AT = (C + 1000, C - 6200)
HERO_AT = (C - 2000, C - 6200)


@pytest.fixture(autouse=True)
def camps(monkeypatch):
    monkeypatch.setattr(farm_map, "farm_data", lambda: DATA)


def snap(clock: int, **kw: Any) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "clock_time": clock,
        "alive": True,
        "health": 900,
        "max_health": 1000,
        "xpos": HERO_AT[0],
        "ypos": HERO_AT[1],
        "team_name": "radiant",
        "lane_creeps": [],
        "neutral_units": [],
        "vision_sources": [],
        "enemy_units": [],
        "towers": [],
        "last_hits": 100,
        "gold_reliable": 500,
        "gold_unreliable": 500,
        "gold_sources": {"creep_kills": 4000, "income": 2000, "hero_kills": 0, "shared": 0},
        "item_names": ["item_power_treads"],
    }
    extra.update(kw)
    return extra


def wave(at: tuple[float, float] = WAVE_AT, n: int = 4) -> list[dict[str, Any]]:
    kinds = ["melee"] * (n - 1) + ["ranged"]
    return [
        {"team": "enemy", "kind": kind, "x": at[0] + 40 * i, "y": at[1]}
        for i, kind in enumerate(kinds)
    ] + [{"team": "own", "kind": "melee", "x": at[0] - 300, "y": at[1]}]


def neutrals(camp: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    return [{"unit": name, "x": camp["x"] + 50 * i, "y": camp["y"]} for i, name in enumerate(names)]


def run(fm: FarmMap, snaps: list[dict[str, Any]], role: str | None = "carry") -> Any:
    out = None
    for extra in snaps:
        out = fm.observe(extra, role)
    return out


def test_a_visible_wave_within_reach_is_named_with_its_creeps():
    fm = FarmMap()
    out = run(fm, [snap(900 + i, lane_creeps=wave()) for i in range(3)])
    assert out is not None and out["kind"] == "wave" and out["creeps"] == 4
    assert out["lane"] == "bot" and 0 < out["travel_s"] <= farm_map.WAVE_TRAVEL_MAX
    # No lane gold measured yet: Valve's bounty, and it says so.
    assert "wave_gold" in out["unknown"] and "creeps_in_fog" in out["unknown"]


@pytest.mark.parametrize(
    ("role", "clock", "extra", "why"),
    [
        ("support", 900, {}, "role"),
        ("carry", 540, {}, "laning"),
        ("carry", 900, {"health": 400}, "hp"),
        ("carry", 900, {"teleporting": True}, "busy"),
        ("carry", 900, {"alive": False}, "dead"),
        ("carry", 900, {"live_plan": {"goal": "after_fight"}}, "plan"),
    ],
)
def test_no_card_when_a_gate_fails(role, clock, extra, why):
    fm = FarmMap()
    assert run(fm, [snap(clock + i, lane_creeps=wave(), **extra) for i in range(3)], role) is None
    assert fm._gate(snap(clock, **extra), role, clock, extra.get("alive", True)) == why


def test_an_enemy_hero_in_sight_near_the_wave_removes_it():
    fm = FarmMap()
    enemy = [{"hero": "Lion", "x": WAVE_AT[0] + 600, "y": WAVE_AT[1]}]
    assert run(fm, [snap(900 + i, lane_creeps=wave(), enemy_units=enemy) for i in range(3)]) is None


def test_a_wave_too_far_to_reach_before_it_moves_is_no_target():
    fm = FarmMap()
    far = (C + 6000, C - 6200)
    assert run(fm, [snap(900 + i, lane_creeps=wave(far)) for i in range(3)]) is None


def test_no_minimap_creeps_turns_the_tip_off():
    fm = FarmMap()
    assert run(fm, [snap(900 + i, lane_creeps=None) for i in range(3)]) is None


def test_a_camp_seen_full_is_no_target_before_the_player_cleared_one():
    # Whether this hero clears a camp is unknown until it does.
    fm = FarmMap()
    seen = neutrals(NEAR_CAMP, ["npc_dota_neutral_centaur_khan"] * 2)
    assert run(fm, [snap(900 + i, neutral_units=seen) for i in range(3)]) is None
    assert fm.camp_state("c02", 902) == "seen_full"


def _clear_own_camp(fm: FarmMap, start: int) -> int:
    """The hero stands at c01 with two kobolds and a khan and kills them."""
    at = {"xpos": OWN_CAMP["x"], "ypos": OWN_CAMP["y"]}
    units = ["npc_dota_neutral_kobold", "npc_dota_neutral_kobold", "npc_dota_neutral_centaur_khan"]
    clock, lh, gold = start, 100, 1000
    run(fm, [snap(clock, neutral_units=neutrals(OWN_CAMP, units), **at)])
    for left in (2, 1, 0):
        clock += 3
        lh += 1
        gold += 30
        run(
            fm,
            [
                snap(
                    clock,
                    neutral_units=neutrals(OWN_CAMP, units[:left]),
                    last_hits=lh,
                    gold_reliable=500,
                    gold_unreliable=gold - 500,
                    **at,
                )
            ],
        )
    return clock


def test_a_clear_by_the_player_teaches_the_capability_and_starts_the_respawn_clock():
    fm = FarmMap()
    end = _clear_own_camp(fm, 900)
    able = fm.capability()
    assert able["cleared"] and able["max_hp"] == 2 * 400 + 1100 and not able["ancient"]
    assert fm.camp_state("c01", end) == "cleared"
    # Valve: an empty camp respawns on the minute; not seen since: expected.
    assert fm.camp_state("c01", 960) == "expected"


def test_a_cleared_capability_lets_a_camp_seen_full_be_named():
    fm = FarmMap()
    end = _clear_own_camp(fm, 900)
    seen = neutrals(NEAR_CAMP, ["npc_dota_neutral_centaur_khan"] * 2)
    hero = {"xpos": OWN_CAMP["x"] + 200, "ypos": OWN_CAMP["y"]}
    out = run(fm, [snap(end + 1 + i, neutral_units=seen, **hero) for i in range(3)])
    assert out is not None and out["kind"] == "camp" and out["id"] == "c02"
    assert out["state"] == "seen_full"


def test_a_camp_bigger_than_any_cleared_or_on_the_enemy_half_or_never_seen_is_no_target():
    fm = FarmMap()
    end = _clear_own_camp(fm, 900)
    hero = {"xpos": OWN_CAMP["x"] + 200, "ypos": OWN_CAMP["y"]}
    # The enemy-half camp, seen full: excluded in v1.
    enemy_side = neutrals(ENEMY_CAMP, ["npc_dota_neutral_centaur_khan"] * 2)
    assert run(fm, [snap(end + 1 + i, neutral_units=enemy_side, **hero) for i in range(3)]) is None
    # c02 never seen: unknown, not a candidate.
    assert fm.camp_state("c02", end + 3) == "unknown"
    # A camp of 5 khans (5500 HP) is more than 1.2x the 1900 HP cleared.
    big = neutrals(NEAR_CAMP, ["npc_dota_neutral_centaur_khan"] * 5)
    monkey = {**DATA, "camps": [{**NEAR_CAMP, "gold": 300, "hp": 5500}]}
    farm_map.farm_data = lambda: monkey  # restored by the autouse fixture
    assert run(fm, [snap(end + 10 + i, neutral_units=big, **hero) for i in range(3)]) is None


def test_a_slightly_better_option_does_not_replace_the_target():
    fm = FarmMap()
    first = run(fm, [snap(900 + i, lane_creeps=wave()) for i in range(3)])
    assert first is not None
    other = (C + 1200, C - 6000)
    both = wave() + wave(other, n=5)
    later = run(fm, [snap(903 + i, lane_creeps=both) for i in range(3)])
    assert later is not None and later["since"] == first["since"]


def test_an_enemy_hero_showing_up_ends_the_target_and_records_why():
    fm = FarmMap()
    assert run(fm, [snap(900 + i, lane_creeps=wave()) for i in range(3)]) is not None
    enemy = [{"hero": "Lion", "x": HERO_AT[0] + 2200, "y": HERO_AT[1]}]
    assert run(fm, [snap(903, lane_creeps=wave(), enemy_units=enemy)]) is None
    assert fm.history[-1]["ended"] == "enemy_near"


def test_the_same_game_second_rechecks_only_the_gates():
    fm = FarmMap()
    out = run(fm, [snap(900 + i, lane_creeps=wave()) for i in range(3)])
    assert out is not None
    # A second payload of game second 902 with the hero stunned ends it.
    assert fm.observe(snap(902, lane_creeps=wave(), stunned=True), "carry") is None
    assert fm.history[-1]["ended"] == "busy"


def test_neutral_gold_is_counted_only_on_neutral_kill_seconds_without_lane_creeps():
    fm = FarmMap()
    _clear_own_camp(fm, 900)
    # 3 kills, +30 gold each, no income change: 90 neutral gold.
    assert fm._sums[1] == 3 and fm._sums[3] == 90
    # A purchase second (items change, gold drops) adds nothing.
    before = list(fm._sums)
    run(fm, [snap(950, gold_unreliable=100, item_names=["item_power_treads", "item_bfury"])])
    assert fm._sums[3] == before[3]


def test_every_farm_card_has_both_languages():
    targets = [
        {
            "kind": "wave",
            "creeps": 4,
            "gold": 180,
            "travel_s": 9,
            "since": 900,
            "where": {"tower": {"team": "radiant", "tier": 1, "lane": "bot"}, "team": "radiant"},
            "then": {"kind": "camp", "ancient": False},
        },
        {
            "kind": "camp",
            "state": "seen_full",
            "gold": 120,
            "travel_s": 7,
            "since": 900,
            "where": {"zone": "jungle", "side": "own", "team": "radiant"},
            "then": None,
        },
        {
            "kind": "camp",
            "ancient": True,
            "state": "expected",
            "respawn": 900,
            "gold": 200,
            "travel_s": 12,
            "since": 900,
            "where": {"zone": "jungle", "side": "own"},
        },
    ]
    for target in targets:
        en, uk = farm_params(target, "en"), farm_params(target, "uk")
        assert en[0] == uk[0] and en[0] in TIPS
        for lang, (key, params) in (("en", en), ("uk", uk)):
            title, hint = TIPS[key][lang]
            assert "{" not in title.format(**params) + hint.format(**params)


def test_the_farm_card_shows_for_its_window_without_voice():
    tips = RoleTips()
    target = {
        "kind": "wave",
        "creeps": 4,
        "gold": 180,
        "travel_s": 9,
        "since": 900,
        "where": {"zone": "bot", "side": "own", "team": "radiant"},
    }
    card = tips.farm(905, "uk", target)
    assert card is not None and card["id"] == "farm@900" and card["label"] == "Фарм"
    assert card["speak"] is False
    assert tips.farm(900 + 26, "uk", target) is None


MINIMAP = {
    "o1": {
        "image": "minimap_creep",
        "unitname": "npc_dota_creep_badguys_ranged",
        "team": 3,
        "xpos": 100,
        "ypos": -200,
        "visionrange": 750,
    },
    "o2": {
        "image": "minimap_siege",
        "unitname": "npc_dota_goodguys_siege",
        "team": 2,
        "xpos": 50,
        "ypos": 60,
        "visionrange": 800,
    },
    # Not placed on the map yet: says nothing.
    "o3": {
        "image": "minimap_creep",
        "unitname": "npc_dota_creep_goodguys_melee",
        "team": 2,
        "xpos": 0,
        "ypos": 0,
    },
    "o4": {
        "image": "minimap_creep",
        "unitname": "npc_dota_neutral_satyr_hellcaller",
        "team": 4,
        "xpos": -300,
        "ypos": 400,
        "visionrange": 800,
    },
    "o5": {
        "image": "minimap_tower",
        "unitname": "npc_dota_goodguys_tower1_bot",
        "team": 2,
        "xpos": 6000,
        "ypos": -6000,
        "visionrange": 1900,
    },
    "o6": {
        "image": "minimap_tower",
        "unitname": "npc_dota_badguys_tower1_top",
        "team": 3,
        "xpos": -6000,
        "ypos": 6000,
        "visionrange": 1900,
    },
}


def test_minimap_parsers_read_lane_creeps_siege_neutrals_and_own_vision():
    assert lane_creeps(MINIMAP, "radiant") == [
        {"team": "enemy", "kind": "ranged", "x": C + 100, "y": C - 200},
        {"team": "own", "kind": "siege", "x": C + 50, "y": C + 60},
    ]
    assert neutral_units(MINIMAP) == [
        {"unit": "npc_dota_neutral_satyr_hellcaller", "x": C - 300, "y": C + 400}
    ]
    # Vision only from the player's own team: neither the enemy's units nor
    # the neutrals light the map for him.
    assert sorted(vision_sources(MINIMAP, "radiant")) == [
        (C + 50, C + 60, 800.0),
        (C + 6000, C - 6000, 1900.0),
    ]
    assert lane_creeps(None, "radiant") is None and lane_creeps(MINIMAP, None) is None
    assert neutral_units("broken") is None
