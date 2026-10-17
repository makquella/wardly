"""Which ability to level next, from how pro players level the hero
(app/skill_build.py): the maxing order of recent pro games, the live skill tip
and the game plan line."""

from __future__ import annotations

import copy
from typing import Any

from app.game_plan import build_game_plan
from app.opendota import OpenDotaClient
from app.player_api import PLAYER_SERVICE
from app.skill_build import next_skill, skill_order, upgrade_names
from app.skill_tips import UNSPENT_WAIT, SkillTips, read_skills

FURY, WARD, DANCE, OMNI = (
    "juggernaut_blade_fury",
    "juggernaut_healing_ward",
    "juggernaut_blade_dance",
    "juggernaut_omni_slash",
)
TALENT = "special_bonus_unique_juggernaut_3"
# Blade Fury maxed first, then Blade Dance, Healing Ward last; the ultimate and
# talents never reach a 4th level.
GAME = [
    FURY,
    DANCE,
    FURY,
    DANCE,
    FURY,
    OMNI,
    FURY,
    DANCE,
    DANCE,
    TALENT,
    WARD,
    OMNI,
    WARD,
    WARD,
    WARD,
]
NAMES = {FURY: "Blade Fury", DANCE: "Blade Dance", WARD: "Healing Ward", OMNI: "Omnislash"}
DATA = {"orders": [GAME, GAME, GAME[:9] + [WARD, WARD, WARD, WARD]], "names": NAMES, "talents": {}}


def test_the_maxing_order_of_pro_games():
    build = skill_order(DATA)
    assert build["order"] == [FURY, DANCE, WARD]
    assert build["names"][FURY] == "Blade Fury"
    assert build["first_agree"] == 3 and build["games"] == 3
    assert skill_order({"orders": [GAME, GAME]}) is None  # two games are not a pattern
    assert skill_order(None) is None
    assert skill_order({"orders": [[TALENT], [TALENT], [TALENT]]}) is None


def test_shadowraze_is_one_skill_in_three_slots():
    raze = ["nevermore_shadowraze1", "nevermore_shadowraze2", "nevermore_shadowraze3"]
    ids = {"1": raze[0], "2": raze[1], "3": raze[2], "4": "nevermore_dark_lord"}
    game = upgrade_names([3, 4, 2, 4, 1, 4, 3, 4], ids)
    assert game.count("nevermore_shadowraze1") == 4
    build = skill_order({"orders": [game] * 3})
    assert build["order"] == ["nevermore_shadowraze1", "nevermore_dark_lord"]
    assert upgrade_names([9, "x"], ids) == [] and upgrade_names(None, ids) == []


def test_the_next_point_follows_the_order_within_the_level_caps():
    build = skill_order(DATA)
    # Level 3: Blade Fury 2 (the cap is 2) → the next in the order.
    assert next_skill(build, {FURY: 2, DANCE: 0, WARD: 0}, 3) == DANCE
    assert next_skill(build, {FURY: 1, DANCE: 1, WARD: 0}, 3) == FURY
    assert next_skill(build, {FURY: 4, DANCE: 4, WARD: 3}, 16) == WARD
    assert next_skill(build, {FURY: 4, DANCE: 4, WARD: 4}, 20) is None
    # Another hero's order (a random or a swap): nothing to say.
    assert next_skill(build, {"axe_berserkers_call": 1}, 3) is None
    assert next_skill(None, {FURY: 1}, 3) is None


def _payload(level, fury, dance, ward, ult=0):
    abilities = {
        "ability0": {"name": FURY, "level": fury, "ultimate": False},
        "ability1": {"name": WARD, "level": ward, "ultimate": False},
        "ability2": {"name": DANCE, "level": dance, "ultimate": False},
        "ability3": {"name": OMNI, "level": ult, "ultimate": True},
    }
    return {"hero": {"level": level}, "abilities": abilities}


def test_the_skill_tip_names_the_ability():
    build = skill_order(DATA)
    tips = SkillTips()
    tips.observe(100, read_skills(_payload(2, 1, 1, 0)))
    tips.observe(110, read_skills(_payload(3, 1, 1, 0)))
    hint = tips.tip(110 + UNSPENT_WAIT, "uk", alive=True, build=build)
    assert hint["title"] == "Вкладіть очко в Blade Fury"
    assert hint["hint"] == (
        "Порядок прокачки в про-гравців на цьому герої: Blade Fury → Blade Dance → Healing Ward."
    )
    # 0.49: the card draws the ability's icon and the order as icons.
    assert hint["icon"] == FURY
    assert [step["key"] for step in hint["order"]] == [FURY, DANCE, WARD]
    assert [step["name"] for step in hint["order"]] == ["Blade Fury", "Blade Dance", "Healing Ward"]
    # Without the pro order: the plain line.
    assert tips.tip(110 + UNSPENT_WAIT, "en", alive=True)["title"] == "Unspent skill point"


