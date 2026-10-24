"""
advice_validity.py - does a card that is still on screen still hold?

A card is built from one snapshot and then held (and spoken on a later poll)
for up to its active window. The game moves on meanwhile: the named item gets
used, a stun lands, the hero dies or respawns, the gold changes. The basis
records what the card depends on when it is made; `withdraw_reason` checks it
against each new snapshot and names why the card no longer holds (None while it
does). The scheduler then drops the card, so the overlay neither shows nor
speaks it; a fresh decision comes from the fresh snapshot, never by patching
one number of the old text.

Rules (each from what the card itself claims):
- the life changed: a card of a living hero after a death, a death card after
  the respawn (a revive withdraws both);
- a named tool: used since (cooldown started, charges down, gone) or, for a
  «now» command, the hero now stunned/hexed (items and spells) or muted (items);
- cited numbers: buyback gold/cost or Magic Wand charges that no longer match;
- a low-HP card once HP is back well above the line it was made at;
- a disable card once the status is classified as the player's own phase (not
  when the disable ends: «the moment it ends, use X» is for exactly then);
- a calm card (farm, TP, smoke, items) once an enemy disable or a fast HP fall
  is seen: it must not stay on screen through a fight it says nothing about.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.last_moments import is_saver, saver_label
from app.live_tools import REGEN_INSTANT, REGEN_OVER_TIME, hero_tools

# HP back this many points above the card's HP (and above HP_RECOVERED_FLOOR):
# the low-HP card has done its job.
HP_RECOVERED_POINTS = 25
HP_RECOVERED_FLOOR = 60
# Cited gold that moved this much (at least GOLD_DRIFT, else this share of
# the cost: farming a few creeps is no new situation, a purchase is), or a cost
# by COST_DRIFT, is a stale number.
GOLD_DRIFT = 150
GOLD_DRIFT_SHARE = 0.25
COST_DRIFT = 50
LOW_HP_DECISIONS = {"LOW_HP", "LOW_HP_WARNING", "RECENT_DAMAGE_WARNING", "OVERSTAY_WARNING"}
# Cards about a threat in progress; every other held card gives way to one.
URGENT_DECISIONS = {
    "LOW_HP",
    "LOW_HP_WARNING",
    "RECENT_DAMAGE_WARNING",
    "OVERSTAY_WARNING",
    "DISABLED_STATUS",
    "HERO_SURVIVABILITY_RISK",
    "ABILITY_SAFETY_COOLDOWN",
    "BAD_FIGHT_RISK",
}
DEATH_DECISIONS = {
    "DEATH_REVIEW",
    "REPEATED_DEATH_PATTERN",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN",
    "DEATH_LOW_RESOURCE",
    "DEAD_WAIT",
    "BUYBACK_AVAILABLE",
}


def _extra(state: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = state.get("extra_context")
    return extra if isinstance(extra, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _label(name: str) -> str:
    if is_saver(name):
        return saver_label(name, "en")
    return REGEN_INSTANT.get(name) or REGEN_OVER_TIME.get(name) or name


def named_tool(action: str, state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The item or own ability a card's action tells the player to use, from
    the tools this snapshot reports (so a label maps back to one GSI name).
    With two named («Doppelganger…, then Magic Wand») the first is the card's."""
    extra = _extra(state)
    lowered = action.lower()
    mode = "after_disable" if lowered.startswith("the moment the disable ends") else "now"
    found: list[tuple[int, dict[str, Any]]] = []
    candidates: list[str] = []
    for key in ("ready_savers", "regen_items"):
        values = extra.get(key)
        if isinstance(values, list):
            candidates.extend(v for v in values if isinstance(v, str))
    for name in candidates:
        at = lowered.find(_label(name).lower())
        if at >= 0:
            charges = extra.get("item_charges")
            count = charges.get(name) if isinstance(charges, Mapping) else None
            found.append(
                (at, {"kind": "item", "name": name, "mode": mode, "charges": _number(count)})
            )
    tools = hero_tools(state.get("hero"), extra.get("abilities"))
    for name, _ in tools["ready"]:
        at = lowered.find(name.lower())
        if at >= 0:
            found.append((at, {"kind": "ability", "name": name, "mode": mode}))
    return min(found, key=lambda pair: pair[0])[1] if found else None


def advice_basis(
    decision_point: str, action: str, reason: str, state: Mapping[str, Any]
) -> dict[str, Any]:
    """What a new card depends on, captured from the snapshot it was made from."""
    extra = _extra(state)
    basis: dict[str, Any] = {
        "decision_point": decision_point,
        "clock": extra.get("clock_time"),
        "game_time": extra.get("game_time"),
        "observed_at": extra.get("observed_at_epoch"),
        "alive": extra.get("alive") is not False,
        "hp_percent": _number(state.get("hp_percent")),
        "tool": named_tool(action, state),
    }
    text = f"{action} {reason}"
    if "buyback costs" in text:
        basis["facts"] = {
            "gold": _number(extra.get("available_gold")),
            "buyback_cost": _number(extra.get("buyback_cost")),
        }
    if "Magic Wand has" in text:
        basis["wand_charges"] = _number(extra.get("wand_charges"))
    return basis


