"""Publish a detached GSI packet/state pair; readers never wait for its builder."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

State = dict[str, Any]
Normalizer = Callable[[State, State | None], Mapping[str, Any]]

# Normalized keys used on their own payload only (minimap creeps for farm_map.py).
TRANSIENT_KEYS = frozenset({"lane_creeps", "neutral_units", "vision_sources"})


@dataclass(frozen=True)
class GSISnapshot:
    raw: State
    state: State
    timestamp: str
    previous_context: State


class GSIRegister:
    """Writer/reset ownership is separate from the short publication lock.

    Normalizer/enrich/reset callbacks must do only in-memory work. Perform
    cache warming, recording, history, debug and network I/O outside update.
    Published dictionaries stay private; capture returns a detached copy.
    """

    def __init__(self) -> None:
        self._writer = threading.RLock()
        self._publication = threading.Lock()
        self._snapshot: GSISnapshot | None = None

    def capture(self) -> GSISnapshot | None:
        with self._publication:
            current = self._snapshot
        # Nobody mutates this private value after publication. A slow consumer
        # or deepcopy cannot block the next replacement or leak writable aliases.
        return deepcopy(current)

    def update(
        self,
        payload: State,
        normalizer: Normalizer,
        *,
        enrich: Callable[[State], None] | None = None,
    ) -> GSISnapshot:
        raw = deepcopy(payload)
        with self._writer:
            previous = self.capture()
            # Adapt the typed normalized mapping to the mutable enrichment port.
            state = dict(normalizer(raw, previous.previous_context if previous else None))
            # The minimap creep lists are read once by the farm tip
            # (farm_map.py) and never kept as the previous context.
            context = deepcopy(
                {
                    key: value
                    for key, value in (state.get("extra_context") or {}).items()
                    if key not in TRANSIENT_KEYS
                }
            )
            if enrich is not None:
                enrich(state)
            new = GSISnapshot(raw, state, datetime.now(UTC).isoformat(), context)
            private = deepcopy(new)
            with self._publication:
                self._snapshot = private
        return new

    def reset(self, reset_context: Callable[[], None] | None = None) -> None:
        with self._writer:
            if reset_context is not None:
                reset_context()
            with self._publication:
                self._snapshot = None