def test_the_ultimate_takes_its_in_game_name_from_the_build():
    build = skill_order(DATA)
    tips = SkillTips()
    tips.observe(300, read_skills(_payload(5, 3, 1, 1)))
    tips.observe(320, read_skills(_payload(6, 3, 1, 1)))
    hint = tips.tip(320 + UNSPENT_WAIT, "en", alive=True, build=build)
    assert hint["title"] == "Learn your ultimate" and "Omnislash" in hint["hint"]
    assert hint["icon"] == OMNI and "order" not in hint


def test_the_game_plan_names_the_pro_order():
    plan = build_game_plan(
        hero="Juggernaut", history=[], all_recent=[], meta=None, lang="uk", skills=skill_order(DATA)
    )
    assert "Прокачка в про: спершу Blade Fury, потім Blade Dance" in plan["lines"]
    plan = build_game_plan(
        hero="Juggernaut", history=[], all_recent=[], meta=None, lang="en", skills=None
    )
    assert not any("Pros max" in line for line in (plan or {}).get("lines", []))


class _Session:
    """requests.Session stand-in answering by path."""

    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.paths: list[str] = []

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        path = "/" + url.split("/api/", 1)[1]
        self.paths.append(path)
        body = self.routes.get(path)

        class _Response:
            status_code = 200 if body is not None else 404

            def json(self) -> Any:
                return copy.deepcopy(body)

        return _Response()


def test_the_client_reads_recent_pro_games():
    ids = {"1": FURY, "2": DANCE, "3": WARD, "4": OMNI, "5": TALENT}
    upgrades = [1, 2, 1, 2, 1, 4, 1, 2, 2, 5, 3]
    player = {"hero_id": 8, "ability_upgrades_arr": upgrades}
    routes = {
        "/constants/ability_ids": ids,
        "/heroes/8/matches": [{"match_id": 10}, {"match_id": 11}, {"match_id": 12}],
        "/matches/10": {"players": [{"hero_id": 1}, player]},
        # 11: not on OpenDota → skipped
        "/matches/12": {"players": [{"hero_id": 8, "ability_upgrades_arr": None}]},
        "/constants/abilities": {
            FURY: {"dname": "Blade Fury"},
            TALENT: {"dname": "+{s:value} Attack Speed"},
        },
        "/constants/hero_abilities": {
            "npc_dota_hero_juggernaut": {"talents": [{"name": TALENT, "level": 1}]}
        },
    }
    session = _Session(routes)
    data = OpenDotaClient(session=session, min_interval=0).pro_skill_orders(8)
    assert data["orders"] == [
        [FURY, DANCE, FURY, DANCE, FURY, OMNI, FURY, DANCE, DANCE, TALENT, WARD]
    ]
    # A talent of the hero is named without its placeholder number, with its row.
    assert data["names"] == {FURY: "Blade Fury", TALENT: "Attack Speed"}
    assert data["talents"] == {TALENT: 10}


def test_the_service_fetches_once_and_reads_the_cache(monkeypatch):
    service = PLAYER_SERVICE
    calls = []

    class _Client:
        def pro_skill_orders(self, hero_id):
            calls.append(hero_id)
            return DATA

    # A hero without an item plan (data/heroes/item_plans): the pro games.
    monkeypatch.setattr(service, "client", _Client())
    assert service.skill_build("Sven") is None  # nothing cached yet: fetched
    service.jobs.run_pending(until=float("inf"))
    assert calls == [18]
    service._plans.clear()
    assert service.skill_build("Sven")["order"] == [FURY, DANCE, WARD]
    service.jobs.run_pending(until=float("inf"))
    assert calls == [18]  # fresh: not fetched again
    assert service.skill_build("Not A Hero") is None


IDS = {"1": FURY, "2": DANCE, "3": WARD, "4": OMNI, "5": TALENT}
REVIEW_DATA = {**DATA, "ids": IDS}


