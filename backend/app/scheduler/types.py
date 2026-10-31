"""
scheduler.types - shared Literal type aliases and the ScheduledAdvice DTO.

Extracted verbatim from advice_scheduler.py as part of the Phase 2 split
(no behavior change). The Literal aliases describe scheduler inputs/outputs;
ScheduledAdvice is the dataclass returned by AdviceScheduler.evaluate.

ScheduledAdvice is re-exported from app.advice_scheduler (rule 3) because
app/main.py imports it from there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.schemas import RecommendationResponse

AdviceType = Literal[
    "LOW_HP",
    "LOW_HP_WARNING",
    "RECENT_DAMAGE_WARNING",
    "OVERSTAY_WARNING",
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
    "LOW_MANA",
    "DISABLED_STATUS",
    "BUYBACK_AVAILABLE",
    "DEAD_WAIT",
    "SMOKED_STATUS",
    "HERO_SURVIVABILITY_RISK",
    "HERO_GAMEPLAY",
    "LANING_REGEN_CHECK",
    "LANING_FARM_CHECK",
    "ABILITY_SAFETY_COOLDOWN",
    "SOFT_STATUS",
    "FARMING_PHASE_PRESSURE",
    "OBJECTIVE_FIGHT_CHECK",
    "BAD_FIGHT_RISK",
    "ITEM_TIMING",
    "SAFE_FARMING",
    "NO_ADVICE",
]

OverlayStatus = Literal["advice", "active_advice", "no_advice", "cooldown"]
OverlaySource = Literal["llm", "fallback", "none"]


@dataclass
class ScheduledAdvice:
    status: OverlayStatus
    decision_point: str
    recommendation: RecommendationResponse | None
    advice_count: int
    llm_used: bool
    source: OverlaySource
    last_updated: str | None
    next_allowed_advice_in_seconds: int
    new_advice: bool = False
    advice_mode: str = "status"
    suppressed_reason: str | None = None
    active_advice_until: str | None = None
    last_visible_advice: dict[str, Any] | None = None
    is_pinned: bool = False
    low_hp_episode_id: int | None = None
    game_time_gap_since_previous_advice: float | None = None
    suppressed_by_game_time_spacing: bool = False
    hero_gameplay: dict[str, Any] | None = None
    # The basis of the card (advice_validity.py): its snapshot clock, the tool
    # it names and the numbers it cites.
    basis: dict[str, Any] | None = None
    # The card just withdrawn because the game moved on ({decision_point,
    # action, reason}): the overlay drops it and stops speaking it.
    withdrawn_advice: dict[str, Any] | None = None
