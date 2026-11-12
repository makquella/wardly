"""Map hints (timers + role tips) and the live position they depend on."""

from __future__ import annotations

import copy

from match_fixtures import MATCH_ID, gsi_match_stream

from app.advice_context import MAP_CENTER
from app.live_role import LiveRoleTracker, lane_kind, lane_of, set_role_setting
from app.map_hints import RoleTips, has_observer_ward, item_names, map_hint, next_timer, timers
from app.match_memory import MATCH_MEMORY


def _world(x, y):
    return MAP_CENTER + x, MAP_CENTER + y


def test_lanes_on_the_map():
    assert lane_of(*_world(0, 0)) == "mid"
    assert lane_of(*_world(-6500, 3000)) == "top"
    assert lane_of(*_world(4000, -6500)) == "bot"
    assert lane_of(*_world(-7000, -6800)) is None  # Radiant fountain
    assert (lane_kind("bot", "radiant"), lane_kind("top", "radiant")) == ("safe", "off")
    assert (lane_kind("top", "dire"), lane_kind("mid", "dire")) == ("safe", "mid")


def _lane(tracker, point, lh_per_min, team="radiant", until=6 * 60):
    for clock in range(0, until + 1, 5):
        tracker.observe(
            clock,
            x=point[0],
            y=point[1],
            last_hits=int(clock / 60 * lh_per_min),
            team=team,
            alive=True,
        )


def test_the_lane_and_the_farm_decide_the_position():
    safe = _world(4000, -6500)
    for lh, role in ((5, "carry"), (1, "support")):
        tracker = LiveRoleTracker()
        _lane(tracker, safe, lh)
        assert tracker.role() == {"role": role, "source": "lane", "lane": "safe"}
    off = _world(-6500, 3000)
    tracker = LiveRoleTracker()
    _lane(tracker, off, 3)
    assert tracker.role()["role"] == "offlane"
    tracker = LiveRoleTracker()
    _lane(tracker, _world(0, 0), 4, team="dire")
    assert tracker.role()["role"] == "mid"


def test_before_the_lane_is_known_the_prior_is_used_and_the_read_stays():
    tracker = LiveRoleTracker()
    _lane(tracker, _world(4000, -6500), 1, until=120)
    prior = {"role": "carry", "source": "history"}
    assert tracker.role(prior) == prior  # 2:00: too early for the lane
    assert tracker.role() is None
    _lane(tracker, _world(4000, -6500), 1)
    assert tracker.role(prior)["role"] == "support"
    # Farming a lane at 20:00 does not change a support into a carry.
    for clock in range(1200, 1300, 5):
        tracker.observe(clock, x=0, y=0, last_hits=200, team="radiant", alive=True)
    assert tracker.role()["role"] == "support"


def test_the_setting_wins():
    tracker = LiveRoleTracker()
    _lane(tracker, _world(4000, -6500), 6)
    set_role_setting("support")
    # The lane read stays known (a safe-lane support gets pull tips); farming at a
    # carry's pace there reads as a role chosen by mistake (test_role_mismatch.py).
    assert tracker.role() == {
        "role": "support",
        "source": "setting",
        "lane": "safe",
        "mismatch": "carry",
    }
    assert LiveRoleTracker().role() == {"role": "support", "source": "setting"}
    assert set_role_setting("jungle") == "auto"
    assert tracker.role()["role"] == "carry"


