"""
scheduler.state - mutable coaching state encapsulated for AdviceScheduler.

Holds the 66 game/advice state fields previously declared on AdviceScheduler
itself (in _reset_locked). Group (a) of the Phase 4 state inventory:
counters, last-*-timestamps, hashes, session id, pressure/death-route tracking,
LLM latencies, advice history. Infrastructure fields (_lock, enable_llm,
cooldowns) stay on AdviceScheduler and are NOT here.

Defaults are transcribed verbatim from the original _reset_locked (Phase 4
behavior-preserving refactor); the only non-None/0/False literals are
``_last_source="none"`` and ``_last_advice_mode="status"``. All mutable
container fields use field(default_factory=...) to avoid the shared-mutable
default trap. The set of fields below is generated from an AST inventory of
_reset_locked (N=66), see AGENTS.md Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.scheduler.types import OverlaySource
from app.schemas import RecommendationResponse


@dataclass
class SchedulerState:
    # --- match session ---
    match_started_at: datetime | None = None
    match_session_id: str | None = None

    # --- last advice / hashes ---
    last_advice_at: datetime | None = None
    last_advice_type: str | None = None
    last_state_hash: str | None = None
    last_tactical_state_hash: str | None = None

    # --- advice / suppression counters ---
    advice_count: int = 0
    llm_call_count: int = 0
    llm_applied_count: int = 0
    fallback_count: int = 0
    stale_llm_count: int = 0
    duplicate_suppressed_count: int = 0
    repeated_laning_suppressed_count: int = 0
    repeated_post_laning_suppressed_count: int = 0
    repeated_objective_suppressed_count: int = 0
    post_laning_safety_suppressed_count: int = 0
    objective_suppressed_by_recent_safety_count: int = 0
    item_timing_suppressed_by_safety_count: int = 0
    death_route_suppressed_count: int = 0
    low_hp_episode_count: int = 0
    repeated_low_hp_suppressed_count: int = 0
    low_hp_pattern_advice_count: int = 0
    tactical_hash_changes: int = 0
    suppressed_by_game_time_spacing_count: int = 0
    heartbeat_nudge_count: int = 0
    suppressed_heartbeat_duplicate_count: int = 0

    # --- last shown advice ---
    _last_advice_state_hash: str | None = None
    _last_advice_tactical_state_hash: str | None = None
    _last_recommendation: RecommendationResponse | None = None
    _last_gameplay_context: dict[str, Any] | None = None
    _last_source: OverlaySource = "none"
    _last_llm_used: bool = False
    _last_advice_mode: str = "status"
    _last_updated: str | None = None
    _active_advice_until: datetime | None = None
    _is_pinned: bool = False
    # What the held card depends on (advice_validity.advice_basis) and the
    # last card withdrawn because it no longer held, with until when the
    # overlay is told so.
    _active_basis: dict[str, Any] | None = None
    _withdrawn: dict[str, Any] | None = None
    _withdrawn_until: datetime | None = None
    # The type of a card withdrawn because the player can now do more than it
    # said (a stun gave way to a silence the named item goes through): the
    # next card of that type is held back neither by its own cooldown nor as
    # a duplicate of the same game state.
    _overtaken_type: str | None = None
    withdrawn_count: int = 0
    no_new_decision_count: int = 0
    # Bumped for each card shown: an async refinement applies only to its card.
    _card_serial: int = 0
    # The kill or revive whose readiness card was shown (one per moment).
    _readiness_shown_key: tuple[str, int] | None = None
    _last_seen_minute: int | None = None

    # --- LLM tracking (mutable) ---
    _pending_llm_tactical_hashes: set[str] = field(default_factory=set)
    _llm_latencies: list[float] = field(default_factory=list)

    # --- advice history (mutable) ---
    _advice_history: list[dict[str, Any]] = field(default_factory=list)

    # --- laning / post-laning / objective tracking ---
    _last_laning_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    _last_post_laning_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    _last_objective_advice_at: datetime | None = None
    _last_objective_advice_game_time: float | None = None

    # --- post-laning safety ---
    _last_post_laning_safety_at: datetime | None = None
    _last_post_laning_safety_game_time: float | None = None
    _post_laning_hp_recovered_since_safety: bool = False

    # --- death-route tracking ---
    _last_post_laning_death_route_at: datetime | None = None
    _last_post_laning_death_route_game_time: float | None = None
    _last_post_laning_death_route_event_id: str | None = None

    # --- low-HP urgent / pattern ---
    _last_low_hp_urgent_at: datetime | None = None
    _last_low_hp_urgent_game_time: float | None = None
    _last_low_hp_pattern_at: datetime | None = None
    _last_low_hp_pattern_game_time: float | None = None

    # --- shown-advice timing ---
    _last_shown_game_time_seconds: float | None = None
    _last_shown_decision_point: str | None = None
    _last_shown_category: str | None = None
    _last_shown_action_hash: str | None = None
    # When a farm pace card (FARM_PACE_PREFIX) was last shown, whatever came after.
    _farm_pace_shown_game_time: float | None = None
    # How many farm pace cards this match has shown (FARM_PACE_SLOW_AFTER).
    _farm_pace_shown_count: int = 0
    _advice_game_time_gaps_seconds: list[float] = field(default_factory=list)

    # --- low-HP episode tracking ---
    _low_hp_episode_active: bool = False
    _low_hp_episode_id: int = 0
    _low_hp_episode_lowest_hp: int | None = None
    _low_hp_episode_repeat_count: int = 0
    _low_hp_episode_pattern_shown: bool = False
    _low_hp_pattern_advice_shown: bool = False
    _low_hp_pattern_last_at: datetime | None = None
    _low_hp_episode_last_severe_signature: str | None = None
