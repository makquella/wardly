"""Counter items for the player's own hero (hero_items.py, data/heroes/item_plans):
every plan follows the template, and Terrorblade's plan answers each lineup the
way his build and the items' 7.41f mechanics say."""

from __future__ import annotations

import json

import pytest
from match_fixtures import gsi_match_stream
from test_next_item import META
from test_situational_items import _stunned

from app.advice_i18n import translate_uk
from app.death_screen import build_death_screen
from app.hero_items import (
    ITEM_PLANS_DIR,
    groups,
    load_plans,
    plan_for,
    plan_skills,
    tempo_threshold,
    validate,
)
from app.next_item import net_worth
from app.post_laning_coach import _next_item_copy
from app.situational_items import draft_item, situational_item

GENERIC_WHYS = {"evasion", "illusions", "healing", "break", "magic"}


def _tb(enemies, owned=(), *, position="carry", minute=20, deaths=()):
    return situational_item(
        list(deaths),
        list(owned),
        META,
        enemies=list(enemies),
        position=position,
        minute=minute,
        hero="Terrorblade",
    )


# --- the template: what every plan must have ----------------------------------------


def test_every_plan_follows_the_template():
    plans = load_plans()
    assert plans, "no plans in data/heroes/item_plans"
    known = groups()
    for plan in plans.values():
        assert plan["patch"] and plan["checked"] and plan["sources"]
        for item in plan.get("tempo", {}).get("items", []):
            assert item["item"] and item["name"]
        for rule in plan["rules"]:
            assert rule["basis"].strip()  # why the item, from the build or the mechanics
            assert rule["enemy"] in known and rule.get("also", "evasion") in known
        # A suppressed counter is a generic one, with the reason it does not fit.
        assert set(plan.get("suppress", {})) <= GENERIC_WHYS


def test_a_broken_plan_is_refused():
    good = json.loads((ITEM_PLANS_DIR / "terrorblade.json").read_text(encoding="utf-8"))
    validate(good)
    broken = [
        {**good, "hero": "Not A Hero"},
        {**good, "positions": ["jungle"]},
        {**good, "rules": [{**good["rules"][0], "enemy": "tanks"}]},
        {**good, "rules": [{**good["rules"][0], "basis": " "}]},
        {**good, "rules": [{**good["rules"][0], "reason": {"en": "x {enemy}"}}]},  # no uk
        {**good, "rules": [{**good["rules"][0], "reason": {"en": "{hero} wins", "uk": "{hero}"}}]},
        {**good, "rules": [{**good["rules"][0], "reason": {"en": "{enemy} heals", "uk": "лікує"}}]},
        {**good, "rules": [{**good["rules"][0], "reason": {"en": "Ends.", "uk": "Кінець"}}]},
        {**good, "rules": [good["rules"][0], good["rules"][0]]},  # the same id twice
        {**good, "suppress": {"illusions": ""}},
        {**good, "tempo": {**good["tempo"], "net_worth": [[25, 16000], [20, 12000]]}},
        {**good, "tempo": {**good["tempo"], "net_worth": [[20, "12k"]]}},
        {**good, "tempo": {**good["tempo"], "items": []}},
        {**good, "tempo": {**good["tempo"], "basis": ""}},
    ]
    for plan in broken:
        with pytest.raises(ValueError):
            validate(plan)


# --- Terrorblade ---------------------------------------------------------------------


def test_against_evasion_alone_monkey_king_bar():
    item = _tb(["Phantom Assassin", "Lion", "Axe", "Crystal Maiden"])
    assert (item["key"], item["why"], item["enemy"]) == (
        "monkey_king_bar",
        "evasion",
        "Phantom Assassin",
    )


@pytest.mark.parametrize(
    ("evasive", "escape", "spell"),
    [
        ("Phantom Assassin", "Queen of Pain", "Blink"),
        ("Windranger", "Storm Spirit", "Ball Lightning"),
        ("Phantom Assassin", "Puck", "Phase Shift"),
    ],
)
def test_against_evasion_and_an_escape_bloodthorn(evasive, escape, spell):
    item = _tb([evasive, "Lion", escape, "Axe"])
    assert (item["key"], item["why"]) == ("bloodthorn", "evasion_escape")
    assert (item["enemy"], item["escape"], item["spell"]) == (evasive, escape, spell)


def test_anti_mage_is_no_escape_for_a_silence():
    # Counterspell turns the targeted silence back: Monkey King Bar stays.
    assert _tb(["Phantom Assassin", "Anti-Mage", "Lion", "Axe"])["key"] == "monkey_king_bar"


def test_one_answer_to_evasion_is_enough():
    lineup = ["Phantom Assassin", "Queen of Pain", "Lion", "Axe"]
    for owned in (["item_monkey_king_bar"], ["item_bloodthorn"]):
        # Not the other answer to evasion; Phantom Assassin's jump is next.
        assert _tb(lineup, owned)["key"] == "hurricane_pike"


def test_against_healing_his_own_skadi_stays_in_the_build():
    # From minute 20, after Manta Style: the build's own answer, not a Spirit Vessel.
    # (No magic lineup here: three magic heroes would ask for Black King Bar.)
    assert _tb(["Huskar", "Axe", "Sven", "Juggernaut"], minute=15) is None
    item = _tb(["Huskar", "Axe", "Sven", "Juggernaut"], minute=20)
    assert (item["key"], item["why"], item["enemy"]) == ("skadi", "healing", "Huskar")
    # With Skadi bought, the generic answer to Berserker's Blood comes next.
    assert _tb(["Huskar", "Lion", "Axe", "Crystal Maiden"], ["item_skadi"])["key"] == "silver_edge"


def test_against_illusions_butterfly_then_the_dragon_lance_into_hydras_breath():
    lineup = ["Phantom Lancer", "Lion", "Axe", "Crystal Maiden"]
    first = _tb(lineup)
    assert (first["key"], first["why"], first["enemy"]) == (
        "butterfly",
        "illusion_evasion",
        "Phantom Lancer",
    )
    second = _tb(lineup, ["item_butterfly"])
    assert (second["key"], second["why"]) == ("hydras_breath", "illusion_splash")
    # No Maelstrom for him; other carries keep the generic counter.
    assert _tb(lineup, ["item_butterfly", "item_hydras_breath"]) is None
    other = situational_item(
        [], [], META, enemies=lineup, position="carry", minute=20, hero="Wraith King"
    )
    assert other["key"] == "maelstrom"


@pytest.mark.parametrize(
    ("jumper", "spell"),
    [("Slark", "Pounce"), ("Spirit Breaker", "Charge of Darkness")],
)
def test_against_a_hero_who_jumps_on_him_hurricane_pike(jumper, spell):
    item = _tb([jumper, "Lion", "Axe", "Crystal Maiden"])
    assert (item["key"], item["why"], item["enemy"], item["spell"]) == (
        "hurricane_pike",
        "jumper",
        jumper,
        spell,
    )
    # Phantom Assassin jumps too: Pike once the evasion is answered.
    assert _tb(["Phantom Assassin", "Lion", "Axe"], ["item_monkey_king_bar"])["key"] == (
        "hurricane_pike"
    )