def test_timers_follow_the_patch_data_and_the_role():
    data = timers()
    assert data["patch"] and {e["id"] for e in data["events"]} >= {
        "power_rune",
        "wisdom_shrine",
        "tormentor",
    }
    rune = next_timer(6 * 60 - 15, "mid", "uk")
    assert rune["title"] == "Руна сили" and rune["in_seconds"] == 15 and rune["at_label"] == "6:00"
    assert rune["title_en"] == "Power rune"  # spoken without a Ukrainian voice
    assert next_timer(6 * 60 - 15, "carry", "en") is None  # not a carry's business
    assert next_timer(6 * 60 - 25, "mid", "en") is None  # 20 s lead
    shrine = next_timer(14 * 60 - 10, "offlane", "en")
    assert shrine["id"] == "wisdom_shrine@840" and shrine["speak"] is True
    tormentor = next_timer(20 * 60 - 5, "carry", "en")
    assert tormentor["title"] == "Tormentor"
    # Power runes stop being a support's timer after 18:00, a mid's after 20:00
    # (till 40:00 the same card came every two minutes, some 17 a game).
    assert next_timer(20 * 60 + 2 * 60 - 10, "support", "en") is None
    assert next_timer(18 * 60 - 10, "mid", "en")["title"] == "Power rune"
    assert next_timer(20 * 60 + 2 * 60 - 10, "mid", "en") is None


def test_every_event_has_both_languages():
    for event in timers()["events"]:
        assert event["en"] and event["uk"] and event["hint_en"] and event["hint_uk"], event["id"]
        assert set(event["roles"]) <= {"carry", "mid", "offlane", "support"}


def test_support_tips_stack_and_wards():
    tips = RoleTips()
    stack = tips.tip(7 * 60 + 45, "support", alive=True, has_ward=True, lang="uk")
    assert stack["title"] == "Застакайте табір" and stack["at_label"] == "7:53"
    assert stack["in_seconds"] == 8
    assert tips.tip(7 * 60 + 45, "carry", alive=True, has_ward=False, lang="en") is None
    assert tips.tip(7 * 60 + 45, "support", alive=False, has_ward=False, lang="en") is None
    # No ward: shown for 20 s, then again 5 minutes later.
    assert tips.tip(300, "support", alive=True, has_ward=False, lang="en")["id"] == "wards@300"
    assert tips.tip(315, "support", alive=True, has_ward=False, lang="en") is not None
    assert tips.tip(330, "support", alive=True, has_ward=False, lang="en") is None
    assert tips.tip(600, "support", alive=True, has_ward=False, lang="en")["id"] == "wards@600"
    assert tips.tip(900, "support", alive=True, has_ward=None, lang="en") is None  # unknown
    # A tip wins over a minor timer (runes), a major timer over a tip.
    hint = map_hint(4 * 60 - 10, "support", RoleTips(), alive=True, has_ward=True, lang="en")
    assert hint["kind"] == "timer" and hint["title"] == "Bounty runes"
    hint = map_hint(7 * 60 + 45, "support", RoleTips(), alive=True, has_ward=True, lang="en")
    assert hint["title"] == "Stack a camp"  # not the 8:00 power rune
    hint = map_hint(20 * 60 - 10, "support", RoleTips(), alive=True, has_ward=False, lang="en")
    assert hint["title"] == "Tormentor"
    # Nothing without a role or before the horn.
    assert map_hint(-30, "support", RoleTips(), alive=True, has_ward=False, lang="en") is None
    assert map_hint(600, None, RoleTips(), alive=True, has_ward=False, lang="en") is None


def test_observer_ward_in_the_raw_items():
    assert has_observer_ward({"slot0": {"name": "item_ward_observer"}}) is True
    assert has_observer_ward({"slot1": {"name": "item_ward_dispenser"}}) is True
    assert has_observer_ward({"stash0": {"name": "item_ward_observer"}}) is False
    assert has_observer_ward({"slot0": {"name": "empty"}}) is False
    assert has_observer_ward(None) is None


def _play_until(client, payloads, clock):
    last = None
    for payload in payloads:
        if payload["map"]["clock_time"] > clock:
            break
        client.post("/gsi", json=payload)
        last = client.get("/overlay/recommendation?lang=uk").json()
    return last


