"""
status_source.py - who put the hero in a blocking status, as far as GSI shows.

GSI sets `hero.stunned` (and hexed/silenced/muted) for the player's own hidden or
invulnerable phases too: Manta Style's split, Phantom Lancer's Doppelganger,
Omnislash and others hide the hero for a moment with the same flag an enemy stun
sets. GSI names no modifier and no caster, so the source is inferred from what
it does show, and the result says how sure it is:

- own_phase: an own hiding ability or item (OWN_PHASES: only mechanics whose
  `stunned` flag was seen in recordings) went on cooldown at the onset, and no
  HP is being lost. It holds only for that mechanic's own duration plus the
  sampling tolerance; a status that outlasts it is judged again without the
  cast. Any other own cast next to a stun (Spirit Lance, a Wand, Blade Fury…)
  proves nothing about the stun's source.
- enemy: HP is being lost during the status, or a debuff appeared at or after
  its onset (a debuff already there before it, from a slow, proves nothing).
  Once seen in an episode it stays: a real stun right after an own phase is
  not hidden by it.
- unexplained: `has_debuff` is reported false and no HP is lost, with no own
  cast seen (an ally's save, a shrine, an unknown own effect): no imperative to
  spend a defensive item.
- unknown: the payload has no `has_debuff` field and nothing else explains the
  status; the callers keep the legacy treatment (a possible enemy disable).

The tracker keeps only the last snapshot and the casts of the last seconds; it
never reads the future. Durations are measured on the observation clock in
seconds (match_memory passes the snapshot's wall time; game time only ticks
whole seconds, too coarse for a one-second phase).

Measured in three recordings (wall time from the onset snapshot to the first
clear one, payloads about 0.5 s apart): Doppelganger 23 times 0.5-1.4 s with no
HP lost; Manta 15 times up to 0.8 s, and twice longer with an enemy stun on top
(476 and 766 HP lost); Metamorphosis 3 times up to 0.6 s. Omnislash never set
`stunned` in the Juggernaut recording, so it is not listed.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

BLOCKING_FLAGS = ("stunned", "hexed", "silenced", "muted")
# Own mechanics that hide the hero and show as `stunned`, with the game's own
# duration of that phase in seconds (patch 7.3x): Doppelganger's 1 s delay,
# Manta's 0.1 s split, Metamorphosis' 0.35 s transformation.
OWN_PHASES = {
    "phantom_lancer_doppelwalk": 1.0,
    "item_manta": 0.1,
    "terrorblade_metamorphosis": 0.35,
}
# Payloads come about every 0.5 s and a cooldown can show a tick late: the
# phase is allowed this much longer than its duration before it is re-judged.
SAMPLING_TOLERANCE = 0.6
# The own cooldown must start this close to the onset (before / after it).
OWN_CAST_BEFORE = 1.0
OWN_CAST_AFTER = 0.6
# The flags an own hidden/invulnerable phase shows: GSI reports Manta's split,
# Doppelganger and Omnislash as `stunned`. A hex, silence or mute is never one.
OWN_PHASE_FLAGS = frozenset({"stunned"})
# HP loss (of max HP) during a status that counts as enemy damage; small
# regen/rounding noise and a max-HP change alone do not.
DAMAGE_MIN_FRACTION = 0.03
DAMAGE_MIN_POINTS = 30


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def observed_cooldowns(extra: Mapping[str, Any]) -> dict[str, float]:
    """Cooldowns of the player's own learned abilities and active-slot items
    ({"ability:<raw_name>" | "item:<name>": seconds}) as GSI reports them."""
    result: dict[str, float] = {}
    abilities = extra.get("abilities")
    if isinstance(abilities, list):
        for ability in abilities:
            if not isinstance(ability, Mapping):
                continue
            raw = ability.get("raw_name")
            cooldown = _number(ability.get("cooldown"))
            if (
                isinstance(raw, str)
                and cooldown is not None
                and (_number(ability.get("level")) or 0) > 0
            ):
                result[f"ability:{raw}"] = cooldown
    items = extra.get("item_cooldowns")
    if isinstance(items, Mapping):
        for name, cooldown in items.items():
            number = _number(cooldown)
            if isinstance(name, str) and number is not None:
                result[f"item:{name}"] = number
    return result


def started_cooldowns(before: Mapping[str, float], now: Mapping[str, float]) -> list[str]:
    """Keys whose cooldown went from ready (0) to running between two snapshots:
    the player pressed it. A key absent before (new item, level-up) is not a cast."""
    return [key for key, value in now.items() if value > 0 and before.get(key) == 0]


def _health(extra: Mapping[str, Any]) -> tuple[float | None, float | None]:
    return _number(extra.get("health")), _number(extra.get("max_health"))


def hp_lost(
    start: tuple[float | None, float | None], now: tuple[float | None, float | None]
) -> float | None:
    """HP points lost since `start`, measured as the fraction of max HP times the
    current max (a max-HP change from Treads, Armlet or illusions moves the raw
    number without any damage). None when health is unknown."""
    (hp0, max0), (hp1, max1) = start, now
    if hp0 is None or hp1 is None or not max0 or not max1:
        return None
    return (hp0 / max0 - hp1 / max1) * max1


def _damaging(lost: float | None, max_health: float | None) -> bool:
    if lost is None or not max_health:
        return False
    return lost >= max(DAMAGE_MIN_POINTS, DAMAGE_MIN_FRACTION * max_health)


class StatusWatch:
    """Classifies the blocking status of each snapshot (see the module doc)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._cooldowns: dict[str, float] = {}
        self._casts: deque[tuple[float, str]] = deque(maxlen=16)
        self._debuff_before: bool | None = None
        self._health_before: tuple[float | None, float | None] | None = None
        self._episode: dict[str, Any] | None = None

    def observe(self, extra: Mapping[str, Any], at: float | None) -> dict[str, Any]:
        cooldowns = observed_cooldowns(extra)
        if at is not None:
            for key in started_cooldowns(self._cooldowns, cooldowns):
                self._casts.append((at, key))
        self._cooldowns = cooldowns
        flags = [flag for flag in BLOCKING_FLAGS if extra.get(flag) is True]
        raw_debuff = extra.get("has_debuff")
        debuff = raw_debuff if isinstance(raw_debuff, bool) else None
        health = _health(extra)
        if not flags or extra.get("alive") is False:
            self._episode = None
            self._debuff_before = debuff
            self._health_before = health if extra.get("alive") is not False else None
            return {"kind": "none"}
        episode = self._episode
        if episode is None:
            # HP from the last snapshot before the status: the damage that
            # landed with it (a stun and a nuke together) belongs to it.
            before = self._health_before
            episode = self._episode = {
                "since": at,
                "flags": flags,
                "health": before if before is not None and before[0] is not None else health,
                "debuff_before": self._debuff_before,
                "enemy": False,
            }
        episode["flags"] = flags
        since = episode["since"]
        elapsed = at - since if at is not None and since is not None else None
        own_cast = None
        if since is not None and set(flags) <= OWN_PHASE_FLAGS:
            for t, key in reversed(self._casts):
                duration = OWN_PHASES.get(key.split(":", 1)[1])
                if duration is None or not since - OWN_CAST_BEFORE <= t <= since + OWN_CAST_AFTER:
                    continue
                # Only while that phase can still last: then judged again.
                if elapsed is None or elapsed <= duration + SAMPLING_TOLERANCE:
                    own_cast = key
                    break
        lost = hp_lost(episode["health"], health)
        evidence: list[str] = []
        if _damaging(lost, health[1]):
            episode["enemy"] = True
            evidence.append("hp_lost")
        if debuff is True and episode["debuff_before"] is False:
            episode["enemy"] = True
            evidence.append("debuff_appeared")
        if own_cast:
            evidence.append(f"own_cooldown_started:{own_cast}")
        if debuff is not None:
            evidence.append("debuff" if debuff else "no_debuff")
        if lost is not None and not _damaging(lost, health[1]):
            evidence.append("no_hp_loss")
        if episode["enemy"]:
            kind, confidence = "enemy", ("high" if debuff else "medium")
        elif own_cast:
            kind, confidence = "own_phase", ("high" if debuff is False else "medium")
        elif debuff is False and lost is not None:
            kind, confidence = "unexplained", "low"
        elif debuff is True:
            # A debuff with no onset to compare (first snapshot) and no own cast:
            # the usual enemy disable.
            kind, confidence = "enemy", "medium"
        else:
            kind, confidence = "unknown", "low"
        result: dict[str, Any] = {
            "kind": kind,
            "confidence": confidence,
            "flags": flags,
            "since": since,
            "evidence": evidence,
        }
        if own_cast:
            result["own_cast"] = own_cast.split(":", 1)[1]
        if lost is not None and health[1]:
            # Share of max HP lost since the onset (how much the status costs).
            result["hp_lost_share"] = round(max(0.0, lost) / health[1], 3)
        return result


def is_threat(status: Any) -> bool:
    """Whether a status classification is (or may be) an enemy disable: the
    legacy treatment for `unknown`, never for an own phase or an unexplained one."""
    if not isinstance(status, Mapping):
        return True
    return status.get("kind") not in {"own_phase", "unexplained", "none"}