def test_one_dragon_lance_upgrade_against_illusions_and_jumpers():
    # Illusions win the Dragon Lance: Hydra's Breath, not Pike as well.
    lineup = ["Phantom Lancer", "Slark", "Axe", "Crystal Maiden"]
    assert _tb(lineup, ["item_butterfly"])["key"] == "hydras_breath"
    assert _tb(lineup, ["item_butterfly", "item_hydras_breath"]) is None
    assert _tb(["Slark", "Axe"], ["item_hurricane_pike"]) is None


def test_the_tempo_curve_from_high_rank_games():
    plan = plan_for("Terrorblade", "carry")
    # 12.5k, 17.5k and 22k gold by 20, 25 and 30 min (85%+ wins), as net worth.
    assert [tempo_threshold(plan, m) for m in (19, 20, 22, 25, 30, 35)] == [
        None,
        12000,
        13920,
        16800,
        21100,
        25400,
    ]


def test_net_worth_is_gold_and_the_items_carried():
    constants = META["constants"]
    owned = ["item_manta", "item_black_king_bar"]
    expected = 900 + sum(constants["items"][k]["cost"] for k in ("manta", "black_king_bar"))
    assert net_worth(owned, 900, constants) == expected
    assert net_worth(owned, None, constants) is None  # no gold: unknown
    assert net_worth(owned, 900, {}) is None  # no prices: unknown


def _ahead(owned, net_worth, *, minute=25, deaths=()):
    lineup = ["Phantom Assassin", "Queen of Pain", "Axe", "Crystal Maiden"]
    return situational_item(
        list(deaths),
        list(owned),
        META,
        enemies=lineup,
        position="carry",
        minute=minute,
        hero="Terrorblade",
        net_worth=net_worth,
    )


def test_farmed_over_the_curve_the_tempo_build_before_the_counters():
    # The order of his farmed won games: Manta, Shard, Dragon Lance, Skadi...
    assert _ahead(["item_manta"], 17000)["key"] == "aghanims_shard"
    ahead = _ahead(["item_manta", "item_aghanims_shard", "item_dragon_lance"], 17000)
    assert (ahead["key"], ahead["why"], ahead["count"]) == ("skadi", "tempo", 17000)
    owned_all = [
        "item_manta",
        "item_aghanims_shard",
        "item_dragon_lance",
        "item_skadi",
        "item_butterfly",
        "item_greater_crit",
    ]
    assert _ahead(owned_all, 30000) is None
    # Under the curve, before minute 20, or with no net worth known: the counters.
    for owned, worth, minute in (
        (["item_manta"], 16000, 25),
        (["item_manta"], 17000, 19),
        (["item_manta"], None, 25),
    ):
        item = _ahead(owned, worth, minute=minute)
        assert item is None or item["why"] != "tempo"
    # Deaths under stuns still come first.
    assert _ahead([], 17000, deaths=[_stunned(600), _stunned(900)])["key"] == "black_king_bar"
    state = {"minute": 25, "gold": 900, "extra_context": {"next_item": ahead, "gpm": 600}}
    _, reason = _next_item_copy(state, state["extra_context"])
    assert reason.startswith(
        "Your net worth is 17000, well ahead for this minute: Eye of Skadi on the tempo build"
    )
    assert translate_uk(reason).startswith(
        "Ваш нетворс — 17000, набагато більше звичайного для цієї хвилини: спершу Eye of Skadi"
    )
    for lang in ("en", "uk"):
        screen = build_death_screen(
            death={"t": 1500, "usable": []},
            place=None,
            respawn=30,
            gold=900,
            buyback_cost=None,
            minute=25,
            next_item={**ahead, "gold_left": 3000},
            lang=lang,
        )
        assert any("Aegis" in line for line in screen["lines"])


def test_the_live_farm_advice_reads_the_net_worth(monkeypatch):
    from app.player_api import PLAYER_SERVICE

    monkeypatch.setattr(PLAYER_SERVICE, "_live_meta", lambda hero_id: META)
    lineup = ["Phantom Assassin", "Queen of Pain", "Axe", "Crystal Maiden"]
    poor = PLAYER_SERVICE.next_item(
        "Terrorblade", ["item_manta"], enemies=lineup, minute=25, gold=500
    )
    assert poor["key"] == "bloodthorn"
    rich = PLAYER_SERVICE.next_item(
        "Terrorblade", ["item_manta"], enemies=lineup, minute=25, gold=13000
    )  # 13000 + Manta Style 4650 = 17650 over 16800 at 25:00
    assert (rich["key"], rich["why"]) == ("aghanims_shard", "tempo")


def test_a_consumed_shard_counts_as_owned(monkeypatch):
    # GSI drops the Shard from the items and sets hero.aghanims_shard instead.
    from app import main
    from app.player_api import PLAYER_SERVICE

    seen = {}

    def next_item(hero, owned, **kwargs):
        seen["owned"] = owned
        return None

    monkeypatch.setattr(PLAYER_SERVICE, "next_item", next_item)
    state = {
        "hero": "Terrorblade",
        "gold": 500,
        "minute": 25,
        "extra_context": {"item_names": ["item_manta"], "aghanims_shard": True},
    }
    main._with_next_item(state, "full", "SAFE_FARMING")
    assert seen["owned"] == ["item_manta", "item_aghanims_shard"]


def test_other_heroes_and_other_positions_keep_the_generic_counters():
    lineup = ["Phantom Assassin", "Queen of Pain", "Lion", "Axe"]
    generic = situational_item(
        [], [], META, enemies=lineup, position="carry", minute=20, hero="Wraith King"
    )
    assert generic["key"] == "monkey_king_bar"
    assert plan_for("Terrorblade", "mid") is None
    generic_mid = situational_item([], [], META, enemies=lineup, position="mid", minute=20)
    assert _tb(lineup, position="mid") == generic_mid


def test_the_minute_gate_and_the_death_patterns_still_come_first():
    # No single-target disabler (Lion's Hex would make it Linken's Sphere).
    lineup = ["Phantom Assassin", "Queen of Pain", "Crystal Maiden", "Axe"]
    assert _tb(lineup, minute=10) is None  # too early in the match for the counter
    stunned = _tb(lineup, deaths=[_stunned(600), _stunned(900)])
    assert stunned["key"] == "black_king_bar"
    # The draft read names the item to plan for, without the minute gate.
    early = draft_item(lineup, [], META, "carry", "Terrorblade")
    assert early["key"] == "bloodthorn"


BLOODTHORN_WHY = {
    "en": (
        "Phantom Assassin dodges attacks and Queen of Pain escapes with Blink: Bloodthorn "
        "silences the escape, and your attacks and illusions never miss the silenced target"
    ),
    "uk": (
        "Phantom Assassin ухиляється від атак, а Queen of Pain тікає через Blink: Bloodthorn "
        "накладає тишу, і по цілі під тишею ваші атаки й ілюзії не промахуються"
    ),
}


