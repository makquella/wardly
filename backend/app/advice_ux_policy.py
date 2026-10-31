"""
advice_ux_policy.py - cognitive load guard for overlay advice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.advice_policy import build_advice_policy
from app.schemas import RecommendationResponse

MAX_ADVICE_PER_MINUTE = 2
MAX_ACTION_CHARS = 100
MAX_REASON_CHARS = 180
MAX_RISK_CHARS = 140
REGULAR_ADVICE_INTERVAL_SECONDS = 45
URGENT_ADVICE_INTERVAL_SECONDS = 15
DUPLICATE_SUPPRESSION_SECONDS = 30
# Urgent cards are never held back by the per-minute quota: a silence with
# Manta ready was dropped because two calm cards had been shown that minute.
# The same-action duplicate window below still applies to them.
RATE_LIMIT_BYPASS_DECISIONS = {
    "LOW_HP",
    "DISABLED_STATUS",
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
}

COACHING_PREFIXES = ("Consider", "It is safer to", "Prioritize", "Avoid")
AUTOPILOT_PREFIXES = ("go ", "buy ", "tp ", "teleport ", "move ")


def apply_ux_policy(
    recommendation: RecommendationResponse,
    decision_point: str,
    recent_advice_history: list[dict[str, Any]],
    now: datetime | None = None,
    action_type: str | None = None,
    moment: bool = False,
    overtaken: bool = False,
) -> dict[str, Any]:
    """`moment`: a card useful for seconds only (readiness right after a kill or
    a revive) passes the per-minute quota; the duplicate window still applies.
    `overtaken`: the last card of this kind was withdrawn because more can be
    done now (advice_validity `can_act_now`): the same action type may follow
    at once in its new form; the same text still may not."""
    if not action_type:
        action_type = str(build_advice_policy({}, decision_point)["action_type"])

    current_time = _now(now)
    recent_minute = [
        entry
        for entry in recent_advice_history
        if _parse_time(entry.get("timestamp")) >= current_time - timedelta(seconds=60)
    ]
    bypass_rate_limit = moment or decision_point in RATE_LIMIT_BYPASS_DECISIONS
    if not bypass_rate_limit and len(recent_minute) >= MAX_ADVICE_PER_MINUTE:
        return _suppressed("rate_limit")

    recent_duplicates = [
        entry
        for entry in recent_advice_history
        if _parse_time(entry.get("timestamp"))
        >= current_time - timedelta(seconds=DUPLICATE_SUPPRESSION_SECONDS)
    ]
    action = recommendation.action.strip()
    same_action = action.lower()
    for entry in reversed(recent_duplicates):
        if entry.get("action_type") == action_type and not overtaken:
            return _suppressed("duplicate")
        if str(entry.get("action", "")).strip().lower() == same_action:
            return _suppressed("duplicate")

    advice_mode = _advice_mode(decision_point)
    if advice_mode == "coaching":
        action = _coaching_action(action)

    reason = recommendation.reason.strip() or _default_reason(decision_point)
    risk = recommendation.risk.strip() or "Keep map risk low."

    adjusted = RecommendationResponse(
        action=_trim(action, MAX_ACTION_CHARS),
        reason=_trim(reason, MAX_REASON_CHARS),
        risk=_trim(risk, MAX_RISK_CHARS),
        priority=recommendation.priority,
        time_window=recommendation.time_window,
        source=recommendation.source,
        tool=recommendation.tool,
    )
    return {
        "recommendation": adjusted,
        "suppressed_reason": None,
        "advice_mode": advice_mode,
        "action_type": action_type,
    }


def _suppressed(reason: str) -> dict[str, Any]:
    return {
        "recommendation": None,
        "suppressed_reason": reason,
        "advice_mode": "status",
        "action_type": None,
    }


def _advice_mode(decision_point: str) -> str:
    if decision_point in {"LOW_HP", "DISABLED_STATUS"}:
        return "urgent"
    if decision_point in {"NO_ADVICE", "SOFT_STATUS", "DEAD_WAIT", "DEATH_REVIEW"}:
        return "status"
    return "coaching"


def _coaching_action(action: str) -> str:
    lowered = action.strip().lower()
    if lowered.startswith(tuple(prefix.lower() for prefix in COACHING_PREFIXES)):
        return action

    if lowered.startswith("move closer to a safer"):
        return action

    if lowered.startswith(AUTOPILOT_PREFIXES):
        return "Consider a safer, lower-risk play."

    if lowered.startswith("avoid"):
        return action
    if lowered.startswith("back"):
        return action
    if lowered.startswith("do not"):
        return action
    if lowered.startswith("retreat"):
        return action
    if lowered.startswith("reset"):
        return action
    if lowered.startswith("keep"):
        return action
    if lowered.startswith("focus"):
        return action
    if lowered.startswith("secure"):
        return action
    if lowered.startswith("take only"):
        return action
    if lowered.startswith("take safe"):
        return action
    if lowered.startswith("recover"):
        return action
    if lowered.startswith("buyback is available"):
        return action
    if lowered.startswith("only consider"):
        return action
    if lowered.startswith(("you reached", "your team is")):
        return action
    if lowered.startswith(("after respawn", "check", "conserve", "stay", "use", "wait", "respect")):
        return action
    # Getting out of a fight is never softened: «Consider: step out of enemy range
    # and use Bottle» read as if the coach was not sure.
    if lowered.startswith(("step out", "leave", "walk out", "back off")):
        return action
    if lowered.startswith("after this item pickup"):
        return action
    # Readiness after a kill or a revive and the TP delivery are conditions or
    # one concrete step already (live_tools.readiness_copy, post_laning TP).
    if lowered.startswith(("second life:", "after your kill:", "have the courier")):
        return action
    # "Consider: farm back your gold" (with a colon: the action stays an imperative;
    # "Consider farm back" is not English). Ukrainian: «Подумайте: …».
    if action:
        return f"Consider: {action[0].lower() + action[1:]}"
    return "Consider playing safely."


def _default_reason(decision_point: str) -> str:
    if decision_point == "LOW_HP":
        return "Low health makes extra action too risky."
    if decision_point == "NO_ADVICE":
        return "No urgent decision is needed."
    return "This reduces risk while keeping your carry game stable."


def _trim(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)