def test_live_support_gets_timers_and_tips_through_the_api(client):
    # Juggernaut played as a support: bottom (Radiant safe) lane, 1 LH per minute.
    stream = gsi_match_stream(
        match_id=MATCH_ID, minutes=9, lh_per_minute=1.0, death_minutes=(), positions=True
    )
    for payload in stream:
        payload["items"] = {"slot0": {"name": "item_tango"}}
    answer = _play_until(client, stream, 6 * 60 + 30)
    assert answer["live_role"] == {"role": "support", "source": "lane", "lane": "safe"}
    assert MATCH_MEMORY.role.role()["role"] == "support"
    # 6:45: the wisdom shrine is 15 s away.
    rest = [p for p in stream if p["map"]["clock_time"] > 6 * 60 + 30]
    answer = _play_until(client, rest, 6 * 60 + 45)
    assert answer["map_hint"]["title"] == "Святилище мудрості"
    assert answer["map_hint"]["in_seconds"] == 15
    # 7:45: stack the camp (wins over the 8:00 power rune).
    rest = [p for p in stream if p["map"]["clock_time"] > 6 * 60 + 45]
    answer = _play_until(client, rest, 7 * 60 + 45)
    assert answer["map_hint"]["title"] == "Застакайте табір"
    status = client.get("/gsi/status").json()
    assert status["live_role"]["role"] == "support"
    # Hints off in the launcher: no hint, the role is still there.
    client.post("/settings/advice", json={"map_hints": False})
    answer = client.get("/overlay/recommendation").json()
    assert "map_hint" not in answer and answer["live_role"]["role"] == "support"


def test_a_carry_gets_only_shared_timers(client):
    stream = gsi_match_stream(match_id=MATCH_ID, minutes=21, death_minutes=(), positions=True)
    _play_until(client, stream, 6 * 60 + 30)
    assert MATCH_MEMORY.role.role()["role"] == "carry"
    power = [p for p in stream if 6 * 60 + 30 < p["map"]["clock_time"] <= 8 * 60 - 10]
    answer = _play_until(client, power, 8 * 60 - 10)
    assert "map_hint" not in answer  # the 8:00 power rune is not a carry timer
    late = copy.deepcopy([p for p in stream if 8 * 60 - 10 < p["map"]["clock_time"] <= 1190])
    answer = _play_until(client, late, 1190)
    assert answer["map_hint"]["title"] == "Торментор"


def test_a_carry_hero_played_as_support_gets_no_farm_advice(client):
    stream = gsi_match_stream(
        match_id=MATCH_ID, minutes=16, lh_per_minute=1.0, death_minutes=(), positions=True
    )
    shown = set()
    for payload in stream:
        client.post("/gsi", json=payload)
        answer = client.get("/overlay/recommendation").json()
        if answer.get("recommendation") and payload["map"]["clock_time"] > 4 * 60:
            shown.add(answer["decision_point"])
    assert MATCH_MEMORY.role.role()["role"] == "support"
    assert not shown & {"LANING_FARM_CHECK", "FARMING_PHASE_PRESSURE", "SAFE_FARMING"}


def test_tp_and_last_hit_tips():
    tips = RoleTips()
    # Without the carry advisor (a support, a hero outside it) the TP tip shows...
    tp = tips.tip(900, "offlane", alive=True, has_ward=None, lang="uk", tp_missing=True)
    assert tp["title"] == "Немає сувою телепортації"
    # ...but the carry advisor has its own TP advice.
    assert (
        RoleTips().tip(
            900, "carry", alive=True, has_ward=None, lang="en", tp_missing=True, carry_advisor=True
        )
        is None
    )
    # A support with 15 last hits at 5:00 (3 per minute) is taking the carry's farm.
    lh = RoleTips().tip(300, "support", alive=True, has_ward=True, lang="en", last_hits=15)
    assert lh["title"] == "Leave the last hits to your carry"
    assert RoleTips().tip(300, "support", alive=True, has_ward=True, lang="en", last_hits=5) is None