def test_the_review_compares_the_first_skill_maxed():
    from app.skill_build import review_skills

    # Healing Ward maxed first (3 ×4 before anything else).
    mine = [3, 1, 3, 2, 3, 4, 3, 1, 1, 5, 1]
    block = review_skills(mine, REVIEW_DATA)
    assert block["yours"] == "Healing Ward" and block["pro"] == "Blade Fury"
    assert block["same"] is False and block["agree"] == 3 and block["games"] == 3
    # 0.49: the game names for the card's icons, in the order's order.
    assert block["yours_key"] == WARD and block["keys"][0] == FURY
    assert len(block["keys"]) == len(block["order"])
    same = review_skills([1, 2, 1, 2, 1, 4, 1, 2, 2], REVIEW_DATA)
    assert same["same"] is True
    assert block["in_order"] is True and same["in_order"] is True
    # Pros rarely max Healing Ward (1 game of 3): not in their order, still named.
    rare = {**REVIEW_DATA, "orders": [GAME[:10]] * 2 + [GAME]}
    block = review_skills(mine, rare)
    assert block["yours"] == "Healing Ward" and block["in_order"] is False
    assert "Healing Ward" not in block["order"]
    assert review_skills([1, 2, 1], REVIEW_DATA) is None  # too short
    assert review_skills(mine, DATA) is None  # no ids: the player's upgrades unreadable
    assert review_skills(mine, None) is None
    # The pros split on the first skill: nothing to say.
    dance_first = [DANCE] * 4 + GAME
    split = {**REVIEW_DATA, "orders": [GAME, GAME, dance_first, dance_first]}
    assert review_skills(mine, split) is None


def test_the_review_finding_and_its_texts():
    from app.analysis_texts import render_finding
    from app.post_match_analysis import analyze_match

    facts = {
        "match_id": 1,
        "hero": "Juggernaut",
        "hero_id": 8,
        "duration": 2400,
        "win": False,
        "sources": ["opendota"],
        "skill_upgrades": [3, 1, 3, 2, 3, 4, 3, 1, 1, 5, 1],
    }
    analysis = analyze_match(facts, meta={"skills": REVIEW_DATA})
    assert analysis["skills"]["yours"] == "Healing Ward"
    assert "skill_first_max" in analysis["problems"]
    finding = next(f for f in analysis["improvements"] if f["id"] == "skill_first_max")
    text = render_finding(finding, "uk")
    assert text["title"] == "Інший порядок прокачки"
    assert "Healing Ward" in text["text"] and "Blade Fury (3 з 3" in text["text"]
    assert "Blade Fury" in render_finding(finding, "en")["drill"]
    # Without the pro data: no block, no finding.
    plain = analyze_match(facts, meta=None)
    assert plain["skills"] is None and "skill_first_max" not in plain["problems"]


def test_the_trim_keeps_the_skill_order():
    from app.match_facts import facts_from_opendota
    from app.opendota import trim_match

    raw = {
        "match_id": 5,
        "players": [{"account_id": 7, "hero_id": 8, "ability_upgrades_arr": [1, 2, 1]}],
    }
    trimmed = trim_match(raw, 7)
    assert trimmed["players"][0]["ability_upgrades_arr"] == [1, 2, 1]
    assert facts_from_opendota(trimmed)["skill_upgrades"] == [1, 2, 1]


def test_invokers_orbs_get_no_order():
    quas, wex, exort = "invoker_quas", "invoker_wex", "invoker_exort"
    game = [quas, exort] * 2 + [quas] * 5 + [exort] * 5 + [wex] * 4
    assert skill_order({"orders": [game] * 3}) is None
    # An order whose ability already went past rank 4 (a rework, an odd hero): silence.
    build = skill_order(DATA)
    assert next_skill(build, {FURY: 5, DANCE: 1, WARD: 1}, 12) is None
    # An innate levelled high does not silence the order.
    assert next_skill(build, {FURY: 1, DANCE: 1, WARD: 0, "juggernaut_innate": 9}, 3) == FURY


LIFESTEAL, CRIT = "special_bonus_unique_juggernaut_lifesteal", "special_bonus_unique_juggernaut_4"


