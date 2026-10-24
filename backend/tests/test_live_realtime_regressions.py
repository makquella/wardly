"""Realtime coach regressions: state, life cycle, freshness and executability.

Every payload here is SYNTHETIC, in the shape of real Wardly match recordings
(the GSI `hero`/`player`/`abilities`/`items`/`minimap` blocks as Dota sends
them). Where a scenario copies the sequence of a real moment, the comment names
it; the recordings themselves stay on the player's computer (match_records.py).
The tests check invariants (no card / a card of this kind / the numbers of this
snapshot), not the full wording of a sentence.
"""

from __future__ import annotations

import copy
import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.action_feedback import used_consumables
from app.advice_validity import advice_basis, withdraw_reason
from app.buyback_tracker import BuybackTracker
from app.live_tools import low_hp_copy, low_mana_reason
from app.match_memory import MATCH_MEMORY
from app.post_laning_coach import build_post_laning_advice
from app.status_source import StatusWatch

MATCH = "9100000001"
PL = "npc_dota_hero_phantom_lancer"

CLOCKED = (
    "app.scheduler.state_utils",
    "app.advice_scheduler",
    "app.main",
    "app.match_memory",
    "app.gsi_snapshot",
    "app.advice_ux_policy",
    "app.coach_summary",
)


@pytest.fixture
def clock(monkeypatch):
    """Wall time under the test's control (MatchMemory HP windows and the
    scheduler read datetime.now): `clock["t"]` seconds after a fixed start."""
    now = {"t": 0.0}
    base = datetime(2026, 1, 1, tzinfo=UTC)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            moment = base + timedelta(seconds=now["t"])
            return moment if tz else moment.replace(tzinfo=None)

    for name in CLOCKED:
        module = importlib.import_module(name)
        if getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", FakeDateTime)
    return now


def _abilities(**cooldowns: Any) -> dict[str, Any]:
    """PL's bar: Spirit Lance, Doppelganger (doppelwalk), passives; `w=None`
    leaves W unlearned."""
    w = cooldowns.get("w", 0)
    block = {
        "ability0": {
            "name": "phantom_lancer_spirit_lance",
            "level": 4,
            "can_cast": True,
            "passive": False,
            "ability_active": True,
            "cooldown": cooldowns.get("q", 0),
            "ultimate": False,
        },
        "ability1": {
            "name": "phantom_lancer_doppelwalk",
            "level": 0 if w is None else 3,
            "can_cast": w == 0,
            "passive": False,
            "ability_active": True,
            "cooldown": 0 if w is None else w,
            "ultimate": False,
        },
        "ability2": {
            "name": "phantom_lancer_phantom_edge",
            "level": 3,
            "can_cast": False,
            "passive": True,
            "ability_active": True,
            "cooldown": 0,
            "ultimate": False,
        },
    }
    return block


def _items(**slots: Any) -> dict[str, Any]:
    items: dict[str, Any] = {}
    for index in range(9):
        items[f"slot{index}"] = {"name": "empty"}
    for index in range(6):
        items[f"stash{index}"] = {"name": "empty"}
    items["teleport0"] = {"name": "item_tpscroll", "can_cast": True, "cooldown": 0, "charges": 1}
    for slot, value in slots.items():
        items[slot] = value
    return items


def manta(cooldown: float = 0) -> dict[str, Any]:
    return {"name": "item_manta", "can_cast": cooldown == 0, "cooldown": cooldown, "passive": False}


def wand(charges: int) -> dict[str, Any]:
    return {
        "name": "item_magic_wand",
        "can_cast": True,
        "cooldown": 0,
        "passive": False,
        "charges": charges,
    }


def tango(charges: int) -> dict[str, Any]:
    return {
        "name": "item_tango",
        "can_cast": True,
        "cooldown": 0,
        "passive": False,
        "charges": charges,
    }


def gsi(
    clock_time: int,
    *,
    hero: str = PL,
    hp: int = 1400,
    max_hp: int = 1400,
    mana: int = 400,
    max_mana: int = 400,
    alive: bool = True,
    deaths: int = 2,
    kills: int = 3,
    stunned: bool = False,
    hexed: bool = False,
    silenced: bool = False,
    debuff: bool | None = False,
    abilities: dict[str, Any] | None = None,
    items: dict[str, Any] | None = None,
    gold: int = 600,
    bb_cost: int = 900,
    xy: tuple[int, int] = (-5000, -5000),
    minimap: dict[str, Any] | None = None,
    match: str = MATCH,
    respawn: int = 0,
    level: int = 14,
) -> dict[str, Any]:
    hero_block: dict[str, Any] = {
        "xpos": xy[0],
        "ypos": xy[1],
        "id": 12,
        "name": hero,
        "level": level,
        "alive": alive,
        "respawn_seconds": respawn,
        "buyback_cost": bb_cost,
        "buyback_cooldown": 0,
        "health": hp,
        "max_health": max_hp,
        "health_percent": round(hp / max_hp * 100),
        "mana": mana,
        "max_mana": max_mana,
        "mana_percent": round(mana / max_mana * 100),
        "silenced": silenced,
        "stunned": stunned,
        "disarmed": False,
        "magicimmune": False,
        "hexed": hexed,
        "muted": False,
        "break": False,
        "smoked": False,
    }
    if debuff is not None:
        hero_block["has_debuff"] = debuff
    return {
        "provider": {"name": "Dota 2", "appid": 570, "version": 48},
        "map": {
            "name": "start",
            "matchid": match,
            "game_time": clock_time + 90,
            "clock_time": clock_time,
            "daytime": True,
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "paused": False,
            "radiant_score": 10,
            "dire_score": 12,
        },
        "player": {
            "steamid": "76561198000000000",
            "accountid": "39734272",
            "name": "Synthetic",
            "team_name": "radiant",
            "kills": kills,
            "deaths": deaths,
            "assists": 4,
            "last_hits": 140,
            "denies": 10,
            "kill_streak": 0,
            "gold": gold,
            "gold_reliable": gold,
            "gold_unreliable": 0,
            "gpm": 450,
            "xpm": 520,
        },
        "hero": hero_block,
        "abilities": abilities if abilities is not None else _abilities(),
        "items": items if items is not None else _items(slot0=manta(), slot1=wand(8)),
        "minimap": minimap or {},
    }


def feed(client, clock, payloads, *, step: float = 0.5) -> dict[str, Any]:
    """Post each payload (wall time advancing by `step`) and poll once a second,
    as the overlay does; returns the last answer, and every answer in `seen`."""
    answer: dict[str, Any] = {}
    seen: list[dict[str, Any]] = []
    for payload in payloads:
        clock["t"] += step
        assert client.post("/gsi", json=payload).status_code == 200
        if clock["t"] % 1 < step:
            answer = client.get("/overlay/recommendation").json()
            seen.append(answer)
    answer = client.get("/overlay/recommendation").json()
    seen.append(answer)
    feed.seen = seen  # type: ignore[attr-defined]
    return answer