def _tool_used(tool: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    extra = _extra(state)
    name = tool.get("name")
    if tool.get("kind") == "item" and isinstance(name, str):
        cooldowns = extra.get("item_cooldowns")
        charges = extra.get("item_charges")
        cooldown = cooldowns.get(name) if isinstance(cooldowns, Mapping) else None
        if (_number(cooldown) or 0) > 0:
            return True
        uses = extra.get("recent_uses")
        if isinstance(uses, Mapping) and name in uses:
            return True
        before = _number(tool.get("charges"))
        now = charges.get(name) if isinstance(charges, Mapping) else None
        if before is not None and (_number(now) is None or (_number(now) or 0) < before):
            return True
        names = extra.get("item_names")
        return isinstance(names, list) and name not in names
    if tool.get("kind") == "ability" and isinstance(name, str):
        cooldowns = hero_tools(state.get("hero"), extra.get("abilities"))["cooldowns"]
        return name in cooldowns
    return False


def _cannot_press_now(tool: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
    if tool.get("mode") != "now":
        return False
    extra = _extra(state)
    if extra.get("stunned") is True or extra.get("hexed") is True:
        return True
    if tool.get("kind") == "item":
        return extra.get("muted") is True
    return extra.get("silenced") is True


BUYBACK_FACT = re.compile(r"You have \d+ gold and buyback costs \d+")
WAND_FACT = re.compile(r"Magic Wand has \d+ charges")


def refreshed_reason(
    basis: Mapping[str, Any] | None, reason: str, state: Mapping[str, Any]
) -> str | None:
    """The held card's reason with the exact numbers of this snapshot, or None
    when it already quotes them. The decision tolerance (GOLD_DRIFT, a rise in
    Wand charges) decides whether the card still holds; it never lets the card
    show a number that is no longer true."""
    if not isinstance(basis, Mapping) or not reason:
        return None
    extra = _extra(state)
    text = reason
    if isinstance(basis.get("facts"), Mapping):
        gold, cost = _number(extra.get("available_gold")), _number(extra.get("buyback_cost"))
        if gold is not None and cost is not None:
            text = BUYBACK_FACT.sub(
                f"You have {int(gold)} gold and buyback costs {int(cost)}", text, count=1
            )
    if "wand_charges" in basis:
        charges = _number(extra.get("wand_charges"))
        if charges is not None:
            text = WAND_FACT.sub(f"Magic Wand has {int(charges)} charges", text, count=1)
    return text if text != reason else None


def withdraw_reason(basis: Mapping[str, Any] | None, state: Mapping[str, Any]) -> str | None:
    """Why the held card no longer holds for this snapshot; None while it does."""
    if not isinstance(basis, Mapping):
        return None
    extra = _extra(state)
    decision_point = str(basis.get("decision_point") or "")
    alive_now = extra.get("alive") is not False
    if basis.get("alive") and not alive_now:
        return "life_lost"
    if not basis.get("alive") and alive_now:
        return "respawned"
    if decision_point in DEATH_DECISIONS:
        return None
    tool = basis.get("tool")
    if isinstance(tool, Mapping):
        if _tool_used(tool, state):
            return "action_done"
        if _cannot_press_now(tool, state):
            return "cannot_act_now"
    facts = basis.get("facts")
    if isinstance(facts, Mapping):
        gold, cost = _number(extra.get("available_gold")), _number(extra.get("buyback_cost"))
        old_gold, old_cost = _number(facts.get("gold")), _number(facts.get("buyback_cost"))
        if gold is not None and cost is not None and gold >= cost:
            return "resolved"
        drift = max(GOLD_DRIFT, GOLD_DRIFT_SHARE * (cost or old_cost or 0))
        if (
            gold is not None
            and old_gold is not None
            and abs(gold - old_gold) >= drift
            or cost is not None
            and old_cost is not None
            and abs(cost - old_cost) >= COST_DRIFT
        ):
            return "stale_numbers"
    if "wand_charges" in basis:
        before, now = _number(basis.get("wand_charges")), _number(extra.get("wand_charges"))
        if before is not None and (now is None or now < before):
            # Charges spent: the Wand was pressed. More charges change only the
            # number the card quotes (refreshed_reason), not the decision.
            return "action_done"
    if decision_point in LOW_HP_DECISIONS:
        hp_then, hp_now = _number(basis.get("hp_percent")), _number(state.get("hp_percent"))
        if (
            hp_then is not None
            and hp_now is not None
            and hp_now >= max(HP_RECOVERED_FLOOR, hp_then + HP_RECOVERED_POINTS)
        ):
            return "recovered"
    source = extra.get("status_source")
    kind = source.get("kind") if isinstance(source, Mapping) else None
    if decision_point == "DISABLED_STATUS" and kind in {"own_phase", "unexplained"}:
        return "not_a_threat"
    if decision_point not in URGENT_DECISIONS and (
        kind == "enemy" or (_number(extra.get("hp_falling_fast")) or 0) > 0
    ):
        return "superseded_by_threat"
    return None


# Generic farm lines with no decision in them: a card of these says nothing the
# player does not know («keep farming safely»), so it is not shown.
FILLER_ACTIONS = frozenset(
    {
        "Keep farming safely and reassess in 60 seconds.",
        "Keep farming the safest wave-and-camp route and reassess soon.",
        "No urgent action.",
    }
)
FILLER_DECISIONS = frozenset({"SAFE_FARMING"})


def is_filler(recommendation: Any, decision_point: str) -> bool:
    action = getattr(recommendation, "action", None)
    return (
        decision_point in FILLER_DECISIONS
        and isinstance(action, str)
        and action.strip() in FILLER_ACTIONS
    )
