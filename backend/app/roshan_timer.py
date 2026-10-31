"""
roshan_timer.py - Roshan's respawn window and the Aegis on the map line.

Dota tells every player when Roshan is killed and when the Aegis is picked up
(the announcer lines); GSI carries them in its `events` block as
`roshan_killed` / `aegis_picked_up` with their game time. From a kill the
respawn window is known (data/meta/map_timers.json `roshan`: 8 to 11 minutes
in patch 7.41), and while the player's own hero holds the Aegis (the hero's
`aegis` flag or `item_aegis`) it expires AEGIS seconds after the pickup.

Hints, in the shape of map_hints timers (kind "timer", never minor):
- «Рошан може з'явитися» from `lead_seconds` before the window opens;
- «Рошан точно живий» when the window closes;
- «Аегіс згорить через 60 с» a minute before the player's Aegis expires;
- «Аегіс у ворогів до 30:03» when an enemy picks it up (the pickup event names
  the player: ids 0-4 are Radiant, 5-9 Dire; without the id the holder stays
  unknown, since a snatch puts it with the other team), and a minute before it
  can expire. An Aegis spent on a death earlier
  is not seen, so the time is the latest it can last.
Nothing is guessed: without a kill event there is no Roshan hint.
"""

from __future__ import annotations

from typing import Any

from app.map_hints import clock_label, strip_item, timers

TEXT = {
    "window": {
        "uk": ("Рошан може з'явитися", "Вікно появи відкривається о {at}, до {until}."),
        "en": ("Roshan can respawn", "The respawn window opens at {at}, until {until}."),
    },
    "alive": {
        "uk": ("Рошан точно живий", "Вікно появи закрилося: Рошан уже в лігві."),
        "en": ("Roshan is up for sure", "The respawn window has closed: Roshan is in the pit."),
    },
    "enemy_aegis": {
        "uk": (
            "Аегіс у ворогів до {until}",
            "Не починайте бійку проти Аегіса: захищайтеся здалеку й тримайте золото на байбек.",
        ),
        "en": (
            "Enemy Aegis until {until}",
            "Do not start a fight against the Aegis: defend from range and keep your buyback gold.",
        ),
    },
    "enemy_aegis_ends": {
        "uk": (
            "Аегіс ворогів згорить через {left} с",
            "Без нього їхній герой помирає по-справжньому: після цього бійка знову рівна.",
        ),
        "en": (
            "Enemy Aegis expires in {left} s",
            "Without it their hero dies for real: after that the fight is even again.",
        ),
    },
    "aegis": {
        "uk": (
            "Аегіс згорить через {left} с",
            "Грайте активніше, поки він у вас: почніть бійку або знесіть вежу.",
        ),
        "en": (
            "Aegis expires in {left} s",
            "Make it count while you hold it: take a fight or a tower.",
        ),
    },
}


def _settings() -> dict[str, int]:
    data = timers()
    roshan = data.get("roshan") or {}
    return {
        "lead": int(data.get("lead_seconds", 20)),
        "grace": int(data.get("grace_seconds", 5)),
        "min": int(roshan.get("respawn_min", 480)),
        "max": int(roshan.get("respawn_max", 660)),
        "aegis": int(roshan.get("aegis_seconds", 300)),
        "warn": int(roshan.get("aegis_warn", 60)),
    }


# The enemy's Aegis card stays this long after the pickup, and comes back this
# long before it can expire.
ENEMY_SHOW = 30
ENEMY_END_WARN = 30
# GSI player ids: 0-4 Radiant, 5-9 Dire.
RADIANT_IDS = range(5)
DIRE_IDS = range(5, 10)


def _team_of(player_id: Any) -> str | None:
    if isinstance(player_id, bool) or not isinstance(player_id, int):
        return None
    if player_id in RADIANT_IDS:
        return "radiant"
    return "dire" if player_id in DIRE_IDS else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return int(value) if abs(value) < 10_000_000 else None