def test_bloodthorn_says_why_on_the_card_the_death_screen_and_the_farm_advice():
    item = _tb(["Phantom Assassin", "Queen of Pain", "Lion", "Axe"])
    assert item["reason"] == BLOODTHORN_WHY
    for lang, why in (("en", "Why Bloodthorn: "), ("uk", "Чому Bloodthorn: ")):
        screen = build_death_screen(
            death={"t": 1200, "usable": []},
            place=None,
            respawn=30,
            gold=900,
            buyback_cost=None,
            minute=20,
            next_item={**item, "gold_left": 4000},
            lang=lang,
        )
        assert why + BLOODTHORN_WHY[lang] + "." in screen["lines"]
    state = {"minute": 20, "gold": 900, "extra_context": {"next_item": item, "gpm": 520}}
    action, reason = _next_item_copy(state, state["extra_context"])
    assert action == "Keep farming toward Bloodthorn on the safest waves and camps."
    assert reason == BLOODTHORN_WHY["en"] + "."
    assert translate_uk(reason) == BLOODTHORN_WHY["uk"] + "."


def test_the_draft_card_for_terrorblade_reaches_the_overlay(client):
    from app.live_role import set_role_setting

    set_role_setting("carry")
    lineup = {
        f"o{i}": {"image": "minimap_enemyicon", "unitname": f"npc_dota_hero_{name}", "team": 3}
        for i, name in enumerate(("phantom_assassin", "queenofpain", "lion", "axe"))
    }
    texts = []
    for payload in gsi_match_stream(minutes=5, death_minutes=(), step_seconds=5):
        payload["hero"]["name"] = "npc_dota_hero_terrorblade"
        payload["minimap"] = lineup
        client.post("/gsi", json=payload)
        if payload["map"]["clock_time"] >= 180:
            hint = client.get("/overlay/recommendation?lang=en").json().get("map_hint") or {}
            texts.append((hint.get("title"), hint.get("hint")))
    assert ("Against their draft: Bloodthorn", BLOODTHORN_WHY["en"] + ".") in texts


# The usual build: real 7.41 recipes (OpenDota constants), so Hydra's Breath
# contains the Dragon Lance.
TB_ITEMS = {
    "power_treads": {"name": "Power Treads", "cost": 1400, "components": ["boots"]},
    "falcon_blade": {"name": "Falcon Blade", "cost": 1125, "components": ["sobi_mask"]},
    "manta": {"name": "Manta Style", "cost": 4650, "components": ["yasha", "diadem"]},
    "aghanims_shard": {"name": "Aghanim's Shard", "cost": 1400, "components": []},
    "dragon_lance": {"name": "Dragon Lance", "cost": 1900, "components": ["blade_of_alacrity"]},
    "skadi": {"name": "Eye of Skadi", "cost": 5900, "components": ["ultimate_orb"]},
    "hurricane_pike": {
        "name": "Hurricane Pike",
        "cost": 4450,
        "components": ["force_staff", "dragon_lance"],
    },
    "butterfly": {"name": "Butterfly", "cost": 5450, "components": ["eagle"]},
    "black_king_bar": {"name": "Black King Bar", "cost": 4050, "components": ["ogre_axe"]},
    "greater_crit": {"name": "Daedalus", "cost": 5100, "components": ["demon_edge"]},
    "hydras_breath": {
        "name": "Hydra's Breath",
        "cost": 5900,
        "components": ["specialists_array", "dragon_lance", "orb_of_venom"],
    },
}
TB_META = {"constants": {"items": TB_ITEMS, "by_id": {}}, "popularity": {}}


def test_his_usual_build_comes_from_high_rank_won_games(monkeypatch):
    from app.player_api import PLAYER_SERVICE

    monkeypatch.setattr(PLAYER_SERVICE, "_live_meta", lambda hero_id: TB_META)

    def next_key(owned):
        # At 45:00 the tempo line (~34k) stays above these items' worth.
        item = PLAYER_SERVICE.next_item("Terrorblade", owned, enemies=[], minute=45, gold=0)
        return item and item["key"]

    order = [
        "power_treads",
        "falcon_blade",
        "manta",
        "aghanims_shard",
        "dragon_lance",
        "skadi",
        "hurricane_pike",
        "butterfly",
        "black_king_bar",
        "greater_crit",
    ]
    owned: list[str] = []
    for key in order:
        assert next_key(owned) == key
        owned.append(f"item_{key}")
    # The Dragon Lance went into Hydra's Breath: no Lance, no Pike after it.
    hydra = [
        "item_power_treads",
        "item_falcon_blade",
        "item_manta",
        "item_aghanims_shard",
        "item_hydras_breath",
    ]
    assert next_key(hydra) == "skadi"
    assert next_key([*hydra, "item_skadi"]) == "butterfly"
    # A counter still comes first.
    lineup = ["Phantom Assassin", "Lion", "Axe", "Crystal Maiden"]
    counter = PLAYER_SERVICE.next_item("Terrorblade", [], enemies=lineup, minute=20, gold=0)
    assert counter["why"] == "evasion"
    # Played mid, the carry plan does not apply (the live role picks the plan).
    mid = PLAYER_SERVICE.next_item("Terrorblade", [], enemies=lineup, minute=20, gold=0, role="mid")
    assert mid is None or mid.get("why") not in ("evasion", "evasion_escape")


def test_a_broken_build_is_refused():
    good = json.loads((ITEM_PLANS_DIR / "terrorblade.json").read_text(encoding="utf-8"))
    for plan in (
        {**good, "build": []},
        {**good, "build": [{"item": "manta"}]},  # no name
        {**good, "build_basis": ""},
    ):
        with pytest.raises(ValueError):
            validate(plan)


def test_the_owned_items_carry_the_consumed_shard():
    from app.next_item import owned_items

    assert owned_items({"item_names": ["item_manta"], "aghanims_shard": True}) == [
        "item_manta",
        "item_aghanims_shard",
    ]
    assert owned_items({"item_names": ["item_manta"], "aghanims_shard": False}) == ["item_manta"]
    assert owned_items({}) is None


# --- the skill build from the same high-rank games ------------------------------------


def _tb_skills(level, levels, *, sunder=0, talents=None):
    names = ("terrorblade_reflection", "terrorblade_conjure_image", "terrorblade_metamorphosis")
    abilities = {
        f"ability{i}": {"name": name, "level": lvl, "ultimate": False}
        for i, (name, lvl) in enumerate(zip(names, levels, strict=True))
    }
    abilities["ability3"] = {"name": "terrorblade_sunder", "level": sunder, "ultimate": True}
    hero = {"level": level, "name": "npc_dota_hero_terrorblade"}
    if talents is not None:
        hero.update({f"talent_{i + 1}": taken for i, taken in enumerate(talents)})
    return {"hero": hero, "abilities": abilities}