def test_level_six_tip_for_mid_and_offlane_once_before_minute_twelve():
    tips = RoleTips()

    def hint(clock, role="mid", level=6):
        return map_hint(clock, role, tips, alive=True, has_ward=None, lang="uk", level=level)

    # Level 5: nothing yet (the minute is chosen away from any timer).
    assert hint(7 * 60 + 30, level=5) is None
    first = hint(7 * 60 + 31)
    assert first["id"] == "mid_six@451" and first["title"] == "6-й рівень: час ротації"
    assert hint(7 * 60 + 50)["id"] == "mid_six@451"  # shown for 25 s
    # Then never again this match (a rune timer may still show).
    for clock in (7 * 60 + 58, 9 * 60 + 30):
        again = hint(clock)
        assert again is None or not again["id"].startswith("mid_six")
    other = RoleTips()
    assert (
        map_hint(13 * 60 + 30, "mid", other, alive=True, has_ward=None, lang="en", level=6) is None
    )  # after 12:00 it is no longer a spike
    offlane = RoleTips()
    # First seen at level 7 (the app started mid-game): not a new spike.
    late = map_hint(7 * 60 + 30, "offlane", offlane, alive=True, has_ward=None, lang="en", level=7)
    assert late is None or not late["id"].startswith("offlane_six")
    fresh = RoleTips()
    map_hint(6 * 60 + 50, "offlane", fresh, alive=True, has_ward=None, lang="en", level=5)
    off = map_hint(7 * 60 + 30, "offlane", fresh, alive=True, has_ward=None, lang="en", level=6)
    assert off["title"] == "Level 6: pressure the lane"
    carry = map_hint(
        7 * 60 + 30, "carry", RoleTips(), alive=True, has_ward=None, lang="en", level=6
    )
    assert carry is None or not carry["id"].startswith(("mid_six", "offlane_six"))


def test_mid_last_hit_pace_and_bottle():
    tips = RoleTips()
    slow = tips.tip(300, "mid", alive=True, has_ward=None, lang="uk", last_hits=14)
    assert slow["title"] == "14 добивань до 5:00" and "25+" in slow["hint"]
    # The count of the first second stays on the card while it is shown.
    assert tips.tip(310, "mid", alive=True, has_ward=None, lang="uk", last_hits=16)["title"] == (
        "14 добивань до 5:00"
    )
    assert tips.tip(330, "mid", alive=True, has_ward=None, lang="uk", last_hits=16) is None
    assert RoleTips().tip(300, "mid", alive=True, has_ward=None, lang="en", last_hits=28) is None
    late = RoleTips().tip(480, "mid", alive=True, has_ward=None, lang="en", last_hits=30)
    assert late["title"] == "30 last hits by 8:00"
    few = RoleTips().tip(480, "mid", alive=True, has_ward=None, lang="uk", last_hits=24)
    assert few["title"] == "24 добивання до 8:00"
    one = RoleTips().tip(300, "mid", alive=True, has_ward=None, lang="uk", last_hits=21)
    assert one["title"] == "21 добивання до 5:00"
    # No Bottle between 3:30 and 6:00: once per match.
    bottle = RoleTips()
    first = bottle.tip(220, "mid", alive=True, has_ward=None, lang="en", items=["item_tango"])
    assert first["title"] == "No Bottle yet"
    assert (
        bottle.tip(250, "mid", alive=True, has_ward=None, lang="en", items=["item_tango"]) is None
    )
    assert (
        RoleTips().tip(220, "mid", alive=True, has_ward=None, lang="en", items=["item_bottle"])
        is None
    )
    assert RoleTips().tip(220, "mid", alive=True, has_ward=None, lang="en", items=None) is None


def test_a_mid_with_a_power_rune_still_bottled_is_told_to_use_it_first():
    for lang, text in (("en", "still holds a Haste rune"), ("uk", "лежить руна прискорення")):
        rune = map_hint(
            8 * 60 - 10,
            "mid",
            RoleTips(),
            alive=True,
            has_ward=None,
            lang=lang,
            level=7,
            items=["item_bottle"],
            bottle_rune="Haste",
        )
        assert rune["id"].startswith("power_rune@") and text in rune["hint"]
    # A Regeneration rune in the Bottle is no reason: the usual rotation text.
    regen = map_hint(
        8 * 60 - 10,
        "mid",
        RoleTips(),
        alive=True,
        has_ward=None,
        lang="en",
        level=7,
        items=["item_bottle"],
        bottle_rune="Regeneration",
    )
    assert "side lane" in regen["hint"]


