"""
Characterization snapshot for AdviceScheduler.state after 4A encapsulation.

This is a safety net for the Phase 4 refactor (and the later evaluate()
decomposition). It runs a fixed, deterministic scenario through the global
ADVICE_SCHEDULER and compares dataclasses.asdict(scheduler.state) against a
frozen baseline captured right after 4A.2 (i.e. the current behavior).

Determinism:
- All wall-clock fields are driven by passing an explicit `now` into
  observe_state/evaluate. _utcnow(value) uses the value verbatim (with a UTC
  fixup), so every last_*_time field is frozen - no monkeypatch of _utcnow.
- USE_LLM stays false (default), so no LLM refinement perturbs the state.
- State hashes are content-derived and verified stable across runs.

If this test breaks in Phase 4B, the extract-method step changed behavior and
must be reverted. If it breaks intentionally later, update the baseline
deliberately and explain why in the commit message.
"""

from __future__ import annotations

import pprint
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime

import pytest

from app.advice_scheduler import ADVICE_SCHEDULER
from app.schemas import GameSituationRequest


def _mk(minute: int, hp: int = 80, **extra) -> GameSituationRequest:
    base: dict[str, object] = {
        "hero": "Phantom Lancer",
        "role": "carry",
        "minute": minute,
        "level": 15,
        "gold": 2000,
        "items": ["Power Treads", "Manta Style"],
        "hp_percent": hp,
        "game_state": "calm farming",
        "team_status": "unknown",
        "extra_context": {
            "source_type": "replay_gsi_like",
            "context_confidence": "high",
            "game_time": minute * 60,
            "timestamp_seconds": minute * 60,
            "alive": True,
            "mana_percent": 80,
            "last_hits": minute * 8,
            "farm_quality": "low" if minute < 20 else "good",
            "hp_pressure_state": "healthy" if hp > 65 else "critical",
            "position_zone": "lane_area",
            "position_risk": "medium",
            "missing_signals": ["enemy_positions", "nearby_allies_enemies"],
        },
    }
    base.update(extra)
    return GameSituationRequest(**base)  # type: ignore[arg-type]


