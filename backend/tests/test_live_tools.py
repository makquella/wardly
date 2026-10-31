"""Survival advice names the tool that can be pressed right now (app/live_tools.py)."""

from __future__ import annotations

import copy

from match_fixtures import gsi_match_stream

from app.advice_i18n import translate_uk
from app.gsi_state import normalize_gsi_payload
from app.live_tools import (
    INSURANCE_COPY,
    death_items_reason,
    disabled_copy,
    hero_tools,
    insurance_copy,
    low_hp_copy,
    regen_items,
)
from app.player_api import PLAYER_SERVICE
from app.recommender import _fallback_text
from app.schemas import GameSituationRequest

READY = {"can_cast": True, "cooldown": 0}
WAND = {"name": "item_magic_wand", "charges": 14, **READY}
FORCE = {"name": "item_force_staff", **READY}
BKB = {"name": "item_black_king_bar", **READY}
MANTA = {"name": "item_manta", **READY}
SALVE = {"name": "item_flask", "charges": 1, **READY}


def _extra(*items, abilities=None, hero="npc_dota_hero_juggernaut", **flags):
    raw = {f"slot{i}": item for i, item in enumerate(items)}
    payload = copy.deepcopy(gsi_match_stream(minutes=20, death_minutes=())[-1])
    payload["items"] = raw
    payload["hero"]["name"] = hero
    if abilities is not None:
        payload["abilities"] = abilities
    return normalize_gsi_payload(payload)["extra_context"] | flags


def test_low_hp_names_an_escape_first_then_a_heal_then_regen():
    action, reason = low_hp_copy(_extra(WAND, FORCE))
    assert action == "Use Force Staff now to get out, then reset HP."
    action, reason = low_hp_copy(_extra(WAND, SALVE))
    assert action == "Use Magic Wand now, then step back."
    assert reason == "Magic Wand has 14 charges: that HP is yours right now."
    action, _ = low_hp_copy(_extra(SALVE))
    assert action == "Step out of enemy range and use Healing Salve."
    # A wand with few charges or a force staff on cooldown is not "ready".
    assert low_hp_copy(_extra({**WAND, "charges": 3}, {**FORCE, "cooldown": 12})) is None
    # No items block in GSI: nothing is claimed.
    assert low_hp_copy({"ready_savers": None}) is None


def test_a_disable_names_what_removes_it_or_gets_out_after_it():
    action, reason = disabled_copy(_extra(BKB, stunned=True))
    assert action == "The moment the disable ends, use Black King Bar."
    # A silence alone does not stop items: dispel it now.
    action, _ = disabled_copy(_extra(MANTA, silenced=True))
    assert action == "Use Manta Style now: it removes the silence."
    assert disabled_copy(_extra(WAND, stunned=True)) is None  # nothing that helps
    assert disabled_copy(_extra(BKB)) is None  # not disabled


def test_a_low_hp_card_under_a_stun_names_the_tool_for_after_it():
    """A stunned and hexed Terrorblade at 28:13 was told «Leave the wave now»."""
    from app.advice_text import clean_action_text, clean_reason_text

    action, reason = low_hp_copy(_extra(MANTA, stunned=True))
    assert action == "The moment the disable ends, use Manta Style."
    assert clean_action_text(action, "LOW_HP") == action
    assert clean_reason_text(reason, "LOW_HP") == reason
    assert translate_uk(action) != action


def test_regen_needs_a_usable_item():
    assert regen_items({"slot0": {"name": "item_bottle", "charges": 0}}) == []
    assert regen_items({"slot0": {"name": "item_bottle", "charges": 2}}) == ["item_bottle"]
    assert regen_items({}) is None


def _request(extra, hero="Juggernaut"):
    payload = copy.deepcopy(gsi_match_stream(minutes=20, death_minutes=())[-1])
    state = normalize_gsi_payload(payload)
    return GameSituationRequest(**{**state, "hero": hero, "hp_percent": 15, "extra_context": extra})