class RoshanTimer:
    """Per match (reset with MatchMemory): the last kill and the player's Aegis."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.killed_at: int | None = None  # match clock of the last Roshan kill
        self.aegis_at: int | None = None  # match clock the player got the Aegis
        self._picked_up_at: int | None = None  # match clock of the last Aegis pickup event
        self.enemy_aegis_at: int | None = None  # match clock an enemy picked the Aegis up
        self._seen_without_aegis = False  # the hero was seen without it this match
        self._seen: set[tuple[str, int]] = set()

    def observe(self, extra: dict[str, Any]) -> None:
        """`extra`: the normalized GSI extra context (gsi_events, has_aegis, clocks)."""
        clock = _int(extra.get("clock_time"))
        game_time = _int(extra.get("game_time"))
        offset = game_time - clock if clock is not None and game_time is not None else None
        for event in extra.get("gsi_events") or []:
            if not isinstance(event, dict):
                continue
            kind, at = event.get("type"), _int(event.get("game_time"))
            if kind not in {"roshan_killed", "aegis_picked_up"} or at is None:
                continue
            if (kind, at) in self._seen or offset is None:
                continue
            self._seen.add((kind, at))
            if kind == "roshan_killed":
                self.killed_at = at - offset
            else:
                self._picked_up_at = at - offset
                holder = _team_of(event.get("player_id"))
                own = extra.get("team_name")
                if holder is not None and own in ("radiant", "dire") and holder != own:
                    self.enemy_aegis_at = at - offset
        has_aegis = extra.get("has_aegis")
        if has_aegis is True and self.aegis_at is None and clock is not None:
            self.aegis_at = self._pickup_clock(clock)
        elif has_aegis is False:
            self.aegis_at = None
            self._seen_without_aegis = True

    def _pickup_clock(self, clock: int) -> int | None:
        """When the player got the Aegis: the pickup event when it fits, else now if
        the hero was seen without it just before; unknown (a restart mid-match with
        no event) → no expiry is claimed."""
        pickup = self._picked_up_at
        if pickup is not None and 0 <= clock - pickup <= _settings()["aegis"]:
            return pickup
        return clock if self._seen_without_aegis else None

    def aegis_expires(self) -> int | None:
        """Match clock the player's Aegis expires at (None: no Aegis, or its
        pickup time is unknown)."""
        if self.aegis_at is None:
            return None
        return self.aegis_at + _settings()["aegis"]

    def enemy_aegis(self, clock: int | None) -> bool:
        """An enemy can still hold the Aegis (from the pickup until it expires)."""
        at = self.enemy_aegis_at
        return clock is not None and at is not None and at <= clock <= at + _settings()["aegis"]

    def hint(self, clock: int | None, lang: str) -> dict[str, Any] | None:
        if clock is None:
            return None
        cfg = _settings()
        lang = "uk" if lang == "uk" else "en"
        enemy = self._enemy_hint(clock, lang, cfg)
        if enemy is not None and self.aegis_at is None:
            return enemy
        if self.aegis_at is not None:
            expires = self.aegis_at + cfg["aegis"]
            if expires - cfg["warn"] <= clock <= expires:
                title, hint = TEXT["aegis"][lang]
                timer = _timer(
                    "aegis", expires, clock, title.format(left=expires - clock), hint, speak=True
                )
                timer["title_en"] = TEXT["aegis"]["en"][0].format(left=expires - clock)
                return timer
        if self.killed_at is not None:
            opens, closes = self.killed_at + cfg["min"], self.killed_at + cfg["max"]
            if opens - cfg["lead"] <= clock <= opens + cfg["grace"]:
                title, hint = TEXT["window"][lang]
                text = hint.format(at=clock_label(opens), until=clock_label(closes))
                timer = _timer("roshan_window", opens, clock, title, text, speak=True)
                # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
                timer["title_en"] = TEXT["window"]["en"][0]
                return timer
            if closes <= clock <= closes + cfg["grace"]:
                title, hint = TEXT["alive"][lang]
                return _timer("roshan_up", closes, clock, title, hint, speak=False)
        return None

    def _enemy_hint(self, clock: int, lang: str, cfg: dict[str, int]) -> dict[str, Any] | None:
        """At the enemy's pickup (ENEMY_SHOW seconds) and ENEMY_END_WARN seconds
        before it can expire."""
        at = self.enemy_aegis_at
        if at is None:
            return None
        expires = at + cfg["aegis"]
        if at <= clock <= at + ENEMY_SHOW:
            title, hint = TEXT["enemy_aegis"][lang]
            timer = _timer(
                "enemy_aegis",
                expires,
                clock,
                title.format(until=clock_label(expires)),
                hint,
                speak=True,
            )
            timer["title_en"] = TEXT["enemy_aegis"]["en"][0].format(until=clock_label(expires))
            # News now, not a countdown: over any scheduled timer (map_hints.map_hint).
            timer["urgent"] = True
            return timer
        if expires - ENEMY_END_WARN <= clock <= expires:
            title, hint = TEXT["enemy_aegis_ends"][lang]
            timer = _timer(
                "enemy_aegis_ends",
                expires,
                clock,
                title.format(left=expires - clock),
                hint,
                speak=False,
            )
            timer["title_en"] = TEXT["enemy_aegis_ends"]["en"][0].format(left=expires - clock)
            return timer
        return None

    def maybe_up(self, clock: int | None) -> bool:
        """Roshan can be up: from the moment his respawn window opens after the
        last kill (never before: the ward tip says «can be up now») until three
        minutes after it closes (later, nobody knows whether he is still there)."""
        if clock is None or self.killed_at is None:
            return False
        cfg = _settings()
        return self.killed_at + cfg["min"] <= clock <= self.killed_at + cfg["max"] + 180

    def strip(self, clock: int | None, lang: str) -> list[dict[str, Any]]:
        """For the overlay's timer strip: the player's Aegis until it expires, and
        Roshan's respawn window (until it opens, then while it is open)."""
        if clock is None:
            return []
        cfg = _settings()
        items = []
        if self.aegis_at is not None and clock <= self.aegis_at + cfg["aegis"]:
            items.append(strip_item("aegis", self.aegis_at + cfg["aegis"], clock, lang))
        if self.enemy_aegis(clock) and self.enemy_aegis_at is not None:
            items.append(strip_item("enemy_aegis", self.enemy_aegis_at + cfg["aegis"], clock, lang))
        if self.killed_at is not None:
            opens, closes = self.killed_at + cfg["min"], self.killed_at + cfg["max"]
            if clock < opens:
                items.append(
                    strip_item("roshan", opens, clock, lang, until_label=clock_label(closes))
                )
            elif clock <= closes:
                items.append(strip_item("roshan_maybe", closes, clock, lang))
        return items


def _timer(kind: str, at: int, clock: int, title: str, hint: str, *, speak: bool) -> dict[str, Any]:
    return {
        "kind": "timer",
        "id": f"{kind}@{at}",
        "at": at,
        "at_label": clock_label(at),
        "in_seconds": at - clock,
        "title": title,
        "hint": hint,
        "speak": speak,
        "minor": False,
        "patch": timers().get("patch"),
    }
