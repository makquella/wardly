"""Hero mechanics the live coach must not misread, grouped by mechanic.

Synthetic snapshots in the shape GSI sends. Only Phantom Lancer, Juggernaut
and Terrorblade have real recordings behind these rules (docs/LIVE_ADVICE_AUDIT.md
names which case comes from which); the others are the same mechanic seen
from GSI's side: what the payload shows, and what the coach must do with it
when the payload cannot tell (illusions, clones, channels: GSI has no flag).
The tests check decisions and invariants, not wording."""

from __future__ import annotations

import copy
from typing import Any

from app.action_feedback import ActionWatch
from app.gsi_state import normalize_gsi_payload
from app.match_memory import MATCH_MEMORY
from app.status_source import StatusWatch, started_cooldowns
from tests import test_live_realtime_regressions as realtime
from tests.test_live_realtime_regressions import _abilities, _calm, _cards, _items, feed, gsi

# The wall-clock fixture of the realtime regressions (MatchMemory and the
# scheduler read datetime.now).
clock = realtime.clock


def _own(raw: str, cooldown: float, **flags: Any) -> dict[str, Any]:
    return {
        "alive": True,
        "health": 1000,
        "max_health": 1000,
        "has_debuff": False,
        "abilities": [{"raw_name": raw, "level": 3, "cooldown": cooldown}],
        "item_cooldowns": {},
        **flags,
    }


# 1. Own hidden or invulnerable phases. Measured in recordings (OWN_PHASES):
#    Doppelganger, Manta, Metamorphosis. Not measured: Phase Shift, Sleight of
#    Fist, Ball Lightning: if GSI ever flags them `stunned`, the source stays
#    unexplained (no imperative to spend an item), never «enemy».


def test_measured_own_phases_are_own():
    for raw in ("phantom_lancer_doppelwalk", "terrorblade_metamorphosis"):
        watch = StatusWatch()
        watch.observe(_own(raw, 0), 100.0)
        assert watch.observe(_own(raw, 20, stunned=True), 100.4)["kind"] == "own_phase", raw


def test_unmeasured_hiding_spells_are_unexplained_not_enemy():
    for raw in ("puck_phase_shift", "ember_spirit_sleight_of_fist", "storm_spirit_ball_lightning"):
        watch = StatusWatch()
        watch.observe(_own(raw, 0), 100.0)
        status = watch.observe(_own(raw, 6, stunned=True), 100.4)
        assert status["kind"] == "unexplained", (raw, status)