def test_his_skill_build_comes_from_high_rank_games():
    from app.player_api import PLAYER_SERVICE
    from app.skill_build import next_skill

    build = PLAYER_SERVICE.skill_build("Terrorblade")
    assert build["order"] == [
        "terrorblade_conjure_image",
        "terrorblade_metamorphosis",
        "terrorblade_reflection",
    ]
    assert (build["games"], build["first_agree"]) == (634, 560)
    assert build["opening"] == {"name": "terrorblade_conjure_image", "agree": 463, "games": 634}
    assert build["talents"][15]["label"] == "Metamorphosis Cooldown"
    # Conjure Image first, then Metamorphosis, Reflection last.
    levels = {
        "terrorblade_reflection": 0,
        "terrorblade_conjure_image": 1,
        "terrorblade_metamorphosis": 1,
    }
    assert next_skill(build, levels, 3) == "terrorblade_conjure_image"
    levels["terrorblade_conjure_image"] = 4
    assert next_skill(build, levels, 9) == "terrorblade_metamorphosis"
    levels["terrorblade_metamorphosis"] = 4
    assert next_skill(build, levels, 13) == "terrorblade_reflection"


def test_the_first_point_and_the_talents_name_the_high_rank_choice():
    from app.player_api import PLAYER_SERVICE
    from app.skill_tips import UNSPENT_WAIT, SkillTips, read_skills

    build = PLAYER_SERVICE.skill_build("Terrorblade")
    tips = SkillTips()
    tips.observe(-80, read_skills(_tb_skills(1, [0, 0, 0])))
    tips.observe(-79, read_skills(_tb_skills(1, [0, 0, 0])))
    hint = tips.tip(-79 + UNSPENT_WAIT, "en", alive=True, build=build)
    assert hint["title"] == "First point: Conjure Image"
    assert "463 of 634" in hint["hint"]
    tips = SkillTips()
    talents = [False, True] + [False] * 6  # the level-10 talent taken
    tips.observe(1500, read_skills(_tb_skills(14, [2, 4, 4], sunder=2, talents=talents)))
    tips.observe(1510, read_skills(_tb_skills(15, [2, 4, 4], sunder=2, talents=talents)))
    hint = tips.tip(1510 + UNSPENT_WAIT, "uk", alive=True, build=build)
    assert "Metamorphosis Cooldown" in hint["hint"] and "409 з 584" in hint["hint"]


def test_other_heroes_keep_the_pro_games_skill_build():
    from app.player_api import PLAYER_SERVICE

    assert PLAYER_SERVICE.skill_build("Wraith King") is None  # nothing cached in the tests


def test_a_broken_skill_plan_is_refused():
    good = json.loads((ITEM_PLANS_DIR / "terrorblade.json").read_text(encoding="utf-8"))
    skills = good["skills"]
    for broken in (
        {**skills, "order": []},
        {**skills, "first_agree": 9999},
        {**skills, "opening": {"name": "terrorblade_conjure_image", "agree": 0}},
        {**skills, "talents": {"11": skills["talents"]["10"]}},
        {**skills, "talents": {"10": {**skills["talents"]["10"], "picked": 9999}}},
        {**skills, "basis": ""},
    ):
        with pytest.raises(ValueError):
            validate({**good, "skills": broken})


def test_level_20_takes_the_stats_when_the_enemy_clears_illusions():
    from app.player_api import PLAYER_SERVICE
    from app.skill_tips import UNSPENT_WAIT, SkillTips, read_skills

    def talent_hint(enemies, lang="en"):
        build = PLAYER_SERVICE.skill_build("Terrorblade", enemies)
        tips = SkillTips()
        talents = [False, True, True, False] + [False] * 4  # rows 10 and 15 taken
        tips.observe(2000, read_skills(_tb_skills(19, [4, 4, 4], sunder=3, talents=talents)))
        tips.observe(2010, read_skills(_tb_skills(20, [4, 4, 4], sunder=3, talents=talents)))
        return tips.tip(2010 + UNSPENT_WAIT, lang, alive=True, build=build)["hint"]

    # Two enemy heroes whose area damage or Hex clears illusions: the stats.
    two = talent_hint(["Lion", "Luna", "Axe"])
    assert two == (
        "Level 20: take “+10 All Attributes”. 2 enemy heroes clear illusions fast "
        "(Lion, Luna): longer images would not last."
    )
    assert "+10 All Attributes" in talent_hint(["Lion", "Luna"], "uk")
    # One of them, or none: the usual pick.
    for lineup in (["Lion", "Axe"], [], None):
        assert "Conjure Image Duration" in talent_hint(lineup)


def test_sunder_hp_threshold_is_never_the_tip():
    build = plan_skills(plan_for("Terrorblade", "carry"), ["Lion", "Luna", "Invoker"])
    assert build["talents"][15]["label"] == "Metamorphosis Cooldown"
    assert all(
        t["name"] != "special_bonus_unique_terrorblade_sunder_hp_threshold"
        for t in build["talents"].values()
    )


def test_a_broken_talent_alternative_is_refused():
    good = json.loads((ITEM_PLANS_DIR / "terrorblade.json").read_text(encoding="utf-8"))
    row = good["skills"]["talents"]["20"]
    for instead in ({**row["instead"], "enemy": "tanks"}, {**row["instead"], "min": 0}):
        talents = {**good["skills"]["talents"], "20": {**row, "instead": instead}}
        with pytest.raises(ValueError):
            validate({**good, "skills": {**good["skills"], "talents": talents}})


# --- wave 1: the first carries after Terrorblade -------------------------------------

MAGIC_LINEUP = ["Lion", "Lina", "Leshrac", "Axe"]


def _carry(hero, enemies, owned=(), minute=20):
    return situational_item(
        [], list(owned), META, enemies=list(enemies), position="carry", minute=minute, hero=hero
    )


@pytest.mark.parametrize(
    ("hero", "enemies", "key", "why"),
    [
        ("Juggernaut", ["Phantom Assassin", "Axe"], "monkey_king_bar", "evasion"),
        ("Juggernaut", ["Bristleback", "Axe"], "silver_edge", "break"),
        ("Phantom Lancer", ["Phantom Assassin", "Axe"], "bloodthorn", "evasion_bloodthorn"),
        ("Phantom Lancer", ["Naga Siren", "Axe"], "butterfly", "illusion_evasion"),
        ("Luna", ["Spectre", "Axe"], "silver_edge", "break"),
        ("Lifestealer", ["Windranger", "Axe"], "monkey_king_bar", "evasion"),
        ("Lifestealer", ["Huskar", "Axe"], "silver_edge", "break"),
        ("Slark", ["Bristleback", "Axe"], "silver_edge", "break"),
    ],
)
def test_wave_one_counters_come_with_the_plans_reason(hero, enemies, key, why):
    item = _carry(hero, enemies)
    assert (item["key"], item["why"], item["enemy"]) == (key, why, enemies[0])
    assert item["reason"]["en"].startswith(enemies[0])
    assert item["reason"]["uk"].startswith(enemies[0])


