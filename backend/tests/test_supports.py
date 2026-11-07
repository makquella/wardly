"""Supports in the advisor: profiles, their saves, what advice they get, their tips."""

from __future__ import annotations

import pytest
from match_fixtures import gsi_match_stream
from test_live_tools import _ability, _extra

from app.gsi_state import _normalize_hero_name
from app.hero_profiles import get_hero_position, get_support_position
from app.live_tools import low_hp_copy
from app.main import SUPPORT_DECISIONS, _covered_decision_point
from app.map_hints import SAVE_ITEMS, RoleTips, has_observer_ward, map_hint, observer_charges
from app.match_memory import MATCH_MEMORY
from app.player_api import PLAYER_SERVICE
from app.schemas import SUPPORTED_HEROES, hero_coverage

SUPPORTS = [hero for hero in SUPPORTED_HEROES if get_hero_position(hero) == "support"]


def test_twenty_five_supports_of_both_positions():
    assert len(SUPPORTS) == 25
    positions = {get_support_position(hero) for hero in SUPPORTS}
    assert positions == {4, 5}
    assert get_support_position("Juggernaut") is None


@pytest.mark.parametrize(
    ("npc", "hero", "support_position"),
    [
        ("npc_dota_hero_crystal_maiden", "Crystal Maiden", 5),
        ("npc_dota_hero_vengefulspirit", "Vengeful Spirit", 5),
        ("npc_dota_hero_treant", "Treant Protector", 5),
        ("npc_dota_hero_rattletrap", "Clockwerk", 4),
        ("npc_dota_hero_spirit_breaker", "Spirit Breaker", 4),
    ],
)
def test_live_names_positions_and_role_prior(npc, hero, support_position):
    assert _normalize_hero_name(npc) == hero
    assert hero_coverage(hero) == "support"
    assert get_support_position(hero) == support_position
    assert PLAYER_SERVICE.role_prior(hero) == {"role": "support", "source": "hero"}


def test_a_support_gets_survival_fights_and_objectives_but_no_farm_or_items():
    for decision in ("LOW_HP", "DEATH_REVIEW", "HERO_SURVIVABILITY_RISK", "OBJECTIVE_FIGHT_CHECK"):
        assert _covered_decision_point(decision, "support") == decision
    for decision in ("LANING_FARM_CHECK", "FARMING_PHASE_PRESSURE", "SAFE_FARMING", "ITEM_TIMING"):
        assert decision not in SUPPORT_DECISIONS
        assert _covered_decision_point(decision, "support") == "NO_ADVICE"
    # The safety-only heroes still get less than a profiled support.
    assert _covered_decision_point("OBJECTIVE_FIGHT_CHECK", "safety") == "NO_ADVICE"


def test_their_own_saves_at_low_hp():
    mirana = _extra(abilities={"ability0": _ability("mirana_leap")}, hero="npc_dota_hero_mirana")
    assert low_hp_copy(mirana, "Mirana")[0] == "Use Leap now to get out, then reset HP."
    dazzle = _extra(
        abilities={"ability0": _ability("dazzle_shallow_grave")}, hero="npc_dota_hero_dazzle"
    )
    assert low_hp_copy(dazzle, "Dazzle")[0] == "Use Shallow Grave now and walk out of the fight."
    # Bounty Hunter's Shadow Walk is "bounty_hunter_wind_walk" in GSI.
    bounty = _extra(
        abilities={"ability0": _ability("bounty_hunter_wind_walk")},
        hero="npc_dota_hero_bounty_hunter",
    )
    assert (
        low_hp_copy(bounty, "Bounty Hunter")[0] == "Use Shadow Walk now to get out, then reset HP."
    )


def test_observer_charges_from_the_raw_items():
    assert observer_charges(None) is None
    assert observer_charges({"slot0": {"name": "item_tango"}}) == 0
    items = {
        "slot0": {"name": "item_ward_observer", "charges": 2},
        "slot1": {"name": "item_ward_dispenser"},
        "stash0": {"name": "item_ward_observer", "charges": 4},
    }
    assert observer_charges(items) == 3  # the stash does not count


