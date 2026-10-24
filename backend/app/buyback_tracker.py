"""
buyback_tracker.py - "you just spent your buyback gold" signal for live advice.

From minute 30 a carry should keep enough gold to buy back: one death without
it can decide the game. Earlier, from minute 20, when the game is already on
the line (`danger`, match_memory.base_danger): the enemy holds the Aegis, or
the player's own tier-3 towers or barracks are falling. GSI gives the gold, the buyback cost and its cooldown.
When a purchase takes the gold from at least the buyback cost to below it
while buyback is ready and the hero is alive, the signal holds for
HOLD_SECONDS of game time (or until the gold is back) so the advice pipeline
can show it once. Deaths (gold lost while dead) never count.

The signal names when the purchase happened, but its `gold` and `cost` are the
latest snapshot's: the card can come many seconds after the purchase (spacing,
a fight in between) and must not quote the gold of that moment (a card at 32:28
said 1338 of 1824, the pair seen 41 s before, with 566 of 1905 by then). Another
purchase under the cost starts the hold again.
"""

from __future__ import annotations

from typing import Any

MIN_CLOCK_SECONDS = 30 * 60
# With the game on the line (the enemy's Aegis, an own tier 3 or barracks lost).
DANGER_MIN_CLOCK_SECONDS = 20 * 60
# A drop smaller than this is not a purchase worth a warning.
MIN_SPEND = 400
HOLD_SECONDS = 60


class BuybackTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last: tuple[int, int, int | None, bool] | None = None
        self._signal: dict[str, Any] | None = None

    def observe(
        self,
        clock: int | None,
        gold: int | None,
        cost: int | None,
        cooldown: int | None,
        alive: bool | None,
        danger: str | None = None,
    ) -> None:
        if clock is None or gold is None:
            return
        signal = self._signal
        if signal and (clock - signal["clock"] > HOLD_SECONDS or (cost and gold >= cost)):
            self._signal = None
        elif signal:
            signal["gold"], signal["observed"] = int(gold), int(clock)
            if cost:
                signal["cost"] = int(cost)
        last = self._last
        self._last = (int(clock), int(gold), cost, alive is not False)
        start = DANGER_MIN_CLOCK_SECONDS if danger else MIN_CLOCK_SECONDS
        if last is None or clock < start or alive is False or not last[3]:
            return
        if not cost or cooldown not in (0, None) or clock < last[0]:
            return
        last_cost = last[2] or cost
        spent = last[1] - gold >= MIN_SPEND
        if self._signal and gold < cost and spent:
            # Another purchase while still under the cost: a new decision.
            self._signal.update({"clock": int(clock), "gold": int(gold), "cost": int(cost)})
        elif last[1] >= last_cost and gold < cost and spent:
            self._signal = {
                "clock": int(clock),
                "gold": int(gold),
                "cost": int(cost),
                "observed": int(clock),
            }
            if danger:
                self._signal["danger"] = danger

    def signal(self) -> dict[str, Any] | None:
        return dict(self._signal) if self._signal else None
