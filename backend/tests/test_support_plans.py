"""The 25 support hero plans against their scenarios (tests/support_plan_scenarios.json,
written with the plans, docs/HERO_ITEM_PLANS.md «Support wave»): for an enemy lineup,
a minute and the items owned, the counter a support's plan names (or none: the
build or the save item tip speaks then), and the note it shows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.hero_items import load_plans, plan_for, plan_note
from app.situational_items import situational_item

SCENARIOS = json.loads(
    (Path(__file__).parent / "support_plan_scenarios.json").read_text(encoding="utf-8")
)


def _id(case):
    return f"{case['hero']}:{'+'.join(case['enemies'])}@{case['minute']}"


@pytest.mark.parametrize("case", SCENARIOS, ids=[_id(c) for c in SCENARIOS])
def test_a_support_plan_names_its_counter(case):
    item = situational_item(
        [],
        case["owned"],
        None,
        enemies=case["enemies"],
        position="support",
        minute=case["minute"],
        hero=case["hero"],
    )
    assert (item["key"] if item else None) == case["expect"], case["why"]
    if "note" in case:
        note = plan_note(plan_for(case["hero"], "support"), case["enemies"], case["minute"])
        assert note is not None and note["id"] == case["note"], case["why"]


def test_every_support_plan_has_scenarios_and_no_tempo():
    supports = {p["hero"] for p in load_plans().values() if p["positions"] == ["support"]}
    assert len(supports) == 25
    assert supports <= {case["hero"] for case in SCENARIOS}
    for plan in load_plans().values():
        if "support" in plan["positions"]:
            assert "tempo" not in plan


def test_a_support_rule_never_reaches_a_core_of_the_same_hero():
    # A support plan is for the support position only: as a core the hero gets
    # the generic counters (Spirit Breaker, Mirana are played as cores too).
    assert plan_for("Spirit Breaker", "offlane") is None
    assert plan_for("Hoodwink", "support") is not None
    item = situational_item(
        [],
        [],
        None,
        enemies=["Queen of Pain", "Storm Spirit"],
        position="carry",
        minute=30,
        hero="Hoodwink",
    )
    assert item is None or item["key"] != "rod_of_atos"