def test_the_cards_use_the_tools_and_keep_the_plain_text_without_them():
    text = _fallback_text(_request(_extra(WAND)), "retreat_reset")
    assert text["action"] == "Use Magic Wand now, then step back."
    plain = _fallback_text(_request(_extra()), "retreat_reset")
    assert "Magic Wand" not in plain["action"]
    stunned = _fallback_text(_request(_extra(BKB, stunned=True)), "wait_out_disable")
    assert stunned["action"] == "The moment the disable ends, use Black King Bar."
    assert (
        _fallback_text(_request(_extra(stunned=True)), "wait_out_disable")["action"]
        == "Wait out the disable and avoid forcing actions."
    )


def test_the_death_review_says_which_item_was_left_unpressed():
    extra = _extra() | {"death_items": ["item_black_king_bar"]}
    text = _fallback_text(_request(extra), "plan_safer_respawn_route")
    assert text["reason"] == (
        "You died with Black King Bar ready: next time use it at the first big hit."
    )
    assert death_items_reason({"death_items": ["not_an_item"]}) is None


def test_the_last_death_of_the_live_match_names_its_unpressed_item():
    stream = gsi_match_stream(death_minutes=(18,), step_seconds=1, minutes=19)
    for payload in stream:
        before = 18 * 60 - payload["map"]["clock_time"]
        if 0 < before <= 6:
            payload["hero"]["health_percent"] = 12 * before
            payload["items"]["slot5"] = dict(BKB)
        PLAYER_SERVICE.tracker.observe(payload)
        if payload["map"]["clock_time"] == 18 * 60 + 5:
            death = PLAYER_SERVICE.recent_death(18 * 60 + 5)
            assert death["items"] == ["item_black_king_bar"]
    assert PLAYER_SERVICE.recent_death(18 * 60 + 200) is None  # long ago
    assert PLAYER_SERVICE.recent_death(None) is None


def test_the_live_card_through_gsi(client):
    payload = copy.deepcopy(gsi_match_stream(minutes=20, death_minutes=())[-1])
    payload["hero"]["health_percent"] = 12
    payload["hero"]["health"] = 200
    payload["items"]["slot4"] = dict(WAND)
    client.post("/gsi", json=payload)
    body = client.get("/overlay/recommendation").json()
    assert body["recommendation"]["action"] == "Use Magic Wand now, then step back."
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()["recommendation"]
    assert ukrainian["action"] == "Натисніть Magic Wand зараз і відійдіть."


def test_every_new_text_has_ukrainian():
    texts = [
        "Use Force Staff now to get out, then reset HP.",
        "Your HP is low and Force Staff is ready: use it before the next hit, not after.",
        "Use Magic Wand now, then step back.",
        "Magic Wand has 14 charges: that HP is yours right now.",
        "Magic Wand is charged: that HP is yours right now.",
        "Guardian Greaves is ready and heals you at once.",
        "Faerie Fire heals you at once.",
        "Step out of enemy range and use Healing Salve.",
        "Consider: step out of enemy range and use Healing Salve.",
        "Healing Salve heals over time: use it where enemies cannot hit you.",
        "Use Manta Style now: it removes the silence.",
        "A silence does not stop items: get rid of it before the next spell lands.",
        "The moment the disable ends, use Black King Bar.",
        "Black King Bar is ready: the second after a disable is when most kills finish.",
        "You died with Eul's Scepter ready: next time use it at the first big hit.",
        "Use Doppelganger now to get out, then Magic Wand.",
        "Your HP is low and Doppelganger is ready: use it before the next hit. "
        "Magic Wand has 12 charges: press it on the way out.",
        "After your kill: hold the next engage until Doppelganger is back in 5 s.",
        "Second life: hold the next engage until Doppelganger is back in 3 s.",
    ]
    for text in texts:
        assert translate_uk(text), text


def _feed_until(client, clock, **stream_args):
    for payload in gsi_match_stream(positions=True, **stream_args):
        if payload["map"]["clock_time"] > clock:
            break
        client.post("/gsi", json=payload)