def test_a_dispenser_with_only_sentries_carries_no_observer():
    # The combined dispenser reports its observers as `charges` (sentries as
    # `secondary_charges`): zero observers is a real zero, not a missing count.
    only_sentries = {"slot1": {"name": "item_ward_dispenser", "charges": 0, "secondary_charges": 2}}
    assert observer_charges(only_sentries) == 0
    assert has_observer_ward(only_sentries) is False
    one = {"slot1": {"name": "item_ward_dispenser", "charges": 1, "secondary_charges": 1}}
    assert observer_charges(one) == 1
    assert has_observer_ward(one) is True
    # A broken count still means one ward.
    assert observer_charges({"slot0": {"name": "item_ward_observer", "charges": "x"}}) == 1
    assert observer_charges({"slot0": {"name": "item_ward_observer", "charges": -3}}) == 1


def test_a_ward_kept_in_the_bag_for_two_minutes():
    tips = RoleTips()
    assert tips.tip(300, "support", alive=True, has_ward=True, lang="en", ward_charges=2) is None
    # Buying more keeps the time; nothing placed for two minutes → the tip.
    assert tips.tip(380, "support", alive=True, has_ward=True, lang="en", ward_charges=3) is None
    hint = tips.tip(420, "support", alive=True, has_ward=True, lang="uk", ward_charges=3)
    assert hint["title"] == "Поставте вард"
    # Placing one restarts the count.
    fresh = RoleTips()
    fresh.tip(300, "support", alive=True, has_ward=True, lang="en", ward_charges=2)
    fresh.tip(400, "support", alive=True, has_ward=True, lang="en", ward_charges=1)
    assert fresh.tip(430, "support", alive=True, has_ward=True, lang="en", ward_charges=1) is None
    # Not for a core.
    core = RoleTips()
    core.tip(300, "carry", alive=True, has_ward=True, lang="en", ward_charges=1)
    assert core.tip(450, "carry", alive=True, has_ward=True, lang="en", ward_charges=1) is None


def test_no_ward_nag_right_after_placing_the_last_one():
    # Wards placed at 9:00 and 9:30 (the count goes 2 → 1 → none): no "No observer
    # wards" for WARD_EVERY after the last one, then the usual reminder.
    from app.map_hints import WARD_EVERY

    tips = RoleTips()
    tips.tip(500, "support", alive=True, has_ward=True, lang="en", ward_charges=2)
    tips.tip(540, "support", alive=True, has_ward=True, lang="en", ward_charges=1)
    assert tips.tip(570, "support", alive=True, has_ward=False, lang="en", ward_charges=0) is None
    assert tips.tip(600, "support", alive=True, has_ward=False, lang="en") is None
    later = tips.tip(570 + WARD_EVERY, "support", alive=True, has_ward=False, lang="en")
    assert later["title"] == "No observer wards on you"
    # Never warded at all: the reminder comes as before.
    idle = RoleTips().tip(600, "support", alive=True, has_ward=False, lang="en")
    assert idle["title"] == "No observer wards on you"


def test_the_ward_reminder_slows_down_after_three():
    from app.map_hints import WARD_EVERY

    tips = RoleTips()
    shown = []
    for clock in range(150, 40 * 60, 5):
        hint = tips.tip(clock, "support", alive=True, has_ward=False, lang="en")
        if hint and hint["title"] == "No observer wards on you" and hint["id"] not in shown:
            shown.append(hint["id"])
    starts = [int(i.split("@")[1]) for i in shown]
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert gaps[:2] == [WARD_EVERY, WARD_EVERY]
    assert set(gaps[2:]) == {2 * WARD_EVERY}


