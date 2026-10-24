"""Late-game "keep buyback gold" advice after a purchase breaks the reserve."""

from __future__ import annotations

from match_fixtures import gsi_match_stream

from app.advice_i18n import translate_uk
from app.buyback_tracker import BuybackTracker
from app.match_memory import MATCH_MEMORY
from app.post_laning_coach import build_post_laning_advice


def test_purchase_below_buyback_cost_raises_the_signal_once():
    tracker = BuybackTracker()
    tracker.observe(1850, 5200, 2400, 0, True)
    tracker.observe(1855, 900, 2410, 0, True)  # bought an item
    signal = tracker.signal()
    assert signal == {"clock": 1855, "gold": 900, "cost": 2410, "observed": 1855}
    tracker.observe(1900, 1500, 2410, 0, True)
    # Still within the hold time, with this snapshot's gold (not the purchase's).
    assert tracker.signal() == {"clock": 1855, "gold": 1500, "cost": 2410, "observed": 1900}
    tracker.observe(1920, 1600, 2410, 0, True)
    assert tracker.signal() is None  # held for a minute


def test_no_signal_early_dead_on_cooldown_small_or_already_short():
    cases = [
        [(1500, 5000, 2000, 0, True), (1505, 900, 2000, 0, True)],  # minute 25
        [(1850, 5000, 2400, 0, True), (1855, 900, 2400, 0, False)],  # died
        [(1850, 5000, 2400, 30, True), (1855, 900, 2400, 30, True)],  # buyback on cooldown
        [(1850, 2500, 2400, 0, True), (1855, 2300, 2400, 0, True)],  # 200 gold: not a purchase
        [(1850, 2000, 2400, 0, True), (1855, 500, 2400, 0, True)],  # was short already
    ]
    for plan in cases:
        tracker = BuybackTracker()
        for sample in plan:
            tracker.observe(*sample)
        assert tracker.signal() is None, plan


def test_gold_back_clears_the_signal():
    tracker = BuybackTracker()
    tracker.observe(1850, 5200, 2400, 0, True)
    tracker.observe(1855, 900, 2400, 0, True)
    tracker.observe(1880, 2600, 2400, 0, True)
    assert tracker.signal() is None


def _state(**extra):
    return {
        "hero": "Juggernaut",
        "role": "carry",
        "minute": 31,
        "level": 22,
        "gold": 900,
        "items": [],
        "hp_percent": 90,
        "game_state": "calm_farming",
        "team_status": "unknown",
        "extra_context": {"farm_quality": "okay", "hp_pressure_state": "healthy", **extra},
    }


def test_coach_turns_the_signal_into_advice_with_numbers():
    advice = build_post_laning_advice(
        _state(buyback_spent={"clock": 1855, "gold": 900, "cost": 2410}), "SAFE_FARMING"
    )
    assert advice.category == "post_laning_buyback_reserve"
    assert advice.reason.startswith("You have 900 gold and buyback costs 2410")
    assert translate_uk(advice.action).startswith("Нафарміть золото на байбек")
    assert translate_uk(advice.reason).startswith("Золота 900, байбек коштує 2410")


def test_live_purchase_reaches_the_overlay(client):
    shown = []
    for payload in gsi_match_stream(minutes=34, death_minutes=(), step_seconds=5):
        clock = payload["map"]["clock_time"]
        payload["hero"]["buyback_cost"] = 2400
        payload["hero"]["buyback_cooldown"] = 0
        payload["player"]["gold"] = 5000 if clock < 31 * 60 else 900
        client.post("/gsi", json=payload)
        if 31 * 60 <= clock <= 32 * 60 and clock % 5 == 0:
            response = client.get("/overlay/recommendation?lang=uk").json()
            shown.append((response.get("recommendation") or {}).get("action") or "")
    # Coaching tips get the UX policy's "Consider:" prefix.
    assert any("нафарміть золото на байбек" in text.lower() for text in shown), shown
    assert MATCH_MEMORY.buyback.signal() is None  # held for a minute, then gone