def test_repeated_deaths_in_one_place_are_named(client):
    # The fixture's Radiant Juggernaut dies at 18:00, 19:00 and 20:00 at (3600, 3200):
    # next to the mid lane on the Dire half.
    _feed_until(client, 19 * 60 + 5, death_minutes=(18, 19, 20), minutes=21)
    death = PLAYER_SERVICE.recent_death(19 * 60 + 5)
    assert death["place"] == {
        "zone": "mid",
        "side": "enemy",
        "count": 2,
        "minutes": 1,
        "in_match": 2,
    }
    body = client.get("/overlay/recommendation").json()
    assert body["recommendation"]["action"] == (
        "After respawn, stay away from the mid lane on the enemy side."
    )
    assert body["recommendation"]["reason"] == (
        "2 deaths in the mid lane on the enemy side in 1 minute: "
        "farm somewhere safer until your team is there."
    )
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()["recommendation"]
    assert (
        ukrainian["action"]
        == "Після відродження тримайтеся подалі від центральної лінії на половині ворога."
    )
    assert ukrainian["reason"].startswith(
        "2 смерті на центральній лінії на половині ворога за 1 хв"
    )


def test_one_death_on_the_enemy_half_says_to_farm_your_own():
    extra = _extra() | {"death_place": {"zone": "top", "side": "enemy", "count": 1, "minutes": 1}}
    text = _fallback_text(_request(extra), "plan_safer_respawn_route")
    # The route card says it in the action; the reason stays for other lessons.
    assert text["action"] == (
        "After respawn, farm your own half: you died in the top lane on the enemy side."
    )
    assert "enemy side" not in text["reason"]
    # The escape card keeps its action, so the place goes to the reason.
    text = _fallback_text(_request(extra), "respect_escape_cooldown_after_respawn")
    assert text["reason"] == (
        "You died in the top lane on the enemy side: "
        "farm your own half until your team is with you."
    )
    # One death on your own side: the place is in the action, not the reason.
    own = _extra() | {"death_place": {"zone": "top", "side": "own", "count": 1, "minutes": 1}}
    assert "top lane" not in _fallback_text(_request(own), "plan_safer_respawn_route")["reason"]
    # The unpressed item is the lesson and wins the reason; the place keeps the action.
    both = _extra() | {
        "death_items": ["item_black_king_bar"],
        "death_place": {"zone": "mid", "side": "river", "count": 3, "minutes": 6},
    }
    text = _fallback_text(_request(both), "break_repeated_death_pattern")
    assert text["action"] == "After respawn, stay away from the mid lane by the river."
    assert text["reason"].startswith("You died with Black King Bar ready")


def test_the_first_death_says_where_or_how_it_happened():
    """The first death card named nothing («plan a safer route»): now the lane,
    the part of the map or how fast the kill came."""
    from app.advice_i18n import translate_uk

    def action(extra):
        return _fallback_text(_request(_extra() | extra), "plan_safer_respawn_route")["action"]

    lane = {"death_place": {"zone": "bot", "side": "own", "count": 1, "minutes": 1}}
    laning = action(lane | {"clock_time": 420})
    assert laning == (
        "After respawn, play the bottom lane closer to your tower until you see the enemy heroes."
    )
    assert translate_uk(laning) == (
        "Після відродження грайте на нижній лінії ближче до своєї вежі, доки не побачите ворожих героїв."
    )
    later = action(lane | {"clock_time": 1500})
    assert (
        later
        == "After respawn, avoid the bottom lane on your side without your team: you died there."
    )
    assert translate_uk(later) == (
        "Після відродження не ходіть на нижню лінію на своїй половині без команди: ви загинули там."
    )
    jungle = action(
        {"death_place": {"zone": "jungle", "side": "river", "count": 1, "minutes": 1}}
        | {"clock_time": 420}
    )
    assert (
        jungle == "After respawn, avoid the jungle by the river without your team: you died there."
    )
    assert translate_uk(jungle).startswith(
        "Після відродження не ходіть до лісу біля річки без команди"
    )
    enemy = action({"death_place": {"zone": "mid", "side": "enemy", "count": 1, "minutes": 1}})
    assert translate_uk(enemy) == (
        "Після відродження фарміть на своїй половині: ви загинули на центральній лінії на половині ворога."
    )
    # No place known (the base, or no position): how fast it came.
    burst = action({"death_burst": 2})
    assert burst == (
        "After respawn, stay near your towers or your team: you went down in 2 seconds from high HP."
    )
    assert translate_uk(burst) == (
        "Після відродження тримайтеся біля своїх веж або поруч із командою: вас убили за 2 с з високого здоров'я."
    )
    assert action({"death_burst": 1}).endswith("in 1 second from high HP.")
    # Nothing known: the card as it was.
    assert not action({}).startswith("After respawn")
    # The escape card keeps its own action.
    kept = _fallback_text(_request(_extra() | lane), "respect_escape_cooldown_after_respawn")
    assert "bottom lane" not in kept["action"]


