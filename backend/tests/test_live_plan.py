"""The short-term plan (live_plan.py): when one starts, what it rests on, and
when it ends. Synthetic snapshots in the shape of the normalized live state;
where a case copies a moment of the Phantom Lancer recording (9054793282) the
comment names it. The tests check decisions (which plan, its basis, how it
ended), not wording."""

from __future__ import annotations

from typing import Any

from app.live_plan import LivePlan
from app.map_hints import plan_params


def snap(clock: int, **kw: Any) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "clock_time": clock,
        "alive": True,
        "health": 700,
        "max_health": 800,
        "last_hits": 20,
        "xpos": 10000.0,
        "ypos": 15000.0,
        "team_name": "radiant",
        "radiant_score": 5,
        "dire_score": 5,
        "kills": 2,
        "assists": 3,
        "deaths": 1,
        "ally_units": [],
        "enemy_units": [],
        "towers": [],
        "stash_items": [],
        "active_items": ["item_power_treads"],
        "backpack_items": [],
        "has_aegis": False,
    }
    extra.update(kw)
    return extra


def run(plan: LivePlan, snaps: list[dict[str, Any]], role: str | None = "offlane") -> Any:
    result = None
    for extra in snaps:
        result = plan.observe(extra, role)
    return result


ENEMY = {"hero": "Phantom Assassin", "x": 10300.0, "y": 15100.0}
ALLY = {"hero": "Axe", "x": 10200.0, "y": 15000.0}


def _lane(start: int, seconds: int, lh: int, **kw: Any) -> list[dict[str, Any]]:
    return [snap(start + i, last_hits=lh, **kw) for i in range(seconds)]


# Lane: PL 05:14-07:00, +1 last hit in 106 s, HP down to 21-37 %, 3-5 enemies.


