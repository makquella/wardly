"""
tp_tracker.py - "no TP scroll" signal for live advice.

Carrying a Town Portal scroll is how a hero joins a fight or saves a tower
across the map. GSI shows the TP slot (items.teleport0) and the inventory
(Boots of Travel teleport too). From minute 10, when the hero has been alive
without a way to teleport for MISSING_SECONDS of game time, the signal is on
until a TP is back. Unknown items (no items block) never count as missing.
"""

from __future__ import annotations

from typing import Any

MIN_CLOCK_SECONDS = 10 * 60
MISSING_SECONDS = 60
# A reconnect or a replay seek that jumps the clock back restarts the count.
MAX_BACKWARD_SECONDS = 30

TP_ITEMS = {"item_tpscroll", "item_travel_boots", "item_travel_boots_2"}


def has_teleport(items: Any) -> bool | None:
    """True/False from a raw GSI items block ({"slot0": {"name": ...}, "teleport0": ...});
    None when the block is missing."""
    if not isinstance(items, dict) or not items:
        return None
    for slot, item in items.items():
        name = item.get("name") if isinstance(item, dict) else item
        if not str(slot).startswith(("slot", "teleport")):
            continue  # stash and neutral items do not teleport
        if str(name or "") in TP_ITEMS:
            return True
    return False


def teleport_cooldown(items: Any) -> int | None:
    """Seconds until the TP scroll (or Boots of Travel) can be used: 0 ready;
    None when there is none or the block says nothing."""
    if not isinstance(items, dict):
        return None
    for slot, item in items.items():
        if not isinstance(item, dict) or not str(slot).startswith(("slot", "teleport")):
            continue
        if str(item.get("name") or "") not in TP_ITEMS:
            continue
        cooldown = item.get("cooldown")
        if isinstance(cooldown, bool) or not isinstance(cooldown, (int, float)):
            return None
        return max(0, int(cooldown))
    return None


class TpTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._missing_since: int | None = None
        self._clock: int | None = None
        self._alive = True

    def observe(
        self, clock: int | None, has_tp: bool | None, alive: bool | None, paused: bool = False
    ) -> None:
        if clock is None or paused:
            return
        if self._clock is not None and clock < self._clock - MAX_BACKWARD_SECONDS:
            self._missing_since = None
        self._clock = int(clock)
        self._alive = alive is not False
        if not self._alive:
            # Only time alive counts: a respawn starts the count again.
            self._missing_since = None
            return
        if has_tp is None:
            return
        if has_tp:
            self._missing_since = None
        elif self._missing_since is None:
            self._missing_since = int(clock)

    def signal(self) -> dict[str, Any] | None:
        if self._missing_since is None or self._clock is None or not self._alive:
            return None
        if self._clock < MIN_CLOCK_SECONDS:
            return None
        missing = self._clock - self._missing_since
        if missing < MISSING_SECONDS:
            return None
        return {"seconds": int(missing), "minutes": max(1, int(missing) // 60)}
