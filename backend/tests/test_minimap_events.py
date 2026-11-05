"""Own buildings attacked and enemy summons pushing (minimap_events.py, cards in
map_hints.RoleTips): parsed from the minimap as a real recording shows it, named
only with an enemy hero or summons seen, never a call. Synthetic snapshots in
the shape of the live minimap and of the normalized extra context; the tests
check decisions, not wording."""

from __future__ import annotations

from typing import Any

from app import minimap_events as events
from app.map_hints import TIPS, RoleTips, building_attack_params, summon_push_params

C = 16384.0
# Radiant's bottom T1 and the player far from it (absolute replay units).
TOWER = (C + 4850.0, C - 6380.0)
FAR_AWAY = (C - 6000.0, C + 2000.0)


def minimap_unit(image: str, team: Any, name: str, at: tuple[float, float]) -> dict[str, Any]:
    return {"image": image, "team": team, "unitname": name, "xpos": at[0] - C, "ypos": at[1] - C}


def test_the_parsers_read_pings_buildings_and_only_the_enemys_summons():
    minimap = {
        "o1": minimap_unit("minimap_ping_baseattacked", None, None, TOWER),  # type: ignore[arg-type]
        "o2": minimap_unit("minimap_tower90", 2, "npc_dota_goodguys_tower1_bot", TOWER),
        "o3": minimap_unit(
            "minimap_racks90", 2, "npc_dota_goodguys_melee_rax_mid", (C - 4000, C - 4000)
        ),
        "o4": minimap_unit("minimap_ancient", 3, "npc_dota_badguys_fort", (C + 6000, C + 6000)),
        "o5": minimap_unit("minimap_controlledcreep", 3, "npc_dota_furion_treant", TOWER),
        "o6": minimap_unit("minimap_controlledcreep", 3, "npc_dota_neutral_centaur_khan", TOWER),
        "o7": minimap_unit("minimap_controlledcreep", 2, "npc_dota_invoker_forged_spirit", TOWER),
        "o8": minimap_unit("minimap_ping_baseattacked", None, None, (C, C)),  # (0, 0): not placed
    }
    assert events.building_pings(minimap) == [{"x": TOWER[0], "y": TOWER[1]}]
    found = {(b["team"], b["kind"], b.get("tier"), b["lane"]) for b in events.buildings(minimap)}
    assert found == {
        ("radiant", "tower", 1, "bot"),
        ("radiant", "barracks", None, "mid"),
        ("dire", "ancient", None, None),
    }
    summons = events.enemy_summons(minimap, "radiant")
    assert [(s["unit"], s["hero"]) for s in summons] == [
        ("npc_dota_furion_treant", "Nature's Prophet"),
        ("npc_dota_neutral_centaur_khan", None),  # dominated: no summoner named
    ]
    assert events.building_pings(None) is None and events.enemy_summons({}, "nobody") is None


def extra(**kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "clock_time": 15 * 60,
        "alive": True,
        "team_name": "radiant",
        "xpos": FAR_AWAY[0],
        "ypos": FAR_AWAY[1],
        "building_pings": [{"x": TOWER[0], "y": TOWER[1]}],
        "buildings": [
            {
                "team": "radiant",
                "kind": "tower",
                "tier": 1,
                "lane": "bot",
                "x": TOWER[0],
                "y": TOWER[1],
            }
        ],
        "enemy_units": [],
        "enemy_summons": [],
    }
    out.update(kw)
    return out


def treants(n: int, at: tuple[float, float] = TOWER) -> list[dict[str, Any]]:
    return [
        {
            "unit": "npc_dota_furion_treant",
            "hero": "Nature's Prophet",
            "x": at[0] + 60 * i,
            "y": at[1],
        }
        for i in range(n)
    ]


def test_a_building_attack_is_named_only_with_an_enemy_hero_or_summons_at_it():
    hero = {"hero": "Anti-Mage", "x": TOWER[0] + 300, "y": TOWER[1]}
    attack = events.building_attack(extra(enemy_units=[hero]))
    assert attack is not None and attack["heroes"] == ["Anti-Mage"]
    assert attack["building"] == {"kind": "tower", "tier": 1, "lane": "bot", "melee": None}
    summoned = events.building_attack(extra(enemy_summons=treants(4)))
    assert summoned["heroes"] == [] and summoned["summons"] == [
        {"hero": "Nature's Prophet", "count": 4}
    ]
    # Lane creeps alone at a tower are the lane; the player there sees it; laning.
    assert events.building_attack(extra()) is None
    assert (
        events.building_attack(extra(enemy_units=[hero], xpos=TOWER[0] + 800, ypos=TOWER[1]))
        is None
    )
    assert events.building_attack(extra(enemy_units=[hero], clock_time=8 * 60)) is None
    assert events.building_attack(extra(enemy_units=[hero], alive=False)) is None
    # A ping not on an own building says nothing.
    assert events.building_attack(extra(enemy_units=[hero], buildings=[])) is None