def test_the_talent_the_pros_take_on_each_row():
    from app.skill_build import talent_label

    assert talent_label("-{s:bonus_AbilityCooldown}s Blade Fury Cooldown") == "Blade Fury Cooldown"
    assert talent_label("+{s:bonus_heal}% Healing Ward Heal") == "Healing Ward Heal"
    assert talent_label("+15% Blade Dance Crit Damage") == "+15% Blade Dance Crit Damage"
    assert talent_label("{s:value}") == ""
    games = [GAME + [LIFESTEAL], GAME + [LIFESTEAL], GAME + [CRIT], GAME + [LIFESTEAL]]
    data = {
        "orders": games,
        "names": {**NAMES, LIFESTEAL: "Blade Dance Lifesteal", CRIT: "+15% Crit"},
        "talents": {LIFESTEAL: 10, CRIT: 10, TALENT: 15},
    }
    talents = skill_order(data)["talents"]
    assert talents == {
        10: {"name": LIFESTEAL, "label": "Blade Dance Lifesteal", "picked": 3, "games": 4}
    }  # TALENT has no name → not offered; a 2–2 split would not be either
    split = {**data, "orders": [GAME + [LIFESTEAL]] * 2 + [GAME + [CRIT]] * 2}
    assert skill_order(split)["talents"] == {}


def test_the_talent_tip_names_the_pros_pick():
    data = {
        "orders": [GAME + [LIFESTEAL]] * 3,
        "names": {**NAMES, LIFESTEAL: "Blade Dance Lifesteal"},
        "talents": {LIFESTEAL: 10},
    }
    build = skill_order(data)
    payload = _payload(9, 4, 4, 0, ult=1)
    payload["hero"].update({f"talent_{i}": False for i in range(1, 9)})
    tips = SkillTips()
    tips.observe(900, read_skills(payload))
    payload = _payload(10, 4, 4, 0, ult=1)
    payload["hero"].update({f"talent_{i}": False for i in range(1, 9)})
    tips.observe(910, read_skills(payload))
    hint = tips.tip(910 + UNSPENT_WAIT, "uk", alive=True, build=build)
    assert hint["title"] == "Оберіть талант"
    assert hint["hint"] == (
        "Талант 10-го рівня: про-гравці на цьому герої беруть «Blade Dance Lifesteal» (3 з 3)."
    )


def test_data_cached_before_the_talents_is_fetched_again(monkeypatch):
    service = PLAYER_SERVICE
    calls = []

    class _Client:
        def pro_skill_orders(self, hero_id):
            calls.append(hero_id)
            return DATA

    monkeypatch.setattr(service, "client", _Client())
    old = {key: value for key, value in DATA.items() if key != "talents"}
    service.store.cache_set("opendota:pro_skills:8", old)
    assert service.skill_build("Juggernaut")["order"] == [FURY, DANCE, WARD]  # used meanwhile
    service.jobs.run_pending(until=float("inf"))
    assert calls == [8]
    assert "talents" in service.store.cache_get("opendota:pro_skills:8")


def test_a_game_counts_once_per_talent_row():
    # Late in a game the other talent of the row is taken too: still one game.
    games = [GAME + [LIFESTEAL, CRIT]] * 5
    data = {
        "orders": games,
        "names": {**NAMES, LIFESTEAL: "Blade Dance Lifesteal", CRIT: "+15% Crit"},
        "talents": {LIFESTEAL: 10, CRIT: 10},
    }
    assert skill_order(data)["talents"][10] == {
        "name": LIFESTEAL,
        "label": "Blade Dance Lifesteal",
        "picked": 5,
        "games": 5,
    }


def test_talent_rows_given_as_hero_levels_are_read_too():
    ids = {"1": FURY, "5": TALENT}
    routes = {
        "/constants/ability_ids": ids,
        "/heroes/8/matches": [{"match_id": 10}],
        "/matches/10": {"players": [{"hero_id": 8, "ability_upgrades_arr": [1, 5]}]},
        "/constants/abilities": {TALENT: {"dname": "+20 Attack Speed"}},
        "/constants/hero_abilities": {
            "npc_dota_hero_juggernaut": {
                "talents": [{"name": TALENT, "level": 15}, {"name": "x", "level": 7}]
            }
        },
    }
    data = OpenDotaClient(session=_Session(routes), min_interval=0).pro_skill_orders(8)
    assert data["talents"] == {TALENT: 15}


