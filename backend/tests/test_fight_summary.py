"""Fight summaries: «Бійка біля вашої T2…: союзників 3, ворогів 2 — ТП — готово»
as facts, the decision left to the player (fight_summary, minimap_units,
map_hints.RoleTips.fight)."""

from __future__ import annotations

import copy
import json

import pytest
from match_fixtures import gsi_match_stream

from app.fight_summary import (
    FIGHT_FROM,
    FightWatch,
    ability_states,
    find_fight,
    nearest_tower,
)
from app.hero_items import ITEM_PLANS_DIR, plan_fight, plan_for, validate
from app.map_hints import FIGHT_EVERY, FIGHT_SHOW, RoleTips, fight_params
from app.minimap_units import towers, visible_ally_units
from app.tp_tracker import teleport_cooldown

CENTER = 16384


def _unit(hero, x, y):
    return {"hero": hero, "x": CENTER + x, "y": CENTER + y}


ALLIES = [_unit("Lich", 6000, 1000), _unit("Ogre Magi", 6200, 900), _unit("Invoker", 5800, 1200)]
ENEMIES = [_unit("Pudge", 6300, 1300), _unit("Tidehunter", 6100, 700)]
FAR = (CENTER - 3000, CENTER + 6000)


def _find(allies=ALLIES, enemies=ENEMIES, at=FAR, clock=20 * 60, kills=0, known=None):
    return find_fight(
        allies, enemies, at[0], at[1], clock=clock, recent_kills=kills, known_enemies=known
    )


def test_a_fight_is_allies_and_visible_enemies_together_far_from_the_player():
    fight = _find()
    assert sorted(fight["allies"]) == ["Invoker", "Lich", "Ogre Magi"]
    assert sorted(fight["enemies"]) == ["Pudge", "Tidehunter"]
    # The player is there already, or the laning stage: nothing.
    assert _find(at=(CENTER + 6000, CENTER + 1000)) is None
    assert _find(clock=FIGHT_FROM - 1) is None
    # One enemy, or one ally: no fight.
    assert _find(enemies=ENEMIES[:1]) is None
    assert _find(allies=ALLIES[:1]) is None


def test_a_quiet_two_on_two_is_a_fight_only_with_a_kill():
    assert _find(allies=ALLIES[:2]) is None
    assert _find(allies=ALLIES[:2], kills=1) is not None


def test_a_hero_seen_as_an_enemy_is_never_counted_as_an_ally():
    allies = [*ALLIES[:2], _unit("Pudge", 6100, 1000)]
    fight = _find(allies=allies, known=["Pudge", "Tidehunter"], kills=1)
    assert "Pudge" not in fight["allies"]


def test_kills_are_read_from_the_score():
    watch = FightWatch()
    watch.observe(600, 3, 4)
    watch.observe(610, 3, 4)
    assert watch.kills_since(610) == 0
    watch.observe(615, 4, 4)
    watch.observe(618, 4, 5)
    assert watch.kills_since(620) == 2
    assert watch.kills_since(640) == 0  # 20 s on
    watch.observe(700, 4, 5)
    assert watch.kills_since(700) == 0
    watch.observe(None, 4, 5)  # unknown values change nothing
    assert watch.kills_since(700) == 0


def test_the_nearest_tower_names_the_place():
    standing = [
        {"team": "dire", "tier": 2, "lane": "bot", "x": CENTER + 6400, "y": CENTER + 384},
        {"team": "radiant", "tier": 1, "lane": "mid", "x": CENTER - 1600, "y": CENTER - 1600},
    ]
    fight = _find()
    assert nearest_tower(fight, standing)["tier"] == 2
    assert nearest_tower(fight, standing[1:]) is None


def test_ability_states():
    abilities = [
        {"raw_name": "terrorblade_metamorphosis", "level": 3, "cooldown": 0, "can_cast": True},
        {"raw_name": "terrorblade_sunder", "level": 1, "cooldown": 49, "can_cast": False},
        {"raw_name": "terrorblade_reflection", "level": 0, "cooldown": 0, "can_cast": False},
    ]
    names = ["terrorblade_metamorphosis", "terrorblade_sunder", "terrorblade_reflection"]
    states = ability_states(abilities, names, {"terrorblade_metamorphosis": "Metamorphosis"})
    assert states == [
        {"name": "Metamorphosis", "ready": True, "cooldown": 0},
        {"name": "terrorblade_sunder", "ready": False, "cooldown": 49},
    ]


