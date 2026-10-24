"""
advice_scheduler.py - in-memory live advice scheduling for the GSI overlay.

Purpose:
- accept normalized live/demo state plus a decision point;
- return either a new visible advice card, the still-active previous card, or a
  compact status/cooldown response;
- keep realtime coaching useful without spamming the player.

The scheduler does not choose high-level game meaning by itself. Decision
selection comes from ``decision_points.py`` and wording comes from the
fallback recommender or optional LLM refinement. This module owns the display
contract: game-time spacing, duplicate suppression, active-card lifetime,
urgent interrupts, low-HP episode handling, death pinning, objective/card
suppression, and accounting metrics.

Timing distinction:
- decision frequency and duplicate suppression use Dota game_time / simulated
  replay time when available;
- wall-clock time is kept for UI visibility, async LLM staleness, and ordinary
  HTTP polling.

The overlay should get immediate rule-based advice. Optional LLM refinement runs
in the background and is discarded if the tactical state changes before it
arrives.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.advice_policy import apply_advice_policy, build_advice_policy
from app.advice_text import clean_recommendation_text
from app.advice_ux_policy import (
    apply_ux_policy,
)
from app.advice_validity import (
    FILLER_ACTIONS,
    advice_basis,
    is_filler,
    named_tool,
    refreshed_reason,
    withdraw_reason,
)
from app.config import ADVICE_FREQUENCY, USE_LLM
from app.hero_gameplay import rule_valid
from app.laning_coach import (
    REPEAT_WINDOW_SECONDS,
    build_laning_advice,
    important_laning_context_changed,
)
from app.llm_provider import generate_llm_recommendation, is_llm_provider_enabled
from app.post_laning_coach import (
    OBJECTIVE_REPEAT_WINDOW_SECONDS,
    POST_LANING_DEATH_ROUTE_WINDOW_SECONDS,
    POST_LANING_RECENT_SAFETY_WINDOW_SECONDS,
    POST_LANING_REPEAT_WINDOW_SECONDS,
    POST_LANING_SAME_ACTION_WINDOW_SECONDS,
    build_post_laning_advice,
    important_post_laning_context_changed,
)
from app.recommender import generate_recommendation
from app.scheduler.constants import (
    COACHING_GAME_TIME_GAP_SECONDS,
    DEATH_REVIEW_DECISIONS,
    FARM_PACE_PREFIX,
    FARM_PACE_REPEAT_SECONDS,
    FARM_PACE_SLOW_AFTER,
    HEARTBEAT_DUPLICATE_WAIT_SECONDS,
    HEARTBEAT_NUDGE_SECONDS,
    LLM_REFINEMENT_EVERY_N_ADVICES,
    POST_LANING_GAME_TIME_GAP_SECONDS,
    QUIETER_GAP_FACTOR,
    RECENT_SAFETY_GAME_TIME_GAP_SECONDS,
    REGULAR_ADVICE_COOLDOWN_SECONDS,
    SAME_ACTION_GAME_TIME_GAP_SECONDS,
    URGENT_LOW_HP_COOLDOWN_SECONDS,
)
from app.scheduler.frequency import (
    UNSCALED_DECISIONS,
    heartbeat_enabled,
    normalize_frequency,
    scaled_seconds,
)
from app.scheduler.hashing import (
    _action_hash,
    build_state_hash,
    build_tactical_state_hash,
)
from app.scheduler.heartbeat import (
    _heartbeat_context_is_confident,
    _heartbeat_copy,
    _heartbeat_safe_category_available,
    _is_heartbeat_recommendation,
    _low_hp_pattern_recommendation,
)
from app.scheduler.safety_predicates import (
    _death_event_id,
    _low_hp_severe_signature,
    _objective_context_changed_clearly,
    _post_laning_int,
    _post_laning_item_timing_is_unsafe,
    _post_laning_new_death_or_severe_pressure,
    _post_laning_safety_suppression_exception,
    _strong_laning_interrupt,
    _strong_post_laning_interrupt,
    _suggests_fighting_without_safety,
)
from app.scheduler.state import SchedulerState
from app.scheduler.state_utils import (
    _ctx_int,
    _is_dead_or_respawning,
    _optional_float,
    _state_game_time_seconds,
    _to_int,
    _utcnow,
)
from app.scheduler.stats_utils import (
    _average,
    _maximum,
    _minimum,
    _p95,
    _rate,
    _session_id_from_state,
)
from app.scheduler.text import (
    MAX_ACTION_LENGTH,
    MAX_REASON_LENGTH,
    _compact_recommendation,
)
from app.scheduler.types import OverlaySource, OverlayStatus, ScheduledAdvice
from app.schemas import GameSituationRequest, RecommendationResponse
from app.team_context import contest_near

# A withdrawn card is reported to the overlay for this long (it may poll late).
WITHDRAWN_NOTICE = timedelta(seconds=10)
# HP regained over 3 s that counts as recovering (points of max HP).
LOW_HP_RECOVERING_POINTS = 5
# Game seconds between two readiness moments that may skip the usual gates.
READINESS_BYPASS_GAP = 60

# Public types, constants, and the ScheduledAdvice DTO now live in leaf modules app.scheduler.types and app.scheduler.constants. They are imported below and re-exported by this facade for backwards compatibility.


@dataclass
class _SegmentResult:
    """Phase 4B (Zone 3 decomposition): carrier for locals produced by the
    extracted ``_evaluate_*_locked`` segments of ``evaluate``.

    ``advice`` is set when a segment short-circuits with a finished
    ``ScheduledAdvice`` (early return); the remaining fields carry the
    fall-through locals back to ``evaluate`` byte-for-byte. All default to
    ``None`` so each segment populates only what it produces.
    """

    advice: ScheduledAdvice | None = None
    ux_result: dict[str, Any] | None = None
    fallback: RecommendationResponse | None = None
    laning_category: str | None = None
    post_laning_category: str | None = None


class AdviceScheduler:
    def __init__(
        self,
        *,
        enable_llm: bool | None = None,
        regular_cooldown_seconds: int = REGULAR_ADVICE_COOLDOWN_SECONDS,
        urgent_cooldown_seconds: int = URGENT_LOW_HP_COOLDOWN_SECONDS,
    ) -> None:
        self.enable_llm = enable_llm
        # The player's preference; survives reset() (a new match keeps it).
        self.frequency = normalize_frequency(ADVICE_FREQUENCY)
        # Decision points the player mostly marks as not to the point or repeated
        # (advice_feedback.quieter_decisions); also survives reset().
        self.quieter: frozenset[str] = frozenset()
        self.regular_cooldown_seconds = regular_cooldown_seconds
        self.urgent_cooldown_seconds = urgent_cooldown_seconds
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def set_frequency(self, frequency: str) -> str:
        with self._lock:
            self.frequency = normalize_frequency(frequency)
            return self.frequency

    def set_quieter(self, decisions: Iterable[str]) -> frozenset[str]:
        with self._lock:
            self.quieter = frozenset(str(decision) for decision in decisions)
            return self.quieter

    def _reset_locked(self) -> None:
        # Phase 4: all 66 game/advice state fields now live in SchedulerState;
        # recreating the dataclass reproduces the previous 66 assignments
        # verbatim (defaults transcribed from the former reset body).
        self.state = SchedulerState()

    # ------------------------------------------------------------------
    # Public API — observe_state and evaluate are the two entry points.
    # observe_state is a lightweight state tracker used by the demo path.
    # evaluate is the full scheduling decision, called per overlay tick.
    # ------------------------------------------------------------------

    def observe_state(
        self,
        state: dict[str, Any],
        decision_point: str,
        now: datetime | None = None,
    ) -> None:
        current_time = _utcnow(now)
        state_hash = build_state_hash(state, decision_point)
        policy = build_advice_policy(state, decision_point)
        tactical_hash = build_tactical_state_hash(
            state,
            decision_point,
            action_type=policy["action_type"],
        )
        minute = _to_int(state.get("minute"), 0)

        with self._lock:
            self._ensure_session_locked(current_time, minute, state)
            self._cancel_gameplay_if_invalid_locked(state)
            self._game_time_seconds_locked(state, current_time)
            self._update_hashes_locked(state_hash, tactical_hash)
            self._update_low_hp_recovery_locked(state)
            self._revalidate_active_locked(state, current_time)

    def _evaluate_normalize_input(
        self,
        request: GameSituationRequest,
        decision_point: str,
        now: datetime | None,
    ) -> tuple[datetime, dict[str, Any], str, dict[str, Any], str]:
        # Phase 4B extract (S0): input normalization. No lock; pure derivation
        # of current_time/state/hashes/policy from the request. Behavior-preserving.
        current_time = _utcnow(now)
        state = request.model_dump()
        state_hash = build_state_hash(state, decision_point)
        policy = build_advice_policy(request, decision_point)
        tactical_hash = build_tactical_state_hash(
            state,
            decision_point,
            action_type=policy["action_type"],
        )
        return current_time, state, state_hash, policy, tactical_hash

    def _evaluate_locked_setup(
        self,
        current_time: datetime,
        request: GameSituationRequest,
        state: dict[str, Any],
        decision_point: str,
        state_hash: str,
        tactical_hash: str,
    ) -> float | None:
        # Phase 4B extract (S1): session/game-time/hash/recovery setup.
        # Runs under the already-held evaluate lock (Zone 1); does NOT acquire it.
        # Produces game_time_seconds and mutates session/hash/recovery state.
        self._ensure_session_locked(current_time, request.minute, state)
        self._cancel_gameplay_if_invalid_locked(state)
        game_time_seconds = self._game_time_seconds_locked(state, current_time)
        self._update_hashes_locked(state_hash, tactical_hash)
        if decision_point != "LOW_HP":
            self._update_low_hp_recovery_locked(state)
        self._revalidate_active_locked(state, current_time)
        return game_time_seconds

    def _evaluate_no_advice_locked(
        self, decision_point: str, current_time: datetime
    ) -> ScheduledAdvice | None:
        # Phase 4B extract (S2): NO_ADVICE gate. Runs under the evaluate lock;
        # returns a ScheduledAdvice when active advice is kept visible, otherwise
        # a no_advice result, or None to fall through. Early-return preserved.
        if decision_point == "NO_ADVICE":
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=0,
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                return active
            return self._result_locked(
                status="no_advice",
                decision_point=decision_point,
                recommendation=None,
                source="none",
                llm_used=False,
                next_allowed=0,
                new_advice=False,
                advice_mode="status",
                suppressed_reason="no_advice",
            )

        return None

    def _evaluate_cooldown_locked(
        self,
        decision_point: str,
        current_time: datetime,
        cooldown_remaining: int,
        tactical_hash: str,
    ) -> ScheduledAdvice | None:
        # Phase 4B extract (S4): cooldown gate. Runs under the evaluate lock.
        # When a cooldown is still active, keep an active advice visible or
        # return a cooldown result; None to fall through. Early-return preserved.
        if cooldown_remaining > 0:
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=cooldown_remaining,
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                return active
            recommendation, source, llm_used, advice_mode = self._last_matching_advice_locked(
                tactical_hash
            )
            return self._result_locked(
                status="cooldown",
                decision_point=decision_point,
                recommendation=recommendation,
                source=source,
                llm_used=llm_used,
                next_allowed=cooldown_remaining,
                new_advice=False,
                advice_mode=advice_mode,
                suppressed_reason="cooldown",
            )

        return None

    def _evaluate_fallback_recommendation(
        self,
        request: GameSituationRequest,
        rag_context: list[str],
        policy: dict[str, Any],
        decision_point: str,
    ) -> RecommendationResponse:
        # Phase 4B extract (S7): fallback recommendation generation.
        # NO lock: generate_recommendation is intentionally expensive and runs
        # outside the lock between Zone 1 and Zone 3 (preserved here).
        fallback = apply_advice_policy(generate_recommendation(request, rag_context), policy)
        fallback = _compact_recommendation(fallback, decision_point)
        return fallback

    def _evaluate_record_advice_locked(
        self,
        current_time: datetime,
        decision_point: str,
        fallback: RecommendationResponse,
        game_time_seconds: float | None,
        laning_category: str | None,
        post_laning_category: str | None,
        state: dict[str, Any],
        state_hash: str,
        tactical_hash: str,
        ux_result: dict[str, Any],
    ) -> tuple[bool, int, float | None]:
        # Phase 4B extract (S11): final advice recording. Runs under the evaluate
        # lock (Zone 3 tail, after all gating). Increments counters, records shown
        # timing, mutates last-advice state, appends history, runs laning/post-laning/
        # safety recorders, and computes should_refine/next_allowed/gap. Returns
        # (should_refine, next_allowed, gap); gap is consumed by the finalize step.
        # Side-effect order is preserved verbatim.
        self.state.advice_count += 1
        self.state.fallback_count += 1
        shown_category = post_laning_category or laning_category or decision_point
        if _is_heartbeat_recommendation(fallback):
            self.state.heartbeat_nudge_count += 1
        gap = self._record_shown_advice_timing_locked(
            decision_point=decision_point,
            state=state,
            recommendation=fallback,
            category=shown_category,
            game_time_seconds=game_time_seconds,
        )
        self.state.last_advice_at = current_time
        self.state.last_advice_type = decision_point
        self.state._last_advice_state_hash = state_hash
        self.state._last_advice_tactical_state_hash = tactical_hash
        self.state._last_recommendation = fallback
        moment = self._readiness_moment_locked(decision_point, state)
        if moment is not None:
            self.state._readiness_shown_key = moment
        self._set_basis_locked(decision_point, fallback, state)
        gameplay = (state.get("extra_context") or {}).get("hero_gameplay")
        self.state._last_gameplay_context = (
            deepcopy(gameplay)
            if decision_point == "HERO_GAMEPLAY" and isinstance(gameplay, dict)
            else None
        )
        self.state._last_source = "fallback"
        self.state._last_llm_used = False
        self.state._last_advice_mode = ux_result["advice_mode"]
        self.state._last_updated = current_time.isoformat()
        self._set_active_advice_locked(decision_point, state, current_time)
        self.state._advice_history.append(
            {
                "timestamp": self.state._last_updated,
                "decision_point": decision_point,
                "source": "fallback",
                "action": fallback.action,
                "action_type": ux_result["action_type"],
                "laning_category": laning_category or "",
                "post_laning_category": post_laning_category or "",
                "game_time_gap_since_previous_advice": gap,
            }
        )
        self._record_laning_advice_locked(
            decision_point=decision_point,
            state=state,
            recommendation=fallback,
            now=current_time,
            game_time_seconds=game_time_seconds,
        )
        self._record_post_laning_advice_locked(
            decision_point=decision_point,
            state=state,
            recommendation=fallback,
            now=current_time,
            game_time_seconds=game_time_seconds,
        )
        self._record_safety_advice_locked(
            decision_point=decision_point,
            state=state,
            post_laning_category=post_laning_category,
            now=current_time,
            game_time_seconds=game_time_seconds,
        )
        should_refine = self._should_start_llm_locked(decision_point, tactical_hash)
        next_allowed = self._cooldown_for_type_locked(decision_point)
        return should_refine, next_allowed, gap

    def _evaluate_duplicate_locked(
        self,
        decision_point: str,
        current_time: datetime,
        cooldown_remaining: int,
        state_hash: str,
        tactical_hash: str,
    ) -> ScheduledAdvice | None:
        # Phase 4B extract (S3): duplicate gate. Runs under the evaluate lock.
        # cooldown_remaining is hoisted into evaluate (unconditional pure read,
        # computed just above this call) and passed in - keeps S3 uniform with
        # S2/S4/S5/S6 (all return a bare ScheduledAdvice | None). On a duplicate
        # it keeps an active advice visible or returns a cooldown result; None
        # to fall through. Early-return preserved.
        duplicate = self.state._last_advice_state_hash == state_hash
        if duplicate:
            self.state.duplicate_suppressed_count += 1
            suppressed_reason = (
                "duplicate_death_review"
                if decision_point in DEATH_REVIEW_DECISIONS
                else "duplicate"
            )
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=cooldown_remaining,
                suppressed_reason="cooldown_keep_visible"
                if suppressed_reason == "duplicate"
                else suppressed_reason,
            )
            if active is not None:
                return active
            recommendation, source, llm_used, advice_mode = self._last_matching_advice_locked(
                tactical_hash
            )
            return self._result_locked(
                status="cooldown",
                decision_point=decision_point,
                recommendation=recommendation,
                source=source,
                llm_used=llm_used,
                next_allowed=cooldown_remaining,
                new_advice=False,
                advice_mode=advice_mode,
                suppressed_reason=suppressed_reason,
            )

        return None

    def _evaluate_low_hp_warning_locked(
        self, decision_point: str, current_time: datetime, game_time_seconds: float | None
    ) -> ScheduledAdvice | None:
        # Phase 4B extract (S5): LOW_HP_WARNING gate. Runs under the evaluate lock.
        # When a low-HP episode is active (or a recent low-HP pattern is live), a
        # LOW_HP_WARNING is suppressed as duplicate_low_hp_episode; returns None to
        # fall through. Uniform with S2/S3/S4: bare ScheduledAdvice | None.
        if decision_point == "LOW_HP_WARNING" and (
            self.state._low_hp_episode_active
            or self._recent_low_hp_pattern_locked(current_time, game_time_seconds)
        ):
            self.state.repeated_low_hp_suppressed_count += 1
            self.state.duplicate_suppressed_count += 1
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=self._cooldown_for_type_locked(decision_point),
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                return active
            return self._result_locked(
                status="cooldown",
                decision_point=decision_point,
                recommendation=None,
                source="none",
                llm_used=False,
                next_allowed=self._cooldown_for_type_locked(decision_point),
                new_advice=False,
                advice_mode="status",
                suppressed_reason="duplicate_low_hp_episode",
            )

        return None

    def _evaluate_low_hp_locked(
        self,
        current_time: datetime,
        decision_point: str,
        game_time_seconds: float | None,
        state: dict[str, Any],
        state_hash: str,
        tactical_hash: str,
    ) -> ScheduledAdvice | None:
        # Phase 4B extract (S6): LOW_HP episode gate. Runs under the evaluate
        # lock. Dispatches on _low_hp_episode_action_locked: suppress (repeat in
        # episode), show+suppress (show action but recent safety), or pattern
        # (third repeat). The pattern branch is the heaviest - it mutates state,
        # appends history, and returns a constructed ScheduledAdvice - and is
        # extracted as one atomic block. Returns a bare ScheduledAdvice | None.
        if decision_point == "LOW_HP":
            low_hp_action = self._low_hp_episode_action_locked(state)
            raw_extra = state.get("extra_context")
            if (
                low_hp_action == "pattern"
                and isinstance(raw_extra, dict)
                and raw_extra.get("teleporting") is True
            ):
                # «Stop re-contesting the lane» while the TP out channels: it
                # names no tool and asks for what the TP does (_held_by_channel).
                low_hp_action = "suppress"
            if low_hp_action == "suppress":
                self.state.repeated_low_hp_suppressed_count += 1
                self.state.post_laning_safety_suppressed_count += _post_laning_int(state)
                self.state.duplicate_suppressed_count += 1
                active = self._active_result_locked(
                    decision_point=decision_point,
                    now=current_time,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    suppressed_reason="cooldown_keep_visible",
                )
                if active is not None:
                    return active
                return self._result_locked(
                    status="cooldown",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    new_advice=False,
                    advice_mode="status",
                    suppressed_reason="duplicate_low_hp_episode",
                )
            if low_hp_action == "show" and self._should_suppress_post_laning_low_hp_locked(
                state=state,
                now=current_time,
                game_time_seconds=game_time_seconds,
            ):
                self.state.repeated_low_hp_suppressed_count += 1
                self.state.post_laning_safety_suppressed_count += 1
                self.state.duplicate_suppressed_count += 1
                active = self._active_result_locked(
                    decision_point=decision_point,
                    now=current_time,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    suppressed_reason="cooldown_keep_visible",
                )
                if active is not None:
                    return active
                return self._result_locked(
                    status="cooldown",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    new_advice=False,
                    advice_mode="status",
                    suppressed_reason="duplicate_low_hp_episode",
                )
            if low_hp_action == "pattern":
                pattern = _low_hp_pattern_recommendation()
                self.state.advice_count += 1
                self.state.fallback_count += 1
                self.state.low_hp_pattern_advice_count += 1
                self._record_post_laning_safety_locked(
                    now=current_time,
                    state=state,
                    category="low_hp_pattern",
                    game_time_seconds=game_time_seconds,
                )
                self.state._last_low_hp_pattern_at = current_time
                self.state._low_hp_pattern_last_at = current_time
                gap = self._record_shown_advice_timing_locked(
                    decision_point=decision_point,
                    state=state,
                    recommendation=pattern,
                    category="low_hp_pattern",
                    game_time_seconds=game_time_seconds,
                )
                self.state.last_advice_at = current_time
                self.state.last_advice_type = decision_point
                self.state._last_advice_state_hash = state_hash
                self.state._last_advice_tactical_state_hash = tactical_hash
                self.state._last_recommendation = pattern
                self._set_basis_locked(decision_point, pattern, state)
                self.state._last_source = "fallback"
                self.state._last_llm_used = False
                self.state._last_advice_mode = "coaching"
                self.state._last_updated = current_time.isoformat()
                self._set_active_advice_locked(decision_point, state, current_time)
                self.state._advice_history.append(
                    {
                        "timestamp": self.state._last_updated,
                        "decision_point": decision_point,
                        "source": "fallback",
                        "action": pattern.action,
                        "action_type": "low_hp_pattern",
                        "low_hp_episode_id": self.state._low_hp_episode_id,
                        "game_time_gap_since_previous_advice": gap,
                    }
                )
                return ScheduledAdvice(
                    status="advice",
                    decision_point=decision_point,
                    recommendation=pattern,
                    advice_count=self.state.advice_count,
                    llm_used=False,
                    source="fallback",
                    last_updated=self.state._last_updated,
                    next_allowed_advice_in_seconds=self._cooldown_for_type_locked(decision_point),
                    new_advice=True,
                    advice_mode="coaching",
                    suppressed_reason=None,
                    active_advice_until=(
                        self.state._active_advice_until.isoformat()
                        if self.state._active_advice_until
                        else None
                    ),
                    last_visible_advice=pattern.model_dump(),
                    is_pinned=self.state._is_pinned,
                    low_hp_episode_id=self.state._low_hp_episode_id,
                    game_time_gap_since_previous_advice=gap,
                    basis=deepcopy(self.state._active_basis),
                )

        return None

    def _evaluate_ux_laning_locked(
        self,
        *,
        current_time: datetime,
        decision_point: str,
        state: dict[str, Any],
        game_time_seconds: float | None,
        fallback: RecommendationResponse,
        policy: dict[str, Any],
    ) -> _SegmentResult:
        # Phase 4B extract (S8): UX policy application + laning-repeat gate.
        # Behavior-preserving via result object: each early ``return <advice>``
        # becomes ``return _SegmentResult(advice=<advice>)``; the fall-through
        # carries ux_result/fallback/laning_category back to ``evaluate``.
        # Counter mutations stay immediately before their returns, byte-for-byte.
        ux_result = apply_ux_policy(
            fallback,
            decision_point,
            list(self.state._advice_history),
            now=current_time,
            action_type=policy["action_type"],
            moment=self._readiness_moment_locked(decision_point, state) is not None,
        )
        if ux_result["recommendation"] is None:
            reason = ux_result["suppressed_reason"] or "cooldown"
            if reason == "duplicate":
                self.state.duplicate_suppressed_count += 1
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=self._cooldown_for_type_locked(decision_point),
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                return _SegmentResult(advice=active)
            return _SegmentResult(
                advice=self._result_locked(
                    status="cooldown",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    new_advice=False,
                    advice_mode=ux_result["advice_mode"],
                    suppressed_reason=reason,
                )
            )

        fallback = clean_recommendation_text(ux_result["recommendation"], decision_point)
        suppress_laning, laning_category = self._should_suppress_laning_locked(
            decision_point=decision_point,
            state=state,
            recommendation=fallback,
            now=current_time,
            game_time_seconds=game_time_seconds,
        )
        if suppress_laning:
            self.state.repeated_laning_suppressed_count += 1
            self.state.duplicate_suppressed_count += 1
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=self._cooldown_for_type_locked(decision_point),
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                return _SegmentResult(advice=active)
            return _SegmentResult(
                advice=self._result_locked(
                    status="cooldown",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    new_advice=False,
                    advice_mode=ux_result["advice_mode"],
                    suppressed_reason="duplicate_laning",
                )
            )

        return _SegmentResult(
            ux_result=ux_result,
            fallback=fallback,
            laning_category=laning_category,
        )

    def _evaluate_post_laning_locked(
        self,
        *,
        current_time: datetime,
        decision_point: str,
        state: dict[str, Any],
        game_time_seconds: float | None,
        fallback: RecommendationResponse,
        ux_result: dict[str, Any],
    ) -> _SegmentResult:
        # Phase 4B extract (S9): post-laning suppression gate. Behavior-preserving
        # via result object: the suppressed early return becomes
        # _SegmentResult(advice=...); the fall-through carries the (possibly
        # heartbeat-rebound) fallback plus post_laning_category back to
        # evaluate. The heartbeat path REBINDS fallback, so it is returned and
        # rebound in evaluate. Counter mutations stay immediately before the
        # early returns, byte-for-byte.
        suppress_post_laning, post_laning_category, post_laning_reason = (
            self._should_suppress_post_laning_locked(
                decision_point=decision_point,
                state=state,
                recommendation=fallback,
                now=current_time,
                game_time_seconds=game_time_seconds,
            )
        )
        if suppress_post_laning:
            heartbeat = self._heartbeat_nudge_locked(
                decision_point=decision_point,
                state=state,
                recommendation=fallback,
                category=post_laning_category,
                reason=post_laning_reason,
                game_time_seconds=game_time_seconds,
            )
            if heartbeat is not None:
                fallback = heartbeat
                post_laning_category = "post_laning_safe_farm_route"
                post_laning_reason = None
                suppress_post_laning = False
            else:
                if post_laning_reason == "objective_after_recent_safety":
                    self.state.objective_suppressed_by_recent_safety_count += 1
                    self.state.repeated_objective_suppressed_count += 1
                elif post_laning_reason in {"duplicate_objective", "objective_context_missing"}:
                    self.state.repeated_objective_suppressed_count += 1
                elif post_laning_reason == "item_timing_after_recent_safety":
                    self.state.item_timing_suppressed_by_safety_count += 1
                elif post_laning_reason == "death_route_duplicate":
                    self.state.death_route_suppressed_count += 1
                elif post_laning_reason == "recent_safety":
                    self.state.post_laning_safety_suppressed_count += 1
                    self.state.repeated_post_laning_suppressed_count += 1
                else:
                    self.state.repeated_post_laning_suppressed_count += 1
                self.state.duplicate_suppressed_count += 1
                active = self._active_result_locked(
                    decision_point=decision_point,
                    now=current_time,
                    next_allowed=self._cooldown_for_type_locked(decision_point),
                    suppressed_reason="cooldown_keep_visible",
                )
                if active is not None:
                    return _SegmentResult(advice=active)
                return _SegmentResult(
                    advice=self._result_locked(
                        status="cooldown",
                        decision_point=decision_point,
                        recommendation=None,
                        source="none",
                        llm_used=False,
                        next_allowed=self._cooldown_for_type_locked(decision_point),
                        new_advice=False,
                        advice_mode=ux_result["advice_mode"],
                        suppressed_reason=post_laning_reason or "duplicate_post_laning",
                    )
                )

        return _SegmentResult(
            fallback=fallback,
            post_laning_category=post_laning_category,
        )

    def _evaluate_spacing_locked(
        self,
        *,
        current_time: datetime,
        decision_point: str,
        state: dict[str, Any],
        game_time_seconds: float | None,
        fallback: RecommendationResponse,
        ux_result: dict[str, Any],
        post_laning_category: str | None,
        laning_category: str | None,
    ) -> _SegmentResult:
        # Phase 4B extract (S10): game-time spacing gate. Behavior-preserving via
        # result object: the spacing early return becomes _SegmentResult(advice=...).
        # The active sub-path still mutates the active card (suppressed_by_game_time
        # _spacing + gap) before returning it. The fall-through carries no locals
        # back to evaluate (spacing_remaining/spacing_gap are local-only). Counter
        # mutations stay immediately before the early returns, byte-for-byte.
        spacing_remaining, spacing_gap = self._game_time_spacing_remaining_locked(
            decision_point=decision_point,
            state=state,
            recommendation=fallback,
            advice_mode=ux_result["advice_mode"],
            category=post_laning_category or laning_category,
            game_time_seconds=game_time_seconds,
        )
        if spacing_remaining > 0:
            self.state.suppressed_by_game_time_spacing_count += 1
            self.state.duplicate_suppressed_count += 1
            active = self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=spacing_remaining,
                suppressed_reason="cooldown_keep_visible",
            )
            if active is not None:
                active.suppressed_by_game_time_spacing = True
                active.game_time_gap_since_previous_advice = spacing_gap
                return _SegmentResult(advice=active)
            return _SegmentResult(
                advice=self._result_locked(
                    status="cooldown",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=spacing_remaining,
                    new_advice=False,
                    advice_mode=ux_result["advice_mode"],
                    suppressed_reason="game_time_spacing",
                    game_time_gap_since_previous_advice=spacing_gap,
                    suppressed_by_game_time_spacing=True,
                )
            )

        return _SegmentResult()

    def _evaluate_finalize(
        self,
        *,
        should_refine: bool,
        tactical_hash: str,
        request: GameSituationRequest,
        decision_point: str,
        rag_context: list[str],
        fallback: RecommendationResponse,
        next_allowed: int,
        ux_result: dict[str, Any],
        gap: float | None,
    ) -> ScheduledAdvice:
        # Phase 4B extract (S12): async LLM-refinement kickoff + finalize return.
        # NO lock: this runs AFTER the second `with self._lock` block, exactly as
        # the inlined tail did, so it does NOT acquire the lock. The refinement is
        # fire-and-forget and never overrides the rule-based result. State reads
        # (advice_count/_last_updated/_active_advice_until/_is_pinned) stay outside
        # the lock, byte-for-byte.
        if should_refine:
            self._start_llm_refinement(tactical_hash, request, decision_point, rag_context)

        return ScheduledAdvice(
            status="advice",
            decision_point=decision_point,
            recommendation=fallback,
            advice_count=self.state.advice_count,
            llm_used=False,
            source="fallback",
            last_updated=self.state._last_updated,
            next_allowed_advice_in_seconds=next_allowed,
            new_advice=True,
            advice_mode=ux_result["advice_mode"],
            suppressed_reason=None,
            active_advice_until=self.state._active_advice_until.isoformat()
            if self.state._active_advice_until
            else None,
            last_visible_advice=fallback.model_dump(),
            is_pinned=self.state._is_pinned,
            game_time_gap_since_previous_advice=gap,
            hero_gameplay=deepcopy(request.extra_context.get("hero_gameplay"))
            if decision_point == "HERO_GAMEPLAY"
            else None,
            basis=deepcopy(self.state._active_basis),
        )

    def evaluate(
        self,
        request: GameSituationRequest,
        decision_point: str,
        rag_context: list[str] | Callable[[], list[str]],
        now: datetime | None = None,
    ) -> ScheduledAdvice:
        current_time, state, state_hash, policy, tactical_hash = self._evaluate_normalize_input(
            request, decision_point, now
        )

        with self._lock:
            game_time_seconds = self._evaluate_locked_setup(
                current_time=current_time,
                request=request,
                state=state,
                decision_point=decision_point,
                state_hash=state_hash,
                tactical_hash=tactical_hash,
            )

            _no_advice = self._evaluate_no_advice_locked(decision_point, current_time)
            if _no_advice is not None:
                return _no_advice

            cooldown_remaining = (
                0
                if self._readiness_moment_locked(decision_point, state) is not None
                else self._cooldown_remaining_locked(
                    decision_point,
                    current_time,
                    game_time_seconds,
                )
            )
            _duplicate = self._evaluate_duplicate_locked(
                decision_point=decision_point,
                current_time=current_time,
                cooldown_remaining=cooldown_remaining,
                state_hash=state_hash,
                tactical_hash=tactical_hash,
            )
            if _duplicate is not None:
                return _duplicate

            _cooldown = self._evaluate_cooldown_locked(
                decision_point=decision_point,
                current_time=current_time,
                cooldown_remaining=cooldown_remaining,
                tactical_hash=tactical_hash,
            )
            if _cooldown is not None:
                return _cooldown

            _low_hp_warning = self._evaluate_low_hp_warning_locked(
                decision_point, current_time, game_time_seconds
            )
            if _low_hp_warning is not None:
                return _low_hp_warning

            _low_hp = self._evaluate_low_hp_locked(
                current_time=current_time,
                decision_point=decision_point,
                game_time_seconds=game_time_seconds,
                state=state,
                state_hash=state_hash,
                tactical_hash=tactical_hash,
            )
            if _low_hp is not None:
                return _low_hp

        # Retrieval is unnecessary for early suppression and executes outside
        # the scheduler owner. Existing direct-list callers remain compatible.
        if callable(rag_context):
            rag_context = rag_context()
        fallback = self._evaluate_fallback_recommendation(
            request, rag_context, policy, decision_point
        )

        with self._lock:
            channel = self._held_by_channel_locked(state, decision_point, fallback)
            if is_filler(fallback, decision_point) or channel:
                # A card without a decision (a generic «keep farming») is not
                # worth the player's attention: keep what is shown, say nothing.
                self.state.no_new_decision_count += 1
                active = self._active_result_locked(
                    decision_point=decision_point,
                    now=current_time,
                    next_allowed=0,
                    suppressed_reason="cooldown_keep_visible",
                )
                if active is not None:
                    return active
                return self._result_locked(
                    status="no_advice",
                    decision_point=decision_point,
                    recommendation=None,
                    source="none",
                    llm_used=False,
                    next_allowed=0,
                    new_advice=False,
                    advice_mode="status",
                    suppressed_reason="channelling" if channel else "no_new_decision",
                )
            r = self._evaluate_ux_laning_locked(
                current_time=current_time,
                decision_point=decision_point,
                state=state,
                game_time_seconds=game_time_seconds,
                fallback=fallback,
                policy=policy,
            )
            if r.advice is not None:
                return r.advice
            # Fall-through invariant (S8): ux_result/fallback are always populated
            # on the non-advice return (line guarded by the ux_result-is-None and
            # suppress_laning early returns above). laning_category may be None.
            assert r.ux_result is not None and r.fallback is not None
            ux_result, fallback, laning_category = r.ux_result, r.fallback, r.laning_category

            r = self._evaluate_post_laning_locked(
                current_time=current_time,
                decision_point=decision_point,
                state=state,
                game_time_seconds=game_time_seconds,
                fallback=fallback,
                ux_result=ux_result,
            )
            if r.advice is not None:
                return r.advice
            # Fall-through invariant (S9): fallback is always populated on the
            # non-advice return. post_laning_category may be None.
            assert r.fallback is not None
            fallback, post_laning_category = r.fallback, r.post_laning_category

            r = self._evaluate_spacing_locked(
                current_time=current_time,
                decision_point=decision_point,
                state=state,
                game_time_seconds=game_time_seconds,
                fallback=fallback,
                ux_result=ux_result,
                post_laning_category=post_laning_category,
                laning_category=laning_category,
            )
            if r.advice is not None:
                return r.advice

            should_refine, next_allowed, gap = self._evaluate_record_advice_locked(
                current_time=current_time,
                decision_point=decision_point,
                fallback=fallback,
                game_time_seconds=game_time_seconds,
                laning_category=laning_category,
                post_laning_category=post_laning_category,
                state=state,
                state_hash=state_hash,
                tactical_hash=tactical_hash,
                ux_result=ux_result,
            )

        return self._evaluate_finalize(
            should_refine=should_refine,
            tactical_hash=tactical_hash,
            request=request,
            decision_point=decision_point,
            rag_context=rag_context,
            fallback=fallback,
            next_allowed=next_allowed,
            ux_result=ux_result,
            gap=gap,
        )

    # ------------------------------------------------------------------
    # Public helpers — read-only or secondary entry points used by the
    # demo path, the launcher, and debug/stats endpoints.
    # ------------------------------------------------------------------

    def active_advice_for_state(
        self,
        state: dict[str, Any],
        decision_point: str,
        now: datetime | None = None,
    ) -> ScheduledAdvice | None:
        current_time = _utcnow(now)
        minute = _to_int(state.get("minute"), 0)
        state_hash = build_state_hash(state, decision_point)
        policy = build_advice_policy(state, decision_point)
        tactical_hash = build_tactical_state_hash(
            state,
            decision_point,
            action_type=policy["action_type"],
        )
        with self._lock:
            self._ensure_session_locked(current_time, minute, state)
            game_time_seconds = self._game_time_seconds_locked(state, current_time)
            self._update_hashes_locked(state_hash, tactical_hash)
            self._revalidate_active_locked(state, current_time)
            return self._active_result_locked(
                decision_point=decision_point,
                now=current_time,
                next_allowed=self._current_cooldown_remaining_locked(
                    current_time, game_time_seconds
                ),
                suppressed_reason="cooldown_keep_visible",
            )

    def withdrawn_advice(self) -> dict[str, Any] | None:
        """The card withdrawn moments ago (see _revalidate_active_locked)."""
        with self._lock:
            return dict(self.state._withdrawn) if self.state._withdrawn else None

    def stats(self, now: datetime | None = None) -> dict[str, Any]:
        current_time = _utcnow(now)
        with self._lock:
            game_time_seconds = None
            return {
                "match_started_at": self.state.match_started_at.isoformat()
                if self.state.match_started_at
                else None,
                "match_session_id": self.state.match_session_id,
                "advice_count": self.state.advice_count,
                "llm_call_count": self.state.llm_call_count,
                "llm_applied_count": self.state.llm_applied_count,
                "llm_applied_rate": _rate(self.state.llm_applied_count, self.state.llm_call_count),
                "fallback_count": self.state.fallback_count,
                "stale_llm_count": self.state.stale_llm_count,
                "withdrawn_count": self.state.withdrawn_count,
                "no_new_decision_count": self.state.no_new_decision_count,
                "duplicate_suppressed_count": self.state.duplicate_suppressed_count,
                "repeated_laning_suppressed_count": self.state.repeated_laning_suppressed_count,
                "repeated_post_laning_suppressed_count": self.state.repeated_post_laning_suppressed_count,
                "repeated_objective_suppressed_count": self.state.repeated_objective_suppressed_count,
                "post_laning_safety_suppressed_count": self.state.post_laning_safety_suppressed_count,
                "objective_suppressed_by_recent_safety_count": self.state.objective_suppressed_by_recent_safety_count,
                "item_timing_suppressed_by_safety_count": self.state.item_timing_suppressed_by_safety_count,
                "death_route_suppressed_count": self.state.death_route_suppressed_count,
                "low_hp_episode_count": self.state.low_hp_episode_count,
                "repeated_low_hp_suppressed_count": self.state.repeated_low_hp_suppressed_count,
                "low_hp_pattern_advice_count": self.state.low_hp_pattern_advice_count,
                "tactical_hash_changes": self.state.tactical_hash_changes,
                "last_advice_type": self.state.last_advice_type,
                "average_llm_latency": _average(self.state._llm_latencies),
                "p95_llm_latency": _p95(self.state._llm_latencies),
                "current_cooldown_remaining": self._current_cooldown_remaining_locked(
                    current_time, game_time_seconds
                ),
                "active_advice_until": self.state._active_advice_until.isoformat()
                if self.state._active_advice_until
                else None,
                "is_pinned": self.state._is_pinned,
                "suppressed_by_game_time_spacing_count": self.state.suppressed_by_game_time_spacing_count,
                "heartbeat_nudge_count": self.state.heartbeat_nudge_count,
                "suppressed_heartbeat_duplicate_count": self.state.suppressed_heartbeat_duplicate_count,
                "min_game_time_gap_seconds": _minimum(self.state._advice_game_time_gaps_seconds),
                "max_game_time_silence_seconds": _maximum(
                    self.state._advice_game_time_gaps_seconds
                ),
                "average_game_time_gap_seconds": _average(
                    self.state._advice_game_time_gaps_seconds
                ),
                "advice_game_time_gaps_seconds": list(self.state._advice_game_time_gaps_seconds),
            }

    def state_machine_debug(
        self,
        *,
        current_decision_point: str,
        state: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = _utcnow(now)
        raw_extra_context = state.get("extra_context")
        extra_context = raw_extra_context if isinstance(raw_extra_context, dict) else {}
        with self._lock:
            game_time_seconds = self._game_time_seconds_locked(state, current_time)
            return {
                "current_decision_point": current_decision_point,
                "last_full_advice": self.state._last_recommendation.model_dump()
                if self.state._last_recommendation
                else None,
                "last_full_advice_at": self.state._last_updated,
                "active_advice_until": self.state._active_advice_until.isoformat()
                if self.state._active_advice_until
                else None,
                "is_pinned": self.state._is_pinned,
                "cooldown_reason": self._cooldown_reason_locked(
                    current_decision_point, current_time, game_time_seconds
                ),
                "last_shown_game_time_seconds": self.state._last_shown_game_time_seconds,
                "hp_delta_5s": extra_context.get("hp_delta_5s", 0),
                "hp_delta_10s": extra_context.get("hp_delta_10s", 0),
                "recent_damage_taken": extra_context.get("recent_damage_taken", False),
                "alive": extra_context.get("alive"),
                "deaths": extra_context.get("deaths"),
                "match_death_count": extra_context.get("match_death_count", 0),
            }

    @property
    def advice_count(self) -> int:
        # Phase 4 shim: advice_count moved into SchedulerState, but app/main.py
        # and scripts/check_overlay_scheduler_accounting.py read it directly off
        # the scheduler. Keep the public read-only accessor stable so external
        # callers (which we do not edit) keep working.
        return self.state.advice_count

    def llm_latencies(self) -> list[float]:
        with self._lock:
            return list(self.state._llm_latencies)

    def latest_advice_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recommendation = (
                self.state._last_recommendation.model_dump()
                if self.state._last_recommendation is not None
                else None
            )
            return {
                "recommendation": recommendation,
                "source": self.state._last_source,
                "llm_used": self.state._last_llm_used,
                "advice_mode": self.state._last_advice_mode,
                "last_updated": self.state._last_updated,
            }

    def wait_for_pending(self, timeout: float = 0.0) -> None:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                if not self.state._pending_llm_tactical_hashes:
                    return
            time.sleep(0.01)

    # ------------------------------------------------------------------
    # Private locked helpers — all called under self._lock.
    # Groups: hash tracking, suppression logic, low-HP episodes,
    # session management, cooldown, timing, LLM refinement.
    # ------------------------------------------------------------------

    def _update_hashes_locked(self, state_hash: str, tactical_hash: str) -> None:
        self.state.last_state_hash = state_hash
        if (
            self.state.last_tactical_state_hash is not None
            and self.state.last_tactical_state_hash != tactical_hash
        ):
            self.state.tactical_hash_changes += 1
        self.state.last_tactical_state_hash = tactical_hash

    def _last_matching_advice_locked(
        self,
        tactical_hash: str,
    ) -> tuple[RecommendationResponse | None, OverlaySource, bool, str]:
        if (
            self.state._last_recommendation is None
            or self.state._last_advice_tactical_state_hash != tactical_hash
        ):
            return None, "none", False, "status"
        return (
            self.state._last_recommendation,
            self.state._last_source,
            self.state._last_llm_used,
            self.state._last_advice_mode,
        )

    def _should_suppress_laning_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        now: datetime,
        game_time_seconds: float | None,
    ) -> tuple[bool, str | None]:
        laning_advice = build_laning_advice(state, decision_point)
        if laning_advice is None:
            return False, None
        if laning_advice.category == "critical_hp_reset" or decision_point == "LOW_HP":
            return False, laning_advice.category

        previous = self.state._last_laning_category.get(laning_advice.category)
        if previous is None:
            return False, laning_advice.category

        elapsed = self._elapsed_since_locked(previous, now, game_time_seconds)
        changed = important_laning_context_changed(previous, laning_advice)
        same_action = str(previous.get("action") or "") == recommendation.action
        same_category = str(previous.get("category") or "") == laning_advice.category

        if (
            elapsed < REPEAT_WINDOW_SECONDS
            and same_category
            and same_action
            and not _strong_laning_interrupt(previous, laning_advice)
        ):
            return True, laning_advice.category
        if elapsed < REPEAT_WINDOW_SECONDS and not changed:
            return True, laning_advice.category
        if same_action and not changed:
            return True, laning_advice.category
        return False, laning_advice.category

    def _record_laning_advice_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        now: datetime,
        game_time_seconds: float | None,
    ) -> None:
        laning_advice = build_laning_advice(state, decision_point)
        if laning_advice is None:
            return
        self.state._last_laning_category[laning_advice.category] = {
            "at": now,
            "game_time_seconds": game_time_seconds,
            "category": laning_advice.category,
            "action": recommendation.action,
            "farm_deficit": laning_advice.farm_deficit,
            "pressure_state": laning_advice.pressure_state,
            "pressure_active": laning_advice.pressure_active,
            "position_risk": laning_advice.position_risk,
        }

    def _should_suppress_post_laning_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        now: datetime,
        game_time_seconds: float | None,
    ) -> tuple[bool, str | None, str | None]:
        post_laning_advice = build_post_laning_advice(state, decision_point)
        if post_laning_advice is None:
            return False, None, None

        if decision_point == "ITEM_TIMING" and _post_laning_item_timing_is_unsafe(state):
            return True, post_laning_advice.category, "item_timing_after_recent_safety"

        if decision_point == "ITEM_TIMING" and self._recent_post_laning_safety_locked(
            now,
            seconds=POST_LANING_DEATH_ROUTE_WINDOW_SECONDS,
            game_time_seconds=game_time_seconds,
        ):
            return True, post_laning_advice.category, "item_timing_after_recent_safety"

        if post_laning_advice.category == "post_laning_death_route_reset":
            if decision_point not in DEATH_REVIEW_DECISIONS and not _is_dead_or_respawning(state):
                return True, post_laning_advice.category, "death_route_duplicate"
            if self._should_suppress_death_route_locked(state, now, game_time_seconds):
                return True, post_laning_advice.category, "death_route_duplicate"

        # Urgent cards are never a repeat of a farm card: a silence or stun with
        # Manta ready was swallowed as «duplicate_post_laning» after a farm card
        # of the same post-laning category had been shown.
        if post_laning_advice.category == "post_laning_low_hp_reset" or decision_point in {
            "LOW_HP",
            "DISABLED_STATUS",
        }:
            return False, post_laning_advice.category, None

        if post_laning_advice.category == "post_laning_objective_caution":
            if self._recent_post_laning_safety_locked(
                now,
                seconds=POST_LANING_RECENT_SAFETY_WINDOW_SECONDS,
                game_time_seconds=game_time_seconds,
            ):
                if not _objective_context_changed_clearly(state):
                    return True, post_laning_advice.category, "objective_after_recent_safety"
            if (
                post_laning_advice.objective_context_missing
                and not post_laning_advice.clear_pressure_context
            ):
                return True, post_laning_advice.category, "objective_context_missing"
            if self.state._last_objective_advice_at is not None:
                elapsed = self._elapsed_since_time_locked(
                    at=self.state._last_objective_advice_at,
                    game_time_at=getattr(self, "_last_objective_advice_game_time", None),
                    now=now,
                    game_time_seconds=game_time_seconds,
                )
                if elapsed < OBJECTIVE_REPEAT_WINDOW_SECONDS:
                    return True, post_laning_advice.category, "duplicate_objective"

        if self._recent_post_laning_safety_locked(
            now,
            seconds=POST_LANING_RECENT_SAFETY_WINDOW_SECONDS,
            game_time_seconds=game_time_seconds,
        ) and _is_lower_value_post_laning_advice(decision_point, post_laning_advice.category):
            if not _post_laning_safety_suppression_exception(
                state, decision_point, post_laning_advice
            ):
                return True, post_laning_advice.category, "recent_safety"

        previous = self.state._last_post_laning_category.get(post_laning_advice.category)
        if previous is None:
            return False, post_laning_advice.category, None

        elapsed = self._elapsed_since_locked(previous, now, game_time_seconds)
        changed = important_post_laning_context_changed(previous, post_laning_advice)
        same_action = str(previous.get("action") or "") == recommendation.action
        same_category = str(previous.get("category") or "") == post_laning_advice.category
        strong_interrupt = _strong_post_laning_interrupt(previous, post_laning_advice)

        if (
            elapsed <= POST_LANING_SAME_ACTION_WINDOW_SECONDS
            and same_category
            and same_action
            and not strong_interrupt
        ):
            return True, post_laning_advice.category, "duplicate_post_laning"
        if (
            elapsed < POST_LANING_REPEAT_WINDOW_SECONDS
            and same_category
            and same_action
            and not strong_interrupt
        ):
            return True, post_laning_advice.category, "duplicate_post_laning"
        if elapsed < POST_LANING_REPEAT_WINDOW_SECONDS and not changed:
            return True, post_laning_advice.category, "duplicate_post_laning"
        if same_action and not changed and not strong_interrupt:
            return True, post_laning_advice.category, "duplicate_post_laning"
        return False, post_laning_advice.category, None

    def _record_post_laning_advice_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        now: datetime,
        game_time_seconds: float | None,
    ) -> None:
        post_laning_advice = build_post_laning_advice(state, decision_point)
        if post_laning_advice is None:
            return
        self.state._last_post_laning_category[post_laning_advice.category] = {
            "at": now,
            "game_time_seconds": game_time_seconds,
            "category": post_laning_advice.category,
            "action": recommendation.action,
            "farm_quality": post_laning_advice.farm_quality,
            "hp_pressure_state": post_laning_advice.hp_pressure_state,
            "pressure_active": post_laning_advice.pressure_active,
            "position_risk": post_laning_advice.position_risk,
            "position_zone": post_laning_advice.position_zone,
        }
        if post_laning_advice.category == "post_laning_objective_caution":
            self.state._last_objective_advice_at = now
            self.state._last_objective_advice_game_time = game_time_seconds

    def _should_suppress_post_laning_low_hp_locked(
        self,
        *,
        state: dict[str, Any],
        now: datetime,
        game_time_seconds: float | None,
    ) -> bool:
        if _to_int(state.get("minute"), 0) < 10:
            return False
        if self.state._last_low_hp_urgent_at is None:
            return False
        if self.state._last_low_hp_pattern_at is not None:
            elapsed_pattern = self._elapsed_since_time_locked(
                at=self.state._last_low_hp_pattern_at,
                game_time_at=getattr(self, "_last_low_hp_pattern_game_time", None),
                now=now,
                game_time_seconds=game_time_seconds,
            )
            if (
                elapsed_pattern < POST_LANING_RECENT_SAFETY_WINDOW_SECONDS
                and not _post_laning_new_death_or_severe_pressure(state)
            ):
                return True
        elapsed = self._elapsed_since_time_locked(
            at=self.state._last_low_hp_urgent_at,
            game_time_at=getattr(self, "_last_low_hp_urgent_game_time", None),
            now=now,
            game_time_seconds=game_time_seconds,
        )
        if elapsed >= POST_LANING_RECENT_SAFETY_WINDOW_SECONDS:
            return False
        if self.state._post_laning_hp_recovered_since_safety:
            return False
        if _post_laning_new_death_or_severe_pressure(state):
            return False
        return True

    def _should_suppress_death_route_locked(
        self,
        state: dict[str, Any],
        now: datetime,
        game_time_seconds: float | None,
    ) -> bool:
        if self._recent_post_laning_safety_locked(
            now,
            seconds=POST_LANING_DEATH_ROUTE_WINDOW_SECONDS,
            game_time_seconds=game_time_seconds,
        ) and not _is_dead_or_respawning(state):
            return True

        if self.state._last_low_hp_pattern_at is not None:
            elapsed_pattern = self._elapsed_since_time_locked(
                at=self.state._last_low_hp_pattern_at,
                game_time_at=getattr(self, "_last_low_hp_pattern_game_time", None),
                now=now,
                game_time_seconds=game_time_seconds,
            )
            if elapsed_pattern < POST_LANING_DEATH_ROUTE_WINDOW_SECONDS:
                return True

        if self.state._last_post_laning_death_route_at is None:
            return False

        elapsed = self._elapsed_since_time_locked(
            at=self.state._last_post_laning_death_route_at,
            game_time_at=getattr(self, "_last_post_laning_death_route_game_time", None),
            now=now,
            game_time_seconds=game_time_seconds,
        )
        if elapsed >= POST_LANING_DEATH_ROUTE_WINDOW_SECONDS:
            return False

        current_event_id = _death_event_id(state)
        if (
            current_event_id
            and current_event_id != self.state._last_post_laning_death_route_event_id
        ):
            return False
        return True

    def _record_safety_advice_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        post_laning_category: str | None,
        now: datetime,
        game_time_seconds: float | None,
    ) -> None:
        if _to_int(state.get("minute"), 0) < 10:
            return
        if decision_point == "LOW_HP":
            self.state._last_low_hp_urgent_at = now
            self.state._last_low_hp_urgent_game_time = game_time_seconds
            self._record_post_laning_safety_locked(
                now=now,
                state=state,
                category=post_laning_category or "post_laning_low_hp_reset",
                game_time_seconds=game_time_seconds,
            )
            return
        if (
            decision_point in DEATH_REVIEW_DECISIONS
            or post_laning_category == "post_laning_death_route_reset"
        ):
            self._record_post_laning_safety_locked(
                now=now,
                state=state,
                category=post_laning_category or decision_point,
                game_time_seconds=game_time_seconds,
            )

    def _record_post_laning_safety_locked(
        self,
        *,
        now: datetime,
        state: dict[str, Any],
        category: str,
        game_time_seconds: float | None,
    ) -> None:
        if _to_int(state.get("minute"), 0) < 10:
            return
        self.state._last_post_laning_safety_at = now
        self.state._last_post_laning_safety_game_time = game_time_seconds
        self.state._post_laning_hp_recovered_since_safety = False
        if category == "post_laning_death_route_reset":
            self.state._last_post_laning_death_route_at = now
            self.state._last_post_laning_death_route_game_time = game_time_seconds
            self.state._last_post_laning_death_route_event_id = _death_event_id(state)
        if category == "low_hp_pattern":
            self.state._last_low_hp_pattern_at = now
            self.state._last_low_hp_pattern_game_time = game_time_seconds

    def _recent_post_laning_safety_locked(
        self,
        now: datetime,
        *,
        seconds: int,
        game_time_seconds: float | None,
    ) -> bool:
        if self.state._last_post_laning_safety_at is None:
            return False
        return (
            self._elapsed_since_time_locked(
                at=self.state._last_post_laning_safety_at,
                game_time_at=getattr(self, "_last_post_laning_safety_game_time", None),
                now=now,
                game_time_seconds=game_time_seconds,
            )
            <= seconds
        )

    def _update_low_hp_recovery_locked(self, state: dict[str, Any]) -> None:
        hp_percent = _ctx_int(state, "hp_percent", _to_int(state.get("hp_percent"), 100))
        if _is_dead_or_respawning(state):
            self.state._low_hp_episode_active = False
            self.state._low_hp_episode_lowest_hp = None
            self.state._low_hp_episode_repeat_count = 0
            self.state._low_hp_episode_pattern_shown = False
            self.state._low_hp_episode_last_severe_signature = None
            return
        if hp_percent > 60:
            self.state._low_hp_episode_active = False
            self.state._low_hp_episode_lowest_hp = None
            self.state._low_hp_episode_repeat_count = 0
            self.state._low_hp_episode_pattern_shown = False
            self.state._low_hp_episode_last_severe_signature = None
            if _to_int(state.get("minute"), 0) >= 10:
                self.state._post_laning_hp_recovered_since_safety = True

    def _low_hp_episode_action_locked(self, state: dict[str, Any]) -> str:
        hp_percent = _ctx_int(state, "hp_percent", _to_int(state.get("hp_percent"), 100))
        severe_signature = _low_hp_severe_signature(state)
        raw_extra = state.get("extra_context")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
        recovering = _to_int(
            extra.get("hp_rise_3s"), 0
        ) >= LOW_HP_RECOVERING_POINTS and not extra.get("hp_falling_fast")
        if recovering and (self.state._low_hp_episode_active or extra.get("regen_active")):
            # HP is coming back (own regen running, or healed since the card):
            # the player is already acting; only a new fall speaks again.
            if not self.state._low_hp_episode_active:
                self._start_low_hp_episode_locked(hp_percent, severe_signature)
            self.state._low_hp_episode_lowest_hp = min(
                hp_percent, self.state._low_hp_episode_lowest_hp or hp_percent
            )
            return "suppress"

        if not self.state._low_hp_episode_active:
            self._start_low_hp_episode_locked(hp_percent, severe_signature)
            return "show"

        lowest_hp = self.state._low_hp_episode_lowest_hp
        significant_drop = lowest_hp is not None and hp_percent <= lowest_hp - 15
        new_severe_event = bool(
            severe_signature
            and severe_signature != self.state._low_hp_episode_last_severe_signature
        )
        if significant_drop or new_severe_event:
            self.state._low_hp_episode_lowest_hp = (
                hp_percent if lowest_hp is None else min(lowest_hp, hp_percent)
            )
            self.state._low_hp_episode_last_severe_signature = severe_signature
            self.state._low_hp_episode_repeat_count = 0
            return "show"

        self.state._low_hp_episode_repeat_count += 1
        if (
            self.state._low_hp_episode_repeat_count >= 2
            and not self.state._low_hp_episode_pattern_shown
        ):
            self.state._low_hp_episode_pattern_shown = True
            if not self.state._low_hp_pattern_advice_shown:
                self.state._low_hp_pattern_advice_shown = True
                return "pattern"
        return "suppress"

    def _start_low_hp_episode_locked(
        self,
        hp_percent: int,
        severe_signature: str | None,
    ) -> None:
        self.state.low_hp_episode_count += 1
        self.state._low_hp_episode_id += 1
        self.state._low_hp_episode_active = True
        self.state._low_hp_episode_lowest_hp = hp_percent
        self.state._low_hp_episode_repeat_count = 0
        self.state._low_hp_episode_pattern_shown = False
        self.state._low_hp_episode_last_severe_signature = severe_signature

    def _recent_low_hp_pattern_locked(
        self,
        now: datetime,
        game_time_seconds: float | None,
    ) -> bool:
        if self.state._low_hp_pattern_last_at is None:
            return False
        return (
            self._elapsed_since_time_locked(
                at=self.state._low_hp_pattern_last_at,
                game_time_at=getattr(self, "_last_low_hp_pattern_game_time", None),
                now=now,
                game_time_seconds=game_time_seconds,
            )
            < REPEAT_WINDOW_SECONDS
        )

    def _active_result_locked(
        self,
        *,
        decision_point: str,
        now: datetime,
        next_allowed: int,
        suppressed_reason: str,
    ) -> ScheduledAdvice | None:
        if (
            self.state._last_recommendation is None
            or self.state._active_advice_until is None
            or now >= self.state._active_advice_until
        ):
            return None

        return self._result_locked(
            status="active_advice",
            decision_point=self.state.last_advice_type or decision_point,
            recommendation=self.state._last_recommendation,
            source=self.state._last_source,
            llm_used=self.state._last_llm_used,
            next_allowed=next_allowed,
            new_advice=False,
            advice_mode=self.state._last_advice_mode,
            suppressed_reason=suppressed_reason,
        )

    def _set_active_advice_locked(
        self,
        decision_point: str,
        state: dict[str, Any],
        now: datetime,
    ) -> None:
        duration = _active_advice_duration(decision_point, state)
        self.state._active_advice_until = now + duration
        self.state._is_pinned = decision_point in DEATH_REVIEW_DECISIONS or _is_dead_or_respawning(
            state
        )

    def _held_by_channel_locked(
        self, state: dict[str, Any], decision_point: str, card: RecommendationResponse
    ) -> bool:
        """A TP channel is on (action_feedback teleporting): a card that names
        no tool to press (leave, farm elsewhere, group up) asks for what the
        TP already does or cannot be done without cancelling it, urgent or
        not («leave the wave now» while the TP home channels). A card naming a
        tool still passes: a Wand or a Faerie Fire may save the channel."""
        raw_extra = state.get("extra_context")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
        if extra.get("teleporting") is not True or decision_point == "DISABLED_STATUS":
            return False
        return named_tool(card.action, state) is None

    def _readiness_moment_locked(
        self, decision_point: str, state: dict[str, Any]
    ) -> tuple[str, int] | None:
        """The kill or revive a readiness card (live_tools.readiness_copy) is
        about, while its first card is not shown yet: such a card is useful for
        seconds, so it passes the type cooldown, coaching spacing and the minute
        quota once; the next one waits as usual. Only with a fight still around
        (team_context.contest_near), and at most once per READINESS_BYPASS_GAP
        of game time: a multi-kill or a kill right after a revive is one
        moment, not one spoken card each."""
        if decision_point != "ABILITY_SAFETY_COOLDOWN":
            return None
        raw_extra = state.get("extra_context")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}
        clock = extra.get("clock_time")
        if not isinstance(clock, int):
            return None
        revive = extra.get("recent_revive")
        key: tuple[str, int] | None = None
        if isinstance(revive, dict) and isinstance(revive.get("seconds_ago"), int):
            key = ("revive", clock - revive["seconds_ago"])
        elif isinstance(extra.get("recent_kill_seconds"), int):
            key = ("kill", clock - extra["recent_kill_seconds"])
        if key is None or key == self.state._readiness_shown_key:
            return None
        shown = self.state._readiness_shown_key
        if shown is not None and 0 <= key[1] - shown[1] < READINESS_BYPASS_GAP:
            return None
        if not contest_near(extra):
            return None
        return key

    def _set_basis_locked(
        self, decision_point: str, recommendation: RecommendationResponse, state: dict[str, Any]
    ) -> None:
        self.state._card_serial += 1
        self.state._active_basis = advice_basis(
            decision_point, recommendation.action, recommendation.reason, state
        )
        self.state._withdrawn = None
        self.state._withdrawn_until = None

    def _revalidate_active_locked(self, state: dict[str, Any], now: datetime) -> None:
        """Drop the held card once the snapshot no longer supports it
        (advice_validity.withdraw_reason): it is neither shown nor spoken again."""
        if self.state._withdrawn_until is not None and now >= self.state._withdrawn_until:
            self.state._withdrawn = None
            self.state._withdrawn_until = None
        recommendation = self.state._last_recommendation
        basis = self.state._active_basis
        if recommendation is None or basis is None:
            return
        reason = withdraw_reason(basis, state)
        if reason is None:
            # Still valid: the numbers it quotes are this snapshot's.
            refreshed = refreshed_reason(basis, recommendation.reason, state)
            if refreshed is not None:
                self.state._last_recommendation = recommendation.model_copy(
                    update={"reason": refreshed}
                )
            return
        self.state.withdrawn_count += 1
        self.state._withdrawn = {
            "decision_point": basis.get("decision_point"),
            "action": recommendation.action,
            "reason": reason,
            "card_clock": basis.get("clock"),
        }
        self.state._withdrawn_until = now + WITHDRAWN_NOTICE
        if reason in {"cannot_act_now", "superseded_by_threat"}:
            # Not done, only overtaken (a stun landed on «use X now»): the next
            # low-HP evaluation may speak again, in the form that fits now.
            self.state._low_hp_episode_active = False
        self.state._last_recommendation = None
        self.state._active_advice_until = None
        self.state._active_basis = None
        self.state._is_pinned = False
        self.state._last_gameplay_context = None

    def _cancel_gameplay_if_invalid_locked(self, state: dict[str, Any]) -> None:
        context = self.state._last_gameplay_context
        if context is not None and not rule_valid(state, context.get("rule_id")):
            self.state._active_advice_until = None
            self.state._last_recommendation = None
            self.state._last_gameplay_context = None

    def _ensure_session_locked(self, now: datetime, minute: int, state: dict[str, Any]) -> None:
        session_id = _session_id_from_state(state)
        if self.state.match_started_at is None:
            self.state.match_started_at = now
            self.state.match_session_id = session_id
            self.state._last_seen_minute = minute
            return

        if session_id and self.state.match_session_id and session_id != self.state.match_session_id:
            self._reset_locked()
            self.state.match_started_at = now
            self.state.match_session_id = session_id
            self.state._last_seen_minute = minute
            return

        if session_id and self.state.match_session_id is None:
            self.state.match_session_id = session_id

        if self.state._last_seen_minute is not None and minute < self.state._last_seen_minute - 5:
            self._reset_locked()
            self.state.match_started_at = now
            self.state.match_session_id = session_id

        self.state._last_seen_minute = minute

    def _game_time_seconds_locked(self, state: dict[str, Any], now: datetime) -> float | None:
        explicit = _state_game_time_seconds(state)
        if explicit is not None:
            return explicit
        if self.state.match_started_at is None:
            return None
        return max(0.0, (now - self.state.match_started_at).total_seconds())

    def _elapsed_since_locked(
        self,
        previous: dict[str, Any],
        now: datetime,
        game_time_seconds: float | None,
    ) -> float:
        return self._elapsed_since_time_locked(
            at=previous.get("at"),
            game_time_at=previous.get("game_time_seconds"),
            now=now,
            game_time_seconds=game_time_seconds,
        )

    def _elapsed_since_time_locked(
        self,
        *,
        at: Any,
        game_time_at: Any,
        now: datetime,
        game_time_seconds: float | None,
    ) -> float:
        previous_game_time = _optional_float(game_time_at)
        if previous_game_time is not None and game_time_seconds is not None:
            return max(0.0, game_time_seconds - previous_game_time)
        if isinstance(at, datetime):
            return max(0.0, (now - at).total_seconds())
        return 999999.0

    def _game_time_spacing_remaining_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        advice_mode: str,
        category: str | None,
        game_time_seconds: float | None,
    ) -> tuple[int, float | None]:
        if self.state._last_shown_game_time_seconds is None or game_time_seconds is None:
            return 0, None

        gap = max(0.0, game_time_seconds - self.state._last_shown_game_time_seconds)
        if decision_point in {"LOW_HP", *DEATH_REVIEW_DECISIONS}:
            return 0, gap
        if self._readiness_moment_locked(decision_point, state) is not None:
            return 0, gap

        min_gap = 0
        normalized_category = str(category or decision_point or "").strip()
        action_hash = _action_hash(recommendation.action)
        same_action = action_hash == self.state._last_shown_action_hash
        same_category = (
            normalized_category and normalized_category == self.state._last_shown_category
        )
        post_laning = _to_int(state.get("minute"), 0) >= 10

        if decision_point in {"RECENT_DAMAGE_WARNING", "OVERSTAY_WARNING"}:
            if self.state._last_shown_decision_point in {
                "LOW_HP",
                "RECENT_DAMAGE_WARNING",
                "OVERSTAY_WARNING",
                *DEATH_REVIEW_DECISIONS,
            }:
                min_gap = max(min_gap, RECENT_SAFETY_GAME_TIME_GAP_SECONDS)

        if same_action and same_category:
            min_gap = max(
                min_gap, scaled_seconds(SAME_ACTION_GAME_TIME_GAP_SECONDS, self.frequency)
            )
        elif advice_mode == "coaching":
            min_gap = max(min_gap, scaled_seconds(COACHING_GAME_TIME_GAP_SECONDS, self.frequency))

        if (
            post_laning
            and advice_mode == "coaching"
            and str(recommendation.priority or "").lower() in {"medium", "high"}
            and same_category
        ):
            min_gap = max(
                min_gap, scaled_seconds(POST_LANING_GAME_TIME_GAP_SECONDS, self.frequency)
            )

        # Advice the player keeps marking as not to the point waits twice as long.
        if advice_mode == "coaching" and decision_point in self.quieter:
            min_gap *= QUIETER_GAP_FACTOR

        # A farm pace card keeps its own four minutes, even with other advice
        # shown in between (which moves the last-shown values above).
        pace_at = self.state._farm_pace_shown_game_time
        pace_left = 0.0
        if recommendation.action.startswith(FARM_PACE_PREFIX) and pace_at is not None:
            repeat = FARM_PACE_REPEAT_SECONDS * (
                2 if self.state._farm_pace_shown_count >= FARM_PACE_SLOW_AFTER else 1
            )
            pace_left = scaled_seconds(repeat, self.frequency) - max(
                0.0, game_time_seconds - pace_at
            )
        left = max(min_gap - gap if min_gap > 0 else 0.0, pace_left)
        if left <= 0:
            return 0, gap
        return int(max(1, round(left))), gap

    def _heartbeat_nudge_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        category: str | None,
        reason: str | None,
        game_time_seconds: float | None,
    ) -> RecommendationResponse | None:
        if not self._heartbeat_allowed_locked(
            decision_point=decision_point,
            state=state,
            game_time_seconds=game_time_seconds,
        ):
            return None

        # _heartbeat_allowed_locked returns False whenever game_time_seconds is None,
        # so reaching this point guarantees it is set (narrows float | None -> float).
        assert game_time_seconds is not None
        gap = max(0.0, game_time_seconds - (self.state._last_shown_game_time_seconds or 0.0))
        if (
            category
            and category == self.state._last_shown_category
            and _action_hash(recommendation.action) == self.state._last_shown_action_hash
            and gap < HEARTBEAT_DUPLICATE_WAIT_SECONDS
        ):
            self.state.suppressed_heartbeat_duplicate_count += 1
            return None

        if reason in {
            "objective_after_recent_safety",
            "objective_context_missing",
            "duplicate_objective",
            "item_timing_after_recent_safety",
            "death_route_duplicate",
        }:
            return None

        action, reason_text, risk = _heartbeat_copy(state)
        if action in FILLER_ACTIONS:
            # Nothing to decide: the nudge stays silent rather than repeat
            # «keep farming» (the frequency setting still spaces real cards).
            return None
        return RecommendationResponse(
            action=action,
            reason=reason_text,
            risk=risk,
            priority="low",
            time_window="reassess in 60-90 seconds",
            source="fallback",
        )

    def _heartbeat_allowed_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        game_time_seconds: float | None,
    ) -> bool:
        if game_time_seconds is None or self.state._last_shown_game_time_seconds is None:
            return False
        if not heartbeat_enabled(self.frequency):
            return False
        if game_time_seconds - self.state._last_shown_game_time_seconds < scaled_seconds(
            HEARTBEAT_NUDGE_SECONDS, self.frequency
        ):
            return False
        if _to_int(state.get("minute"), 0) < 10:
            return False
        if decision_point in {
            "LOW_HP",
            "RECENT_DAMAGE_WARNING",
            "OVERSTAY_WARNING",
            "BUYBACK_AVAILABLE",
            "DISABLED_STATUS",
            *DEATH_REVIEW_DECISIONS,
        }:
            return False
        if _is_dead_or_respawning(state) or self.state._is_pinned:
            return False
        if self.state._last_shown_decision_point in {"LOW_HP", *DEATH_REVIEW_DECISIONS}:
            recent_safety_gap = game_time_seconds - self.state._last_shown_game_time_seconds
            if recent_safety_gap < POST_LANING_RECENT_SAFETY_WINDOW_SECONDS:
                return False
        if not _heartbeat_context_is_confident(state):
            return False
        return _heartbeat_safe_category_available(state)

    def _record_shown_advice_timing_locked(
        self,
        *,
        decision_point: str,
        state: dict[str, Any],
        recommendation: RecommendationResponse,
        category: str | None,
        game_time_seconds: float | None,
    ) -> float | None:
        gap = None
        if self.state._last_shown_game_time_seconds is not None and game_time_seconds is not None:
            gap = max(0.0, game_time_seconds - self.state._last_shown_game_time_seconds)
            self.state._advice_game_time_gaps_seconds.append(round(gap, 1))

        self.state._last_shown_game_time_seconds = game_time_seconds
        self.state._last_shown_decision_point = decision_point
        self.state._last_shown_category = str(category or decision_point or "").strip()
        self.state._last_shown_action_hash = _action_hash(recommendation.action)
        if recommendation.action.startswith(FARM_PACE_PREFIX):
            self.state._farm_pace_shown_game_time = game_time_seconds
            self.state._farm_pace_shown_count += 1
        return None if gap is None else round(gap, 1)

    def _result_locked(
        self,
        *,
        status: OverlayStatus,
        decision_point: str,
        recommendation: RecommendationResponse | None,
        source: OverlaySource,
        llm_used: bool,
        next_allowed: int,
        new_advice: bool,
        advice_mode: str,
        suppressed_reason: str | None,
        game_time_gap_since_previous_advice: float | None = None,
        suppressed_by_game_time_spacing: bool = False,
    ) -> ScheduledAdvice:
        return ScheduledAdvice(
            status=status,
            decision_point=decision_point,
            recommendation=recommendation,
            advice_count=self.state.advice_count,
            llm_used=llm_used,
            source=source,
            last_updated=self.state._last_updated,
            next_allowed_advice_in_seconds=max(0, next_allowed),
            new_advice=new_advice,
            advice_mode=advice_mode,
            suppressed_reason=suppressed_reason,
            active_advice_until=self.state._active_advice_until.isoformat()
            if self.state._active_advice_until
            else None,
            last_visible_advice=self.state._last_recommendation.model_dump()
            if self.state._last_recommendation
            else None,
            is_pinned=self.state._is_pinned,
            low_hp_episode_id=self.state._low_hp_episode_id if decision_point == "LOW_HP" else None,
            game_time_gap_since_previous_advice=game_time_gap_since_previous_advice,
            suppressed_by_game_time_spacing=suppressed_by_game_time_spacing,
            hero_gameplay=deepcopy(self.state._last_gameplay_context)
            if recommendation is not None and decision_point == "HERO_GAMEPLAY"
            else None,
            basis=deepcopy(self.state._active_basis) if recommendation is not None else None,
            withdrawn_advice=dict(self.state._withdrawn) if self.state._withdrawn else None,
        )

    def _cooldown_remaining_locked(
        self,
        decision_point: str,
        now: datetime,
        game_time_seconds: float | None,
    ) -> int:
        if self.state.last_advice_at is None:
            return 0

        if (
            decision_point
            in {
                "LOW_HP",
                "DISABLED_STATUS",
                "RECENT_DAMAGE_WARNING",
                "OVERSTAY_WARNING",
                *DEATH_REVIEW_DECISIONS,
            }
            and self.state.last_advice_type != decision_point
        ):
            return 0

        cooldown = self._cooldown_for_type_locked(decision_point)
        elapsed = self._elapsed_since_time_locked(
            at=self.state.last_advice_at,
            game_time_at=self.state._last_shown_game_time_seconds,
            now=now,
            game_time_seconds=game_time_seconds,
        )
        return max(0, int(cooldown - elapsed))

    def _current_cooldown_remaining_locked(
        self,
        now: datetime,
        game_time_seconds: float | None,
    ) -> int:
        if self.state.last_advice_at is None or self.state.last_advice_type is None:
            return 0
        cooldown = self._cooldown_for_type_locked(self.state.last_advice_type)
        elapsed = self._elapsed_since_time_locked(
            at=self.state.last_advice_at,
            game_time_at=self.state._last_shown_game_time_seconds,
            now=now,
            game_time_seconds=game_time_seconds,
        )
        return max(0, int(cooldown - elapsed))

    def _cooldown_for_type_locked(self, decision_point: str) -> int:
        if decision_point in {"LOW_HP", "DISABLED_STATUS", *DEATH_REVIEW_DECISIONS}:
            return self.urgent_cooldown_seconds
        if decision_point in UNSCALED_DECISIONS:
            return self.regular_cooldown_seconds
        return scaled_seconds(self.regular_cooldown_seconds, self.frequency)

    def _cooldown_reason_locked(
        self,
        decision_point: str,
        now: datetime,
        game_time_seconds: float | None,
    ) -> str | None:
        if (
            self.state._last_recommendation is not None
            and self.state._active_advice_until
            and now < self.state._active_advice_until
        ):
            return "cooldown_keep_visible"
        remaining = self._cooldown_remaining_locked(decision_point, now, game_time_seconds)
        return "cooldown" if remaining > 0 else None

    def _should_start_llm_locked(self, decision_point: str, tactical_hash: str) -> bool:
        if decision_point in {
            "NO_ADVICE",
            "SOFT_STATUS",
            "LOW_HP",
            "HERO_GAMEPLAY",
            *DEATH_REVIEW_DECISIONS,
        }:
            return False
        if not self._llm_enabled():
            return False
        if tactical_hash in self.state._pending_llm_tactical_hashes:
            return False
        if decision_point in {
            "OBJECTIVE_FIGHT_CHECK",
            "BAD_FIGHT_RISK",
            "ITEM_TIMING",
            "HERO_SURVIVABILITY_RISK",
        }:
            self.state._pending_llm_tactical_hashes.add(tactical_hash)
            self.state.llm_call_count += 1
            return True
        if self.state.advice_count % LLM_REFINEMENT_EVERY_N_ADVICES == 0:
            self.state._pending_llm_tactical_hashes.add(tactical_hash)
            self.state.llm_call_count += 1
            return True
        return False

    def _llm_enabled(self) -> bool:
        if self.enable_llm is not None:
            return self.enable_llm
        return USE_LLM and is_llm_provider_enabled()

    def _start_llm_refinement(
        self,
        tactical_hash: str,
        request: GameSituationRequest,
        decision_point: str,
        rag_context: list[str],
    ) -> None:
        thread = threading.Thread(
            target=self._run_llm_refinement,
            args=(tactical_hash, request, decision_point, rag_context, self.state._card_serial),
            daemon=True,
        )
        thread.start()

    def _run_llm_refinement(
        self,
        tactical_hash: str,
        request: GameSituationRequest,
        decision_point: str,
        rag_context: list[str],
        card_serial: int | None = None,
    ) -> None:
        started = time.perf_counter()
        result = generate_llm_recommendation(request, decision_point, rag_context)
        latency = time.perf_counter() - started

        with self._lock:
            self.state._pending_llm_tactical_hashes.discard(tactical_hash)
            self.state._llm_latencies.append(latency)

            if self.state.last_tactical_state_hash != tactical_hash or (
                card_serial is not None
                and (
                    card_serial != self.state._card_serial
                    or self.state._last_recommendation is None
                )
            ):
                # A newer card (or a withdrawn one): the late answer is for a
                # situation that is gone and must not overwrite the decision.
                self.state.stale_llm_count += 1
                return

            if result.recommendation is None:
                return

            policy = build_advice_policy(request, decision_point)
            recommendation = apply_advice_policy(result.recommendation, policy)
            recommendation = _compact_recommendation(recommendation, decision_point)
            ux_result = apply_ux_policy(
                recommendation,
                decision_point,
                [],
                action_type=policy["action_type"],
            )
            if ux_result["recommendation"] is None:
                if ux_result["suppressed_reason"] == "duplicate":
                    self.state.duplicate_suppressed_count += 1
                return
            recommendation = clean_recommendation_text(ux_result["recommendation"], decision_point)
            if not _is_safe_recommendation(recommendation, decision_point):
                return

            self.state._last_recommendation = recommendation
            self.state._active_basis = advice_basis(
                decision_point, recommendation.action, recommendation.reason, request.model_dump()
            )
            self.state._last_source = "llm"
            self.state._last_llm_used = True
            self.state.llm_applied_count += 1
            self.state._last_updated = datetime.now(UTC).isoformat()
            if self.state._advice_history:
                self.state._advice_history[-1]["source"] = "llm"
                self.state._advice_history[-1]["action"] = recommendation.action


def _is_safe_recommendation(recommendation: RecommendationResponse, decision_point: str) -> bool:
    if (
        len(recommendation.action) > MAX_ACTION_LENGTH
        or len(recommendation.reason) > MAX_REASON_LENGTH
    ):
        return False
    text = f"{recommendation.action} {recommendation.reason}".lower()
    mechanical_terms = (
        "press ",
        "click ",
        "hotkey",
        "animation cancel",
        "manta dodge",
        "blink dodge",
    )
    if any(term in text for term in mechanical_terms):
        return False
    if decision_point in {
        "BAD_FIGHT_RISK",
        "LOW_MANA",
        "LOW_HP_WARNING",
        "RECENT_DAMAGE_WARNING",
        "OVERSTAY_WARNING",
        "DISABLED_STATUS",
        "BUYBACK_AVAILABLE",
        "DEAD_WAIT",
        "SMOKED_STATUS",
        "HERO_SURVIVABILITY_RISK",
        "ABILITY_SAFETY_COOLDOWN",
        "LANING_REGEN_CHECK",
        *DEATH_REVIEW_DECISIONS,
    } and _suggests_fighting_without_safety(text):
        return False
    if decision_point != "LOW_HP":
        return True

    return not _suggests_fighting_without_safety(text)


def _is_lower_value_post_laning_advice(decision_point: str, category: str) -> bool:
    if decision_point in {"LOW_HP", *DEATH_REVIEW_DECISIONS}:
        return False
    return category in {
        "post_laning_farm_recovery",
        "post_laning_farm_stall",
        "post_laning_carry_tp",
        "post_laning_pressure_avoidance",
        "post_laning_safe_farm_route",
        "post_laning_objective_caution",
    }


def _active_advice_duration(decision_point: str, state: dict[str, Any]) -> timedelta:
    if decision_point in DEATH_REVIEW_DECISIONS or _is_dead_or_respawning(state):
        respawn_seconds = _ctx_int(state, "respawn_seconds", 0)
        return timedelta(seconds=max(15, respawn_seconds))
    if decision_point in {"LOW_HP", "DISABLED_STATUS"}:
        return timedelta(seconds=12)
    if decision_point in {
        "RECENT_DAMAGE_WARNING",
        "OVERSTAY_WARNING",
        "LOW_HP_WARNING",
        "ABILITY_SAFETY_COOLDOWN",
        "HERO_SURVIVABILITY_RISK",
    }:
        return timedelta(seconds=10)
    return timedelta(seconds=8)


ADVICE_SCHEDULER = AdviceScheduler()