def test_no_save_item_after_twelve_minutes_with_gold():
    items = ["item_tranquil_boots", "item_magic_wand"]
    hint = RoleTips().tip(
        13 * 60, "support", alive=True, has_ward=True, lang="en", gold=1300, items=items
    )
    assert hint["title"] == "No save item yet"
    # Before 12:00, without the gold, or with a Glimmer Cape: nothing.
    assert (
        RoleTips().tip(
            11 * 60, "support", alive=True, has_ward=True, lang="en", gold=1300, items=items
        )
        is None
    )
    assert (
        RoleTips().tip(
            13 * 60, "support", alive=True, has_ward=True, lang="en", gold=600, items=items
        )
        is None
    )
    glimmer = [*items, "item_glimmer_cape"]
    tip = RoleTips().tip(
        13 * 60, "support", alive=True, has_ward=True, lang="en", gold=1300, items=glimmer
    )
    assert tip is None


def test_map_hint_passes_the_ward_count():
    tips = RoleTips()
    map_hint(3 * 60 + 5, "support", tips, alive=True, has_ward=True, lang="en", ward_charges=1)
    hint = map_hint(
        5 * 60 + 20, "support", tips, alive=True, has_ward=True, lang="en", ward_charges=1
    )
    assert hint is not None and hint["id"].startswith("ward_bag@")


def test_a_live_support_hero_gets_no_farm_advice_through_the_api(client):
    stream = gsi_match_stream(
        match_id=1, minutes=14, lh_per_minute=1.0, death_minutes=(), positions=True
    )
    shown = set()
    for payload in stream:
        payload["hero"]["name"] = "npc_dota_hero_lion"
        client.post("/gsi", json=payload)
        answer = client.get("/overlay/recommendation").json()
        if answer.get("recommendation"):
            shown.add(answer["decision_point"])
    status = client.get("/gsi/status").json()
    assert status["hero_coverage"] == "support"
    assert MATCH_MEMORY.role.role()["role"] == "support"
    assert not shown & {"LANING_FARM_CHECK", "FARMING_PHASE_PRESSURE", "SAFE_FARMING"}


SAVE_CONSTANTS = {
    "by_id": {"1": "glimmer_cape", "2": "force_staff", "3": "tranquil_boots", "4": "ward_observer"},
    "items": {
        "glimmer_cape": {
            "name": "Glimmer Cape",
            "cost": 1950,
            "assembled": True,
            "components": ["shadow_amulet", "cloak"],
        },
        "shadow_amulet": {"name": "Shadow Amulet", "cost": 1000, "components": []},
        "cloak": {"name": "Cloak", "cost": 800, "components": []},
        "force_staff": {
            "name": "Force Staff",
            "cost": 2200,
            "assembled": True,
            "components": ["staff_of_wizardry", "ring_of_regen"],
        },
        "staff_of_wizardry": {"name": "Staff of Wizardry", "cost": 1000, "components": []},
        "ring_of_regen": {"name": "Ring of Regen", "cost": 175, "components": []},
        "hurricane_pike": {
            "name": "Hurricane Pike",
            "cost": 4450,
            "assembled": True,
            "components": ["force_staff", "dragon_lance"],
        },
        "tranquil_boots": {
            "name": "Tranquil Boots",
            "cost": 925,
            "assembled": True,
            "components": ["boots"],
        },
    },
}
SAVE_META = {
    "constants": SAVE_CONSTANTS,
    # Boots are bought more, then Force Staff over Glimmer Cape.
    "popularity": {"mid_game_items": {"3": 90, "2": 60, "1": 40}},
}