def test_the_minimap_gives_allies_and_towers():
    minimap = {
        "o1": {
            "image": "minimap_herocircle",
            "team": 3,
            "unitname": "npc_dota_hero_lich",
            "xpos": 100,
            "ypos": 200,
        },
        "o2": {
            "image": "minimap_herocircle_self",
            "team": 3,
            "unitname": "npc_dota_hero_terrorblade",
            "xpos": 1,
            "ypos": 2,
        },
        "o3": {
            "image": "minimap_plaincircle",
            "team": 3,
            "unitname": "npc_dota_hero_rubick",
            "xpos": 0,
            "ypos": 0,
        },
        "o4": {
            "image": "minimap_herocircle",
            "team": 2,
            "unitname": "npc_dota_hero_pudge",
            "xpos": 5,
            "ypos": 5,
        },
        "o5": {
            "image": "minimap_tower90",
            "team": 3,
            "unitname": "npc_dota_badguys_tower2_bot",
            "xpos": 6400,
            "ypos": 384,
        },
        "o6": {
            "image": "minimap_tower45",
            "team": 2,
            "unitname": "npc_dota_goodguys_tower4",
            "xpos": -5700,
            "ypos": -4800,
        },
        "o7": {
            "image": "minimap_miscbuilding",
            "team": 3,
            "unitname": "npc_dota_watch_tower",
            "xpos": 3392,
            "ypos": -448,
        },
    }
    allies = visible_ally_units(minimap, "dire", lambda raw: raw[14:].title())
    assert allies == [{"hero": "Lich", "x": CENTER + 100, "y": CENTER + 200}]
    assert visible_ally_units(None, "dire", str) is None
    assert towers(minimap) == [
        {"team": "dire", "tier": 2, "lane": "bot", "x": CENTER + 6400, "y": CENTER + 384},
        {"team": "radiant", "tier": 4, "lane": None, "x": CENTER - 5700, "y": CENTER - 4800},
    ]


def test_the_tp_cooldown():
    assert teleport_cooldown({"teleport0": {"name": "item_tpscroll", "cooldown": 0}}) == 0
    assert teleport_cooldown({"teleport0": {"name": "item_tpscroll", "cooldown": 17.4}}) == 17
    assert teleport_cooldown({"slot0": {"name": "item_travel_boots", "cooldown": 3}}) == 3
    assert teleport_cooldown({"teleport0": {"name": "empty"}}) is None
    assert teleport_cooldown({"stash0": {"name": "item_tpscroll", "cooldown": 0}}) is None


# --- the card -----------------------------------------------------------------------------


def _card_fight(**over):
    fight = _find()
    return {
        **fight,
        "team": "dire",
        "tower": {"team": "dire", "tier": 2, "lane": "bot"},
        "has_tp": True,
        "tp_cooldown": 0,
        "abilities": [{"name": "Metamorphosis", "ready": True, "cooldown": 0}],
        **over,
    }


def test_the_card_names_the_place_the_heroes_and_the_players_tp():
    uk = fight_params(_card_fight(), "uk")
    assert uk == {
        "place": "біля вашої T2 на нижній лінії",
        "a": 3,
        "e": 2,
        "status": "ТП — готово, Metamorphosis — готово. ",
    }
    en = fight_params(_card_fight(), "en")
    assert en["place"] == "at your T2 in the bottom lane"
    assert en["status"] == "TP ready, Metamorphosis ready. "
    late = fight_params(
        _card_fight(
            tower={"team": "radiant", "tier": 1, "lane": "top"},
            tp_cooldown=17,
            abilities=[{"name": "Metamorphosis", "ready": False, "cooldown": 119}],
        ),
        "uk",
    )
    assert late["place"] == "біля їхньої T1 на верхній лінії"
    assert late["status"] == "ТП — через 17 с, Metamorphosis — через 119 с. "
    bare = fight_params(_card_fight(tower=None, has_tp=False, abilities=[]), "uk")
    assert bare["place"] == "на нижній лінії на своїй половині"
    assert bare["status"] == "ТП немає. "


