"""Every hero item plan (data/heroes/item_plans) passes the same checks, so a new
plan is tested the moment it lands: each rule can fire and is answered by its
own items, its reason renders in both languages on every screen, and every
supported hero has a plan or is listed as pending (data/heroes/plan_coverage.json)."""

from __future__ import annotations

import json

import pytest

from app.advice_i18n import translate_uk
from app.config import DATA_DIR
from app.hero_items import format_reason, groups, hero_rows, load_plans, placeholders
from app.post_laning_coach import _next_item_copy
from app.schemas import _SUPPORTED_HERO_LOOKUP
from app.situational_items import situational_item

PLANS = sorted(load_plans().values(), key=lambda plan: plan["hero"])
RULES = [(plan, rule) for plan in PLANS for rule in plan["rules"]]


def _rule_id(param):
    plan, rule = param
    return f"{plan['hero']}:{rule['id']}"


def _lineup(plan, rule):
    """Enemies that make `rule` the first of its family; None when none do."""
    known = groups()
    others = known.get(rule.get("also"), {}) if rule.get("also") else {None: None}
    for enemy in sorted(known[rule["enemy"]]):
        for escape in sorted(others, key=str):
            lineup = [enemy] + ([escape] if escape and escape != enemy else [])
            if rule.get("also") and len(lineup) < 2:
                continue
            rows = hero_rows(plan, lineup, 60)
            first = next((r for r in rows if rule["item"] in r["family_items"]), None)
            if first and first["key"] == rule["item"]:
                return lineup
    return None


@pytest.mark.parametrize("pair", RULES, ids=[_rule_id(p) for p in RULES])
def test_every_rule_can_fire_and_its_family_answers_it(pair):
    plan, rule = pair
    lineup = _lineup(plan, rule)
    assert lineup, "no lineup makes this rule the first of its family (shadowed?)"
    position = plan["positions"][0]
    item = situational_item(
        [], [], None, enemies=lineup, position=position, minute=60, hero=plan["hero"]
    )
    assert item is not None
    family = [r["item"] for r in plan["rules"] if r["family"] == rule["family"]]
    # Its minute gate holds it back before.
    if rule["minute"] > 0:
        early = situational_item(
            [],
            [],
            None,
            enemies=lineup,
            position=position,
            minute=rule["minute"] - 1,
            hero=plan["hero"],
        )
        assert early is None or early["key"] != rule["item"]
    # Owning any item of the family answers it.
    owned = [f"item_{key}" for key in family]
    later = situational_item(
        [], owned, None, enemies=lineup, position=position, minute=60, hero=plan["hero"]
    )
    assert later is None or later["key"] not in family


@pytest.mark.parametrize("pair", RULES, ids=[_rule_id(p) for p in RULES])
def test_every_reason_renders_in_both_languages(pair):
    plan, rule = pair
    values = {name: f"<{name}>" for name in placeholders(rule["reason"]["en"])}
    filled = format_reason(rule["reason"], **values)
    assert "{" not in filled["en"] and "{" not in filled["uk"]
    item = {
        "key": rule["item"],
        "name": rule["name"],
        "why": rule["why"],
        "count": 0,
        "gold_left": None,
        "reason": filled,
    }
    state = {"minute": 30, "gold": 0, "extra_context": {"next_item": item, "gpm": 600}}
    _, reason = _next_item_copy(state, state["extra_context"])
    assert reason == filled["en"] + "."
    assert translate_uk(reason) == filled["uk"] + "."


@pytest.mark.parametrize("plan", PLANS, ids=[p["hero"] for p in PLANS])
def test_the_tempo_reason_renders_too(plan):
    tempo = plan.get("tempo")
    if not tempo:
        pytest.skip("no tempo build")
    filled = format_reason(tempo["reason"], item="<item>", net_worth=12345)
    item = {
        "key": "x",
        "name": "<item>",
        "why": "tempo",
        "count": 12345,
        "gold_left": None,
        "reason": filled,
    }
    state = {"minute": 30, "gold": 0, "extra_context": {"next_item": item, "gpm": 600}}
    _, reason = _next_item_copy(state, state["extra_context"])
    assert translate_uk(reason) == filled["uk"] + "."


def test_every_supported_hero_has_a_plan_or_is_pending():
    coverage = json.loads((DATA_DIR / "heroes" / "plan_coverage.json").read_text(encoding="utf-8"))
    pending = {hero for heroes in coverage["pending"].values() for hero in heroes}
    planned = {plan["hero"] for plan in PLANS}
    supported = set(_SUPPORTED_HERO_LOOKUP.values())
    assert not planned & pending, "a hero with a plan is still listed as pending"
    assert supported <= planned | pending, sorted(supported - planned - pending)
    assert pending <= supported, sorted(pending - supported)


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p["hero"])
def test_skill_build_names_its_abilities(plan):
    skills = plan.get("skills")
    if not skills:
        pytest.skip("no skill build")
    named = skills.get("names") or {}
    for key in [*skills["order"], (skills.get("opening") or {}).get("name")]:
        if key:
            assert named.get(key), f"{key} has no in-game name"