@pytest.mark.parametrize(
    ("hero", "enemies"),
    [
        # Battle Fury cleaves, Moon Glaives bounce, Diffusal is in the build.
        ("Juggernaut", ["Naga Siren", "Axe"]),
        ("Luna", ["Phantom Lancer", "Axe"]),
        ("Slark", ["Chaos Knight", "Axe"]),
        # Blade Fury and Rage: debuff immunity with 80% magic resistance.
        ("Juggernaut", MAGIC_LINEUP),
        ("Lifestealer", MAGIC_LINEUP),
        # His illusions do not break: no Silver Edge.
        ("Phantom Lancer", ["Bristleback", "Axe"]),
        # Radiance is enough (a note names Mjollnir).
        ("Lifestealer", ["Naga Siren", "Axe"]),
    ],
)
def test_wave_one_suppressed_generic_counters(hero, enemies):
    assert _carry(hero, enemies) is None
    # A hero without a plan keeps the generic counter.
    assert _carry("Wraith King", enemies) is not None


def test_lifestealer_takes_manta_or_sange_and_yasha_not_both():
    from app.next_item import next_listed_item

    build = plan_for("Lifestealer", "carry")["build"]
    items = {e["item"]: {"name": e["name"], "cost": 4000, "components": []} for e in build}
    meta = {"constants": {"items": items, "by_id": {}}, "popularity": {}}
    owned = ["item_phase_boots", "item_radiance", "item_armlet"]
    assert next_listed_item(build, meta, owned)["key"] == "sange_and_yasha"
    for first in ("item_sange_and_yasha", "item_manta"):
        assert next_listed_item(build, meta, [*owned, first])["key"] == "ultimate_scepter"


def test_juggernaut_tempo_line_is_straight_from_20_to_30():
    plan = plan_for("Juggernaut", "carry")
    assert [tempo_threshold(plan, m) for m in (20, 25, 30)] == [11000, 16050, 21100]
    # Phantom Lancer's line starts at 25:00: nothing earlier.
    assert tempo_threshold(plan_for("Phantom Lancer", "carry"), 20) is None


def test_luna_and_slark_take_their_own_80_percent_tempo_line():
    # No 85% line in their high-rank games: the hero's own 80% one (player review).
    luna, slark = plan_for("Luna", "carry"), plan_for("Slark", "carry")
    # Luna's 25:00 point rested on 15 games: from 30:00 only (PLAN_POINT_GAMES).
    assert [tempo_threshold(luna, m) for m in (25, 29, 30)] == [None, None, 22100]
    assert [tempo_threshold(slark, m) for m in (20, 30)] == [11000, 16300]
    item = situational_item(
        [],
        [],
        META,
        enemies=["Bristleback"],
        position="carry",
        minute=20,
        hero="Slark",
        net_worth=12000,
    )
    assert item["why"] == "tempo" and "12000" in item["reason"]["en"]


@pytest.mark.parametrize(
    ("enemies", "owned", "key", "why", "spell"),
    [
        # Eye of Skadi first for the bulk, whatever the evasion.
        (["Phantom Assassin", "Axe"], [], "skadi", "evasion_skadi", None),
        (["Windranger", "Axe"], [], "skadi", "evasion_skadi", None),
        # Then Phantom Assassin: break turns off Immaterial.
        (["Phantom Assassin", "Axe"], ["item_skadi"], "silver_edge", "evasion_break", "Immaterial"),
        # With an escape a silence stops: Bloodthorn answers both.
        (
            ["Phantom Assassin", "Queen of Pain"],
            ["item_skadi"],
            "bloodthorn",
            "evasion_escape",
            "Blink",
        ),
        # Windrun is cast, break does nothing: the silence.
        (["Windranger", "Axe"], ["item_skadi"], "bloodthorn", "evasion_bloodthorn", None),
    ],
)
def test_slark_against_evasion_skadi_then_silver_edge_or_bloodthorn(
    enemies, owned, key, why, spell
):
    item = _carry("Slark", enemies, owned)
    assert (item["key"], item["why"], item["spell"]) == (key, why, spell)
    if key != "skadi":
        assert item["reason"]["en"].endswith(
            "Monkey King Bar is cheaper but only pierces the evasion"
        )
        # One answer to the evasion owned: the family is done.
        assert _carry("Slark", enemies, ["item_skadi", f"item_{key}"]) is None
    # Other carries keep the generic Monkey King Bar.
    assert _carry("Wraith King", enemies)["key"] == "monkey_king_bar"


def test_plan_notes_name_no_item():
    from app.hero_items import plan_note
    from app.map_hints import RoleTips

    slark = plan_for("Slark", "carry")
    assert plan_note(slark, ["Phantom Lancer", "Axe"], 9) is None
    note = plan_note(slark, ["Axe", "Phantom Lancer"], 10)
    assert note["enemy"] == "Phantom Lancer" and "Essence Shift" in note["reason"]["en"]
    assert plan_note(slark, ["Axe"], 30) is None
    ls = plan_for("Lifestealer", "carry")
    assert plan_note(ls, ["Naga Siren"], 24) is None
    assert "Mjollnir" in plan_note(ls, ["Naga Siren"], 25)["reason"]["uk"]
    assert plan_note(plan_for("Juggernaut", "carry"), ["Naga Siren"], 30) is None

    tips = RoleTips()

    def shown(clock, lang="en"):
        return tips.tip(clock, "carry", alive=True, has_ward=None, lang=lang, plan_note=note)

    first = shown(15 * 60)
    assert first["title"] == "Against Phantom Lancer"
    assert first["hint"] == note["reason"]["en"] + "."
    assert shown(15 * 60 + 10, "uk")["hint"] == note["reason"]["uk"] + "."
    assert shown(15 * 60 + 30) is None  # once per match


# --- wave 2: Anti-Mage, Medusa, Phantom Assassin, Spectre, Sven -----------------------


@pytest.mark.parametrize(
    ("hero", "enemies", "key", "why"),
    [
        ("Anti-Mage", ["Windranger", "Axe"], "monkey_king_bar", "evasion"),
        ("Medusa", ["Phantom Assassin", "Axe"], "monkey_king_bar", "evasion"),
        ("Medusa", ["Naga Siren", "Axe"], "maelstrom", "illusions_maelstrom"),
        ("Anti-Mage", ["Huskar", "Axe"], "skadi", "healing"),
        ("Medusa", ["Bristleback", "Axe"], "silver_edge", "break"),
        ("Phantom Assassin", ["Windranger", "Axe"], "monkey_king_bar", "evasion"),
        ("Phantom Assassin", ["Spectre", "Axe"], "ultimate_scepter", "break_fan_of_knives"),
        ("Spectre", ["Phantom Assassin", "Axe"], "skadi", "evasion_skadi"),
        ("Sven", ["Phantom Assassin", "Axe"], "monkey_king_bar", "evasion"),
    ],
)
def test_wave_two_counters_come_with_the_plans_reason(hero, enemies, key, why):
    item = _carry(hero, enemies)
    assert (item["key"], item["why"], item["enemy"]) == (key, why, enemies[0])
    assert item["reason"]["en"].startswith(enemies[0])
    assert item["reason"]["uk"].startswith(enemies[0])


