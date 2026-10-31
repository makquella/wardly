"""
replay_outcomes.py - what the recorded match did after a card the current code
would show: an OFFLINE analysis, run after the replay, that reads the future of
the recording. Nothing here feeds the live decisions.

An offline replay cannot show the player's reaction to a card: the player of
the recorded match never saw the new cards. So the words are «the historical
use happened N s after», «the card came before the recorded use», «the action
was already done»; never «the player followed the card».

Time points, kept apart (wall time `w` of the recording, seconds):

- decision: the snapshot the card stands on (advice_basis observed_at);
- formed / shown: the replay's poll that returned the card as new. The
  backend may form the card at GSI ingestion or at the poll; offline only the
  poll is seen, so `formed` is known to lie in [decision, shown];
- voice: not observable offline (the overlay speaks); always None;
- historical use: the named tool's use found in the recording, bounded by the
  last snapshot where it was still unused and the first where it was used
  (cooldown 0 → running for an item or ability; a charge less for a
  consumable). GSI samples about every 0.5 s: the use lies in that interval,
  and the delay is reported as that interval, never rounded to a point.

The use counts for the card only inside the card's episode: until the status
(stun, silence…) the card was about ends plus EPISODE_GRACE, or EPISODE_MAX
after the decision for a card with no status; a later use of the same tool
belongs to another moment and is not the card's. A use before the card was
shown is «already done» (a negative delay, reported as it is). A use in the
same snapshot as the status ending has an unknown order relative to it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

BLOCKING = ("stunned", "hexed", "silenced", "muted")
EPISODE_GRACE = 5.0
EPISODE_MAX = 15.0


def snapshot_row(w: float, extra: Mapping[str, Any], hero: Any) -> dict[str, Any]:
    """The facts of one normalized snapshot the analysis needs."""
    from app.live_tools import hero_tools

    abilities = extra.get("abilities")
    tools = hero_tools(hero, abilities if isinstance(abilities, list) else None)
    ready = {name for name, _ in tools["ready"]}
    abilities_cd = {name: 0.0 for name in ready}
    abilities_cd.update({name: float(left) for name, left in tools["cooldowns"].items()})
    item_cd = extra.get("item_cooldowns")
    charges = extra.get("item_charges")
    return {
        "w": float(w),
        "clock": extra.get("clock_time"),
        "flags": [flag for flag in BLOCKING if extra.get(flag) is True],
        "alive": extra.get("alive") is not False,
        "item_cd": dict(item_cd) if isinstance(item_cd, Mapping) else {},
        "item_charges": dict(charges) if isinstance(charges, Mapping) else {},
        "ability_cd": abilities_cd,
    }


def _state(row: Mapping[str, Any], tool: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """(cooldown, charges) of the tool in a row; None where the row has none."""
    name = tool.get("name")
    if tool.get("kind") == "ability":
        return row["ability_cd"].get(name), None
    cooldown = row["item_cd"].get(name)
    charges = row["item_charges"].get(name)
    return (
        float(cooldown) if isinstance(cooldown, (int, float)) else None,
        float(charges) if isinstance(charges, (int, float)) else None,
    )


def _used(before: Mapping[str, Any], after: Mapping[str, Any], tool: Mapping[str, Any]) -> bool:
    cd0, ch0 = _state(before, tool)
    cd1, ch1 = _state(after, tool)
    if cd0 is not None and cd1 is not None and cd0 == 0 and cd1 > 0:
        return True
    return ch0 is not None and ch1 is not None and ch1 < ch0


def historical_use(
    rows: list[dict[str, Any]],
    *,
    tool: Mapping[str, Any] | None,
    decision_w: float | None,
    shown_w: float,
    status_flags: Iterable[str] = (),
) -> dict[str, Any]:
    """The recorded use of the card's tool within its episode (module doc)."""
    result: dict[str, Any] = {
        "decision_w": decision_w,
        "formed_between": [decision_w, shown_w],
        "shown_w": shown_w,
        "voice_w": None,  # not observable offline
        "tool": dict(tool) if tool else None,
    }
    if not tool or not tool.get("name"):
        return {**result, "outcome": "no_tool"}
    if decision_w is None:
        return {**result, "outcome": "decision_unknown"}
    at = next((i for i, r in enumerate(rows) if r["w"] >= decision_w - 1e-6), None)
    if at is None:
        return {**result, "outcome": "decision_unknown"}
    flags = set(status_flags)
    # The episode: the status the card is about (any of its flags) and the
    # grace after its end; without a status, EPISODE_MAX from the decision.
    end_w: float | None = None
    status_end_w: float | None = None
    if flags:
        for row in rows[at:]:
            if not flags & set(row["flags"]):
                status_end_w = row["w"]
                break
        end_w = (status_end_w if status_end_w is not None else rows[-1]["w"]) + EPISODE_GRACE
    else:
        end_w = decision_w + EPISODE_MAX
    # Already used at or before the decision? (A card names a ready tool, so
    # this should not happen; a use between decision and show does.)
    for i in range(at + 1, len(rows)):
        before, after = rows[i - 1], rows[i]
        if after["w"] > end_w:
            break
        if not after["alive"]:
            return {**result, "outcome": "died_before_use", "died_w": after["w"]}
        if not _used(before, after, tool):
            continue
        low, high = before["w"], after["w"]
        out = {
            **result,
            "used_between": [low, high],
            "delay_from_decision": [round(low - decision_w, 2), round(high - decision_w, 2)],
            "delay_from_shown": [round(low - shown_w, 2), round(high - shown_w, 2)],
            "status_end_w": status_end_w,
        }
        if high <= shown_w:
            out["outcome"] = "already_done"
        elif low < shown_w:
            out["outcome"] = "around_show"  # in the interval that holds the show
        else:
            out["outcome"] = "after_show"
        if status_end_w is not None and abs(status_end_w - high) < 1e-6:
            out["order_with_status_end"] = "same_snapshot_unknown"
        return out
    return {**result, "outcome": "not_used_in_episode", "episode_end_w": end_w}


def describe(outcome: Mapping[str, Any]) -> str:
    """One line for the report, in the words the module doc allows."""
    kind = outcome.get("outcome")
    if kind in {"after_show", "around_show"}:
        low, high = outcome["delay_from_shown"]
        text = f"the historical use happened {low:+.2f}..{high:+.2f} s after the card was shown"
        if kind == "around_show":
            text += " (the sampling interval holds the show: order unknown)"
        if outcome.get("order_with_status_end"):
            text += "; in the same snapshot the status ended (order unknown)"
        return text
    if kind == "already_done":
        low, high = outcome["delay_from_shown"]
        return f"the action was already done ({low:+.2f}..{high:+.2f} s, before the card)"
    if kind == "not_used_in_episode":
        return "no recorded use within the card's episode"
    if kind == "died_before_use":
        return "the hero died before any recorded use"
    return str(kind)