def test_the_save_item_is_the_one_bought_on_the_hero():
    """«Glimmer Cape or Force Staff» named neither the hero's usual choice nor its price."""
    from app.next_item import save_build_item

    item = save_build_item(SAVE_META, ["item_tranquil_boots", "item_staff_of_wizardry"], SAVE_ITEMS)
    assert item == {"key": "force_staff", "name": "Force Staff", "cost": 2200, "gold_left": 1200}
    # Owned, or built into a Hurricane Pike: nothing to say.
    assert save_build_item(SAVE_META, ["item_force_staff"], SAVE_ITEMS) is None
    assert save_build_item(SAVE_META, ["item_hurricane_pike"], SAVE_ITEMS) is None
    # No save item in the hero's build, no cached build or no items block.
    boots_only = {**SAVE_META, "popularity": {"mid_game_items": {"3": 90}}}
    assert save_build_item(boots_only, [], SAVE_ITEMS) is None
    assert save_build_item(None, [], SAVE_ITEMS) is None
    assert save_build_item(SAVE_META, None, SAVE_ITEMS) is None

    items = ["item_tranquil_boots"]
    hint = RoleTips().tip(
        13 * 60,
        "support",
        alive=True,
        has_ward=True,
        lang="en",
        gold=1300,
        items=items,
        save_item={**item, "gold_left": 2200},
    )
    assert hint["title"] == "No save item yet: Force Staff"
    # 2200 for the parts, 1300 carried: 900 still to farm.
    assert hint["hint"] == "Force Staff is the save item most bought on this hero: 900 gold to go."
    uk = RoleTips().tip(
        13 * 60,
        "support",
        alive=True,
        has_ward=True,
        lang="uk",
        gold=2500,
        items=items,
        save_item={**item, "gold_left": 2200},
    )
    assert uk["title"] == "Купіть Force Staff зараз"
    # Unknown build: the old tip.
    plain = RoleTips().tip(
        13 * 60, "support", alive=True, has_ward=True, lang="en", gold=1300, items=items
    )
    assert plain["hint"].startswith("Glimmer Cape or Force Staff")


def test_the_service_reads_the_save_item_from_the_heros_build(monkeypatch):
    from app.player_api import PLAYER_SERVICE

    monkeypatch.setattr(PLAYER_SERVICE, "_live_meta", lambda hero_id: SAVE_META)
    # A hero without a support plan (every support has one now): the build's save item.
    item = PLAYER_SERVICE.save_item("Mars", ["item_boots"])
    assert item is not None and item["name"] == "Force Staff"
    assert PLAYER_SERVICE.save_item("Not A Hero", []) is None


def test_the_ward_tip_says_where_to_put_it():
    """«Put it where the next fight will come from» named no place."""
    from app.map_hints import score_gap

    def hint(clock, **kwargs):
        tips = RoleTips()
        tips.tip(clock - 150, "support", alive=True, has_ward=True, lang="en", ward_charges=1)
        return tips.tip(
            clock, "support", alive=True, has_ward=True, lang="en", ward_charges=1, **kwargs
        )["hint"]

    assert hint(7 * 60).startswith("Put it by the river next to your lane")
    assert hint(20 * 60, score_gap=-9).startswith("Your team is 9 kills behind: ward the entrances")
    assert hint(20 * 60, score_gap=10).startswith("Your team is 10 kills ahead: ward the enemy")
    assert hint(20 * 60, score_gap=3).startswith("A ward in the bag shows nothing")
    assert hint(20 * 60, score_gap=-9, roshan_open=True).startswith("Roshan can be up now")
    assert score_gap({"team_name": "dire", "radiant_score": 20, "dire_score": 11}) == -9
    assert score_gap({"team_name": "radiant", "radiant_score": 20, "dire_score": 11}) == 9
    assert score_gap({"radiant_score": 20, "dire_score": 11}) is None
    assert score_gap({"team_name": "dire", "radiant_score": True, "dire_score": 1}) is None


def test_roshan_can_be_up_around_his_window():
    from app.roshan_timer import RoshanTimer

    timer = RoshanTimer()
    assert not timer.maybe_up(1500)
    timer.killed_at = 1200  # respawn window 28:00-31:00
    assert not timer.maybe_up(1200 + 400)
    # Not before the window opens: the tip says «can be up now».
    assert not timer.maybe_up(1200 + 480 - 1)
    assert timer.maybe_up(1200 + 480)
    assert timer.maybe_up(1200 + 660 + 180)
    assert not timer.maybe_up(1200 + 660 + 181)