@pytest.mark.parametrize(
    ("hero", "enemies"),
    [
        # Battle Fury, Radiance and Great Cleave answer illusions; Abyssal for AM.
        ("Anti-Mage", ["Naga Siren", "Axe"]),
        ("Phantom Assassin", ["Phantom Lancer", "Axe"]),
        ("Spectre", ["Chaos Knight", "Axe"]),
        ("Sven", ["Naga Siren", "Axe"]),
        ("Anti-Mage", ["Bristleback", "Axe"]),
        # Counterspell and Mana Shield: no BKB for 3+ magic damage heroes.
        ("Anti-Mage", MAGIC_LINEUP),
        ("Medusa", MAGIC_LINEUP),
        # Blink after Mask of Madness and Echo Sabre: no Silver Edge for Sven.
        ("Sven", ["Bristleback", "Axe"]),
    ],
)
def test_wave_two_suppressed_generic_counters(hero, enemies):
    assert _carry(hero, enemies) is None
    assert _carry("Wraith King", enemies) is not None


def test_spectre_keeps_the_generic_monkey_king_bar_after_her_skadi():
    item = _carry("Spectre", ["Windranger", "Axe"], ["item_skadi"])
    assert (item["key"], item["why"]) == ("monkey_king_bar", "evasion")


def test_passive_ultimates_name_an_active_fight_ability():
    assert plan_for("Phantom Assassin", "carry")["fight"] == ["phantom_assassin_blur"]
    assert plan_for("Phantom Lancer", "carry")["fight"] == ["phantom_lancer_doppelwalk"]


MEDUSA_META = {
    "constants": {
        "items": {
            "maelstrom": {"name": "Maelstrom", "cost": 2950, "components": ["gauntlets"]},
            "mjollnir": {"name": "Mjollnir", "cost": 5500, "components": ["maelstrom"]},
            "ultimate_scepter": {"name": "Aghanim's Scepter", "cost": 4200, "components": []},
        },
        "by_id": {},
    },
    "popularity": {},
}


def test_medusa_against_illusions_maelstrom_then_mjollnir_then_aghanims():
    lineup = ["Naga Siren", "Axe"]

    def medusa(owned=(), minute=20):
        return situational_item(
            [],
            list(owned),
            MEDUSA_META,
            enemies=lineup,
            position="carry",
            minute=minute,
            hero="Medusa",
        )

    assert medusa(minute=19)["key"] == "maelstrom"
    assert medusa(["item_maelstrom"], minute=19) is None  # Mjollnir from 20:00
    item = medusa(["item_maelstrom"])
    assert (item["key"], item["why"]) == ("mjollnir", "illusions_mjollnir")
    # Mjollnir is built from Maelstrom: both answered; Aghanim's from 25:00.
    assert medusa(["item_mjollnir"], minute=24) is None
    aghs = medusa(["item_mjollnir"], minute=25)
    assert (aghs["key"], aghs["why"]) == ("ultimate_scepter", "illusions_split_shot")
    assert "Split Shot" in aghs["reason"]["en"]


def test_spectre_after_skadi_bloodthorn_with_an_escape_else_monkey_king_bar():
    escape = _carry("Spectre", ["Phantom Assassin", "Queen of Pain"], ["item_skadi"])
    assert (escape["key"], escape["why"], escape["escape"]) == (
        "bloodthorn",
        "evasion_escape",
        "Queen of Pain",
    )
    plain = _carry("Spectre", ["Windranger", "Axe"], ["item_skadi"])
    assert plain["key"] == "monkey_king_bar"


def test_phantom_assassin_names_nullifier_and_maxes_the_dagger_first():
    item = _carry("Phantom Assassin", ["Windranger", "Axe"])
    assert "Nullifier" in item["reason"]["en"] and "Nullifier" in item["reason"]["uk"]
    skills = plan_skills(plan_for("Phantom Assassin", "carry"))
    assert skills["order"][0] == "phantom_assassin_stifling_dagger"
    assert skills["first_agree"] == 219


# --- wave 3: Drow Ranger, Gyrocopter, Kez, Monkey King, Morphling, Muerta, Naga Siren,
# Sniper, Ursa -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hero", "enemies", "key", "why", "minute"),
    [
        ("Drow Ranger", ["Bristleback", "Axe"], "silver_edge", "break", 20),
        ("Gyrocopter", ["Windranger", "Axe"], "monkey_king_bar", "evasion", 20),
        ("Gyrocopter", ["Huskar", "Axe"], "silver_edge", "break", 20),
        ("Kez", ["Phantom Assassin", "Axe"], "monkey_king_bar", "evasion", 20),
        ("Monkey King", ["Spectre", "Axe"], "silver_edge", "break", 20),
        ("Morphling", ["Windranger", "Axe"], "monkey_king_bar", "evasion", 20),
        ("Muerta", ["Bristleback", "Axe"], "silver_edge", "break", 20),
        ("Naga Siren", ["Phantom Assassin", "Axe"], "bloodthorn", "evasion_bloodthorn", 22),
        ("Sniper", ["Phantom Lancer", "Axe"], "hydras_breath", "illusion_splash", 20),
        ("Ursa", ["Phantom Assassin", "Axe"], "monkey_king_bar", "evasion", 15),
    ],
)
def test_wave_three_counters_come_with_the_plans_reason(hero, enemies, key, why, minute):
    item = _carry(hero, enemies, minute=minute)
    assert (item["key"], item["why"], item["enemy"]) == (key, why, enemies[0])
    assert item["reason"]["en"].startswith(enemies[0])
    assert item["reason"]["uk"].startswith(enemies[0])


@pytest.mark.parametrize(
    ("hero", "enemies"),
    [
        # Multishot, Flak Cannon, Echo Slash, Rip Tide, Battle Fury: no Maelstrom.
        ("Drow Ranger", ["Naga Siren", "Axe"]),
        ("Gyrocopter", ["Phantom Lancer", "Axe"]),
        ("Kez", ["Naga Siren", "Axe"]),
        ("Monkey King", ["Phantom Lancer", "Axe"]),
        ("Naga Siren", ["Phantom Lancer", "Axe"]),
        ("Ursa", ["Chaos Knight", "Axe"]),
        # Marksmanship procs have true strike: no Monkey King Bar for Drow.
        ("Drow Ranger", ["Phantom Assassin", "Axe"]),
        # Abyssal Blade for Ursa; Kez's high-rank games skip Silver Edge.
        ("Ursa", ["Bristleback", "Axe"]),
        ("Kez", ["Huskar", "Axe"]),
    ],
)
def test_wave_three_suppressed_generic_counters(hero, enemies):
    assert _carry(hero, enemies) is None
    assert _carry("Wraith King", enemies) is not None


def test_naga_answers_evasion_once_with_bloodthorn():
    lineup = ["Phantom Assassin", "Axe"]
    assert _carry("Naga Siren", lineup, ["item_bloodthorn"], minute=22) is None
    assert _carry("Wraith King", lineup, ["item_bloodthorn"])["key"] == "monkey_king_bar"