def test_a_stalled_lane_under_pressure_starts_the_lane_plan():
    plan = LivePlan()
    snaps = _lane(300, 60, 22, health=300) + _lane(360, 40, 23, health=300)
    current = run(plan, snaps)
    assert current is not None and current["goal"] == "lane_recover"
    assert current["basis"]["last_hits"] <= 1
    assert current["basis"]["hp_min"] <= 50
    # It names what it cannot see instead of sending a weak hero to the jungle.
    assert current["next"] == "tower_last_hits_and_support"
    assert "camp_clear_speed" in current["basis"]["unknown"]
    # Last hits come back: the plan is done, not shown again.
    back = [snap(400 + i, last_hits=23 + i // 10) for i in range(61)]
    assert run(plan, back) is None
    assert plan.history[-1]["ended"] == "done:last_hits_back"


def test_a_quiet_stretch_without_pressure_is_no_stalled_lane():
    # Counterexample: few last hits but full HP and nobody around (a rune
    # trip, a pushed-out wave): nothing to fix.
    plan = LivePlan()
    assert run(plan, _lane(300, 100, 22, health=800)) is None


def test_a_support_or_a_death_in_the_window_starts_no_lane_plan():
    plan = LivePlan()
    assert run(plan, _lane(300, 100, 22, health=300), role="support") is None
    plan = LivePlan()
    snaps = _lane(300, 50, 22, health=300)
    snaps += [snap(350 + i, alive=False, last_hits=22) for i in range(10)]
    snaps += _lane(360, 40, 22, health=300)
    assert run(plan, snaps) is None


def test_after_the_laning_phase_there_is_no_lane_plan():
    plan = LivePlan()
    assert run(plan, _lane(620, 100, 40, health=300)) is None


# Items: purchase vs stash vs delivery. PL 31:48: the Orchid recipe waited in
# the stash, assembled in the inventory 30 s later.


def test_an_active_item_waiting_in_the_stash_starts_a_delivery_plan():
    plan = LivePlan()
    waiting = [snap(1900 + i, stash_items=["item_recipe_manta"]) for i in range(31)]
    current = run(plan, waiting)
    assert current is not None and current["goal"] == "deliver_item"
    assert current["basis"]["item"] == "item_manta"
    run(plan, [snap(1931, stash_items=[])])
    assert plan.history[-1]["ended"] == "done:delivered"


def test_a_passive_item_waiting_in_the_stash_is_not_excluded():
    # Skadi gives nothing from the stash: being passive is no reason to skip
    # it. The card says so without naming a press.
    plan = LivePlan()
    waiting = [snap(1900 + i, stash_items=["item_skadi"]) for i in range(31)]
    current = run(plan, waiting)
    assert current is not None and current["goal"] == "deliver_item"
    assert current["basis"]["save"] is False
    assert plan_params(current, "en")[0] == "plan_delivery_item"


def test_an_item_delivered_in_time_needs_no_card():
    plan = LivePlan()
    snaps = [snap(1900 + i, stash_items=["item_black_king_bar"]) for i in range(20)]
    snaps += [snap(1920 + i, stash_items=[]) for i in range(20)]
    assert run(plan, snaps) is None


# Item received: the plan is reassessed. PL: Manta 16:14 (recipe in the stash
# 29 s, assembled in slot0), Aghanim's 23:08, Skadi 29:04 inside the Aegis
# window that started at 28:51.

FULL = ["item_power_treads", "item_magic_wand", "item_diffusal_blade", "item_ring_of_health"]
FULL += ["item_quelling_blade", "item_wraith_band"]


def _manta_waits(plan: LivePlan) -> None:
    waiting = [
        snap(1900 + i, stash_items=["item_recipe_manta"], active_items=FULL) for i in range(31)
    ]
    assert run(plan, waiting)["next"] == "courier"


def test_an_item_delivered_into_the_backpack_changes_the_next_step():
    plan = LivePlan()
    _manta_waits(plan)
    # The courier came, the inventory is full: Manta lands in the backpack.
    backpack = [snap(1931 + i, active_items=FULL, backpack_items=["item_manta"]) for i in range(11)]
    current = run(plan, backpack)
    assert plan.reassessments[-2]["result"] == "kept:backpack_wait"
    assert current is not None and current["next"] == "to_main_slots" and current["new"]
    assert plan.history[-1]["ended"] == "changed:in_backpack"
    assert plan_params(current, "en")[0] == "plan_backpack"
    # Swapped in: done, no further card.
    run(plan, [snap(1942, active_items=FULL[1:] + ["item_manta"], backpack_items=FULL[:1])])
    assert plan.plan is None and plan.history[-1]["ended"] == "done:carried"


def test_an_item_assembled_in_the_main_slots_ends_the_plan_with_no_new_card():
    # Counterexample: received where it presses: the delivery plan is done;
    # no new plan, no «go fight».
    plan = LivePlan()
    _manta_waits(plan)
    after = run(plan, [snap(1931 + i, active_items=FULL[:5] + ["item_manta"]) for i in range(5)])
    assert after is None and plan.history[-1]["ended"] == "done:carried"
    entry = plan.reassessments[-1]
    assert entry["item"] == "item_manta" and entry["to"] == "carried"
    assert entry["result"] == "ended" and entry["effect"] == "save_tool"


def test_a_recipe_delivered_but_not_assembled_ends_as_such():
    plan = LivePlan()
    _manta_waits(plan)
    run(plan, [snap(1931, active_items=FULL[:5] + ["item_recipe_manta"])])
    assert plan.history[-1]["ended"] == "done:delivered_not_assembled"


def test_a_quick_swap_out_of_the_backpack_needs_no_card():
    plan = LivePlan()
    snaps = [snap(1900, active_items=FULL)]
    snaps += [snap(1901 + i, active_items=FULL, backpack_items=["item_skadi"]) for i in range(5)]
    snaps += [snap(1906 + i, active_items=FULL[1:] + ["item_skadi"]) for i in range(20)]
    assert run(plan, snaps) is None


def test_skadi_received_in_the_aegis_window_keeps_the_plan_without_a_card():
    # Counterexample: a big item in the middle of the Aegis window changes no
    # step any rule knows; the plan stays as it was, its effect is unknown.
    plan = LivePlan()
    support = {"steady": ["Axe", "Lion"], "known": True, "enemies_near": 0}
    picked = run(
        plan,
        [
            snap(1730, active_items=FULL),
            snap(1731, has_aegis=True, own_aegis_left=300, team_support=support, active_items=FULL),
        ],
    )
    assert picked["goal"] == "aegis_window" and picked["new"]
    skadi = FULL[:5] + ["item_skadi"]
    current = run(plan, [snap(1744, has_aegis=True, team_support=support, active_items=skadi)])
    assert current["goal"] == "aegis_window" and current["since"] == 1731 and not current["new"]
    entry = plan.reassessments[-1]
    assert entry["item"] == "item_skadi" and entry["plan"] == "aegis_window"
    assert entry["result"] == "kept" and entry["effect"] == "unknown"


def test_an_item_received_with_no_plan_starts_none():
    # Manta at 16:14 and Aghanim's at 23:08 with no plan running: recorded,
    # no card. Manta's readiness is its cooldown, not its purchase.
    plan = LivePlan()
    snaps = [snap(974, active_items=FULL)]
    snaps.append(
        snap(975, active_items=FULL[:5] + ["item_manta"], item_cooldowns={"item_manta": 0})
    )
    snaps.append(snap(1388, active_items=FULL[:4] + ["item_manta", "item_ultimate_scepter"]))
    assert run(plan, snaps) is None
    manta, scepter = list(plan.reassessments)
    assert manta["result"] == "no_plan" and manta["ready"] is True
    assert scepter["item"] == "item_ultimate_scepter" and scepter["effect"] == "unknown"
    assert scepter["ready"] is None


def test_items_seen_at_the_first_snapshot_after_a_gap_or_a_move_are_no_receipt():
    plan = LivePlan()
    run(plan, [snap(900, active_items=FULL[:5] + ["item_manta"])])
    run(plan, [snap(901, active_items=None, stash_items=None)])
    run(plan, [snap(902, active_items=FULL[:5] + ["item_manta"])])
    # PL 24:09: slot0 empty for one snapshot while Aghanim's is moved.
    scepter = FULL[:4] + ["item_manta", "item_ultimate_scepter"]
    run(plan, [snap(903, active_items=scepter), snap(904, active_items=FULL[:4])])
    run(plan, [snap(905, active_items=scepter)])
    assert [entry["item"] for entry in plan.reassessments] == ["item_ultimate_scepter"]


# Fight result: from the player's own counters (kills + assists, deaths), never
# from the map-wide team score or from enemies off the minimap.


def _fight(
    score_after: tuple[int, int],
    *,
    allies: list[dict[str, Any]],
    took_part: int = 0,
    **end: Any,
):
    during = [snap(2000 + i, enemy_units=[ENEMY], ally_units=allies) for i in range(8)]
    radiant, dire = score_after
    quiet = [
        snap(
            2008 + i,
            ally_units=allies,
            radiant_score=radiant,
            dire_score=dire,
            kills=2 + took_part,
            **end,
        )
        for i in range(8)
    ]
    return during + quiet


TOWER = {"team": "dire", "tier": 2, "lane": "mid", "x": 11500.0, "y": 15500.0}
SUPPORT = {"steady": ["Axe"], "known": True, "allies": ["Axe"], "enemies_near": 0}


def test_a_won_fight_with_the_team_next_to_a_tower_plans_the_tower():
    plan = LivePlan()
    fight = _fight((8, 5), allies=[ALLY], took_part=3, towers=[TOWER], team_support=SUPPORT)
    current = run(plan, fight)
    assert current is not None and current["goal"] == "after_fight"
    assert current["next"] == "tower" and current["basis"]["took_part"] == 3
    # The team score over the interval is kept, labelled, not as the result.
    assert current["basis"]["team_interval"]["kills"] == 3
    # The tower falls: done.
    run(plan, [snap(2020, kills=5, towers=[], team_support=SUPPORT)])
    assert plan.history[-1]["ended"] == "done:tower_down"


def test_the_team_score_rising_from_fights_elsewhere_is_not_this_fights_result():
    # Counterexample: two fights elsewhere put the team 4 kills up while the
    # player, next to a tower with an ally, took part in none and lost HP.
    # The team score is map-wide: no «won, hit the tower».
    plan = LivePlan()
    fight = _fight((9, 5), allies=[ALLY], towers=[TOWER], team_support=SUPPORT, health=500)
    assert run(plan, fight) is None
    # Worse: at low HP the plan is to recover, not to push.
    plan = LivePlan()
    fight = _fight((9, 5), allies=[ALLY], towers=[TOWER], team_support=SUPPORT, health=300)
    current = run(plan, fight)
    assert current is not None and current["next"] == "recover"
    assert current["basis"]["took_part"] == 0


def test_enemies_off_the_minimap_with_no_score_change_are_no_result():
    # Counterexample: the enemies vanished from sight but no kill happened:
    # they may be alive behind the trees. No plan.
    plan = LivePlan()
    assert run(plan, _fight((5, 5), allies=[ALLY], towers=[TOWER], team_support=SUPPORT)) is None


def test_a_fight_with_unknown_own_counters_has_no_result():
    plan = LivePlan()
    fight = _fight((8, 5), allies=[ALLY], took_part=3, towers=[TOWER], team_support=SUPPORT)
    for extra in fight:
        extra["kills"] = None
    assert run(plan, fight) is None


def test_a_gap_in_the_data_during_the_fight_drops_it():
    plan = LivePlan()
    fight = _fight((8, 5), allies=[ALLY], took_part=3, towers=[TOWER], team_support=SUPPORT)
    for extra in fight[8:]:
        extra["clock_time"] += 30  # 30 s unseen between the fight and the quiet
    assert run(plan, fight) is None


def test_a_won_fight_alone_at_low_hp_plans_recovery_not_the_tower():
    plan = LivePlan()
    current = run(plan, _fight((7, 5), allies=[], took_part=2, towers=[TOWER], health=300))
    assert current is not None and current["next"] == "recover"


# Aegis: PL 28:51, picked with 3 allies next to him, timer known.


def test_the_aegis_window_plan_starts_at_the_pickup_and_ends_with_it():
    plan = LivePlan()
    support = {"steady": ["Axe", "Lion", "Zeus"], "known": True, "enemies_near": 0}
    current = run(
        plan,
        [
            snap(1730),
            snap(1731, has_aegis=True, own_aegis_left=300, team_support=support),
        ],
    )
    assert current is not None and current["goal"] == "aegis_window"
    assert current["next"] == "push_with_team" and current["basis"]["until"] == "33:51"
    run(plan, [snap(1990, has_aegis=False)])
    assert plan.history[-1]["ended"] == "done:aegis_gone"


def test_an_aegis_of_unknown_age_starts_no_window_plan():
    # The recording started with the Aegis already held: no timer, no plan.
    plan = LivePlan()
    assert run(plan, [snap(1731, has_aegis=True, own_aegis_left=None)] * 3) is None


def test_a_stronger_plan_replaces_a_weaker_one_not_the_other_way():
    plan = LivePlan()
    waiting = [snap(1900 + i, stash_items=["item_recipe_manta"]) for i in range(31)]
    assert run(plan, waiting)["goal"] == "deliver_item"
    support = {"steady": ["Axe"], "known": True, "enemies_near": 0}
    picked = snap(
        1931,
        stash_items=["item_recipe_manta"],
        has_aegis=True,
        own_aegis_left=300,
        team_support=support,
    )
    assert run(plan, [picked])["goal"] == "aegis_window"
    assert plan.history[-1]["ended"] == "replaced"


def test_every_plan_card_has_both_languages():
    plans = [
        {
            "goal": "lane_recover",
            "since": 400,
            "basis": {"last_hits": 1, "from": "5:05", "to": "6:35", "hp_min": 12, "enemies": 2},
        },
        {
            "goal": "deliver_item",
            "since": 1900,
            "basis": {"item": "item_manta", "label": "Manta Style", "label_uk": "Manta Style"},
        },
        {
            "goal": "deliver_item",
            "since": 1900,
            "basis": {"item": "item_skadi", "label": "Eye of Skadi", "save": False},
        },
        {
            "goal": "deliver_item",
            "since": 1900,
            "next": "to_main_slots",
            "basis": {"item": "item_manta", "label": "Manta Style", "save": True},
        },
        {
            "goal": "after_fight",
            "since": 2016,
            "basis": {"next": "tower", "took_part": 3, "allies": 1, "tower": TOWER},
        },
        {
            "goal": "after_fight",
            "since": 2016,
            "basis": {"next": "recover", "took_part": 1, "hp": 30},
        },
        {
            "goal": "after_fight",
            "since": 2016,
            "basis": {"next": "recover", "took_part": 0, "hp": 30},
        },
        {"goal": "aegis_window", "since": 1731, "basis": {"until": "33:51", "allies": 3}},
        {"goal": "aegis_window", "since": 1731, "basis": {"until": "33:51", "allies": 0}},
    ]
    for item in plans:
        en, uk = plan_params(item, "en"), plan_params(item, "uk")
        assert en is not None and uk is not None and en[0] == uk[0], item