def _cards(seen: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [
        (a["decision_point"], a["recommendation"]["action"])
        for a in seen
        if a.get("new_advice") and a.get("recommendation")
    ]


def _calm(start: int, seconds: int, **kw: Any) -> list[dict[str, Any]]:
    return [gsi(start + i // 2, **kw) for i in range(seconds * 2)]


# 1. Own Doppelganger at full HP (PL 19:21/23:48 in the report; the same shape
#    is Manta's split at 28:31 of recording 9042382595: `stunned` appears in the
#    snapshot where the own cooldown starts, has_debuff false, HP unchanged).


def test_own_doppelganger_at_full_hp_raises_no_manta_order(client, clock):
    before = _calm(1160, 3)
    phase = [
        gsi(1163, stunned=True, abilities=_abilities(w=25)),
        gsi(1163, stunned=True, abilities=_abilities(w=25)),
        gsi(1164, abilities=_abilities(w=24), xy=(-4600, -5200)),
    ]
    feed(client, clock, before + phase)
    cards = _cards(feed.seen)  # type: ignore[attr-defined]
    assert not any(dp == "DISABLED_STATUS" for dp, _ in cards), cards
    source = client.get("/state/current").json()["state"]["extra_context"]["status_source"]
    assert source["kind"] == "none"  # the phase ended


def test_the_real_control_after_an_own_phase_is_not_lost(client, clock):
    # PL 19:22-19:23: right after the own phase an enemy stun lands, with a
    # debuff appearing and HP going down. It gets the post-disable card.
    feed(client, clock, _calm(1160, 3))
    feed(
        client,
        clock,
        [
            gsi(1163, stunned=True, abilities=_abilities(w=25)),
            gsi(1164, abilities=_abilities(w=24)),
            gsi(1165, stunned=True, debuff=True, hp=1250, abilities=_abilities(w=23)),
            gsi(1165, stunned=True, debuff=True, hp=1100, abilities=_abilities(w=23)),
        ],
    )
    source = client.get("/state/current").json()["state"]["extra_context"]["status_source"]
    assert source["kind"] == "enemy" and "hp_lost" in source["evidence"]
    cards = _cards(feed.seen)  # type: ignore[attr-defined]
    assert ("DISABLED_STATUS", "The moment the disable ends, use Manta Style.") in cards


def test_an_unexplained_stun_without_debuff_or_damage_orders_nothing(client, clock):
    # 9:22 of recording 9042382595: 3 s `stunned`, has_debuff false, HP
    # regenerating, no own cooldown starting. The source is unknown.
    feed(client, clock, _calm(560, 3) + [gsi(563, stunned=True, hp=1395)] * 6)
    source = client.get("/state/current").json()["state"]["extra_context"]["status_source"]
    assert source["kind"] == "unexplained"
    assert not any(dp == "DISABLED_STATUS" for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]


def test_a_payload_without_has_debuff_keeps_the_legacy_disable():
    # A missing field is unknown, not false: no own cast, no debuff field.
    watch = StatusWatch()
    calm = {"alive": True, "health": 900, "max_health": 1000, "abilities": [], "item_cooldowns": {}}
    watch.observe(calm, 100.0)
    assert watch.observe({**calm, "stunned": True}, 101.0)["kind"] == "unknown"
    watch = StatusWatch()
    watch.observe({**calm, "has_debuff": False}, 100.0)
    explained = watch.observe({**calm, "stunned": True, "has_debuff": False}, 101.0)
    assert explained["kind"] == "unexplained"


def test_a_hex_is_never_an_own_phase():
    # 28:09 of recording 9042342539: an own cast moments before, then a hex and
    # a stun land. Own phases show as `stunned` only.
    watch = StatusWatch()
    ready = {"alive": True, "health": 2742, "max_health": 2742, "has_debuff": False}
    watch.observe({**ready, "item_cooldowns": {"item_manta": 0}}, 100.0)
    hexed = watch.observe(
        {**ready, "hexed": True, "has_debuff": True, "item_cooldowns": {"item_manta": 30}}, 101.0
    )
    assert hexed["kind"] == "enemy"


# 1b. Counterexamples for the own phase: an own cooldown next to a stun is
#     not proof by itself; the phase lasts only as long as its mechanic.


def _pl_extra(q: float = 0, w: float = 0, **flags: Any) -> dict[str, Any]:
    abilities = [
        {"raw_name": "phantom_lancer_spirit_lance", "level": 4, "cooldown": q},
        {"raw_name": "phantom_lancer_doppelwalk", "level": 3, "cooldown": w},
    ]
    base = {"alive": True, "health": 1400, "max_health": 1400, "has_debuff": False}
    return {**base, "abilities": abilities, "item_cooldowns": {"item_manta": 0}, **flags}


def test_a_spirit_lance_cast_next_to_a_stun_is_not_an_own_phase():
    # Real recordings: Spirit Lance, a Wand, Blade Fury started next to enemy
    # stuns. Only mechanics that hide the hero (OWN_PHASES) explain one.
    watch = StatusWatch()
    watch.observe(_pl_extra(), 100.0)
    status = watch.observe(_pl_extra(q=7, stunned=True), 100.5)
    assert status["kind"] != "own_phase"


def test_a_doppelganger_stun_that_outlasts_the_phase_is_judged_again():
    watch = StatusWatch()
    watch.observe(_pl_extra(), 100.0)
    assert watch.observe(_pl_extra(w=25, stunned=True), 100.5)["kind"] == "own_phase"
    assert watch.observe(_pl_extra(w=24, stunned=True), 101.5)["kind"] == "own_phase"
    # 2.5 s after the onset: longer than Doppelganger's 1 s plus the sampling
    # tolerance. Still no debuff and no damage: unexplained, not own.
    late = watch.observe(_pl_extra(w=23, stunned=True), 103.0)
    assert late["kind"] == "unexplained"
    hit = watch.observe(_pl_extra(w=23, stunned=True, health=1100), 103.5)
    assert hit["kind"] == "enemy"


def test_manta_with_an_enemy_stun_on_top_is_enemy():
    # Recording 9042382595: Manta pressed into a stun, 476 HP lost meanwhile.
    watch = StatusWatch()
    ready = _pl_extra()
    watch.observe(ready, 100.0)
    pressed = {**ready, "item_cooldowns": {"item_manta": 45}, "stunned": True}
    assert watch.observe(pressed, 100.5)["kind"] == "own_phase"
    hurt = watch.observe({**pressed, "health": 924}, 101.0)
    assert hurt["kind"] == "enemy" and "hp_lost" in hurt["evidence"]


def test_an_own_cast_long_before_the_stun_explains_nothing():
    watch = StatusWatch()
    watch.observe(_pl_extra(), 100.0)
    watch.observe(_pl_extra(w=25), 100.5)
    status = watch.observe(_pl_extra(w=22, stunned=True), 103.5)
    assert status["kind"] == "unexplained"


def test_a_short_stun_at_high_hp_with_little_damage_gets_no_post_disable_card(client, clock):
    # PL 33:52: a 0.6 s stun at 89 % HP, nothing lost; 14:03: 1.1 s at 93 %,
    # 6 % lost. The status is still an enemy disable (classification), but
    # «the moment it ends, use Doppelganger» has nothing at stake.
    feed(client, clock, _calm(1300, 3, hp=1250))
    feed(client, clock, [gsi(1303, stunned=True, debuff=True, hp=1200)] * 2)
    source = client.get("/state/current").json()["state"]["extra_context"]["status_source"]
    assert source["kind"] == "enemy"
    assert not any(dp == "DISABLED_STATUS" for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]
    # The same stun with a nuke on top (more than 15 % of max HP lost since
    # the onset): the card comes during the stun.
    feed(client, clock, [gsi(1304, stunned=True, debuff=True, hp=950)] * 2)
    assert ("DISABLED_STATUS", "The moment the disable ends, use Manta Style.") in _cards(
        feed.seen  # type: ignore[attr-defined]
    )


def test_one_disable_card_per_stun_even_a_long_chain(client, clock):
    # 18 s of chained stuns with HP sinking: one card, not one per type
    # cooldown (the held card and the tactical-state dedup hold it).
    feed(client, clock, _calm(1400, 3, hp=900))
    chain = [gsi(1403 + i // 2, stunned=True, debuff=True, hp=700 - 2 * i) for i in range(36)]
    feed(client, clock, chain)
    disables = [c for c in _cards(feed.seen) if c[0] == "DISABLED_STATUS"]  # type: ignore[attr-defined]
    assert len(disables) == 1, disables


# 2. Ordinary enemy control with a ready answer still gets its card.


def test_a_silence_with_manta_ready_says_press_it_now(client, clock):
    feed(client, clock, _calm(1500, 3))
    feed(client, clock, [gsi(1503, silenced=True, debuff=True, hp=1300)] * 2)
    cards = _cards(feed.seen)  # type: ignore[attr-defined]
    assert ("DISABLED_STATUS", "Use Manta Style now: it removes the silence.") in cards


def test_an_urgent_disable_card_is_not_held_back_by_the_minute_quota():
    # 33:07 of recording 9042382595: two calm cards in the last minute, then a
    # silence with Manta ready; the per-minute quota dropped it.
    from datetime import UTC, datetime

    from app.advice_ux_policy import apply_ux_policy
    from app.schemas import RecommendationResponse

    now = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    recent = [
        {"timestamp": "2026-01-01T00:00:20+00:00", "action": "a", "action_type": "x"},
        {"timestamp": "2026-01-01T00:00:40+00:00", "action": "b", "action_type": "y"},
    ]
    card = RecommendationResponse(
        action="Use Manta Style now: it removes the silence.",
        reason="A silence does not stop items.",
        risk="High.",
        priority="high",
        time_window="now",
    )
    kept = apply_ux_policy(card, "DISABLED_STATUS", recent, now=now, action_type="wait_out_disable")
    assert kept["recommendation"] is not None
    calm = apply_ux_policy(card, "SAFE_FARMING", recent, now=now, action_type="keep_farming")
    assert calm["suppressed_reason"] == "rate_limit"


# 3-4. Aegis, ordinary death, Aegis expiry, incomplete history, Reincarnation.


def _aegis_items(**extra: Any) -> dict[str, Any]:
    return _items(slot0=manta(), slot1=wand(8), slot2={"name": "item_aegis"}, **extra)


def test_an_aegis_revive_is_no_death_and_no_death_pattern(client, clock):
    # PL 33:02-33:13: Aegis held, alive goes false with the death counter
    # still 2, the hero stands again on the spot.
    feed(client, clock, [gsi(1980 + i // 2, items=_aegis_items(), hp=300) for i in range(6)])
    events_before = list(MATCH_MEMORY.death_events)
    dead = [gsi(1983, alive=False, hp=0, items=_items(slot0=manta(), slot1=wand(8)), respawn=5)]
    answer = feed(client, clock, dead * 4)
    assert answer["decision_point"] == "NO_ADVICE"
    assert answer.get("death_screen") is None
    assert not any(dp.startswith("DEATH") or "REPEATED" in dp for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]
    feed(client, clock, [gsi(1988, items=_items(slot0=manta(), slot1=wand(8)))] * 2)
    assert MATCH_MEMORY.death_events == events_before
    assert MATCH_MEMORY.death_count == len(events_before)
    assert [e["type"] for e in MATCH_MEMORY.life_events] == ["aegis_revive"]
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra["recent_revive"]["type"] == "aegis_revive"


ENEMY_NEAR = {
    "e0": {
        "image": "minimap_enemyicon",
        "unitname": "npc_dota_hero_juggernaut",
        "team": 3,
        "xpos": -4400,
        "ypos": -4700,
    }
}


def test_the_second_life_gets_its_readiness(client, clock):
    # PL 33:13: revived on the spot in the fight (an enemy hero visible next
    # to him), Manta ready, W back in about 3 s: what to hold until then.
    bar = _abilities(w=5)
    held = _aegis_items()
    feed(client, clock, [gsi(1980 + i // 2, items=held, hp=300, abilities=bar) for i in range(6)])
    gone = _items(slot0=manta(), slot1=wand(8))
    feed(client, clock, [gsi(1983, alive=False, hp=0, items=gone, abilities=bar)] * 4)
    revived = gsi(1985, items=gone, abilities=_abilities(w=3), minimap=ENEMY_NEAR)
    feed(client, clock, [revived] * 3)
    cards = _cards(feed.seen)  # type: ignore[attr-defined]
    assert (
        "ABILITY_SAFETY_COOLDOWN",
        "Second life: hold the next engage until Doppelganger is back in 3 s.",
    ) in cards


def test_a_second_life_with_no_fight_around_gets_no_readiness(client, clock):
    # Counterexample: revived with no enemy in sight and no damage coming: the
    # cooldown alone answers no question.
    bar = _abilities(w=5)
    feed(client, clock, [gsi(1980 + i // 2, items=_aegis_items(), abilities=bar) for i in range(6)])
    gone = _items(slot0=manta(), slot1=wand(8))
    feed(client, clock, [gsi(1983, alive=False, hp=0, items=gone, abilities=bar)] * 4)
    feed(client, clock, [gsi(1985, items=gone, abilities=_abilities(w=3))] * 3)
    cards = _cards(feed.seen)  # type: ignore[attr-defined]
    assert not any(dp == "ABILITY_SAFETY_COOLDOWN" for dp, _ in cards), cards


def test_an_ordinary_death_still_counts(client, clock):
    feed(client, clock, _calm(1100, 3))
    feed(client, clock, [gsi(1103, alive=False, hp=0, deaths=3, respawn=40)] * 2)
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.life_events == []


def test_the_aegis_running_out_while_alive_is_no_death(client, clock):
    feed(client, clock, [gsi(2000, items=_aegis_items())] * 2 + [gsi(2001)] * 2)
    assert MATCH_MEMORY.death_count == 0
    assert [e["type"] for e in MATCH_MEMORY.life_events] == ["aegis_gone_alive"]


def test_a_backend_started_while_dead_records_nothing(client, clock):
    # No history: the first snapshot is already dead; nothing is inferred.
    feed(client, clock, [gsi(1500, alive=False, hp=0, respawn=30)] * 3)
    assert MATCH_MEMORY.death_count == 0 and MATCH_MEMORY.life_events == []


def test_reincarnation_has_its_own_life_cycle(client, clock):
    wk = "npc_dota_hero_skeleton_king"
    ultimate = {
        "name": "skeleton_king_reincarnation",
        "level": 2,
        "can_cast": False,
        "passive": True,
        "ability_active": True,
        "cooldown": 0,
        "ultimate": True,
    }
    on_cooldown = {**ultimate, "cooldown": 200}
    feed(client, clock, [gsi(1700, hero=wk, abilities={"ability5": ultimate}, hp=200)] * 2)
    feed(
        client,
        clock,
        [gsi(1701, hero=wk, alive=False, hp=0, abilities={"ability5": on_cooldown})] * 3,
    )
    feed(client, clock, [gsi(1704, hero=wk, abilities={"ability5": on_cooldown})] * 2)
    assert MATCH_MEMORY.death_count == 0
    assert [e["type"] for e in MATCH_MEMORY.life_events] == ["reincarnation"]


def test_two_deaths_across_the_map_are_not_one_repeated_route(client, clock):
    # PL 18:33: two deaths ten minutes apart, about 6.7k units from each other.
    feed(client, clock, _calm(500, 2, xy=(-4060, 4360), deaths=0))
    feed(client, clock, [gsi(502, alive=False, hp=0, deaths=1, xy=(-4060, 4360))] * 2)
    feed(client, clock, _calm(560, 2, deaths=1, xy=(776, -279)))
    feed(client, clock, [gsi(1100, hp=900, deaths=1, xy=(776, -279))] * 2)
    feed(client, clock, [gsi(1102, alive=False, hp=0, deaths=2, xy=(776, -279))] * 2)
    assert "REPEATED_DEATHS" not in MATCH_MEMORY.death_events[-1]["patterns"]
    assert MATCH_MEMORY.death_review_decision() != "REPEATED_DEATH_PATTERN"


ALLY_NEAR = {
    "a0": {
        "image": "minimap_herocircle",
        "unitname": "npc_dota_hero_axe",
        "team": 2,
        "xpos": 3200,
        "ypos": 3000,
    }
}


def _death_at(client, clock, start: int, deaths: int, minimap: dict[str, Any] | None) -> None:
    alive = [gsi(start + i // 2, deaths=deaths, xy=(3000, 3000), minimap=minimap) for i in range(8)]
    dead = gsi(start + 4, alive=False, hp=0, deaths=deaths + 1, xy=(3000, 3000), respawn=30)
    feed(client, clock, alive + [dead] * 2)


def test_deaths_at_one_spot_with_the_team_are_a_place_not_a_route_mistake(client, clock):
    # Three deaths at one tower, each with an ally staying next to the hero:
    # where the team fought (REPEATED_PLACE), no «reset your route».
    for n, start in enumerate((1200, 1400, 1600)):
        _death_at(client, clock, start, 2 + n, ALLY_NEAR)
    last = MATCH_MEMORY.death_events[-1]
    assert last["with_team"] is True
    assert "REPEATED_PLACE" in last["patterns"] and "REPEATED_DEATHS" not in last["patterns"]
    assert MATCH_MEMORY.death_review_decision() != "REPEATED_DEATH_PATTERN"


def test_lone_deaths_at_one_spot_are_a_repeated_mistake(client, clock):
    # The same spot, alone each time (the minimap shows no ally next to him).
    for n, start in enumerate((1200, 1400)):
        _death_at(client, clock, start, 2 + n, {})
    last = MATCH_MEMORY.death_events[-1]
    assert last["with_team"] is False
    assert "REPEATED_DEATHS" in last["patterns"]


def test_without_a_minimap_no_route_mistake_is_claimed(client, clock):
    def bare(payload: dict[str, Any]) -> dict[str, Any]:
        payload = copy.deepcopy(payload)
        payload.pop("minimap")
        return payload

    for n, start in enumerate((1200, 1400)):
        alive = [bare(gsi(start + i // 2, deaths=2 + n, xy=(3000, 3000))) for i in range(8)]
        dead = bare(gsi(start + 4, alive=False, hp=0, deaths=3 + n, xy=(3000, 3000), respawn=30))
        feed(client, clock, alive + [dead] * 2)
    last = MATCH_MEMORY.death_events[-1]
    assert last["with_team"] is None
    assert "REPEATED_DEATHS" not in last["patterns"] and "REPEATED_PLACE" in last["patterns"]


def test_low_hp_at_the_last_tick_does_not_make_a_low_resource_death(client, clock):
    # PL 09:10-09:22: 81 % HP when the fight starts, a burst, the death.
    entry = [gsi(550 + i // 2, hp=1134, max_hp=1400, deaths=0) for i in range(8)]
    burst = [gsi(554, hp=400, max_hp=1400, deaths=0), gsi(555, hp=60, max_hp=1400, deaths=0)]
    feed(client, clock, entry + burst + [gsi(555, alive=False, hp=0, deaths=1)] * 2)
    death = MATCH_MEMORY.death_events[-1]
    assert death["entry_hp_percent"] >= 80
    assert "LOW_RESOURCE_DEATH" not in death["patterns"]


# 3b. Counterexamples for the life cycle: a late, missing or jumping counter,
#     a gap, a stand-up with no revive item. An alive drop is a revive only
#     when the hero stands up where it fell; a death only once an observation
#     shows it; never counted twice.


def _without_counter(payload: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(payload)
    payload["player"].pop("deaths")
    return payload


def test_a_late_counter_is_one_death_after_an_unresolved_moment(client, clock):
    feed(client, clock, _calm(1100, 2))
    feed(client, clock, [gsi(1102, alive=False, hp=0, deaths=2)])
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra["life_state"] == "unresolved"
    assert MATCH_MEMORY.death_count == 0
    feed(client, clock, [gsi(1102, alive=False, hp=0, deaths=3, respawn=40)] * 2)
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.death_events[-1]["counter"] == "late"
    assert MATCH_MEMORY.life_events == []


def test_a_death_the_counter_never_shows_is_inferred_once_and_confirmed_later(client, clock):
    feed(client, clock, _calm(1100, 2))
    feed(client, clock, [gsi(1102 + i // 2, alive=False, hp=0, deaths=2) for i in range(10)])
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.death_events[-1]["counter"] == "not_seen"
    # The counter catches up much later: the same death, not a second one.
    feed(client, clock, [gsi(1130, alive=False, hp=0, deaths=3, respawn=20)] * 2)
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.death_events[-1]["counter"] == "confirmed_late"


def test_a_respawn_timer_longer_than_any_revive_is_a_death_at_once(client, clock):
    feed(client, clock, [gsi(1500 + i // 2, items=_aegis_items(), hp=200) for i in range(4)])
    feed(client, clock, [gsi(1502, alive=False, hp=0, items=_aegis_items(), respawn=45)])
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.life_events == []


def test_a_counter_missing_for_a_while_is_not_a_second_death(client, clock):
    # A reconnect: the player block comes back without `deaths` for a while.
    feed(client, clock, _calm(1200, 2))
    feed(client, clock, [_without_counter(gsi(1202))] * 2)
    feed(client, clock, [_without_counter(gsi(1203, alive=False, hp=0))] * 2)
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.death_events[-1]["counter"] == "missing"
    feed(client, clock, [gsi(1204, alive=False, hp=0, deaths=3, respawn=30)] * 2)
    assert MATCH_MEMORY.death_count == 1


def test_deaths_across_a_gap_are_counted_without_a_place(client, clock):
    # 50 s with no payload, then the counter is two higher: two deaths whose
    # place no snapshot shows; no route or place claim from them.
    feed(client, clock, _calm(1300, 2, xy=(-4000, 4000)))
    feed(client, clock, [gsi(1350, deaths=4, xy=(7100, 6376))] * 2)
    assert MATCH_MEMORY.death_count == 2
    assert all(event["position"] is None for event in MATCH_MEMORY.death_events)
    assert all("REPEATED_DEATHS" not in event["patterns"] for event in MATCH_MEMORY.death_events)


def test_standing_up_with_no_revive_item_is_no_second_life(client, clock):
    # Alive drops and returns on the spot two seconds later, counter unchanged,
    # no Aegis, no Reincarnation: neither a death nor a confirmed revive.
    feed(client, clock, _calm(1400, 2, abilities=_abilities(w=8)))
    feed(client, clock, [gsi(1402, alive=False, hp=0, abilities=_abilities(w=7))] * 2)
    feed(client, clock, [gsi(1403, hp=600, abilities=_abilities(w=6))] * 3)
    assert MATCH_MEMORY.death_count == 0
    assert [e["type"] for e in MATCH_MEMORY.life_events] == ["revive_unconfirmed"]
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra["recent_revive"] is None
    assert not any("Second life" in action for _, action in _cards(feed.seen))  # type: ignore[attr-defined]


def test_coming_back_at_the_fountain_with_no_counter_is_a_death_not_a_revive(client, clock):
    feed(client, clock, _calm(1600, 2, xy=(-4000, 4000)))
    feed(client, clock, [gsi(1602, alive=False, hp=0, xy=(-4000, 4000))])
    feed(client, clock, [gsi(1603, xy=(7100, 6376))] * 2)
    assert MATCH_MEMORY.death_count == 1
    assert MATCH_MEMORY.death_events[-1]["counter"] == "not_seen"
    assert MATCH_MEMORY.life_events == []


# 5. Stale numbers and late async answers.


def test_the_buyback_card_quotes_this_snapshot_not_the_purchase():
    # PL 31:47 → 32:28: bought at 1338/1824, by the card 566/1905.
    tracker = BuybackTracker()
    tracker.observe(1906, 2400, 1820, 0, True)
    tracker.observe(1907, 1338, 1824, 0, True)
    tracker.observe(1948, 566, 1905, 0, True)
    signal = tracker.signal()
    assert signal is not None and (signal["gold"], signal["cost"]) == (566, 1905)
    state = {
        "minute": 32,
        "hp_percent": 100,
        "extra_context": {
            "buyback_spent": signal,
            "available_gold": 566,
            "buyback_cost": 1905,
            "advisor_coverage": "full",
        },
    }
    advice = build_post_laning_advice(state, "SAFE_FARMING")
    assert advice is not None and "566 gold" in advice.reason and "1905" in advice.reason
    assert "1338" not in advice.reason
    # Holding an Aegis that still lasts (pickup seen, 83 s left at 32:28) the
    # next death revives: no buyback lock on items.
    extra = state["extra_context"]
    aegis = {**state, "extra_context": {**extra, "has_aegis": True, "own_aegis_left": 83}}
    held = build_post_laning_advice(aegis, "SAFE_FARMING")
    assert held is None or "buyback" not in held.reason


def test_an_aegis_of_unknown_age_or_about_to_expire_keeps_the_buyback_card():
    # Counterexamples: the timer is unknown (recording started after the
    # pickup), it ends in 20 s, or the base is on the line.
    signal = {"clock": 1948, "gold": 566, "cost": 1905, "observed": 1948}
    base = {
        "buyback_spent": signal,
        "available_gold": 566,
        "buyback_cost": 1905,
        "advisor_coverage": "full",
        "has_aegis": True,
    }
    for extra in (
        base,
        {**base, "own_aegis_left": 20},
        {
            **base,
            "buyback_spent": {**signal, "danger": "own_base_down"},
            "own_aegis_left": 200,
            "base_danger": "own_base_down",
        },
    ):
        advice = build_post_laning_advice(
            {"minute": 32, "hp_percent": 100, "extra_context": extra}, "SAFE_FARMING"
        )
        assert advice is not None and advice.category == "post_laning_buyback_reserve", extra


def test_a_held_card_with_old_numbers_is_withdrawn():
    then = {"hp_percent": 100, "extra_context": {"available_gold": 1338, "buyback_cost": 1824}}
    basis = advice_basis(
        "SAFE_FARMING",
        "Farm back your buyback gold before the next purchase.",
        "You have 1338 gold and buyback costs 1824; after minute 30 ...",
        then,
    )
    now = {"hp_percent": 100, "extra_context": {"available_gold": 566, "buyback_cost": 1905}}
    assert withdraw_reason(basis, then) is None
    assert withdraw_reason(basis, now) == "stale_numbers"
    back = {"hp_percent": 100, "extra_context": {"available_gold": 2000, "buyback_cost": 1905}}
    assert withdraw_reason(basis, back) == "resolved"


def test_a_held_card_within_tolerance_shows_this_snapshots_numbers():
    # The decision tolerates 100 gold of drift; the card does not quote the
    # old 1338 while the player has 1438.
    from datetime import UTC, datetime

    from app.advice_scheduler import ADVICE_SCHEDULER
    from app.schemas import RecommendationResponse

    reason = "You have 1338 gold and buyback costs 1824; after minute 30 a death costs more."
    then = {"hp_percent": 100, "extra_context": {"available_gold": 1338, "buyback_cost": 1824}}
    action = "Farm back your buyback gold before the next purchase."
    card = RecommendationResponse(
        action=action, reason=reason, risk="", priority="medium", time_window="now"
    )
    ADVICE_SCHEDULER.state._last_recommendation = card
    ADVICE_SCHEDULER.state._active_basis = advice_basis("SAFE_FARMING", action, reason, then)
    now = {"hp_percent": 100, "extra_context": {"available_gold": 1438, "buyback_cost": 1830}}
    with ADVICE_SCHEDULER._lock:
        ADVICE_SCHEDULER._revalidate_active_locked(now, datetime.now(UTC))
    shown = ADVICE_SCHEDULER.state._last_recommendation
    assert shown is not None and shown.action == action
    assert "1438 gold" in shown.reason and "1830" in shown.reason and "1338" not in shown.reason
    # The decision still measures drift from the numbers it was made on.
    assert ADVICE_SCHEDULER.state._active_basis["facts"]["gold"] == 1338


def test_more_wand_charges_refresh_the_number_and_spent_ones_withdraw():
    from app.advice_validity import refreshed_reason

    reason = "Magic Wand has 8 charges: that HP is yours right now."
    then = {"hp_percent": 30, "extra_context": {"wand_charges": 8}}
    basis = advice_basis("LOW_HP", "Use Magic Wand now.", reason, then)
    more = {"hp_percent": 30, "extra_context": {"wand_charges": 10}}
    assert withdraw_reason(basis, more) is None
    assert refreshed_reason(basis, reason, more) == (
        "Magic Wand has 10 charges: that HP is yours right now."
    )
    spent = {"hp_percent": 45, "extra_context": {"wand_charges": 0}}
    assert withdraw_reason(basis, spent) == "action_done"


def test_a_late_llm_answer_does_not_overwrite_a_newer_card(monkeypatch):
    from app import advice_scheduler as module
    from app.advice_scheduler import ADVICE_SCHEDULER
    from app.llm_provider import LLMResult
    from app.schemas import GameSituationRequest, RecommendationResponse

    request = GameSituationRequest(
        hero="Phantom Lancer",
        role="carry",
        minute=20,
        level=14,
        gold=600,
        items=[],
        hp_percent=90,
        game_state="objective",
        team_status="advantage",
    )
    ADVICE_SCHEDULER.evaluate(request, "OBJECTIVE_FIGHT_CHECK", [])
    shown = ADVICE_SCHEDULER.state._last_recommendation
    late = RecommendationResponse(
        action="Group with your team at the tower.",
        reason="Late answer.",
        risk="Low.",
        priority="medium",
        time_window="next 30 seconds",
    )
    monkeypatch.setattr(
        module,
        "generate_llm_recommendation",
        lambda *_a, **_k: LLMResult(recommendation=late, provider="test", model="test"),
    )
    tactical = ADVICE_SCHEDULER.state.last_tactical_state_hash or ""
    # A newer card was shown meanwhile (serial moved on).
    ADVICE_SCHEDULER._run_llm_refinement(tactical, request, "OBJECTIVE_FIGHT_CHECK", [], -1)
    assert ADVICE_SCHEDULER.state._last_recommendation is shown
    assert ADVICE_SCHEDULER.state.stale_llm_count == 1


# 6. A used heal ends the repeat; a new burst speaks again.


def test_a_tango_eaten_is_not_asked_for_again(client, clock):
    # PL 06:56 → 07:00: a Tango charge went at 06:56, «use Tango» came at 07:00.
    items = _items(slot0=tango(3))
    low = [gsi(416 + i // 2, hp=330, max_hp=1000, items=items) for i in range(4)]
    eaten = [
        gsi(418 + i // 2, hp=340 + i * 10, max_hp=1000, items=_items(slot0=tango(2)))
        for i in range(6)
    ]
    feed(client, clock, low + eaten)
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert "item_tango" in extra["regen_active"]
    tool = low_hp_copy(extra, "Phantom Lancer")
    assert tool is None or "Tango" not in tool[0]


def test_moving_or_selling_is_not_using():
    alive = {"alive": True, "available_gold": 100}
    before = {**alive, "item_charges": {"item_tango": 3}, "item_names": ["item_tango"]}
    moved = {**alive, "item_charges": {}, "item_names": ["item_tango"]}  # to the backpack
    sold = {"alive": True, "available_gold": 145, "item_charges": {}, "item_names": []}
    assert used_consumables(before, moved, gap=0.5) == []
    assert used_consumables(before, sold, gap=0.5) == []
    assert used_consumables(before, {**before, "item_charges": {"item_tango": 2}}, gap=0.5) == [
        "item_tango"
    ]
    # A reconnect gap: nothing is inferred across it.
    assert used_consumables(before, {**before, "item_charges": {"item_tango": 2}}, gap=9) == []


def test_recovering_hp_mutes_the_repeat_but_a_new_burst_speaks(client, clock):
    # PL 05:14 / 05:37 / 05:52 / 06:27.
    feed(client, clock, _calm(300, 2, hp=780, max_hp=780))
    feed(client, clock, [gsi(302, hp=v, max_hp=780) for v in (700, 560, 469, 400)], step=1)
    first = _cards(feed.seen)  # type: ignore[attr-defined]
    assert any(dp == "LOW_HP" for dp, _ in first)
    feed(client, clock, [gsi(306 + i, hp=170 + i * 25, max_hp=780) for i in range(8)], step=1)
    assert not any(dp == "LOW_HP" for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]
    clock["t"] += 30
    feed(client, clock, [gsi(380, hp=v, max_hp=1000) for v in (600, 420, 233)], step=1)
    assert any(dp == "LOW_HP" for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]


# 7. Max-HP changes and self costs are no burst; real damage still is.


def test_a_max_hp_drop_alone_is_no_fall(client, clock):
    # Armlet off / Treads: health and max fall together, no damage.
    feed(client, clock, _calm(900, 2, hp=1200, max_hp=1700))
    feed(client, clock, [gsi(902, hp=730, max_hp=1230), gsi(903, hp=730, max_hp=1230)])
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra.get("hp_falling_fast") is None
    # The same max change with real damage on top is still a fall.
    feed(client, clock, _calm(910, 2, hp=1200, max_hp=1700))
    feed(client, clock, [gsi(912, hp=300, max_hp=1230), gsi(912, hp=200, max_hp=1230)])
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert (extra.get("hp_falling_fast") or 0) >= 30


def test_a_burst_that_stopped_is_not_projected(client, clock):
    # PL 14:20: 735/1066 after the W, the damage over. No «seconds left».
    feed(client, clock, _calm(860, 2, hp=1066, max_hp=1066))
    feed(client, clock, [gsi(862, hp=735, max_hp=1066)] + [gsi(863, hp=736, max_hp=1066)] * 6)
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra.get("hp_falling_fast") is None
    body = client.get("/overlay/recommendation").json()
    assert "seconds left" not in str(body.get("recommendation"))


# 8. Executability: learned, ready, castable now, and the order once stunned.


def test_low_mana_names_no_escape_that_is_not_learned():
    from app.ability_normalization import normalize_abilities

    unlearned = {"abilities": normalize_abilities(_abilities(w=None))}
    assert "Doppelganger" not in low_mana_reason(unlearned, "Phantom Lancer")
    short = {
        "abilities": normalize_abilities({"a": {**_abilities()["ability1"], "can_cast": False}})
    }
    assert low_mana_reason(short, "Phantom Lancer") == (
        "Doppelganger is off cooldown but cannot be cast now: not enough mana."
    )
    # A stolen or replaced bar without the ability names nothing either.
    stolen = {"abilities": normalize_abilities({"a": {"name": "rubick_spell_steal", "level": 3}})}
    assert "Doppelganger" not in low_mana_reason(stolen, "Phantom Lancer")


def test_a_press_now_card_is_withdrawn_once_a_stun_lands():
    # PL 01:16: «use Faerie Fire now» while `stunned`.
    then = {
        "hero": "Phantom Lancer",
        "hp_percent": 40,
        "extra_context": {
            "alive": True,
            "regen_items": ["item_faerie_fire"],
            "item_names": ["item_faerie_fire"],
        },
    }
    basis = advice_basis("LOW_HP", "Use Faerie Fire now, then step back.", "...", then)
    assert basis["tool"]["name"] == "item_faerie_fire"
    stunned = {**then, "extra_context": {**then["extra_context"], "stunned": True}}
    assert withdraw_reason(basis, stunned) == "cannot_act_now"
    used = {**then, "extra_context": {**then["extra_context"], "item_names": []}}
    assert withdraw_reason(basis, used) == "action_done"


def test_a_stunned_hero_is_told_what_to_press_after_not_now():
    extra = {
        "stunned": True,
        "status_source": {"kind": "enemy"},
        "ready_savers": ["item_manta"],
        "regen_items": ["item_faerie_fire"],
    }
    action, _ = low_hp_copy(extra, "Phantom Lancer") or ("", "")
    assert action == "The moment the disable ends, use Manta Style."


# 9-10. Missing vs explicitly absent; TP reminders and what changes them.


def test_tp_in_the_stash_asks_for_the_courier_not_a_purchase():
    signal = {"seconds": 120, "minutes": 2}
    base = {"minute": 21, "hp_percent": 100}
    missing = {**base, "extra_context": {"tp_missing": signal, "advisor_coverage": "full"}}
    advice = build_post_laning_advice(missing, "SAFE_FARMING")
    assert advice is not None and advice.action.startswith("Keep a TP scroll")
    stash = {**base, "extra_context": {"tp_missing": signal, "tp_in_stash": True}}
    advice = build_post_laning_advice(stash, "SAFE_FARMING")
    assert advice is not None and "stash" in advice.action
    furion = {
        **base,
        "extra_context": {
            "tp_missing": signal,
            "abilities": [{"raw_name": "furion_teleportation", "level": 2}],
        },
    }
    advice = build_post_laning_advice(furion, "SAFE_FARMING")
    assert advice is None or "TP" not in advice.action


def test_no_items_block_is_unknown_not_empty():
    from app.gsi_state import _active_item_numbers
    from app.tp_tracker import has_teleport, teleport_in_stash

    assert _active_item_numbers(None, "cooldown") is None
    assert _active_item_numbers({}, "cooldown") == {}
    assert has_teleport(None) is None and teleport_in_stash(None) is None


# 11. Deep with allies (and the Aegis) is not a lone deep showing.


def test_deep_with_allies_next_to_you_is_not_a_lone_deep_showing():
    base = {
        "minute": 31,
        "hp_percent": 95,
        "extra_context": {
            "position_zone": "deep_enemy_side",
            "position_risk": "high",
            "xpos": 20000.0,
            "ypos": 20000.0,
            "advisor_coverage": "full",
        },
    }
    alone = build_post_laning_advice(base, "SAFE_FARMING")
    assert alone is not None and alone.category == "post_laning_risky_showing"
    grouped = copy.deepcopy(base)
    grouped["extra_context"]["ally_units"] = [
        {"hero": "Axe", "x": 20250.0, "y": 20000.0},
        {"hero": "Shadow Fiend", "x": 21160.0, "y": 20000.0},
    ]
    advice = build_post_laning_advice(grouped, "SAFE_FARMING")
    assert advice is None or advice.category != "post_laning_risky_showing"


def _deep(clock_time: int, allies: list[dict[str, Any]], enemies: int = 0) -> dict[str, Any]:
    minimap = {
        f"o{i}": {
            "image": "minimap_herocircle",
            "unitname": f"npc_dota_hero_{name}",
            "team": 2,
            "xpos": x,
            "ypos": y,
        }
        for i, (name, x, y) in enumerate((a["hero"], a["x"], a["y"]) for a in allies)
    }
    for i in range(enemies):
        minimap[f"e{i}"] = {
            "image": "minimap_enemyicon",
            "unitname": f"npc_dota_hero_{('lion', 'lina', 'tusk', 'sven')[i]}",
            "team": 3,
            "xpos": 4300 + 50 * i,
            "ypos": 4300,
        }
    return gsi(clock_time, xy=(4000, 4000), minimap=minimap)


def test_an_ally_crossing_for_one_tick_is_not_a_group(client, clock):
    axe = {"hero": "axe", "x": 4200, "y": 4000}
    feed(client, clock, [_deep(1800, [])] * 4 + [_deep(1802, [axe])])
    support = client.get("/state/current").json()["state"]["extra_context"]["team_support"]
    assert support["allies"] and not support["steady"]
    # Staying with the hero for seconds: a group.
    feed(client, clock, [_deep(1803 + i // 2, [axe]) for i in range(6)])
    support = client.get("/state/current").json()["state"]["extra_context"]["team_support"]
    assert support["steady"] == support["allies"]


def test_a_steady_ally_against_more_visible_enemies_is_not_grouped():
    from app.team_context import grouped_with_team

    support = {"known": True, "allies": ["Axe"], "steady": ["Axe"], "enemies_near": 3}
    assert not grouped_with_team({"team_support": support})
    assert grouped_with_team({"team_support": {**support, "enemies_near": 2}})
    assert not grouped_with_team({"team_support": {"known": False}})


def test_the_own_hero_on_the_ally_circle_is_not_an_ally(client, clock):
    # GSI sometimes draws the player with `minimap_herocircle` (not `_self`).
    minimap = {
        "o1": {
            "xpos": -5000,
            "ypos": -5000,
            "image": "minimap_herocircle",
            "team": 2,
            "unitname": PL,
        },
        "o2": {
            "xpos": -4800,
            "ypos": -5000,
            "image": "minimap_herocircle",
            "team": 2,
            "unitname": "npc_dota_hero_axe",
        },
        "o3": {
            "xpos": -4900,
            "ypos": -5000,
            "image": "minimap_heroimage",
            "team": 2,
            "unitname": PL,
        },
    }
    feed(client, clock, [gsi(1900, minimap=minimap)] * 2)
    allies = client.get("/state/current").json()["state"]["extra_context"]["ally_units"]
    assert [unit["hero"] for unit in allies] == ["Axe"]


# 13. A purchase in the stash is no ready item.


def test_an_item_in_the_stash_is_not_ready_to_press(client, clock):
    items = _items(stash0=manta(), slot1=wand(0))
    feed(client, clock, _calm(1500, 2, items=items))
    feed(client, clock, [gsi(1502, silenced=True, debuff=True, hp=1200, items=items)] * 2)
    assert not any("Manta" in action for _, action in _cards(feed.seen))  # type: ignore[attr-defined]


# 14. Illusions: own illusions are no allies (above) and do not count as uses.


# 16. Duplicates, out-of-order payloads and a new match.


def test_duplicates_and_out_of_order_payloads_do_not_invent_casts():
    from app.action_feedback import ActionWatch

    watch = ActionWatch()
    ready = {"alive": True, "item_cooldowns": {"item_manta": 0}, "abilities": []}
    used = {"alive": True, "item_cooldowns": {"item_manta": 40}, "abilities": []}
    watch.observe(ready, 100.0)
    assert watch.observe(used, 101.0)["recent_casts"] == {"item:item_manta": 0.0}
    assert watch.observe(used, 101.0)["recent_casts"] == {"item:item_manta": 0.0}  # duplicate
    watch = ActionWatch()
    watch.observe(used, 101.0)
    assert watch.observe(ready, 99.0)["recent_casts"] == {}  # older payload


def test_a_new_match_starts_its_own_life_cycle(client, clock):
    feed(client, clock, [gsi(1980, items=_aegis_items())] * 2)
    feed(client, clock, [gsi(1981, alive=False, hp=0)] * 2)
    feed(client, clock, [gsi(-60, match="9100000002", deaths=0)] * 2)
    assert MATCH_MEMORY.life_events == [] and MATCH_MEMORY.death_count == 0
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert extra.get("life_state") is None


# 17. The queue: a calm card gives way to a threat; urgent cards pass.


def test_a_held_calm_card_gives_way_to_an_enemy_stun():
    basis = advice_basis(
        "SAFE_FARMING",
        "Keep a TP scroll in its slot: buy one now, the courier can bring it.",
        "No TP scroll for 1 minute.",
        {"hp_percent": 100, "extra_context": {"alive": True}},
    )
    fight = {"hp_percent": 80, "extra_context": {"alive": True, "status_source": {"kind": "enemy"}}}
    assert withdraw_reason(basis, fight) == "superseded_by_threat"
    own = {
        "hp_percent": 100,
        "extra_context": {"alive": True, "status_source": {"kind": "own_phase"}},
    }
    assert withdraw_reason(basis, own) is None


def test_the_post_disable_card_survives_the_end_of_the_disable():
    then = {
        "hero": "Phantom Lancer",
        "hp_percent": 70,
        "extra_context": {
            "alive": True,
            "ready_savers": ["item_manta"],
            "item_names": ["item_manta"],
            "item_cooldowns": {"item_manta": 0},
        },
    }
    basis = advice_basis(
        "DISABLED_STATUS", "The moment the disable ends, use Manta Style.", "...", then
    )
    ended = {**then, "extra_context": {**then["extra_context"], "status_source": {"kind": "none"}}}
    assert withdraw_reason(basis, ended) is None
    pressed = {
        **then,
        "extra_context": {**then["extra_context"], "item_cooldowns": {"item_manta": 40}},
    }
    assert withdraw_reason(basis, pressed) == "action_done"


def test_the_overlay_is_told_which_card_was_withdrawn(client, clock):
    items = _items(
        slot0={"name": "item_faerie_fire", "can_cast": True, "cooldown": 0, "charges": 1}
    )
    # W on cooldown: the instant heal is the tool (with W ready the card says
    # «Use Doppelganger now to get out» instead).
    bar = _abilities(w=20)
    feed(client, clock, _calm(70, 2, hp=600, max_hp=600, items=items, abilities=bar))
    feed(
        client,
        clock,
        [gsi(72, hp=v, max_hp=600, items=items, abilities=bar) for v in (480, 330, 220)],
        step=1,
    )
    card = next(a for a in feed.seen if a.get("new_advice"))  # type: ignore[attr-defined]
    assert "Faerie Fire" in card["recommendation"]["action"]
    assert card["advice_basis"]["tool"]["name"] == "item_faerie_fire"
    answer = feed(
        client,
        clock,
        [gsi(73, hp=220, max_hp=600, items=items, abilities=bar, stunned=True, debuff=True)],
    )
    assert answer["withdrawn_advice"]["reason"] == "cannot_act_now"
    assert (
        answer["recommendation"] is None
        or "Faerie Fire now" not in answer["recommendation"]["action"]
    )


def test_a_charged_wand_is_named_next_to_the_escape(client, clock):
    # PL 12:30: low HP, Doppelganger ready and the Wand charged: the escape
    # first, the Wand's HP on the way out (it was lost from the card).
    feed(client, clock, _calm(740, 3, items=_items(slot0=wand(12))))
    hit = [gsi(743, hp=v, items=_items(slot0=wand(12))) for v in (1000, 700, 420, 400)]
    feed(client, clock, hit)
    actions = [a for _, a in _cards(feed.seen)]  # type: ignore[attr-defined]
    assert "Use Doppelganger now to get out, then Magic Wand." in actions, actions


def test_a_wand_with_two_charges_is_not_worth_naming(client, clock):
    feed(client, clock, _calm(740, 3, items=_items(slot0=wand(2))))
    feed(
        client, clock, [gsi(743, hp=v, items=_items(slot0=wand(2))) for v in (1000, 700, 420, 400)]
    )
    actions = [a for _, a in _cards(feed.seen)]  # type: ignore[attr-defined]
    assert actions and not any("Magic Wand" in a for a in actions), actions


# 5.4 / 5.7: readiness after a kill or a revive.


def test_after_a_kill_with_w_on_cooldown_the_card_says_what_to_hold(client, clock):
    # PL 18:25: 62 % HP, a fresh kill with an enemy still in sight, W back in
    # 5 s, Manta in 21 s. W coming back is availability, not «go in»: the card
    # names what to hold until then.
    items = _items(slot0=manta(21), slot1=wand(20))
    # Above the 70 % line during the exchange (no card), then the kill at 62 %.
    feed(client, clock, _calm(1100, 3, kills=3, hp=1050, items=items, abilities=_abilities(w=7)))
    kill = gsi(1103, kills=4, hp=868, items=items, abilities=_abilities(w=5), minimap=ENEMY_NEAR)
    feed(client, clock, [kill] * 2)
    actions = [action for _, action in _cards(feed.seen)]  # type: ignore[attr-defined]
    assert "After your kill: hold the next engage until Doppelganger is back in 5 s." in actions
    assert not any("go in again" in action for action in actions)


def test_kills_in_a_row_are_one_readiness_moment(client, clock):
    # A double kill eight seconds apart: the second kill does not skip the
    # gates again (one spoken readiness card per fight, not per kill).
    from app.advice_scheduler import ADVICE_SCHEDULER

    items = _items(slot0=manta(21), slot1=wand(20))
    feed(client, clock, _calm(1100, 3, kills=3, hp=1050, items=items, abilities=_abilities(w=9)))
    first = gsi(1103, kills=4, hp=868, items=items, abilities=_abilities(w=7), minimap=ENEMY_NEAR)
    feed(client, clock, [first] * 2)
    assert ADVICE_SCHEDULER.state._readiness_shown_key == ("kill", 1103)
    later = [
        gsi(
            1104 + i // 2,
            kills=4,
            hp=868,
            items=items,
            abilities=_abilities(w=6),
            minimap=ENEMY_NEAR,
        )
        for i in range(14)
    ]
    second = gsi(1111, kills=5, hp=800, items=items, abilities=_abilities(w=2), minimap=ENEMY_NEAR)
    feed(client, clock, later + [second] * 2)
    assert ADVICE_SCHEDULER.state._readiness_shown_key == ("kill", 1103)


# 18. A prefix of a match decides exactly what the full run decided up to it.


def _scripted_match() -> list[dict[str, Any]]:
    payloads = _calm(600, 4)
    payloads += [gsi(604, hp=v) for v in (1200, 900, 600, 380)]
    payloads += [gsi(606, stunned=True, abilities=_abilities(w=25))]
    payloads += _calm(607, 3, abilities=_abilities(w=20))
    payloads += [gsi(610, silenced=True, debuff=True, hp=900)]
    payloads += [gsi(612, alive=False, hp=0, deaths=3, respawn=30)] * 3
    payloads += _calm(650, 3, deaths=3)
    return payloads


def _decisions(client, clock, payloads) -> list[tuple[int, str, str | None]]:
    rows = []
    for payload in payloads:
        clock["t"] += 0.5
        client.post("/gsi", json=payload)
        answer = client.get("/overlay/recommendation").json()
        recommendation = answer.get("recommendation") or {}
        rows.append(
            (payload["map"]["clock_time"], answer["decision_point"], recommendation.get("action"))
        )
    return rows


def test_a_prefix_decides_what_the_full_run_decided(client, clock, tmp_path):
    from app import gsi_state
    from app.advice_scheduler import ADVICE_SCHEDULER
    from app.coach_summary import COACH_SESSION_HISTORY
    from app.player_api import PLAYER_SERVICE

    payloads = _scripted_match()
    full = _decisions(client, clock, payloads)
    # Fresh state in the same process (what the autouse fixture does between
    # tests), then only the first part of the same match.
    PLAYER_SERVICE.configure(tmp_path / "again", client=None, auto_start=False)
    MATCH_MEMORY.reset()
    ADVICE_SCHEDULER.reset()
    COACH_SESSION_HISTORY.reset()
    gsi_state.reset_latest_gsi()
    clock["t"] = 0.0
    cut = 14
    prefix = _decisions(client, clock, payloads[:cut])
    assert prefix == full[:cut]
    # The future is never read: the cut snapshot's own decision is the same.
    assert any(dp != "NO_ADVICE" for _, dp, _ in prefix)