def test_the_card_shows_once_a_minute_and_keeps_its_words():
    tips = RoleTips()
    first = tips.fight(20 * 60, "uk", _card_fight())
    assert first["title"] == "Бійка біля вашої T2 на нижній лінії: союзників 3, ворогів 2"
    assert first["hint"] == (
        "ТП — готово, Metamorphosis — готово. Іти чи ні — вирішуйте з командою."
    )
    # Up for FIGHT_SHOW seconds, the same words even when the fight changes.
    again = tips.fight(20 * 60 + 5, "en", _card_fight(tp_cooldown=40))
    assert again["title"] == "Fight at your T2 in the bottom lane: 3 allies, 2 enemies"
    assert again["hint"].startswith("TP ready")
    assert tips.fight(20 * 60 + FIGHT_SHOW + 1, "uk", _card_fight()) is None
    assert tips.fight(20 * 60 + FIGHT_EVERY, "uk", _card_fight()) is not None


# --- the plan names the fight abilities ----------------------------------------------------


def test_terrorblade_names_metamorphosis():
    fight = plan_fight(plan_for("Terrorblade", "carry"))
    assert fight == {
        "names": ["terrorblade_metamorphosis"],
        "labels": pytest.approx(fight["labels"]),
    }
    assert fight["labels"]["terrorblade_metamorphosis"] == "Metamorphosis"
    assert plan_fight(plan_for("Juggernaut", "carry")) is None
    good = json.loads((ITEM_PLANS_DIR / "terrorblade.json").read_text(encoding="utf-8"))
    for broken in ("terrorblade_metamorphosis", [""], [3]):
        with pytest.raises(ValueError):
            validate({**good, "fight": broken})


# --- live: /gsi → the overlay ----------------------------------------------------------------


def _minimap():
    def hero(name, team, x, y, image):
        return {
            "image": image,
            "team": team,
            "unitname": f"npc_dota_hero_{name}",
            "xpos": x,
            "ypos": y,
        }

    units = {
        "a1": hero("lich", 2, 6000, 1000, "minimap_herocircle"),
        "a2": hero("ogre_magi", 2, 6200, 900, "minimap_herocircle"),
        "a3": hero("invoker", 2, 5800, 1200, "minimap_herocircle"),
        "e1": hero("pudge", 3, 6300, 1300, "minimap_enemyicon"),
        "e2": hero("tidehunter", 3, 6100, 700, "minimap_enemyicon"),
        "t1": {
            "image": "minimap_tower90",
            "team": 2,
            "unitname": "npc_dota_goodguys_tower2_bot",
            "xpos": 6300,
            "ypos": 600,
        },
    }
    return units


def test_the_fight_reaches_the_overlay(client):
    client.post("/settings/advice", json={"role": "carry"})
    payload = copy.deepcopy(gsi_match_stream(minutes=25, death_minutes=())[-2])
    payload["map"]["clock_time"] = 21 * 60
    payload["hero"].update({"xpos": -3000, "ypos": 6000, "alive": True})
    payload["minimap"] = _minimap()
    payload["items"]["teleport0"] = {"name": "item_tpscroll", "cooldown": 0, "can_cast": True}
    client.post("/gsi", json=payload)
    answer = client.get("/overlay/recommendation?lang=uk").json()
    hint = answer["map_hint"]
    assert hint["title"] == "Бійка біля вашої T2 на нижній лінії: союзників 3, ворогів 2"
    assert hint["hint"].startswith("ТП — готово")


def test_a_passive_ultimate_is_marked():
    from app.skill_tips import read_skills

    payload = {
        "hero": {"level": 6},
        "abilities": {
            "ability0": {"name": "phantom_assassin_blur", "level": 1, "ultimate": False},
            "ability1": {
                "name": "phantom_assassin_coup_de_grace",
                "level": 1,
                "ultimate": True,
                "passive": True,
            },
        },
    }
    assert read_skills(payload)["ultimate"] == {
        "raw_name": "phantom_assassin_coup_de_grace",
        "level": 1,
        "passive": True,
    }
