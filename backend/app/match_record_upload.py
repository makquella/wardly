"""
match_record_upload.py - the copy of a match recording that a player may send
to the developer (docs/DATA_PLAN.md, stage 5).

The local file (match_records.py) is already free of the Steam ID, nickname,
GSI token and chat. The copy goes further, because an uploaded file lives on a
server for 60 days:
- every payload goes through `redact` once more (a file written by an older
  version may predate a rule);
- the match id is gone (it leads to the player's account on OpenDota), from the
  meta line and from `map.matchid` of every payload; the local file name, which
  carries it, is never part of the copy;
- every absolute time (`provider.timestamp`, the snapshot stamps `ts` / `snap`,
  the card's `observed_at`, the meta `started_at`) becomes seconds from the
  match's first stamp, and `w` counts from the first line, so nobody can tell
  when the match was played. Joins stay valid: equal stamps stay equal.
The replay scripts read the copy as they read a local file.

Nothing here trusts the file: a last scan refuses a copy in which any private
key is still present (`unredacted`). The server only looks at the first line
of the upload (services/api/src/session.js), so this scan is the guarantee.
"""

from __future__ import annotations

import gzip
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.match_records import _PLAYER_PRIVATE, is_chat_event, redact

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # the Worker refuses more (services/api/src/session.js)
UPLOAD_FORMAT = 1
# Keys that must not be anywhere in the copy, at any depth (`name` stays: it
# names heroes and abilities; only the player block's own name is private).
_FORBIDDEN_KEYS = (_PLAYER_PRIVATE - {"name"}) | {"auth", "matchid", "match_id"}
# A Unix time in seconds (2001 and later) as opposed to a game clock.
_EPOCH_MIN = 1_000_000_000
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T")


class UploadError(Exception):
    """The recording cannot be sent; `code` is what the launcher shows."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UploadCopy:
    data: bytes
    hero: str
    minutes: int
    payloads: int
    advice: int


def _epoch(value: Any) -> float | None:
    """Unix seconds of an ISO stamp or an epoch number; None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= _EPOCH_MIN else None
    if isinstance(value, str) and _ISO.match(value):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def _stamps(record: dict[str, Any]) -> list[Any]:
    """Every absolute time of a line, for the first pass."""
    if record.get("k") == "gsi":
        provider = (record.get("p") or {}).get("provider")
        return [record.get("ts"), provider.get("timestamp") if isinstance(provider, dict) else None]
    if record.get("k") == "advice":
        basis = record.get("basis")
        return [record.get("snap"), basis.get("observed_at") if isinstance(basis, dict) else None]
    return []