def test_recent_death_passes_the_burst(client, monkeypatch):
    from app.main import _with_death_items

    monkeypatch.setattr(
        PLAYER_SERVICE,
        "recent_death",
        lambda clock: {"items": [], "place": None, "recent": None, "burst": 2},
    )
    state = {"extra_context": {"clock_time": 400}}
    assert _with_death_items(state, "DEATH_REVIEW")["extra_context"]["death_burst"] == 2


def test_deaths_in_different_places_are_counted():
    from app.player_service import _recent_deaths

    assert _recent_deaths([{"t": 600}], 600) is None
    # 20:00 is outside ten minutes of 31:00; 25:00 and 31:00 count.
    assert _recent_deaths([{"t": 1200}, {"t": 1500}, {"t": 1860}], 1860) == {
        "count": 2,
        "minutes": 6,
    }
    # Deaths in different places are several events, not one route: a count
    # alone names no route to change, so the line of this death speaks.
    extra = _extra() | {
        "death_place": {"zone": "top", "side": "own", "count": 1, "minutes": 1},
        "recent_deaths": {"count": 3, "minutes": 7},
    }
    text = _fallback_text(_request(extra), "break_repeated_death_pattern")
    assert "change your route" not in text["action"]
    assert text["action"].startswith("After respawn,")
    spread = _extra() | {"match_deaths": 4}
    text = _fallback_text(_request(spread), "break_repeated_death_pattern")
    assert "4 deaths" not in text["action"]
    # The escape and resource cards keep their own action.
    for action_type in ("respect_escape_cooldown_after_respawn", "reset_before_resources_collapse"):
        kept = _fallback_text(_request(spread), action_type)["action"]
        assert "change your route" not in kept
    # The same place wins: it says where not to go.
    same = extra | {"death_place": {"zone": "mid", "side": "river", "count": 2, "minutes": 3}}
    assert "stay away" in _fallback_text(_request(same), "break_repeated_death_pattern")["action"]


def test_the_game_total_comes_from_the_game(client, monkeypatch):
    from app.main import _with_death_items

    monkeypatch.setattr(
        PLAYER_SERVICE, "recent_death", lambda clock: {"items": [], "place": None, "recent": None}
    )
    # The recording saw 1 death (the app started mid-match); Dota says 6.
    state = {"extra_context": {"clock_time": 1500, "deaths": 6}}
    extra = _with_death_items(state, "REPEATED_DEATH_PATTERN")["extra_context"]
    assert extra["match_deaths"] == 6
    no_count = _with_death_items({"extra_context": {"clock_time": 1500}}, "DEATH_REVIEW")
    assert no_count["extra_context"]["match_deaths"] is None


def test_satanic_is_not_an_instant_heal():
    """Satanic heals through lifesteal while attacking: never «press it and step back»."""
    satanic = {"name": "item_satanic", **READY}
    copy_ = low_hp_copy(_extra(satanic))
    assert copy_ is None or "Satanic" not in copy_[0]
    greaves = {"name": "item_guardian_greaves", **READY}
    assert low_hp_copy(_extra(greaves))[0] == "Use Guardian Greaves now, then step back."


