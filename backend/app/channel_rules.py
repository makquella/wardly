"""
channel_rules.py - whether a card's action fits a channel the hero is (maybe)
in: a Town Portal Scroll, the only channel GSI lets the coach infer.

GSI has no channel flag. action_feedback infers a TP channel from its cooldown
starting while the hero stands still (`teleporting`); that stays an inference,
so every verdict here is about an assumed channel. Ability channels (Black
Hole, Freezing Field…) are not inferred at all: their cooldown starts at the
cast as any other spell's, nothing tells a channel from a cast.

What interrupts a channel, from Valve's item definitions
(data/live/channel_ignore_items.json): using an item interrupts it unless its
behaviour has IGNORE_CHANNEL; casting an ability interrupts it; moving
interrupts it. So, for the card's action (its tool, resolved against the tools
this snapshot reports, and the policy's action type for cards without one):

- compatible: an item that ignores channels, or a card that orders nothing to
  do right now (a constraint, a timing, a check);
- interrupts: any other item, any ability, any move order (leave, step back,
  farm elsewhere, group up);
- a card that orders a tool (an escape, a heal, a dispel) and would break
  the channel is still justified when the danger it answers is observed now:
  HP falling fast, or enemy heroes visible next to the hero with HP already
  lost. Then the card stands (it says what to do instead of waiting for the
  TP). A plain move order never is: walking away cancels the TP that is
  already taking the hero out. Otherwise the card waits until the channel is
  over (at most action_feedback.TP_CHANNEL_SECONDS).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR
from app.team_context import visible_enemies_near

# Policy action types (advice_policy.py) that order a move or a fight now.
MOVE_ACTIONS = frozenset(
    {
        "retreat_reset",
        "play_back_and_regen",
        "stop_overstay_low_hp",
        "stabilize_after_recent_damage",
        "reset_before_resources_collapse",
        "switch_to_safe_farm",
        "stabilize_lane_farm",
        "keep_farming",
        "avoid_bad_fight",
        "join_only_if_objective_value",
        "conserve_mana_or_reset",
    }
)
# HP (% of max) lost over the last 10 s that, with an enemy hero next to the
# hero, makes waiting for the TP the riskier choice.
DANGER_HP_LOST = 15


@lru_cache(maxsize=1)
def channel_safe_items() -> frozenset[str]:
    try:
        data = json.loads((DATA_DIR / "live" / "channel_ignore_items.json").read_text("utf-8"))
    except (OSError, ValueError):
        return frozenset()
    items = data.get("items") if isinstance(data, Mapping) else None
    return frozenset(str(name) for name in items) if isinstance(items, list) else frozenset()


def interrupts_channel(tool: Mapping[str, Any] | None, action_type: str | None) -> bool | None:
    """True when doing the card's action now would end a channel; False when
    it would not; None when the card orders nothing that touches it."""
    if isinstance(tool, Mapping) and tool.get("name"):
        if tool.get("kind") == "item":
            return str(tool["name"]) not in channel_safe_items()
        return True  # casting an ability interrupts a channel
    if action_type in MOVE_ACTIONS:
        return True
    return None


def danger_now(extra: Mapping[str, Any]) -> bool:
    """Danger observed on this snapshot that can justify breaking a channel."""
    falling = extra.get("hp_falling_fast")
    if isinstance(falling, (int, float)) and not isinstance(falling, bool) and falling > 0:
        return True
    lost = extra.get("hp_delta_10s")
    return (
        bool(visible_enemies_near(extra))
        and isinstance(lost, (int, float))
        and not isinstance(lost, bool)
        and lost <= -DANGER_HP_LOST
    )


def channel_verdict(
    extra: Mapping[str, Any], tool: Mapping[str, Any] | None, action_type: str | None
) -> str:
    """`none` (no channel assumed), `compatible`, `justified` (interrupts, and
    the danger is observed) or `hold` (interrupts the assumed channel for
    nothing seen)."""
    if extra.get("teleporting") is not True:
        return "none"
    interrupts = interrupts_channel(tool, action_type)
    if not interrupts:
        return "compatible"
    has_tool = isinstance(tool, Mapping) and bool(tool.get("name"))
    return "justified" if has_tool and danger_now(extra) else "hold"