def test_a_push_by_summons_alone_on_the_players_half():
    push = events.summon_push(extra(enemy_summons=treants(3)))
    assert push is not None and push["count"] == 3 and push["zone"] == "bot"
    assert events.summon_push(extra(enemy_summons=treants(2))) is None
    # A hero with them is a push the fight and group cards read.
    hero = {"hero": "Nature's Prophet", "x": TOWER[0], "y": TOWER[1] + 500}
    assert events.summon_push(extra(enemy_summons=treants(5), enemy_units=[hero])) is None
    # On the enemy half, or next to the player: no card.
    assert events.summon_push(extra(enemy_summons=treants(5, (C + 5000, C + 5000)))) is None
    assert events.summon_push(extra(enemy_summons=treants(5), xpos=TOWER[0], ypos=TOWER[1])) is None


def test_the_cards_keep_their_rhythm_and_never_say_the_same_thing_twice():
    tips = RoleTips()
    hero = {"hero": "Anti-Mage", "x": TOWER[0] + 300, "y": TOWER[1]}
    attack = events.building_attack(extra(enemy_units=[hero]))
    card = tips.building_attack(900, "uk", attack)
    assert card is not None and "T1" in card["title"] and "Anti-Mage" in card["hint"]
    assert card["speak"] is False
    assert tips.building_attack(905, "uk", None) is not None  # stays while it is up
    assert tips.building_attack(940, "uk", attack) is None  # once per BUILDING_EVERY
    assert tips.building_attack(1000, "uk", attack) is None  # the same building: later
    # A summons card up now: an attack by those summons alone adds nothing.
    tips = RoleTips()
    push = events.summon_push(extra(enemy_summons=treants(4)))
    assert tips.summon_push(900, "uk", push) is not None
    alone = events.building_attack(extra(enemy_summons=treants(4)))
    assert tips.building_attack(901, "uk", alone) is None
    assert tips.summon_push(901, "uk", None) is not None


def test_both_languages_render_every_kind_of_building_and_summoner():
    for key in ("building_attack", "summon_push"):
        assert set(TIPS[key]) == {"en", "uk"}
    kinds = [
        {"kind": "tower", "tier": 2, "lane": "mid"},
        {"kind": "barracks", "lane": "top", "melee": True},
        {"kind": "barracks", "lane": "bot", "melee": False},
        {"kind": "ancient"},
        {"kind": "fillers"},
    ]
    for lang in ("en", "uk"):
        for building in kinds:
            for heroes, summons in (
                (["Anti-Mage"], []),
                ([], [{"hero": "Nature's Prophet", "count": 3}]),
                (["Lycan"], [{"hero": None, "count": 2}]),
            ):
                attack = {
                    "building": building,
                    "heroes": heroes,
                    "summons": summons,
                    "team": "radiant",
                }
                params = building_attack_params({**attack, "has_tp": True, "tp_cooldown": 0}, lang)
                title, hint = TIPS["building_attack"][lang]
                assert "{" not in title.format(**params) + hint.format(**params)
        for hero in ("Nature's Prophet", None):
            push = {
                "summons": [{"hero": hero, "count": 3}],
                "count": 3,
                "zone": "bot",
                "side": "own",
            }
            title, hint = TIPS["summon_push"][lang]
            text = title.format(**summon_push_params(push, lang))
            assert "{" not in text and "3" in text


def test_the_live_state_carries_the_minimap_events():
    from app.gsi_state import normalize_gsi_payload

    payload = {
        "map": {"clock_time": 900, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
        "player": {"team_name": "radiant"},
        "hero": {"name": "npc_dota_hero_juggernaut", "xpos": 0, "ypos": 0},
        "minimap": {
            "o1": minimap_unit("minimap_ping_baseattacked", None, None, TOWER),  # type: ignore[arg-type]
            "o2": minimap_unit("minimap_tower90", 2, "npc_dota_goodguys_tower1_bot", TOWER),
            "o3": minimap_unit("minimap_controlledcreep", 3, "npc_dota_furion_treant", TOWER),
        },
    }
    context = normalize_gsi_payload(payload)["extra_context"]
    assert context["building_pings"] and context["buildings"] and context["enemy_summons"]


def test_the_cards_carry_their_place_on_the_small_map_and_the_player_dot():
    from app.live_hints import _with_player_dot
    from app.map_hints import map_point

    assert map_point(8192, 24576) == [0.0, 0.0] and map_point(24576, 8192) == [1.0, 1.0]
    assert map_point(C, C) == [0.5, 0.5]
    assert map_point(0, C) is None and map_point(None, C) is None and map_point(True, C) is None
    hero = {"hero": "Anti-Mage", "x": TOWER[0] + 300, "y": TOWER[1]}
    card = RoleTips().building_attack(900, "en", events.building_attack(extra(enemy_units=[hero])))
    assert card["marker"] == {"target": map_point(*TOWER), "kind": "danger"}
    shown = _with_player_dot(card, {"xpos": FAR_AWAY[0], "ypos": FAR_AWAY[1]})
    assert shown["marker"]["player"] == map_point(*FAR_AWAY)
    assert "player" not in card["marker"]  # the card itself is not changed
    plain = {"id": "rune", "title": "Rune"}
    assert _with_player_dot(plain, {"xpos": 1, "ypos": 1}) is plain