def test_low_hp_while_stunned_waits_for_the_disable_to_end():
    """No item can be pressed while stunned, hexed or muted."""
    for flag in ("stunned", "hexed", "muted"):
        action, _ = low_hp_copy(_extra(FORCE, **{flag: True}))
        assert action == "The moment the disable ends, use Force Staff."
    assert low_hp_copy(_extra(WAND, stunned=True)) is None  # a wand is no way out of a stun


def _ability(name, cooldown=0, level=1, can_cast=True):
    return {
        "name": name,
        "level": level,
        "can_cast": can_cast,
        "passive": False,
        "ability_active": True,
        "cooldown": cooldown,
        "ultimate": False,
    }


BLADE_FURY = {"ability0": _ability("juggernaut_blade_fury")}


def test_the_heros_own_ability_comes_before_items():
    extra = _extra(FORCE, abilities=BLADE_FURY)
    assert low_hp_copy(extra, "Juggernaut") == (
        "Use Blade Fury now and walk out of the fight.",
        "Blade Fury is ready: it buys you the seconds to get away.",
    )
    blink = {"ability0": _ability("antimage_blink")}
    extra = _extra(abilities=blink, hero="npc_dota_hero_antimage")
    assert low_hp_copy(extra, "Anti-Mage")[0] == "Use Blink now to get out, then reset HP."
    # On cooldown or not learned: the items decide.
    on_cooldown = _extra(FORCE, abilities={"ability0": _ability("juggernaut_blade_fury", 7)})
    assert low_hp_copy(on_cooldown, "Juggernaut")[0].startswith("Use Force Staff")
    unlearned = _extra(abilities={"ability0": _ability("juggernaut_blade_fury", level=0)})
    assert low_hp_copy(unlearned, "Juggernaut") is None


def test_hero_tools_reads_cooldowns_and_skips_passives():
    extra = _extra(abilities={"ability0": _ability("antimage_blink", 5.2)})
    tools = hero_tools("Anti-Mage", extra["abilities"])
    assert tools == {"ready": [], "cooldowns": {"Blink": 6}}
    shield = _extra(abilities={"ability0": _ability("medusa_mana_shield")})
    assert hero_tools("Medusa", shield["abilities"])["ready"] == []


def test_a_stun_names_the_ability_to_press_when_it_ends():
    extra = _extra(abilities=BLADE_FURY, stunned=True)
    assert disabled_copy(extra, "Juggernaut")[0] == "The moment the disable ends, use Blade Fury."
    assert low_hp_copy(extra, "Juggernaut")[0] == "The moment the disable ends, use Blade Fury."


def test_the_escape_cooldown_card_says_when_it_is_back():
    extra = _extra(abilities={"ability0": _ability("antimage_blink", 6)}) | {
        "hero_safety_ability": "Blink",
        "hero_safety_kind": "escape",
        "hero_safety_flags": ["escape_on_cooldown"],
    }
    text = _fallback_text(_request(extra, "Anti-Mage"), "respect_hero_safety_window")
    assert text["reason"] == (
        "Blink is back in 6 s: without it, escaping a bad trade or fight is harder."
    )
    assert translate_uk(text["reason"]).startswith("Blink відновиться через 6 с")


def test_a_death_with_the_heros_ability_ready_is_named(tmp_path):
    from app.match_tracker import MatchTracker

    tracker = MatchTracker(tmp_path / "live.json", on_finished=lambda _: None)
    # The last payload is the score screen, which closes the recording: left out.
    for payload in gsi_match_stream(death_minutes=(18,), step_seconds=1, minutes=19)[:-1]:
        before = 18 * 60 - payload["map"]["clock_time"]
        payload["abilities"] = BLADE_FURY
        if 0 < before <= 6:
            payload["hero"]["health_percent"] = 12 * before
        tracker.observe(payload)
    usable = tracker.last_death()["usable"]
    assert usable == ["ability:Blade Fury"]
    assert death_items_reason({"death_items": usable}) == (
        "You died with Blade Fury ready: next time use it at the first big hit."
    )


