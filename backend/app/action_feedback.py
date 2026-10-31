"""
action_feedback.py - what the player has just done, as far as GSI shows.

A low-HP card that says «use Tango» four seconds after a Tango was eaten tells
the player nothing. This tracker reads two kinds of evidence between
consecutive snapshots of one life:

- a consumable used: its charges in the six active slots went down (or the item
  left them) while the hero was alive, the same item did not turn up in the
  backpack or stash (moved, not used), the gold did not jump (sold), and no
  data gap lies between the snapshots. Tango can also be shared with an ally
  (GSI cannot tell): either way the player acted, so it counts as done.
- an own cooldown started (status_source.started_cooldowns): an ability or item
  was pressed.

`regen_active` lists the healing items whose effect is still running, using the
effect duration below (a Healing Salve stops at the first hit, which GSI does
not report: it counts as running until HP falls again).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.status_source import observed_cooldowns, started_cooldowns

# Seconds of effect after use (patch 7.3x values; Tango 16 s, Salve 10 s,
# Clarity 25 s, a Bottle charge 2.7 s). Instant items have no window.
REGEN_SECONDS = {
    "item_tango": 16,
    "item_tango_single": 16,
    "item_flask": 10,
    "item_clarity": 25,
    "item_bottle": 3,
}
CONSUMABLES = {
    *REGEN_SECONDS,
    "item_faerie_fire",
    "item_enchanted_mango",
    "item_famango",
    "item_great_famango",
    "item_greater_famango",
    "item_magic_stick",
    "item_magic_wand",
    "item_cheese",
}
# Longer than this between two snapshots (game seconds) and a change may be a
# reconnect or a seek: nothing is inferred across it.
MAX_GAP = 3.0
# Uses older than this are forgotten.
KEEP_SECONDS = 30.0
# A TP scroll's channel, inferred: its cooldown started and the hero stands
# within TP_STILL_RADIUS of where it was. Measured in two recordings (4 TPs):
# the hero arrived 2.9-5.1 s (game time) after the cooldown started; past
# TP_CHANNEL_SECONDS the inference ends whatever happened (a cancelled TP with
# the hero still standing must not hold cards for long).
TP_CHANNEL_SECONDS = 6.0
TP_STILL_RADIUS = 150
# Gold rising this much in one tick next to a vanished item: a sale.
SALE_GOLD = 10


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def _charges(extra: Mapping[str, Any]) -> dict[str, float]:
    raw = extra.get("item_charges")
    if not isinstance(raw, Mapping):
        return {}
    return {
        name: value
        for name, value in ((n, _number(v)) for n, v in raw.items())
        if isinstance(name, str) and value is not None
    }


def _owned(extra: Mapping[str, Any]) -> dict[str, int]:
    names = extra.get("item_names")
    counts: dict[str, int] = {}
    if isinstance(names, list):
        for name in names:
            if isinstance(name, str):
                counts[name] = counts.get(name, 0) + 1
    return counts


def used_consumables(
    before: Mapping[str, Any], now: Mapping[str, Any], *, gap: float | None
) -> list[str]:
    """Consumables used between two snapshots of one life (see the module doc)."""
    if gap is None or gap < 0 or gap > MAX_GAP:
        return []
    if before.get("alive") is False or now.get("alive") is False:
        return []
    charges_before, charges_now = _charges(before), _charges(now)
    if not charges_before:
        return []
    owned_before, owned_now = _owned(before), _owned(now)
    gold_before = _number(before.get("available_gold"))
    gold_now = _number(now.get("available_gold"))
    sold = gold_before is not None and gold_now is not None and gold_now - gold_before >= SALE_GOLD
    used = []
    for name, count in charges_before.items():
        if name not in CONSUMABLES:
            continue
        left = charges_now.get(name)
        if left is not None and left < count:
            used.append(name)  # fewer charges, still in a slot: pressed
        elif left is None and owned_now.get(name, 0) >= owned_before.get(name, 0) > 0:
            continue  # moved to the backpack or stash
        elif left is None and not sold:
            used.append(name)  # the last charge went
    return used


class ActionWatch:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last: dict[str, Any] | None = None
        self._last_at: float | None = None
        self._cooldowns: dict[str, float] = {}
        self._uses: dict[str, float] = {}
        self._casts: dict[str, float] = {}
        self._tp_cooldown: float | None = None
        self._tp_cast: tuple[float, float, float] | None = None
        self._tp_seen_at: float | None = None
        # Why the last inferred TP channel ended (tests, audits).
        self.channel_end: str | None = None

    def _teleporting(self, extra: Mapping[str, Any], at: float | None) -> bool:
        """The TP channel inferred (see TP_CHANNEL_SECONDS). It ends, with
        `channel_end` saying why, when the hero moves or lands (arrived or
        walked off), a stun, hex or mute lands (they interrupt it), the TP
        leaves the slot, the hero dies, the data has a gap, or the window is
        over. A channel whose start was not seen (no ready → running) is not
        assumed."""
        cooldown = extra.get("tp_cooldown")
        cooldown = float(cooldown) if isinstance(cooldown, (int, float)) else None
        x, y = extra.get("xpos"), extra.get("ypos")
        last_at = self._tp_seen_at
        self._tp_seen_at = at
        if at is not None and last_at is not None and at - last_at > MAX_GAP:
            self._end_channel("data_gap")
        if (
            at is not None
            and cooldown is not None
            and cooldown > 0
            and self._tp_cooldown == 0
            and isinstance(x, (int, float))
            and isinstance(y, (int, float))
        ):
            self._tp_cast = (at, float(x), float(y))
            self.channel_end = None
        self._tp_cooldown = cooldown
        cast = self._tp_cast
        if cast is None or at is None:
            return False
        if extra.get("alive") is False:
            return self._end_channel("died")
        if any(extra.get(flag) is True for flag in ("stunned", "hexed", "muted")):
            return self._end_channel("interrupted")
        if cooldown is None:
            return self._end_channel("tp_gone")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return self._end_channel("position_unknown")
        if abs(x - cast[1]) + abs(y - cast[2]) > TP_STILL_RADIUS:
            return self._end_channel("moved")
        if at - cast[0] > TP_CHANNEL_SECONDS:
            return self._end_channel("window_over")
        return True

    def _end_channel(self, reason: str) -> bool:
        if self._tp_cast is not None:
            self.channel_end = reason
        self._tp_cast = None
        return False

    def observe(self, extra: Mapping[str, Any], at: float | None) -> dict[str, Any]:
        snapshot = {
            "alive": extra.get("alive"),
            "item_charges": extra.get("item_charges"),
            "item_names": extra.get("item_names"),
            "available_gold": extra.get("available_gold"),
        }
        cooldowns = observed_cooldowns(extra)
        if at is not None and self._last is not None and self._last_at is not None:
            gap = at - self._last_at
            for name in used_consumables(self._last, snapshot, gap=gap):
                self._uses[name] = at
            if 0 <= gap <= MAX_GAP:
                for key in started_cooldowns(self._cooldowns, cooldowns):
                    self._casts[key] = at
        if at is not None:
            self._uses = {n: t for n, t in self._uses.items() if at - t <= KEEP_SECONDS}
            self._casts = {k: t for k, t in self._casts.items() if at - t <= KEEP_SECONDS}
        if extra.get("alive") is False:
            self._uses = {}
        self._last, self._last_at, self._cooldowns = snapshot, at, cooldowns
        teleporting = self._teleporting(extra, at)
        return {
            "teleporting": teleporting,
            "recent_uses": {name: round(at - t, 1) for name, t in self._uses.items()}
            if at is not None
            else {},
            "recent_casts": {key: round(at - t, 1) for key, t in self._casts.items()}
            if at is not None
            else {},
            "regen_active": sorted(
                name
                for name, t in self._uses.items()
                if at is not None and at - t < REGEN_SECONDS.get(name, 0)
            ),
        }