def test_the_first_point_names_the_pros_opening_skill():
    build = skill_order(DATA)
    # All three games open with Blade Fury.
    assert build["opening"] == {"name": FURY, "agree": 3, "games": 3}
    ward_first = [WARD, *GAME[1:10], FURY, *GAME[11:]]
    split = {**DATA, "orders": [GAME, [DANCE, FURY, *GAME[2:]], ward_first]}
    assert skill_order(split)["opening"] is None  # no 60 % agreement
    tips = SkillTips()
    tips.observe(-80, read_skills(_payload(1, 0, 0, 0)))  # level 1, nothing learned
    hint = tips.tip(-80 + UNSPENT_WAIT, "uk", alive=True, build=build)
    assert hint["title"] == "Перше очко: Blade Fury"
    assert hint["hint"] == "Про-гравці на цьому герої починають з Blade Fury (3 з 3 ігор)."
    assert hint["icon"] == FURY
    # Without pro data: the plain unspent-point line.
    assert tips.tip(-80 + UNSPENT_WAIT, "en", alive=True)["title"] == "Unspent skill point"


def test_the_skill_tip_shows_before_the_horn():
    from app.map_hints import RoleTips, map_hint

    skill = {"kind": "tip", "id": "skill-point@1", "title": "First point", "hint": "x"}
    tips = RoleTips()
    base = {"alive": True, "has_ward": None, "lang": "en"}
    assert map_hint(-60, None, tips, skill=skill, **base) is skill
    assert map_hint(-60, "carry", tips, **base) is None
    assert map_hint(None, "carry", tips, skill=skill, **base) is None


def test_a_hard_lane_puts_an_early_point_in_the_escape():
    strike, blink, scream, wave = (
        "queenofpain_shadow_strike",
        "queenofpain_blink",
        "queenofpain_scream_of_pain",
        "queenofpain_sonic_wave",
    )
    game = [strike, scream, scream, strike, scream, wave, scream, strike, strike, blink]
    names = {strike: "Shadow Strike", blink: "Blink", scream: "Scream Of Pain", wave: "Sonic Wave"}
    build = skill_order({"orders": [game] * 3, "names": names, "talents": {}})

    def payload(level, blink_level):
        abilities = {
            "ability0": {"name": strike, "level": 1, "ultimate": False},
            "ability1": {"name": blink, "level": blink_level, "ultimate": False},
            "ability2": {"name": scream, "level": 1, "ultimate": False},
            "ability3": {"name": wave, "level": 0, "ultimate": True},
        }
        return {
            "hero": {"level": level, "name": "npc_dota_hero_queenofpain"},
            "abilities": abilities,
        }

    tips = SkillTips()
    tips.observe(100, read_skills(payload(2, 0)))
    tips.observe(110, read_skills(payload(3, 0)))
    at = 110 + UNSPENT_WAIT
    calm = tips.tip(at, "en", alive=True, build=build, hero="Queen of Pain")
    assert calm["title"] == "Put the point in Scream Of Pain"  # the pro order
    hint = tips.tip(at, "uk", alive=True, build=build, hero="Queen of Pain", lane_pressure=True)
    assert hint["title"] == "Вкладіть очко в Blink"
    assert hint["hint"].startswith("Важка лінія: перше очко в Blink допоможе вижити.")
    assert hint["icon"] == blink
    # Blink already learned, or past level 7: the pro order again.
    learned = SkillTips()
    learned.observe(100, read_skills(payload(2, 1)))
    learned.observe(110, read_skills(payload(3, 1)))
    assert (
        learned.tip(at, "en", alive=True, build=build, hero="Queen of Pain", lane_pressure=True)[
            "title"
        ]
        != "Put the point in Blink"
    )
    late = SkillTips()
    late.observe(100, read_skills(payload(7, 0)))
    late.observe(110, read_skills(payload(8, 0)))
    assert (
        late.tip(at, "en", alive=True, build=build, hero="Queen of Pain", lane_pressure=True)[
            "title"
        ]
        != "Put the point in Blink"
    )


def test_lane_pressure_signals():
    from app.live_hints import lane_pressure

    calm = ({"hp_percent": 90}, {"clock_time": 300, "deaths": 0})
    assert lane_pressure(*calm, None) is False
    assert lane_pressure({"hp_percent": 45}, {"clock_time": 300, "deaths": 0}, None) is True
    assert lane_pressure({"hp_percent": 90}, {"clock_time": 300, "deaths": 1}, None) is True
    assert lane_pressure(*calm, {"kind": "hard"}) is True
    assert lane_pressure(*calm, {"kind": None, "pace": {}}) is False
    assert lane_pressure({"hp_percent": 20}, {"clock_time": 700, "deaths": 2}, None) is False