def test_the_ability_texts_have_ukrainian():
    for text in (
        "Use Blade Fury now and walk out of the fight.",
        "Blade Fury is ready: it buys you the seconds to get away.",
        "Blink is back in 6 s: without it, escaping a bad trade or fight is harder.",
        "Blade Fury is back in 9 s: until then, disables and slows are harder to avoid.",
    ):
        assert translate_uk(text), text


def test_only_abilities_that_can_be_pressed_as_a_save_count():
    """A target is needed (Sunder, Phantom Strike) or it is passive (Dispersion)."""
    cases = {
        "Terrorblade": {"ability0": _ability("terrorblade_sunder")},
        "Phantom Assassin": {"ability0": _ability("phantom_assassin_phantom_strike")},
        "Spectre": {"ability0": _ability("spectre_dispersion")},
    }
    for hero, abilities in cases.items():
        extra = _extra(FORCE, abilities=abilities)
        assert hero_tools(hero, extra["abilities"])["ready"] == [], hero
        assert low_hp_copy(extra, hero)[0] == "Use Force Staff now to get out, then reset HP."
    blur = _extra(abilities={"ability0": _ability("phantom_assassin_blur")})
    assert hero_tools("Phantom Assassin", blur["abilities"])["ready"] == [("Blur", "defensive")]


def test_a_mute_stops_items_not_the_heros_spells():
    muted = _extra(FORCE, abilities=BLADE_FURY, muted=True)
    assert low_hp_copy(muted, "Juggernaut")[0] == "Use Blade Fury now and walk out of the fight."
    assert disabled_copy(muted, "Juggernaut")[0] == (
        "Use Blade Fury now: a mute blocks items, not spells."
    )
    # Muted with no spell ready: the items wait for the mute to end.
    muted_items = _extra(FORCE, muted=True)
    assert low_hp_copy(muted_items, "Juggernaut")[0] == (
        "The moment the disable ends, use Force Staff."
    )
    # Silenced: the spell cannot be cast, the items can.
    silenced = _extra(FORCE, abilities=BLADE_FURY, silenced=True)
    assert low_hp_copy(silenced, "Juggernaut")[0] == (
        "Use Force Staff now to get out, then reset HP."
    )
    assert translate_uk("Use Blade Fury now: a mute blocks items, not spells.")


def _stunned_payload(*items):
    payload = copy.deepcopy(gsi_match_stream(minutes=20, death_minutes=())[-1])
    payload["hero"]["stunned"] = True
    payload["items"] = {f"slot{i}": item for i, item in enumerate(items)}
    return payload


def test_a_disable_card_only_when_something_can_be_pressed(client):
    """«Wait out the disable» alone changes nothing: no card for it."""
    client.post("/gsi", json=_stunned_payload())
    body = client.get("/overlay/recommendation").json()
    assert body["decision_point"] == "NO_ADVICE" and body["recommendation"] is None
    client.post("/gsi", json=_stunned_payload(BKB))
    body = client.get("/overlay/recommendation").json()
    assert body["decision_point"] == "DISABLED_STATUS"
    assert body["recommendation"]["action"] == "The moment the disable ends, use Black King Bar."


def test_a_repeated_low_hp_card_says_how_often_it_happens():
    """«Use Blink now to get out» came nine times in one game with the same reason."""
    from app.advice_i18n import translate_uk
    from app.live_tools import low_hp_repeat_reason

    assert low_hp_repeat_reason({"low_hp_before": 1}) is None  # the second card: as it was
    reason = low_hp_repeat_reason({"low_hp_before": 2, "regen_items": []})
    assert reason == (
        "Your HP has dropped this low 3 times this game: heal up fully before you go back. "
        "No regen in your bag: have the courier bring a Healing Salve."
    )
    assert translate_uk(reason).startswith("HP падає так низько вже 3-й раз за гру")
    assert "Healing Salve" not in low_hp_repeat_reason(
        {"low_hp_before": 4, "regen_items": ["item_flask"]}
    )
    # The card's action keeps naming the tool; only the reason changes.
    extra = _extra(FORCE) | {"low_hp_before": 3}
    text = _fallback_text(_request(extra), "retreat_reset")
    assert text["action"].startswith("Use Force Staff now")
    assert text["reason"].startswith("Your HP has dropped this low 4 times")