def _normalize(obj: object) -> object:
    """Recursively turn a state value into plain JSON-ish data for comparison."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _normalize(v) for k, v in asdict(obj).items()}  # type: ignore[arg-type]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_normalize(x) for x in obj)  # type: ignore[type-var]
    return obj


def _run_scenario() -> dict[str, object]:
    ADVICE_SCHEDULER.reset()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    ADVICE_SCHEDULER.evaluate(_mk(15), "FARMING_PHASE_PRESSURE", [], now=t0)
    t1 = datetime(2026, 1, 1, 0, 0, 12, tzinfo=UTC)
    ADVICE_SCHEDULER.evaluate(_mk(15, hp=28, game_state="pressure"), "LOW_HP", [], now=t1)
    t2 = datetime(2026, 1, 1, 0, 3, 10, tzinfo=UTC)
    ADVICE_SCHEDULER.evaluate(_mk(18, hp=90, game_state="calm farming"), "NO_ADVICE", [], now=t2)
    ADVICE_SCHEDULER.observe_state(_mk(18).model_dump(), "FARMING_PHASE_PRESSURE", now=t2)
    return _normalize(ADVICE_SCHEDULER.state)  # type: ignore[return-value]


# Baseline captured right after Phase 4A.2 (commit d529544). Every datetime is
# frozen via the explicit `now` passed above. Do not update casually; if behavior
# changes intentionally, re-capture and explain in the commit.
_BASELINE: dict[str, object] = {
    # 0.59: at 00:03:10 the hero is back at 90 % HP, so the 28 %-HP «Reset HP»
    # card is withdrawn as recovered (advice_validity.py); before it stayed in
    # _last_recommendation and was re-served on cooldown polls.
    "_active_advice_until": None,
    "_active_basis": None,
    "_card_serial": 2,
    "_readiness_shown_key": None,
    "_withdrawn": {
        "action": "Reset HP before showing on another lane.",
        "card_clock": None,
        "decision_point": "LOW_HP",
        "reason": "recovered",
    },
    "_withdrawn_until": "2026-01-01T00:03:20+00:00",
    "_overtaken_type": None,
    "_disable_card_since": None,
    "withdrawn_count": 1,
    "no_new_decision_count": 0,
    "_advice_game_time_gaps_seconds": [0.0],
    "_advice_history": [
        {
            "action": "Recover farm through the safest wave-and-camp route.",
            "action_type": "switch_to_safe_farm",
            "decision_point": "FARMING_PHASE_PRESSURE",
            "game_time_gap_since_previous_advice": None,
            "laning_category": "",
            "post_laning_category": "post_laning_farm_recovery",
            "source": "fallback",
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
        {
            "action": "Reset HP before showing on another lane.",
            "action_type": "retreat_reset",
            "decision_point": "LOW_HP",
            "game_time_gap_since_previous_advice": 0.0,
            "laning_category": "critical_hp_reset",
            "post_laning_category": "post_laning_low_hp_reset",
            "source": "fallback",
            "timestamp": "2026-01-01T00:00:12+00:00",
        },
    ],
    "_is_pinned": False,
    "_last_advice_mode": "urgent",
    "_last_advice_state_hash": "3a880a05553506f4",
    "_last_advice_tactical_state_hash": "4e24c34fe1e86ba9",
    # New hero-card cancellation metadata is empty in this legacy scenario.
    "_last_gameplay_context": None,
    "_last_laning_category": {
        "critical_hp_reset": {
            "action": "Reset HP before showing on another lane.",
            "at": "2026-01-01T00:00:12+00:00",
            "category": "critical_hp_reset",
            "farm_deficit": None,
            "game_time_seconds": 900.0,
            "position_risk": "medium",
            "pressure_active": True,
            "pressure_state": "critical",
        }
    },
    "_last_llm_used": False,
    "_last_low_hp_pattern_at": None,
    "_last_low_hp_pattern_game_time": None,
    "_last_low_hp_urgent_at": "2026-01-01T00:00:12+00:00",
    "_last_low_hp_urgent_game_time": 900.0,
    "_last_objective_advice_at": None,
    "_last_objective_advice_game_time": None,
    "_last_post_laning_category": {
        "post_laning_farm_recovery": {
            "action": "Recover farm through the safest wave-and-camp route.",
            "at": "2026-01-01T00:00:00+00:00",
            "category": "post_laning_farm_recovery",
            "farm_quality": "low",
            "game_time_seconds": 900.0,
            "hp_pressure_state": "healthy",
            "position_risk": "medium",
            "position_zone": "lane_area",
            "pressure_active": False,
        },
        "post_laning_low_hp_reset": {
            "action": "Reset HP before showing on another lane.",
            "at": "2026-01-01T00:00:12+00:00",
            "category": "post_laning_low_hp_reset",
            "farm_quality": "low",
            "game_time_seconds": 900.0,
            "hp_pressure_state": "critical",
            "position_risk": "medium",
            "position_zone": "lane_area",
            "pressure_active": True,
        },
    },
    "_last_post_laning_death_route_at": None,
    "_last_post_laning_death_route_event_id": None,
    "_last_post_laning_death_route_game_time": None,
    "_last_post_laning_safety_at": "2026-01-01T00:00:12+00:00",
    "_last_post_laning_safety_game_time": 900.0,
    "_last_recommendation": None,
    "_last_seen_minute": 18,
    "_last_shown_action_hash": "e0ad389e6bb2",
    # 0.25: when a farm pace card was last shown (none in this sequence).
    "_farm_pace_shown_game_time": None,
    "_farm_pace_shown_count": 0,
    "_last_shown_category": "post_laning_low_hp_reset",
    "_last_shown_decision_point": "LOW_HP",
    "_last_shown_game_time_seconds": 900.0,
    "_last_source": "fallback",
    "_last_updated": "2026-01-01T00:00:12+00:00",
    "_llm_latencies": [],
    "_low_hp_episode_active": False,
    "_low_hp_episode_id": 1,
    "_low_hp_episode_last_severe_signature": None,
    "_low_hp_episode_lowest_hp": None,
    "_low_hp_episode_pattern_shown": False,
    "_low_hp_episode_repeat_count": 0,
    "_low_hp_pattern_advice_shown": False,
    "_low_hp_pattern_last_at": None,
    "_pending_llm_tactical_hashes": [],
    "_post_laning_hp_recovered_since_safety": True,
    "advice_count": 2,
    "death_route_suppressed_count": 0,
    "duplicate_suppressed_count": 0,
    "fallback_count": 2,
    "heartbeat_nudge_count": 0,
    "item_timing_suppressed_by_safety_count": 0,
    "last_advice_at": "2026-01-01T00:00:12+00:00",
    "last_advice_type": "LOW_HP",
    "last_state_hash": "6d6d3fb5f5c9ad4e",
    "last_tactical_state_hash": "31f821d692d2e249",
    "llm_applied_count": 0,
    "llm_call_count": 0,
    "low_hp_episode_count": 1,
    "low_hp_pattern_advice_count": 0,
    "match_session_id": None,
    "match_started_at": "2026-01-01T00:00:00+00:00",
    "objective_suppressed_by_recent_safety_count": 0,
    "post_laning_safety_suppressed_count": 0,
    "repeated_laning_suppressed_count": 0,
    "repeated_low_hp_suppressed_count": 0,
    "repeated_objective_suppressed_count": 0,
    "repeated_post_laning_suppressed_count": 0,
    "stale_llm_count": 0,
    "suppressed_by_game_time_spacing_count": 0,
    "suppressed_heartbeat_duplicate_count": 0,
    "tactical_hash_changes": 3,
}


def test_scheduler_state_snapshot_matches_baseline() -> None:
    actual = _run_scenario()
    # Compare structurally (order-insensitive on dict keys) with a readable diff.
    assert actual == _BASELINE, (
        "SchedulerState snapshot diverged from the Phase 4A.2 baseline.\n"
        "If this is an INTENTIONAL behavior change, re-capture the baseline and "
        "explain in the commit. If it is NOT intentional, the last refactor step "
        "silently changed behavior - revert it.\n\n"
        "--- actual ---\n"
        + pprint.pformat(actual, sort_dicts=True)
        + "\n\n--- baseline ---\n"
        + pprint.pformat(_BASELINE, sort_dicts=True)
    )


def test_scheduler_state_snapshot_has_expected_key_count() -> None:
    # Cheap structural guard: catches a silently added/removed SchedulerState field
    # (which asdict-based comparison alone would only flag via a changed key set).
    actual = _run_scenario()
    assert set(actual.keys()) == set(_BASELINE.keys()), (
        "SchedulerState field set changed: "
        f"only in actual={set(actual) - set(_BASELINE)}, "
        f"only in baseline={set(_BASELINE) - set(actual)}"
    )


@pytest.mark.parametrize("run_index", [0, 1, 2])
def test_scheduler_state_snapshot_is_deterministic(run_index: int) -> None:
    # Three independent runs must produce identical normalized state. This guards
    # against accidental non-determinism (e.g. set/dict ordering in a hash input)
    # that would otherwise make the baseline comparison flaky.
    actual = _run_scenario()
    assert actual == _BASELINE
