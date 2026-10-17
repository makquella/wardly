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
        [], [], META, enemies=lineup, position="carry", minute=20, hero="Medusa"
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
    medusa = situational_item(
        [], [], META, enemies=lineup, position="carry", minute=20, hero="Medusa"
    )
    assert medusa["key"] == "monkey_king_bar"
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

    assert PLAYER_SERVICE.skill_build("Medusa") is None  # nothing cached in the tests


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
    ],
)
def test_wave_one_suppressed_generic_counters(hero, enemies):
    assert _carry(hero, enemies) is None
    # A hero without a plan keeps the generic counter.
    assert _carry("Medusa", enemies) is not None


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
    assert plan_for("Luna", "carry").get("tempo") is None