def test_the_power_rune_is_a_rotation_for_a_mid_with_level_six():
    early = map_hint(8 * 60 - 10, "mid", RoleTips(), alive=True, has_ward=None, lang="en", level=5)
    assert early["title"] == "Power rune" and "rotate" not in early["hint"]
    tips = RoleTips()
    tips.observe_level(5)
    tips._shown["mid_six"] = 0  # the level-6 tip was already shown
    rune = map_hint(8 * 60 - 10, "mid", tips, alive=True, has_ward=None, lang="uk", level=6)
    assert rune["title"] == "Руна сили" and "бокову лінію" in rune["hint"]
    # Before level 6 with a Bottle: keep the rune in it.
    bottled = map_hint(
        8 * 60 - 10,
        "mid",
        RoleTips(),
        alive=True,
        has_ward=None,
        lang="uk",
        level=5,
        items=["item_bottle"],
    )
    assert bottled["title"] == "Руна сили" and "пляшку" in bottled["hint"]
    # No level in GSI: the plain rune hint, never the pre-six Bottle one.
    unknown = map_hint(
        8 * 60 - 10,
        "mid",
        RoleTips(),
        alive=True,
        has_ward=None,
        lang="uk",
        level=None,
        items=["item_bottle"],
    )
    assert unknown["hint"] == "На одній із точок рун у річці."
    # A Bottle at level 6 does not undo the rotation.
    rotate = map_hint(
        8 * 60 - 10,
        "mid",
        tips,
        alive=True,
        has_ward=None,
        lang="en",
        level=6,
        items=["item_bottle"],
    )
    assert "rotate" in rotate["hint"]


def test_offlane_hard_lane_once():
    tips = RoleTips()

    def hint(clock, deaths=0, level=5):
        return tips.tip(
            clock, "offlane", alive=True, has_ward=None, lang="uk", deaths=deaths, level=level
        )

    assert hint(4 * 60 + 30, deaths=1) is None
    first = hint(4 * 60 + 40, deaths=2)
    assert first["title"] == "Важка лінія" and first["id"] == "offlane_hard_lane@280"
    assert hint(4 * 60 + 60, deaths=2) is not None  # 25 s on screen
    assert hint(5 * 60 + 30, deaths=3) is None  # once per match
    # Level 4 at 6:00 without deaths is a lost lane too; level 5 is not.
    assert RoleTips().tip(
        6 * 60 + 5, "offlane", alive=True, has_ward=None, lang="en", deaths=0, level=4
    )["title"] == ("A hard lane")
    assert (
        RoleTips().tip(
            6 * 60 + 5, "offlane", alive=True, has_ward=None, lang="en", deaths=0, level=5
        )
        is None
    )
    # After 9:00 it is no longer about the lane.
    assert (
        RoleTips().tip(10 * 60, "offlane", alive=True, has_ward=None, lang="en", deaths=3, level=4)
        is None
    )


def test_support_pull_in_the_safe_lane_and_unspent_gold():
    tips = RoleTips()
    pull = tips.tip(3 * 60 + 36, "support", alive=True, has_ward=True, lang="uk", lane="safe")
    assert pull["title"] == "Пул о 3:45" and pull["in_seconds"] == 9
    # At most every two minutes, and only in the safe lane.
    assert (
        tips.tip(4 * 60 + 6, "support", alive=True, has_ward=True, lang="uk", lane="safe") is None
    )
    assert (
        RoleTips().tip(3 * 60 + 36, "support", alive=True, has_ward=True, lang="en", lane="off")
        is None
    )
    assert RoleTips().tip(3 * 60 + 36, "support", alive=True, has_ward=True, lang="en") is None
    # Unspent gold moved to app/gold_tips.py (any role): no role tip for it.
    assert (
        RoleTips().tip(9 * 60, "support", alive=True, has_ward=True, lang="en", gold=1680) is None
    )