def _lines(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a half-written last line of an interrupted match
                if isinstance(record, dict):
                    yield record


def _strip_match_id(value: Any) -> None:
    if isinstance(value, dict):
        for key in list(value):
            if key in ("matchid", "match_id"):
                value.pop(key)
            else:
                _strip_match_id(value[key])
    elif isinstance(value, list):
        for item in value:
            _strip_match_id(item)


def _has_forbidden_key(value: Any, *, in_player: bool = False) -> bool:
    """Private keys, chat events and the player's own name, at any depth.
    `in_player`: inside a `player` block (also `previously.player`, `added.player`)."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_KEYS or (in_player and key == "name"):
                return True
            if _has_forbidden_key(item, in_player=in_player or key == "player"):
                return True
        return False
    if isinstance(value, list):
        return any(
            is_chat_event(item) or _has_forbidden_key(item, in_player=in_player) for item in value
        )
    return False


class _Clock:
    """Absolute times -> seconds from `base`; the same stamp gives the same text."""

    def __init__(self, base: float, first_wall: float) -> None:
        self.base = base
        self.first_wall = first_wall

    def relative(self, value: Any) -> float | None:
        epoch = _epoch(value)
        return None if epoch is None else round(max(0.0, epoch - self.base), 3)

    def stamp(self, value: Any) -> str | None:
        seconds = self.relative(value)
        return None if seconds is None else f"+{seconds:.3f}"

    def wall(self, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return round(max(0.0, float(value) - self.first_wall), 2)


def _shift_provider(payload: dict[str, Any], clock: _Clock) -> None:
    for block in (payload, payload.get("previously"), payload.get("added")):
        provider = block.get("provider") if isinstance(block, dict) else None
        if isinstance(provider, dict) and "timestamp" in provider:
            seconds = clock.relative(provider["timestamp"])
            provider["timestamp"] = 0 if seconds is None else int(seconds)


def _gsi_line(record: dict[str, Any], clock: _Clock) -> dict[str, Any]:
    payload = redact(record["p"]) if isinstance(record.get("p"), dict) else {}
    _strip_match_id(payload)
    _shift_provider(payload, clock)
    return {
        "k": "gsi",
        "w": clock.wall(record.get("w")),
        "ts": clock.stamp(record.get("ts")),
        "p": payload,
    }


def _advice_line(record: dict[str, Any], clock: _Clock) -> dict[str, Any]:
    line = {key: value for key, value in record.items() if key not in ("snap", "w")}
    basis = line.get("basis")
    if isinstance(basis, dict):
        basis = dict(basis)
        basis["observed_at"] = clock.relative(basis.get("observed_at"))
        line["basis"] = basis
    return {**line, "w": clock.wall(record.get("w")), "snap": clock.stamp(record.get("snap"))}


def _scan(path: Path) -> tuple[_Clock, dict[str, Any]]:
    """First pass: the base of the relative times and the totals of the meta line."""
    stamps: list[float] = []
    walls: list[float] = []
    totals: dict[str, Any] = {"hero": "", "payloads": 0, "advice": 0, "last_clock": None}
    for record in _lines(path):
        kind = record.get("k")
        if kind == "meta":
            totals["hero"] = str(record.get("hero") or "")[:60]
        elif kind in ("gsi", "advice"):
            stamps.extend(e for e in map(_epoch, _stamps(record)) if e is not None)
            if isinstance(record.get("w"), (int, float)):
                walls.append(float(record["w"]))
            if kind == "advice":
                totals["advice"] += 1
                continue
            totals["payloads"] += 1
            payload = record.get("p")
            game = payload.get("map") if isinstance(payload, dict) else None
            value = game.get("clock_time") if isinstance(game, dict) else None
            if isinstance(value, int) and not isinstance(value, bool):
                totals["last_clock"] = value
    return _Clock(min(stamps, default=0.0), min(walls, default=0.0)), totals


def upload_copy(path: Path, *, app_version: str | None = None) -> UploadCopy:
    """The anonymized gzip copy of one recording; raises UploadError."""
    try:
        clock, totals = _scan(path)
        if not totals["payloads"]:
            raise UploadError("empty")
        meta = {
            "k": "meta",
            "hero": totals["hero"] or None,
            "payloads": totals["payloads"],
            "advice": totals["advice"],
            "last_clock": totals["last_clock"],
            "format": 1,
            "upload": UPLOAD_FORMAT,
            "anonymized": True,
            "app_version": app_version,
        }
        out = io.BytesIO()
        # mtime=0: the gzip header carries no time either.
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as packed:
            packed.write((json.dumps(meta) + "\n").encode("utf-8"))
            for record in _lines(path):
                kind = record.get("k")
                if kind == "gsi":
                    line = _gsi_line(record, clock)
                elif kind == "advice":
                    line = _advice_line(record, clock)
                else:
                    continue
                if _has_forbidden_key(line):
                    raise UploadError("unredacted")
                packed.write((json.dumps(line, default=str) + "\n").encode("utf-8"))
    except (OSError, EOFError) as error:
        raise UploadError("unreadable") from error
    data = out.getvalue()
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("too_large")
    last = totals["last_clock"]
    minutes = max(0, last // 60) if isinstance(last, int) else 0
    return UploadCopy(data, totals["hero"], minutes, totals["payloads"], totals["advice"])