def test_omnislash_without_a_status_flag_raises_no_disable(client, clock):
    # Recording 9042382595: Omnislash never set `stunned`; the hero is gone
    # from the map for seconds. No flag, no disable card.
    jugg = "npc_dota_hero_juggernaut"
    feed(client, clock, [gsi(1500 + i // 2, hero=jugg, abilities={}) for i in range(10)])
    assert not any(dp == "DISABLED_STATUS" for dp, _ in _cards(feed.seen))  # type: ignore[attr-defined]


# 2. Revive, extra life, delayed outcome.


def test_a_stand_up_on_the_spot_without_aegis_or_reincarnation_claims_no_second_life(client, clock):
    # Phoenix's Supernova or an unknown revive: the life cycle sees an alive
    # drop and a stand-up where it fell; no death, and no «second life» card.
    phoenix = "npc_dota_hero_phoenix"
    feed(client, clock, _calm(1600, 2, hero=phoenix, abilities={}))
    feed(client, clock, [gsi(1602, hero=phoenix, alive=False, hp=0, abilities={})] * 2)
    feed(client, clock, [gsi(1604, hero=phoenix, hp=900, abilities={})] * 2)
    assert MATCH_MEMORY.death_count == 0
    assert [e["type"] for e in MATCH_MEMORY.life_events] == ["revive_unconfirmed"]


def test_damage_healed_back_under_a_delayed_effect_is_no_death(client, clock):
    # Oracle's False Promise: HP drops and is healed back with the hero alive
    # throughout and the counter unchanged: nothing is a death.
    feed(client, clock, _calm(1700, 2))
    feed(client, clock, [gsi(1702, hp=v) for v in (900, 300, 120, 600, 1300)])
    assert MATCH_MEMORY.death_count == 0 and MATCH_MEMORY.life_events == []


# 3. HP cost and max-HP change: Armlet, Treads, Morphling's shift move health
#    and max health together; Huskar pays HP for his spells.


def test_a_max_hp_change_with_the_same_share_is_no_damage():
    watch = StatusWatch()
    calm = {"alive": True, "has_debuff": False, "abilities": [], "item_cooldowns": {}}
    watch.observe({**calm, "health": 780, "max_health": 1000}, 100.0)
    # Treads or Armlet: 780/1000 → 1014/1300, the same 78 % (a stun meanwhile).
    status = watch.observe({**calm, "health": 1014, "max_health": 1300, "stunned": True}, 100.5)
    assert "hp_lost" not in status["evidence"]


def test_armlet_toggling_raises_no_hp_falling_card(client, clock):
    feed(client, clock, _calm(1800, 2, hp=800, max_hp=1000))
    toggles = [
        gsi(1802 + i // 2, hp=800 if i % 2 else 1100, max_hp=1000 if i % 2 else 1375)
        for i in range(10)
    ]
    feed(client, clock, toggles)
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert not extra.get("hp_falling_fast")


def test_a_slow_hp_cost_is_not_a_burst(client, clock):
    # Huskar's Burning Spear: a few HP per hit, no burst.
    huskar = "npc_dota_hero_huskar"
    feed(
        client,
        clock,
        [gsi(1900 + i // 2, hero=huskar, hp=1400 - 8 * i, abilities={}) for i in range(16)],
    )
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert not extra.get("hp_falling_fast")


# 4. Clones and linked units: GSI's hero block is the main hero only.


def _with_own_clone(hero: str) -> dict[str, Any]:
    payload = gsi(1000, hero=hero, abilities={})
    payload["minimap"] = {
        "o1": {
            "image": "minimap_herocircle",
            "unitname": hero,
            "team": 2,
            "xpos": -4900,
            "ypos": -5000,
        }
    }
    return payload


def test_an_own_clone_on_the_minimap_is_no_ally():
    # Meepo's clones and Arc Warden's Tempest Double draw as the same hero:
    # they are not team support (team_context) and never «allies next to you».
    for hero in ("npc_dota_hero_meepo", "npc_dota_hero_arc_warden"):
        extra = normalize_gsi_payload(_with_own_clone(hero))["extra_context"]
        assert extra["ally_units"] == [], hero


# 5. Ability swaps, charges, refresh: a spell appearing on the bar with its
#    cooldown running (Rubick's steal, Invoker's invoke) is not a cast.


def test_a_spell_swapped_in_on_cooldown_is_not_a_cast():
    before = {"ability:rubick_telekinesis": 0.0}
    now = {"ability:rubick_telekinesis": 0.0, "ability:lion_impale": 7.0}
    assert started_cooldowns(before, now) == []


def test_a_refreshed_cooldown_is_not_a_new_cast():
    # Refresher: running → 0 is a refresh, not a press; the next 0 → running is.
    before = {"ability:x": 40.0}
    assert started_cooldowns(before, {"ability:x": 0.0}) == []
    assert started_cooldowns({"ability:x": 0.0}, {"ability:x": 60.0}) == ["ability:x"]


# 6. Channels: GSI has no channel flag. A TP's cooldown starting with the
#    hero standing still is its channel; cards with nothing to press wait.


def _tp(cooldown: float) -> dict[str, Any]:
    return {"name": "item_tpscroll", "can_cast": cooldown == 0, "cooldown": cooldown, "charges": 1}


def test_a_tp_channel_is_seen_and_ends_when_the_hero_moves():
    watch = ActionWatch()
    still = {"alive": True, "xpos": 5000.0, "ypos": 5000.0, "tp_cooldown": 0}
    assert watch.observe(still, 100.0)["teleporting"] is False
    assert watch.observe({**still, "tp_cooldown": 80}, 100.5)["teleporting"] is True
    assert watch.observe({**still, "tp_cooldown": 79}, 102.0)["teleporting"] is True
    arrived = {**still, "xpos": 13000.0, "ypos": 13000.0, "tp_cooldown": 77}
    assert watch.observe(arrived, 103.5)["teleporting"] is False


def _channel_match(client, clock, tp_cooldown: float) -> list[str]:
    # W on cooldown and no item to press: the only low-HP card is a move one.
    bar = _abilities(w=20)
    items = _items()
    feed(client, clock, _calm(2000, 3, items=items, abilities=bar))
    late = copy.deepcopy(items)
    late["teleport0"] = _tp(tp_cooldown)
    hits = [gsi(2003, hp=v, items=late, abilities=bar) for v in (900, 600, 450, 400)]
    feed(client, clock, hits)
    return [action for _, action in _cards(feed.seen)]  # type: ignore[attr-defined]


def test_a_leave_card_waits_while_the_tp_channels(client, clock):
    actions = _channel_match(client, clock, tp_cooldown=80)
    assert not actions, actions


def test_without_a_channel_the_same_moment_gets_its_leave_card(client, clock):
    actions = _channel_match(client, clock, tp_cooldown=0)
    assert actions, actions


# 6b. The channel lifecycle and what each action does to it (channel_rules).


def _tp_watch_sequence(watch: ActionWatch, steps: list[dict[str, Any]]) -> list[bool]:
    return [watch.observe(step, step["at"])["teleporting"] for step in steps]


def _tp_step(at: float, cooldown: float | None, x: float = 5000.0, **kw: Any) -> dict[str, Any]:
    return {"alive": True, "xpos": x, "ypos": 5000.0, "tp_cooldown": cooldown, "at": at, **kw}


def test_a_completed_tp_ends_the_channel_on_arrival():
    watch = ActionWatch()
    seen = _tp_watch_sequence(
        watch,
        [_tp_step(100, 0), _tp_step(101, 80), _tp_step(102, 79), _tp_step(104, None, x=13000)],
    )
    assert seen == [False, True, True, False]
    assert watch.channel_end == "tp_gone"


def test_a_cancelled_tp_with_the_hero_still_standing_holds_nothing_for_long():
    # Cancelled, the hero keeps standing: the inference cannot tell, so it
    # ends with its window (TP_CHANNEL_SECONDS), not never.
    from app.action_feedback import TP_CHANNEL_SECONDS

    watch = ActionWatch()
    steps = [_tp_step(100, 0)] + [_tp_step(101 + i, 80 - i) for i in range(10)]
    seen = _tp_watch_sequence(watch, steps)
    assert seen[1] is True and seen[-1] is False
    assert sum(seen) <= TP_CHANNEL_SECONDS + 1
    assert watch.channel_end == "window_over"


def test_a_stun_or_a_walk_ends_the_assumed_channel():
    watch = ActionWatch()
    seen = _tp_watch_sequence(
        watch, [_tp_step(100, 0), _tp_step(101, 80), _tp_step(102, 79, stunned=True)]
    )
    assert seen == [False, True, False] and watch.channel_end == "interrupted"
    watch = ActionWatch()
    seen = _tp_watch_sequence(
        watch, [_tp_step(100, 0), _tp_step(101, 80), _tp_step(102, 79, x=5400)]
    )
    assert seen == [False, True, False] and watch.channel_end == "moved"


def test_a_missed_channel_start_or_a_data_gap_assumes_no_channel():
    # First seen already on cooldown: no ready → running, no channel assumed.
    watch = ActionWatch()
    assert _tp_watch_sequence(watch, [_tp_step(100, 80), _tp_step(101, 79)]) == [False, False]
    # A gap longer than MAX_GAP right after the start: the channel is unknown.
    watch = ActionWatch()
    seen = _tp_watch_sequence(watch, [_tp_step(100, 0), _tp_step(101, 80), _tp_step(106, 75)])
    assert seen == [False, True, False] and watch.channel_end == "data_gap"


def test_what_each_action_does_to_an_assumed_channel():
    from app.channel_rules import channel_verdict

    calm = {"teleporting": True, "hp_falling_fast": None}
    # An ability cast, Manta, a Wand, BKB: they interrupt a TP (Valve data:
    # no IGNORE_CHANNEL) -> wait while nothing is seen.
    for tool in (
        {"kind": "ability", "name": "Doppelganger"},
        {"kind": "item", "name": "item_manta"},
        {"kind": "item", "name": "item_magic_wand"},
        {"kind": "item", "name": "item_black_king_bar"},
    ):
        assert channel_verdict(calm, tool, "retreat_reset") == "hold", tool
    # Glimmer Cape and Shadow Blade ignore channels: compatible.
    for name in ("item_glimmer_cape", "item_invis_sword"):
        assert channel_verdict(calm, {"kind": "item", "name": name}, "retreat_reset") == (
            "compatible"
        )
    # A constraint with nothing to do now touches no channel.
    assert channel_verdict(calm, None, "respect_hero_safety_window") == "compatible"
    # Observed danger justifies breaking the TP for a tool, never for a walk.
    danger = {"teleporting": True, "hp_falling_fast": 40}
    assert channel_verdict(danger, {"kind": "ability", "name": "Doppelganger"}, None) == (
        "justified"
    )
    assert channel_verdict(danger, None, "retreat_reset") == "hold"
    # No channel assumed: nothing to judge.
    assert channel_verdict({"teleporting": False}, None, "retreat_reset") == "none"


def _scheduler_holds(extra: dict[str, Any], tool: dict[str, str] | None, action_type: str) -> bool:
    from app.advice_scheduler import ADVICE_SCHEDULER
    from app.schemas import RecommendationResponse

    card = RecommendationResponse(
        action="Use Doppelganger now to get out, then reset HP.",
        reason="r",
        risk="",
        priority="high",
        time_window="now",
        tool=tool,
    )
    state = {"hero": "Phantom Lancer", "extra_context": extra}
    return ADVICE_SCHEDULER._held_by_channel_locked(state, card, action_type)


def test_an_escape_card_during_the_tp_waits_when_no_danger_is_seen():
    # 0.60.0 let any card that named a tool through the channel; casting
    # Doppelganger ends the TP, so with nothing dangerous seen it waits.
    doppelganger = {"kind": "ability", "name": "Doppelganger"}
    calm = {"teleporting": True, "hp_falling_fast": None, "hp_delta_10s": -2}
    assert _scheduler_holds(calm, doppelganger, "retreat_reset") is True


def test_an_escape_card_during_the_tp_passes_when_hp_is_falling_fast():
    doppelganger = {"kind": "ability", "name": "Doppelganger"}
    falling = {"teleporting": True, "hp_falling_fast": 45, "hp_delta_10s": -45}
    assert _scheduler_holds(falling, doppelganger, "retreat_reset") is False
    # No assumed channel: nothing is held.
    assert _scheduler_holds({"teleporting": False}, doppelganger, "retreat_reset") is False