def test_item_names_from_the_raw_items():
    items = {
        "slot0": {"name": "item_bottle", "charges": 2},
        "slot1": {"name": "empty"},
        "stash0": {"name": "item_boots"},
        "teleport0": {"name": "item_tpscroll"},
        "neutral0": {"name": "item_trusty_shovel"},
        "slot2": {"name": ["broken"]},
    }
    assert item_names(items) == ["item_bottle", "item_boots"]
    assert item_names({}) is None and item_names("x") is None


MAELSTROM = {"key": "maelstrom", "name": "Maelstrom", "typical_t": 20 * 60}


def test_the_key_item_late_or_early_once():
    tips = RoleTips()

    def hint(clock, items, role="carry"):
        return tips.tip(
            clock, role, alive=True, has_ward=None, lang="uk", items=items, key_item=MAELSTROM
        )

    assert hint(21 * 60, ["item_power_treads"]) is None  # within the 2 minutes
    late = hint(22 * 60, ["item_power_treads"])
    assert late["title"] == "Maelstrom запізнюється" and "до 20:00" in late["hint"]
    assert hint(22 * 60 + 20, ["item_power_treads"]) is not None  # 25 s on screen
    assert hint(23 * 60, ["item_power_treads"]) is None  # once per match
    # Two minutes ahead: "your window", once.
    early = RoleTips().tip(
        17 * 60,
        "mid",
        alive=True,
        has_ward=None,
        lang="en",
        items=["item_maelstrom"],
        key_item=MAELSTROM,
    )
    assert early["title"] == "Maelstrom ahead of time"
    # Bought on time: nothing now, and never "late" afterwards.
    on_time = RoleTips()
    assert (
        on_time.tip(
            19 * 60,
            "carry",
            alive=True,
            has_ward=None,
            lang="en",
            items=["item_maelstrom"],
            key_item=MAELSTROM,
        )
        is None
    )
    assert (
        on_time.tip(
            23 * 60,
            "carry",
            alive=True,
            has_ward=None,
            lang="en",
            items=["item_mjollnir"],
            key_item=MAELSTROM,
        )
        is None
    )
    # Supports and unknown items: no timing tip.
    assert (
        RoleTips().tip(
            23 * 60, "support", alive=True, has_ward=True, lang="en", items=[], key_item=MAELSTROM
        )
        is None
    )
    assert (
        RoleTips().tip(
            23 * 60, "carry", alive=True, has_ward=None, lang="en", items=None, key_item=MAELSTROM
        )
        is None
    )


def test_a_missing_level_is_not_a_hard_lane(client):
    """GSI without hero.level: the state's level falls back to 1, which used to read
    as "level 1 at 6:10" and gave every offlaner «A hard lane"."""
    set_role_setting("offlane")
    stream = gsi_match_stream(match_id=MATCH_ID, minutes=8, death_minutes=(), positions=True)
    for payload in stream:
        payload["hero"].pop("level", None)
        payload["items"] = {"slot0": {"name": "item_tango"}}
    answer = _play_until(client, stream, 6 * 60 + 10)
    hint = answer.get("map_hint") or {}
    assert not str(hint.get("id", "")).startswith("offlane_hard_lane")
    set_role_setting("auto")


def test_a_chosen_support_knows_its_lane_before_three_minutes():
    tracker = LiveRoleTracker()
    set_role_setting("support")
    _lane(tracker, _world(4000, -6500), 1, until=2 * 60)
    assert tracker.role() == {"role": "support", "source": "setting", "lane": "safe"}
    set_role_setting("auto")