def test_sniper_takes_hydras_breath_or_hurricane_pike_and_keeps_the_30_minute_line():
    from app.next_item import next_listed_item

    plan = plan_for("Sniper", "carry")
    build = plan["build"]
    items = {e["item"]: {"name": e["name"], "cost": 4000, "components": []} for e in build}
    items["mjollnir"]["components"] = ["maelstrom"]
    meta = {"constants": {"items": items, "by_id": {}}, "popularity": {}}
    owned = ["item_power_treads", "item_mask_of_madness", "item_mjollnir"]
    assert next_listed_item(build, meta, owned)["key"] == "hurricane_pike"
    assert next_listed_item(build, meta, [*owned, "item_hydras_breath"])["key"] == "greater_crit"
    # 25:00 rested on 12 games and sat above 30:00: one point.
    assert plan["tempo"]["net_worth"] == [[30, 16800]]
    # No slope from one point: the line holds two minutes, then it is unknown.
    assert [tempo_threshold(plan, m) for m in (29, 30, 32, 33, 50)] == [
        None,
        16800,
        16800,
        None,
        None,
    ]


def test_wave_three_fight_abilities_and_skills():
    # Marksmanship is passive: Gust is the fight ability Drow keeps ready.
    assert plan_for("Drow Ranger", "carry")["fight"] == ["drow_ranger_wave_of_silence"]
    # Kez: his stances share the skill points; the order from Yatoro's and Satanic's games.
    kez = plan_skills(plan_for("Kez", "carry"))
    assert kez["order"] == ["kez_kazurai_katana", "kez_echo_slash", "kez_grappling_claw"]
    assert kez["names"]["kez_kazurai_katana"] == "Kazurai Katana / Shodo Sai"
    assert plan_skills(plan_for("Ursa", "carry"))["order"][0] == "ursa_fury_swipes"
    # Crystalys goes on into Daedalus in the build.
    for hero in ("Drow Ranger", "Morphling"):
        build = [e["item"] for e in plan_for(hero, "carry")["build"]]
        assert "greater_crit" in build and "lesser_crit" not in build


def test_morphling_against_illusions_butterfly_then_hydras_breath():
    lineup = ["Naga Siren", "Axe"]
    first = _carry("Morphling", lineup)
    assert (first["key"], first["why"]) == ("butterfly", "illusion_evasion")
    assert _carry("Morphling", lineup, ["item_butterfly"]) is None  # Hydra's Breath from 22:00
    second = _carry("Morphling", lineup, ["item_butterfly"], minute=22)
    assert (second["key"], second["why"]) == ("hydras_breath", "illusion_splash")
    assert "Butterfly" in second["reason"]["uk"]


def test_drow_buys_hurricane_pike_not_aghanims_and_linkens_only_by_the_situation():
    plan = plan_for("Drow Ranger", "carry")
    build = [e["item"] for e in plan["build"]]
    assert "ultimate_scepter" not in build and "sphere" not in build
    assert build.index("hurricane_pike") == build.index("manta") + 1
    tempo = [e["item"] for e in plan["tempo"]["items"]]
    assert "ultimate_scepter" not in tempo and "sphere" not in tempo


def test_monkey_king_names_battle_fury_against_illusions_as_a_note():
    from app.hero_items import plan_note

    mk = plan_for("Monkey King", "carry")
    assert plan_note(mk, ["Phantom Lancer"], 11) is None
    note = plan_note(mk, ["Phantom Lancer"], 12)
    assert "Battle Fury" in note["reason"]["en"] and "Battle Fury" in note["reason"]["uk"]
    assert _carry("Monkey King", ["Phantom Lancer", "Axe"]) is None  # no item pushed


# --- the carry audit (2026-10-19) ------------------------------------------------------


@pytest.mark.parametrize(
    "hero", ["Spectre", "Monkey King", "Phantom Lancer", "Medusa", "Slark", "Naga Siren"]
)
def test_carries_with_skadi_in_the_build_take_it_against_heavy_healing(hero):
    item = _carry(hero, ["Alchemist", "Crystal Maiden", "Axe"])
    assert (item["key"], item["why"], item["enemy"]) == ("skadi", "healing", "Alchemist")
    assert item["reason"]["uk"].startswith("Alchemist багато лікується")
    assert _carry(hero, ["Alchemist", "Crystal Maiden", "Axe"], ["item_skadi"]) is None
    assert _carry("Wraith King", ["Alchemist", "Crystal Maiden", "Axe"]) is None


def test_naga_and_spectre_get_no_generic_bkb_or_silver_edge():
    for hero in ("Naga Siren", "Spectre"):
        assert _carry(hero, MAGIC_LINEUP) is None
    assert _carry("Spectre", ["Bristleback", "Axe"]) is None
    assert _carry("Wraith King", MAGIC_LINEUP)["key"] == "black_king_bar"


def test_lifestealer_names_rage_and_thin_tempo_points_are_left_out():
    assert plan_for("Lifestealer", "carry")["fight"] == ["life_stealer_rage"]
    assert plan_for("Gyrocopter", "carry")["tempo"]["net_worth"] == [[30, 19700]]
    assert plan_for("Drow Ranger", "carry")["tempo"]["net_worth"][0][0] == 25
    assert plan_for("Spectre", "carry")["tempo"]["net_worth"][0][0] == 25
    # Windranger too: Marksmanship, no Monkey King Bar.
    assert _carry("Drow Ranger", ["Windranger", "Axe"]) is None


def test_an_early_item_sold_for_a_slot_is_not_named_again():
    from app.next_item import next_listed_item

    build = plan_for("Terrorblade", "carry")["build"]
    items = {e["item"]: {"name": e["name"], "cost": 4000, "components": []} for e in build}
    items["falcon_blade"]["cost"] = 1125
    items["power_treads"]["cost"] = 1400
    meta = {"constants": {"items": items, "by_id": {}}, "popularity": {}}
    # Early on, Falcon Blade is next.
    assert next_listed_item(build, meta, ["item_power_treads"])["key"] == "falcon_blade"
    # Sold later for a slot (Manta and Skadi owned): the build goes on.
    late = ["item_manta", "item_aghanims_shard", "item_dragon_lance", "item_skadi"]
    assert next_listed_item(build, meta, late)["key"] == "hurricane_pike"


# --- the mid and offlane wave (2026-10-20) --------------------------------------------


def _core(hero, enemies, position, owned=(), minute=20):
    return situational_item(
        [], list(owned), META, enemies=list(enemies), position=position, minute=minute, hero=hero
    )


@pytest.mark.parametrize(
    "hero", ["Axe", "Legion Commander", "Mars", "Primal Beast", "Slardar", "Timbersaw"]
)
def test_offlaners_with_bkb_in_the_build_take_it_against_a_magic_lineup(hero):
    # Three magic damage heroes: their own BKB earlier, not the generic Pipe.
    item = _core(hero, MAGIC_LINEUP, "offlane")
    assert (item["key"], item["why"], item["enemy"]) == ("black_king_bar", "magic_bkb", "Lion")
    assert item["reason"]["en"].startswith("Lion and other magic damage heroes")
    assert item["reason"]["uk"].startswith("Lion та інші герої з магічною шкодою")
    # Two are no lineup, before minute 14 too early, an owned BKB answers it.
    assert _core(hero, ["Lion", "Lina", "Axe"], "offlane") is None
    assert _core(hero, MAGIC_LINEUP, "offlane", minute=13) is None
    assert _core(hero, MAGIC_LINEUP, "offlane", ["item_black_king_bar"]) is None
    assert _core("Dark Seer", MAGIC_LINEUP, "offlane")["key"] == "pipe"


