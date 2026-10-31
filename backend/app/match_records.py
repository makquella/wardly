"""
match_records.py - a week of match recordings on the player's own computer.

Switched on in the launcher («Зберігати записи матчів», Settings → «Ще
налаштування»): every live match is written to its own gzip JSON-lines file —
what the game sent (at most RECORD_EVERY seconds apart, plus every change of
the game state, of life and death or of a blocking status) and every advice
card the coach showed —
so a player can save any match of the last week as a file and send it to the
developer, the next day too. Nothing is uploaded.

The files carry no Steam ID, account id, nickname, GSI token or chat:
`redact` drops them before writing. Files older than KEEP_DAYS are deleted.
Lines: {"k": "gsi", "w": wall time, "ts": snapshot, "p": payload} and
{"k": "advice", "w": …, "snap": snapshot, "clock": …, "dp": …, "action": …,
"reason": …, "priority": …, "basis": …}; the first line is {"k": "meta", …}.
Python's gzip reads the appended members as one file.

`w` of a GSI line is when the payload arrived (before it was published), so
the snapshot a card was decided on never carries a later `w` than the card;
`ts` (gsi_snapshot timestamp) on both lines joins a card to that exact
snapshot when it was stored. Several payloads share one clock second and only
some are stored, so a missing `ts` means the deciding snapshot was not kept.
"""

from __future__ import annotations

import copy
import gzip
import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.diagnostics import record_error

RECORDS_DIR = "match_records"
KEEP_DAYS = 7
RECORD_EVERY = 0.5  # wall seconds between two stored payloads of the same game second
FLUSH_EVERY = 10.0  # seconds between two writes to disk
FLUSH_LINES = 200
MAX_FILE_BYTES = 60 * 1024 * 1024  # a broken match never fills the disk
IN_MATCH_STATES = {
    "DOTA_GAMERULES_STATE_STRATEGY_TIME",
    "DOTA_GAMERULES_STATE_TEAM_SHOWCASE",
    "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD",
    "DOTA_GAMERULES_STATE_PRE_GAME",
    "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
    "DOTA_GAMERULES_STATE_POST_GAME",
}
# Personal fields of the player block; chat lines are other people's words.
_PLAYER_PRIVATE = {"steamid", "accountid", "name", "persona", "persona_name"}
_SAFE_ID = re.compile(r"[^0-9A-Za-z_-]+")


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """A copy without the GSI token, the player's ids and name, and chat."""
    clean = copy.deepcopy(payload)
    clean.pop("auth", None)
    for block in ("player", "previously", "added"):
        value = clean.get(block)
        if isinstance(value, dict):
            _drop_private(value)
    events = clean.get("events")
    if isinstance(events, list):
        clean["events"] = [
            e for e in events if not (isinstance(e, dict) and e.get("event_type") == "chat_message")
        ]
    return clean