def test_the_timer_strip_shows_the_next_events_of_the_position():
    from app.map_hints import timer_strip

    support = timer_strip(5 * 60 + 10, "support", "uk")
    assert [(row["label"], row["in_seconds"]) for row in support] == [
        ("Руна", 50),
        ("Лотос", 50),
        ("Мудрість", 110),
    ]
    # A carry has only the shared timers; a stack is a support's.
    assert [row["kind"] for row in timer_strip(19 * 60, "carry", "en")] == ["tormentor"]
    assert timer_strip(-20, "mid", "en") == [] and timer_strip(300, None, "en") == []
    stack = timer_strip(7 * 60 + 40, "support", "en")
    assert stack[0]["kind"] == "stack" and stack[0]["at_label"] == "7:53"


def test_roshan_and_the_aegis_lead_the_strip():
    from app.map_hints import timer_strip
    from app.roshan_timer import RoshanTimer

    roshan = RoshanTimer()
    roshan.killed_at = 20 * 60
    roshan.aegis_at = 20 * 60 + 5
    items = timer_strip(22 * 60, "carry", "en", roshan.strip(22 * 60, "en"))
    # Roshan and the Aegis first, then the next shared timer (tier 3 at 25:00).
    assert [row["kind"] for row in items] == ["aegis", "roshan", "neutral_tier_3"]
    assert items[0]["at_label"] == "25:05"
    assert items[1]["at_label"] == "28:00" and items[1]["until_label"] == "31:00"
    # Inside the window: «Roshan?» until it closes; after that, nothing.
    assert [row["kind"] for row in roshan.strip(29 * 60, "en")] == ["roshan_maybe"]
    assert roshan.strip(32 * 60, "en") == []


def test_a_rune_card_points_at_the_spot_nearest_to_the_player():
    from app.live_hints import _with_player_dot
    from app.map_hints import MAP_CENTER, map_point, next_timer

    rune = next_timer(355, "mid", "en")
    assert rune is not None and rune["id"] == "power_rune@360" and "marker" not in rune
    top, bottom = (-1640 + MAP_CENTER, 1112 + MAP_CENTER), (1180 + MAP_CENTER, -1216 + MAP_CENTER)
    near_bottom = {"xpos": bottom[0] + 400, "ypos": bottom[1] - 300}
    shown = _with_player_dot(rune, near_bottom)
    assert shown["marker"] == {
        "target": map_point(*bottom),
        "others": [map_point(*top)],  # a power rune is on one of the two
        "kind": "power_rune",
        "player": map_point(near_bottom["xpos"], near_bottom["ypos"]),
    }
    assert _with_player_dot(rune, {"xpos": top[0], "ypos": top[1]})["marker"][
        "target"
    ] == map_point(*top)
    assert "marker" not in rune  # the card itself is not changed

    # No position (dead, a replay without one): the spots still show, no player dot.
    blind = _with_player_dot(rune, {})["marker"]
    assert blind["player"] is None and len([blind["target"], *blind["others"]]) == 2


def test_every_timer_with_a_place_has_its_spots_on_the_map():
    from app.map_hints import MAP_CENTER, map_point, timers

    events = {event["id"]: event for event in timers()["events"]}
    for event_id in (
        "water_rune",
        "power_rune",
        "bounty_rune",
        "wisdom_shrine",
        "lotus",
        "tormentor",
    ):
        spots = events[event_id]["spots"]
        assert len(spots) == 2, event_id
        assert all(map_point(x + MAP_CENTER, y + MAP_CENTER) for x, y in spots), event_id
    # Neutral items have no place: their card stays without a map.
    assert "spots" not in events["neutral_tier_2"]


def test_a_card_with_its_own_place_keeps_it():
    from app.map_hints import with_spot_marker

    farm = {
        "kind": "timer",
        "id": "power_rune@360",
        "marker": {"target": [0.1, 0.1], "kind": "farm"},
    }
    assert with_spot_marker(farm, 1, 1) is farm
    assert with_spot_marker({"kind": "timer", "id": "neutral_tier_2@900"}, 1, 1) == {
        "kind": "timer",
        "id": "neutral_tier_2@900",
    }
    assert with_spot_marker({"kind": "tip", "id": "power_rune@360"}, 1, 1) == {
        "kind": "tip",
        "id": "power_rune@360",
    }