def test_offlane_pipe_stays_or_goes_by_the_hero():
    centaur = _core("Centaur Warrunner", MAGIC_LINEUP, "offlane")
    assert (centaur["key"], centaur["why"]) == ("pipe", "magic_pipe")
    assert "shields your whole team" in centaur["reason"]["en"]
    for hero in ("Tidehunter", "Bristleback"):
        assert _core(hero, MAGIC_LINEUP, "offlane")["why"] == "magic"  # the generic Pipe
    # Rolling Thunder and Roll Up: debuff immunity and 80% magic resistance.
    assert _core("Pangolier", MAGIC_LINEUP, "offlane") is None


def test_caster_mids_get_no_generic_silver_edge_and_right_click_mids_keep_it():
    lineup = ["Bristleback", "Axe"]
    for hero in ("Queen of Pain", "Storm Spirit", "Puck", "Outworld Destroyer", "Void Spirit"):
        assert _core(hero, lineup, "mid") is None
    for hero in ("Shadow Fiend", "Dragon Knight", "Templar Assassin"):
        assert _core(hero, lineup, "mid")["key"] == "silver_edge"
    # The generic BKB against a magic lineup stays for every mid.
    assert _core("Queen of Pain", MAGIC_LINEUP, "mid")["key"] == "black_king_bar"


def test_ember_and_void_finish_spirit_vessel_against_heavy_healing():
    for hero in ("Ember Spirit", "Void Spirit"):
        item = _core(hero, ["Necrophos", "Axe"], "mid", minute=8)
        assert (item["key"], item["why"]) == ("spirit_vessel", "healing_vessel")
        assert "70%" in item["reason"]["en"] and "70%" in item["reason"]["uk"]
        assert _core(hero, ["Necrophos", "Axe"], "mid", minute=7) is None
        assert _core(hero, ["Necrophos", "Axe"], "mid", ["item_spirit_vessel"], minute=8) is None
    # One plan for a carry Ember too: no Maelstrom against illusions.
    assert plan_for("Ember Spirit", "carry") is plan_for("Ember Spirit", "mid")
    assert _core("Ember Spirit", ["Naga Siren", "Axe"], "carry") is None


def test_dragon_knight_silences_escapes_and_evasion():
    escape = _core("Dragon Knight", ["Queen of Pain", "Axe"], "mid", minute=14)
    assert (escape["key"], escape["enemy"], escape["spell"]) == ("orchid", "Queen of Pain", "Blink")
    assert escape["reason"]["en"] == (
        "Queen of Pain escapes with Blink: Orchid Malevolence silences them for 5 seconds, "
        "so the escape cannot be cast"
    )
    both = _core("Dragon Knight", ["Phantom Assassin", "Queen of Pain"], "mid", minute=20)
    assert (both["key"], both["why"]) == ("bloodthorn", "evasion_bloodthorn")
    # Bloodthorn is built from Orchid: it answers the escape too.
    assert (
        _core("Dragon Knight", ["Phantom Assassin", "Queen of Pain"], "mid", ["item_bloodthorn"])
        is None
    )


def test_shadow_fiend_and_templar_pierce_evasion_with_monkey_king_bar():
    for hero in ("Shadow Fiend", "Templar Assassin"):
        item = _core(hero, ["Windranger", "Axe"], "mid", minute=18)
        assert (item["key"], item["why"]) == ("monkey_king_bar", "evasion_mkb")
        assert _core(hero, ["Windranger", "Axe"], "mid", minute=17) is None
    # Not for a caster mid.
    assert _core("Puck", ["Windranger", "Axe"], "mid", minute=30) is None


def test_mid_and_offlane_skill_builds_read_the_live_ability_keys():
    # Shadowraze is logged under three ids; the plan keeps the one the app aliases to.
    sf = plan_skills(plan_for("Shadow Fiend", "mid"))
    assert sf["order"] == ["nevermore_shadowraze1", "nevermore_dark_lord", "nevermore_frenzy"]
    # 7.41 abilities only (Wyrm's Wrath, Objurgation), not 7.40's Dragon Blood or Essence Flux.
    assert plan_skills(plan_for("Dragon Knight", "mid"))["order"][2] == "dragon_knight_wyrms_wrath"
    assert (
        "obsidian_destroyer_objurgation"
        in plan_skills(plan_for("Outworld Destroyer", "mid"))["order"]
    )
    # Void Spirit: Power Treads or Phase Boots, not both.
    build = plan_for("Void Spirit", "mid")["build"]
    phase = next(e for e in build if e["item"] == "phase_boots")
    assert phase["unless"] == ["power_treads"]


def test_a_plan_without_rules_still_needs_something_to_say():
    plan = dict(plan_for("Outworld Destroyer", "mid"))
    assert plan["rules"] == [] and validate(plan) is plan
    with pytest.raises(ValueError, match="nothing else"):
        validate(
            {
                k: v
                for k, v in plan.items()
                if k not in ("build", "build_basis", "skills", "tempo", "suppress")
            }
        )
    rule = plan_for("Axe", "offlane")["rules"][0]
    for count in (0, 6, True, "3"):
        with pytest.raises(ValueError, match="count"):
            validate({**plan_for("Axe", "offlane"), "rules": [{**rule, "count": count}]})


@pytest.mark.parametrize("hero", ["Queen of Pain", "Puck", "Void Spirit", "Storm Spirit"])
def test_mids_block_phantom_strike_and_charge_with_linkens_not_pounce(hero):
    for jumper, spell in (
        ("Phantom Assassin", "Phantom Strike"),
        ("Spirit Breaker", "Charge of Darkness"),
    ):
        item = _core(hero, [jumper, "Axe"], "mid", minute=18)
        assert (item["key"], item["why"], item["spell"]) == ("sphere", "jumper_linken", spell)
        assert item["reason"]["en"] == (
            f"{jumper} jumps on you with {spell}: Linken's Sphere blocks it, once every 14 seconds"
        )
        assert _core(hero, [jumper, "Axe"], "mid", minute=17) is None
        assert _core(hero, [jumper, "Axe"], "mid", ["item_sphere"], minute=18) is None
    # Pounce is not cast on the target: Linken's does nothing.
    assert _core(hero, ["Slark", "Axe"], "mid", minute=30) is None


def test_axe_levels_battle_hunger_second():
    axe = plan_skills(plan_for("Axe", "offlane"))
    assert axe["order"] == ["axe_counter_helix", "axe_battle_hunger", "axe_berserkers_call"]
    assert axe["opening"]["name"] == "axe_battle_hunger"