def _drop_private(block: dict[str, Any]) -> None:
    for key in list(block):
        if key in _PLAYER_PRIVATE:
            block.pop(key, None)
        elif isinstance(block[key], dict):
            _drop_private(block[key])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MatchRecords:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enabled = False
        self._dir: Path | None = None
        self._failures = 0
        self._unconfirmed_lines = 0
        self._last_error: str | None = None
        self._reset_current()

    def _reset_current(self) -> None:
        self._match: str | None = None
        self._path: Path | None = None
        self._meta: dict[str, Any] = {}
        self._buffer: list[str] = []
        self._last_stored = 0.0
        self._last_flush = 0.0
        self._last_key: tuple[Any, ...] | None = None
        self._last_clock: int | None = None
        self._bytes = 0

    # --- settings -------------------------------------------------------------

    def configure(self, base_dir: Path, *, enabled: bool | None = None) -> None:
        """The folder (player data dir) and, when given, the switch."""
        with self._lock:
            self._flush_locked()
            self._reset_current()
            self._dir = Path(base_dir) / RECORDS_DIR
            if enabled is not None:
                self.enabled = bool(enabled)
        self.prune()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._flush_locked()
                self._reset_current()
        if enabled:
            self.prune()

    # --- recording ------------------------------------------------------------

    def record_gsi(
        self, payload: Any, *, now: float | None = None, snapshot: str | None = None
    ) -> None:
        """Store one GSI payload of the player's live match; never raises.
        `now`: when it arrived; `snapshot`: the published snapshot's timestamp."""
        if not self.enabled or not isinstance(payload, dict):
            return
        # Recording must never break /gsi.
        try:
            self._record_gsi(payload, time.monotonic() if now is None else now, snapshot)
        except Exception as error:  # noqa: BLE001 - optional recording never breaks GSI
            with self._lock:
                self._failures += 1
                self._last_error = type(error).__name__
            record_error("match-records-observe", error, with_trace=False)

    def _record_gsi(self, payload: dict[str, Any], now: float, snapshot: str | None = None) -> None:
        raw_game, raw_player, raw_hero = (payload.get(k) for k in ("map", "player", "hero"))
        game: dict[str, Any] = raw_game if isinstance(raw_game, dict) else {}
        state = game.get("game_state")
        match_id = _SAFE_ID.sub("", str(game.get("matchid") or ""))[:24]
        player: dict[str, Any] = raw_player if isinstance(raw_player, dict) else {}
        # A spectator gets per-team player blocks: not the player's own match.
        if state not in IN_MATCH_STATES or not match_id or "team2" in player:
            return
        hero: dict[str, Any] = raw_hero if isinstance(raw_hero, dict) else {}
        # A blocking status or a debuff can begin and end inside one clock
        # second: its change is always stored (audits need the onset).
        key = (
            state,
            hero.get("alive"),
            hero.get("name"),
            *(hero.get(flag) for flag in ("stunned", "hexed", "silenced", "muted", "has_debuff")),
        )
        with self._lock:
            if self._dir is None:
                return
            if match_id != self._match:
                self._flush_locked()
                self._start_locked(match_id, hero, now)
            clock = game.get("clock_time")
            clock = clock if isinstance(clock, int) and not isinstance(clock, bool) else None
            # A new game second, a new state, or RECORD_EVERY of wall time: GSI
            # sends about ten payloads a second, most of them the same moment.
            new_second = clock is not None and (
                self._last_clock is None or clock != self._last_clock
            )
            changed = key != self._last_key
            if not changed and not new_second and now - self._last_stored < RECORD_EVERY:
                return
            if self._bytes > MAX_FILE_BYTES:
                return
            self._last_key = key
            self._last_stored = now
            if clock is not None:
                self._last_clock = clock
            self._meta["payloads"] += 1
            if isinstance(game.get("clock_time"), int):
                self._meta["last_clock"] = game["clock_time"]
            if hero.get("name") and not self._meta.get("hero"):
                self._meta["hero"] = str(hero["name"])[:60]
            self._buffer.append(
                json.dumps(
                    {"k": "gsi", "w": round(now, 2), "ts": snapshot, "p": redact(payload)},
                    default=str,
                )
            )
            if len(self._buffer) >= FLUSH_LINES or now - self._last_flush >= FLUSH_EVERY:
                self._flush_locked(now)

    def record_advice(self, response: dict[str, Any], *, now: float | None = None) -> None:
        """Store an advice card when it is new (the overlay asks every second)."""
        if not self.enabled or not response.get("new_advice"):
            return
        recommendation = response.get("recommendation")
        if not isinstance(recommendation, dict):
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._path is None:
                return
            self._meta["advice"] += 1
            self._buffer.append(
                json.dumps(
                    {
                        "k": "advice",
                        "w": round(now, 2),
                        "snap": response.get("timestamp"),
                        "clock": response.get("clock_time"),
                        "dp": response.get("decision_point"),
                        "hero_gameplay": response.get("hero_gameplay"),
                        "action": recommendation.get("action"),
                        "reason": recommendation.get("reason"),
                        "priority": recommendation.get("priority"),
                        # The snapshot the card was decided on (several GSI
                        # payloads share one clock second): its clock, game
                        # time, and the tool/numbers the card cites.
                        "basis": response.get("advice_basis"),
                    },
                    default=str,
                )
            )

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _start_locked(self, match_id: str, hero: dict[str, Any], now: float) -> None:
        assert self._dir is not None
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        self._reset_current()
        self._match = match_id
        self._path = self._dir / f"{stamp}_{match_id}.jsonl.gz"
        self._meta = {
            "k": "meta",
            "match_id": match_id,
            "hero": str(hero.get("name") or "")[:60] or None,
            "started_at": _now_iso(),
            "payloads": 0,
            "advice": 0,
            "last_clock": None,
            "format": 1,
        }
        self._last_flush = now
        self._buffer.append(json.dumps(self._meta))

    def _flush_locked(self, now: float | None = None) -> None:
        if self._path is None or not self._buffer:
            return
        data = ("\n".join(self._buffer) + "\n").encode("utf-8")
        count = len(self._buffer)
        self._buffer = []
        self._last_flush = time.monotonic() if now is None else now
        try:
            with gzip.open(self._path, "ab") as handle:
                handle.write(data)
            self._bytes = self._path.stat().st_size
            # The summary next to it: the list reads it without opening the gzip.
            summary = {**self._meta, "updated_at": _now_iso(), "bytes": self._bytes}
            self._path.with_suffix("").with_suffix(".json").write_text(
                json.dumps(summary), encoding="utf-8"
            )
        except OSError as error:
            self._failures += 1
            self._unconfirmed_lines += count
            self._last_error = type(error).__name__
            record_error("match-records-flush", error, with_trace=False)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "failures": self._failures,
                "unconfirmed_lines": self._unconfirmed_lines,
                "last_error": self._last_error,
                "buffered_lines": len(self._buffer),
            }

    # --- files ----------------------------------------------------------------

    def prune(self, *, now: float | None = None) -> int:
        """Delete recordings older than KEEP_DAYS; returns how many."""
        base = self._dir
        if base is None or not base.is_dir():
            return 0
        limit = (time.time() if now is None else now) - KEEP_DAYS * 86400
        removed = 0
        for path in base.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < limit:
                    path.unlink()
                    removed += path.name.endswith(".jsonl.gz")
            except OSError:
                continue
        return removed

    def list(self) -> list[dict[str, Any]]:
        """Recordings, newest first: {id, match_id, hero, started_at, minutes, …}."""
        self.flush()
        base = self._dir
        if base is None or not base.is_dir():
            return []
        rows = []
        for path in sorted(base.glob("*.jsonl.gz"), reverse=True):
            record_id = path.name[: -len(".jsonl.gz")]
            try:
                meta = json.loads(path.with_suffix("").with_suffix(".json").read_text("utf-8"))
            except (OSError, ValueError):
                meta = {}
            clock = meta.get("last_clock")
            rows.append(
                {
                    "id": record_id,
                    "match_id": meta.get("match_id"),
                    "hero": meta.get("hero"),
                    "started_at": meta.get("started_at"),
                    "minutes": max(0, clock // 60) if isinstance(clock, int) else None,
                    "payloads": meta.get("payloads"),
                    "advice": meta.get("advice"),
                    "bytes": path.stat().st_size,
                }
            )
        return rows

    def path_of(self, record_id: str) -> Path | None:
        """The file of a recording id from `list` (None for anything else)."""
        if self._dir is None or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}_[0-9A-Za-z_-]{1,24}", record_id
        ):
            return None
        self.flush()
        path = self._dir / f"{record_id}.jsonl.gz"
        return path if path.is_file() else None


MATCH_RECORDS = MatchRecords()