def test_the_overlay_counts_the_low_hp_cards_of_the_match(client, monkeypatch):
    from app.main import _with_low_hp_repeats

    monkeypatch.setattr(PLAYER_SERVICE, "advice_count", lambda dps: 3)
    state = {"extra_context": {"clock_time": 900}}
    assert _with_low_hp_repeats(state, "LOW_HP")["extra_context"]["low_hp_before"] == 3
    assert "low_hp_before" not in _with_low_hp_repeats(state, "SAFE_FARMING")["extra_context"]


AEGIS = {"name": "item_aegis", "can_cast": False, "cooldown": 0, "passive": True}


def test_critical_hp_names_an_aegis_or_a_revive_instead_of_only_leaving():
    aegis = _fallback_text(_request(_extra(AEGIS, FORCE)), "retreat_reset")
    assert aegis["action"] == "You hold the Aegis: leave unless this fight is worth losing it."
    reincarnation = {"ability0": _ability("skeleton_king_reincarnation", can_cast=False)}
    extra = _extra(abilities=reincarnation, hero="npc_dota_hero_skeleton_king")
    text = _fallback_text(_request(extra), "retreat_reset")
    assert text["action"].startswith("Reincarnation is ready")
    # A repeat or HP-falling reason would say «leave now» over the revive.
    text = _fallback_text(_request(extra | {"hp_falling_fast": 60}), "retreat_reset")
    assert text["reason"].startswith("A death now revives you")
    # On cooldown or not learned: the usual card.
    for ability in (
        _ability("skeleton_king_reincarnation", 120),
        _ability("skeleton_king_reincarnation", level=0),
    ):
        extra = _extra(abilities={"ability0": ability}, hero="npc_dota_hero_skeleton_king")
        assert insurance_copy(extra) is None


def test_hero_saves_come_before_a_revive_and_need_a_castable_hero():
    borrowed = {"ability0": _ability("abaddon_borrowed_time")}
    extra = _extra(AEGIS, abilities=borrowed, hero="npc_dota_hero_abaddon")
    assert insurance_copy(extra)[0].startswith("Use Borrowed Time")
    assert insurance_copy(extra | {"silenced": True})[0].startswith("You hold the Aegis")
    sunder = {"ability0": _ability("terrorblade_sunder")}
    extra = _extra(abilities=sunder, hero="npc_dota_hero_terrorblade")
    assert insurance_copy(extra, 20)[0].startswith("If a healthy enemy hero")
    assert insurance_copy(extra, 80) is None  # HP falling fast, still high: no swap
    assert insurance_copy(extra) is None  # unknown HP
    # A stun or hex keeps the post-disable wording.
    assert insurance_copy(_extra(AEGIS, stunned=True)) is None


def test_insurance_is_only_for_critical_hp_not_lane_regen():
    text = _fallback_text(_request(_extra(AEGIS, WAND)), "play_back_and_regen")
    assert text["action"] == "Use Magic Wand now, then step back."


def test_the_insurance_card_through_gsi_and_in_ukrainian(client):
    payload = copy.deepcopy(gsi_match_stream(minutes=20, death_minutes=())[-1])
    payload["hero"]["health_percent"] = 12
    payload["hero"]["health"] = 200
    payload["items"]["slot4"] = dict(AEGIS)
    client.post("/gsi", json=payload)
    body = client.get("/overlay/recommendation").json()
    assert body["recommendation"]["action"] == (
        "You hold the Aegis: leave unless this fight is worth losing it."
    )
    assert body["recommendation"]["reason"] == INSURANCE_COPY["item_aegis"][1]
    ukrainian = client.get("/overlay/recommendation?lang=uk").json()["recommendation"]
    assert ukrainian["action"] == "У вас Aegis: відходьте, якщо цей бій не вартий його втрати."


def test_every_insurance_text_has_ukrainian():
    for action, reason in INSURANCE_COPY.values():
        assert translate_uk(action), action
        assert translate_uk(reason), reason
        assert translate_uk(f"Consider: {action[0].lower()}{action[1:]}"), action
