"""
player_store.py - local SQLite store for the linked player and their matches.

One file, PLAYER_DATA_DIR/coach.sqlite3 (under %APPDATA%\\DotaAICoach in the
installed app). It keeps:

- players: accounts seen by the app (linked by hand or detected from GSI);
- meta: which account is the primary one ("my account");
- matches: one row per (account, match) with summary columns for the match
  table, plus JSON blobs: the trimmed OpenDota match, the GSI timeline the
  app recorded live, and the last post-match analysis.

Nothing here talks to the network; see opendota.py and player_service.py.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.diagnostics import record_error
from app.storage_json import cache_value_valid, load_json

SCHEMA_VERSION = 1

# Summary columns shown in the match table (all optional).
MATCH_COLUMNS = (
    "start_time",
    "duration",
    "hero_id",
    "hero",
    "is_radiant",
    "win",
    "kills",
    "deaths",
    "assists",
    "gpm",
    "xpm",
    "last_hits",
    "denies",
    "lh_10",
    "net_worth",
    "hero_damage",
    "lane_role",
    "game_mode",
    "lobby_type",
    "parsed",
    "score",
    # The final inventory as a JSON list of item keys (the match table's icons).
    "items",
    # The player's own note on the match (0.52, «Нотатка»): only set_note writes it.
    "note",
)

# The match table's sortable columns (a fixed list: the key never reaches SQL).
SORT_COLUMNS = {
    "score": "score",
    "gpm": "gpm",
    "lh_10": "lh_10",
    "duration": "duration",
    "kda": "CASE WHEN kills IS NULL THEN NULL "
    "ELSE (kills + COALESCE(assists, 0)) * 1.0 / MAX(1, COALESCE(deaths, 0)) END",
}
MATCH_SORTS = ("date", *SORT_COLUMNS)

# Match columns added after the first release (name, SQL type).
ADDED_COLUMNS = (("items", "TEXT"), ("note", "TEXT"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS players (
    account_id INTEGER PRIMARY KEY,
    steam_id64 TEXT,
    persona_name TEXT,
    avatar_url TEXT,
    rank_tier INTEGER,
    source TEXT,
    first_seen_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    account_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    start_time INTEGER,
    duration INTEGER,
    hero_id INTEGER,
    hero TEXT,
    is_radiant INTEGER,
    win INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    gpm INTEGER,
    xpm INTEGER,
    last_hits INTEGER,
    denies INTEGER,
    lh_10 INTEGER,
    net_worth INTEGER,
    hero_damage INTEGER,
    lane_role INTEGER,
    game_mode INTEGER,
    lobby_type INTEGER,
    parsed INTEGER DEFAULT 0,
    score INTEGER,
    items TEXT,
    note TEXT,
    sources TEXT DEFAULT '',
    parse_status TEXT DEFAULT '',
    opendota_json TEXT,
    timeline_json TEXT,
    analysis_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (account_id, match_id)
);
CREATE INDEX IF NOT EXISTS matches_by_time ON matches (account_id, start_time DESC);
-- The order every list reads in (newest first, unknown times last), with and
-- without the hero filter: no temporary sort over the whole history.
CREATE INDEX IF NOT EXISTS matches_by_order
  ON matches (account_id, COALESCE(start_time, 0) DESC, match_id DESC);
CREATE INDEX IF NOT EXISTS matches_by_hero_order
  ON matches (account_id, hero_id, COALESCE(start_time, 0) DESC, match_id DESC);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT,
    fetched_at REAL
);
"""


def _plain(value: Any) -> bool:
    """A value SQLite stores as it is (backups are JSON: no nested objects)."""
    return value is None or isinstance(value, (str, int, float))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PlayerStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            # Columns added after the first release: a database made before
            # them gets them here (CREATE TABLE IF NOT EXISTS keeps old tables).
            present = {row[1] for row in self._conn.execute("PRAGMA table_info(matches)")}
            for column, kind in ADDED_COLUMNS:
                if column not in present:
                    self._conn.execute(f"ALTER TABLE matches ADD COLUMN {column} {kind}")
            self._set_meta("schema_version", str(SCHEMA_VERSION))
            self._conn.commit()
        if os.name == "posix":
            # Keys are stored unsealed outside Windows: only the owner reads the file
            # (SQLite gives the -wal/-shm files the same mode).
            with contextlib.suppress(OSError):
                self.db_path.chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- meta / primary account ---------------------------------------------

    def _get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def _set_meta(self, key: str, value: str | None) -> None:
        if value is None:
            self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def primary_account_id(self) -> int | None:
        with self._lock:
            value = self._get_meta("primary_account_id")
        return int(value) if value else None

    def set_primary(self, account_id: int, *, source: str) -> None:
        with self._lock:
            self._touch_player(account_id, source=source)
            self._set_meta("primary_account_id", str(int(account_id)))
            self._set_meta("primary_source", source)
            self._conn.commit()

    def primary_source(self) -> str | None:
        with self._lock:
            return self._get_meta("primary_source")

    def clear_primary(self) -> None:
        with self._lock:
            self._set_meta("primary_account_id", None)
            self._set_meta("primary_source", None)
            self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            return self._get_meta(key)

    def meta_with_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """Every (key, value) whose key starts with `prefix`, in key order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM meta WHERE substr(key, 1, ?) = ? ORDER BY key",
                (len(prefix), prefix),
            ).fetchall()
        return [(row["key"], row["value"]) for row in rows if row["value"] is not None]

    def set_meta(self, key: str, value: str | None) -> None:
        with self._lock:
            self._set_meta(key, value)
            self._conn.commit()

    # --- backup (history_backup.py): whole rows of a table, merged back -----------

    BACKUP_KEYS = {
        "players": ("account_id",),
        "matches": ("account_id", "match_id"),
        "meta": ("key",),
        "cache": ("key",),
    }

    def _columns(self, table: str) -> list[str]:
        return [row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")]

    def export_rows(self, table: str) -> list[dict[str, Any]]:
        if table not in self.BACKUP_KEYS:
            raise ValueError(table)
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]

    def backup_snapshot(self) -> tuple[dict[str, list[dict[str, Any]]], int | None]:
        """Read every table and account selection from one SQLite snapshot."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN")
            tables = {table: self.export_rows(table) for table in self.BACKUP_KEYS}
            account = self.primary_account_id()
        return tables, account

    def merge_backup(
        self, tables: dict[str, list[dict[str, Any]]], account: int | None
    ) -> dict[str, Any]:
        """Merge validated rows and link the account in one rollback-safe transaction."""
        with self._lock, self._conn:
            # Serialize primary-account selection with other SQLite connections too.
            self._conn.execute("BEGIN IMMEDIATE")
            imported = {
                table: self._import_rows(table, tables[table]) for table in self.BACKUP_KEYS
            }
            linked = self.primary_account_id() is None and account is not None
            if linked and account is not None:
                self._touch_player(account, source="backup")
                self._set_meta("primary_account_id", str(account))
                self._set_meta("primary_source", "backup")
            result = {
                "imported": imported,
                "linked": linked,
                "account_id": self.primary_account_id(),
            }
        # The connection context commits before the caller can invalidate caches/queue sync.
        return result

    def preview_backup(
        self, tables: dict[str, list[dict[str, Any]]], account: int | None
    ) -> dict[str, Any]:
        """What merge_backup would do, counted by running it and rolling back."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                imported = {
                    table: self._import_rows(table, tables[table]) for table in self.BACKUP_KEYS
                }
                linked = self.primary_account_id() is None and account is not None
            finally:
                self._conn.rollback()
        return {"imported": imported, "linked": linked, "account_id": self.primary_account_id()}

    def import_rows(self, table: str, rows: list[dict[str, Any]]) -> dict[str, int]:
        """Merge rows: a missing row is added; a stored one only gets the values it
        lacks (never overwritten). Unknown columns are ignored."""
        with self._lock, self._conn:
            return self._import_rows(table, rows)

    def _import_rows(self, table: str, rows: list[dict[str, Any]]) -> dict[str, int]:
        """Caller owns the store lock and transaction; this helper never commits."""
        keys = self.BACKUP_KEYS.get(table)
        if keys is None:
            raise ValueError(table)
        added = filled = 0
        columns = set(self._columns(table))
        for raw in rows:
            if not isinstance(raw, dict) or any(raw.get(k) is None for k in keys):
                continue
            row = {k: v for k, v in raw.items() if k in columns and _plain(v)}
            if any(row.get(k) is None for k in keys):
                continue  # a key that is not a plain value: not a row we can place
            where = " AND ".join(f"{k} = ?" for k in keys)
            params = tuple(row[k] for k in keys)
            stored = self._conn.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchone()
            if stored is None:
                names = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                self._conn.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values())
                )
                added += 1
                continue
            missing = {
                k: v
                for k, v in row.items()
                if k not in keys and v not in (None, "") and stored[k] in (None, "")
            }
            if missing:
                sets = ", ".join(f"{k} = ?" for k in missing)
                self._conn.execute(
                    f"UPDATE {table} SET {sets} WHERE {where}",
                    (*missing.values(), *params),
                )
                filled += 1
        return {"added": added, "filled": filled}

    # --- cache (OpenDota meta data: items, hero builds, bracket win rates) -----

    def cache_get(self, key: str, *, max_age: float | None = None) -> Any:
        """Cached value or a miss; discard and diagnose corrupt entries."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value, fetched_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            try:
                fetched_at = float(row["fetched_at"] or 0)
                if not math.isfinite(fetched_at) or fetched_at < 0:
                    raise ValueError("Invalid cache timestamp")
                value = load_json(row["value"])
                if not cache_value_valid(key, value):
                    raise ValueError("Invalid cache shape")
            except (ValueError, TypeError, OverflowError, RecursionError) as error:
                # Do not log the key, payload or exception text (they can contain private data).
                record_error(
                    "player-cache",
                    f"Corrupt entry discarded: {type(error).__name__}",
                    with_trace=False,
                )
                try:
                    with self._conn:
                        # Another connection may have refreshed the value since SELECT.
                        self._conn.execute(
                            "DELETE FROM cache WHERE key = ? AND value IS ? AND fetched_at IS ?",
                            (key, row["value"], row["fetched_at"]),
                        )
                except sqlite3.Error as error:
                    record_error(
                        "player-cache", f"Discard failed: {type(error).__name__}", with_trace=False
                    )
                return None
            if max_age is not None and time.time() - fetched_at > max_age:
                return None
            return value

    def cache_set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache (key, value, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "fetched_at = excluded.fetched_at",
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )
            self._conn.commit()

    # --- players ------------------------------------------------------------

    def _touch_player(self, account_id: int, *, source: str) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO players (account_id, source, first_seen_at, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO NOTHING",
            (int(account_id), source, now, now),
        )

    def upsert_player(self, account_id: int, *, source: str, **fields: Any) -> None:
        allowed = {"steam_id64", "persona_name", "avatar_url", "rank_tier"}
        updates = {key: value for key, value in fields.items() if key in allowed and value}
        with self._lock:
            self._touch_player(account_id, source=source)
            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                self._conn.execute(
                    f"UPDATE players SET {assignments}, updated_at = ? WHERE account_id = ?",
                    (*updates.values(), _now(), int(account_id)),
                )
            self._conn.commit()

    def get_player(self, account_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM players WHERE account_id = ?", (int(account_id),)
            ).fetchone()
        return dict(row) if row else None

    # --- matches ------------------------------------------------------------

    def upsert_match(
        self,
        account_id: int,
        match_id: int,
        *,
        source: str | None,
        fields: dict[str, Any] | None = None,
        opendota: dict[str, Any] | None = None,
        timeline: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
        parse_status: str | None = None,
    ) -> None:
        """Insert or merge one match. Missing values never erase stored ones."""
        values = {
            key: value
            for key, value in (fields or {}).items()
            if key in MATCH_COLUMNS and value is not None
        }
        with self._lock:
            row = self._conn.execute(
                "SELECT sources FROM matches WHERE account_id = ? AND match_id = ?",
                (int(account_id), int(match_id)),
            ).fetchone()
            sources = set(filter(None, (row["sources"] if row else "").split(",")))
            if source:
                sources.add(source)
            if row is None:
                self._conn.execute(
                    "INSERT INTO matches (account_id, match_id, sources, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (int(account_id), int(match_id), "", _now()),
                )
            blobs: dict[str, Any] = {"sources": ",".join(sorted(sources)), "updated_at": _now()}
            if opendota is not None:
                blobs["opendota_json"] = json.dumps(opendota, ensure_ascii=False)
            if timeline is not None:
                blobs["timeline_json"] = json.dumps(timeline, ensure_ascii=False)
            if analysis is not None:
                blobs["analysis_json"] = json.dumps(analysis, ensure_ascii=False)
            if parse_status is not None:
                blobs["parse_status"] = parse_status
            updates = {**values, **blobs}
            assignments = ", ".join(f"{key} = ?" for key in updates)
            self._conn.execute(
                f"UPDATE matches SET {assignments} WHERE account_id = ? AND match_id = ?",
                (*updates.values(), int(account_id), int(match_id)),
            )
            self._conn.commit()

    @staticmethod
    def _filter(
        account_id: int, hero_id: int | None, win: bool | None
    ) -> tuple[str, tuple[Any, ...]]:
        """WHERE clause for the match table filters (hero, result)."""
        where, params = ["account_id = ?"], [int(account_id)]
        if hero_id is not None:
            where.append("hero_id = ?")
            params.append(int(hero_id))
        if win is not None:
            where.append("win = ?")
            params.append(1 if win else 0)
        return " AND ".join(where), tuple(params)

    def list_matches(
        self,
        account_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        hero_id: int | None = None,
        win: bool | None = None,
        sort: str = "date",
        ascending: bool = False,
    ) -> list[dict[str, Any]]:
        columns = ", ".join(("match_id", *MATCH_COLUMNS, "sources", "parse_status"))
        where, params = self._filter(account_id, hero_id, win)
        order = "COALESCE(start_time, 0) DESC, match_id DESC"
        expression = SORT_COLUMNS.get(sort)
        if expression is not None:
            # Rows without the number last either way; the newest first among equals.
            direction = "ASC" if ascending else "DESC"
            order = f"({expression}) IS NULL, ({expression}) {direction}, {order}"
        elif sort == "date" and ascending:
            order = "COALESCE(start_time, 0) ASC, match_id ASC"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {columns}, analysis_json IS NOT NULL AS has_analysis, "
                f"timeline_json IS NOT NULL AS has_timeline FROM matches WHERE {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, int(limit), int(offset)),
            ).fetchall()
        return [_summary_row(row) for row in rows]

    # The columns the «Профіль» tab reads (player_profile.py), for every match.
    PROFILE_COLUMNS = (
        "match_id",
        "start_time",
        "win",
        "score",
        "hero_id",
        "duration",
        "deaths",
        "lobby_type",
        "sources",
    )

    def profile_rows(self, account_id: int, *, limit: int) -> list[dict[str, Any]]:
        """Newest first, only PROFILE_COLUMNS and has_analysis: the profile reads
        the whole history, so no items, notes or other summary columns."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {', '.join(self.PROFILE_COLUMNS)}, "
                "analysis_json IS NOT NULL AS has_analysis FROM matches WHERE account_id = ? "
                "ORDER BY COALESCE(start_time, 0) DESC, match_id DESC LIMIT ?",
                (int(account_id), int(limit)),
            ).fetchall()
        return [_summary_row(row) for row in rows]

    def count_matches(
        self, account_id: int, *, hero_id: int | None = None, win: bool | None = None
    ) -> int:
        where, params = self._filter(account_id, hero_id, win)
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM matches WHERE {where}", params
            ).fetchone()
        return int(row["n"]) if row else 0

    def match_stats(
        self, account_id: int, *, hero_id: int | None = None, win: bool | None = None
    ) -> dict[str, Any]:
        """Games, wins (of those with a known result) and average score of a filter."""
        where, params = self._filter(account_id, hero_id, win)
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS games, SUM(win = 1) AS wins, "
                "SUM(win IS NOT NULL) AS decided, AVG(score) AS avg_score "
                f"FROM matches WHERE {where}",
                params,
            ).fetchone()
        decided = int(row["decided"] or 0)
        return {
            "games": int(row["games"] or 0),
            "wins": int(row["wins"] or 0),
            "winrate": round(100 * int(row["wins"] or 0) / decided) if decided else None,
            "avg_score": round(row["avg_score"]) if row["avg_score"] is not None else None,
        }

    def hero_counts(self, account_id: int) -> list[dict[str, Any]]:
        """Heroes of the stored matches, most played first (filter choices)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT hero_id, MAX(hero) AS hero, COUNT(*) AS games FROM matches "
                "WHERE account_id = ? AND hero_id IS NOT NULL GROUP BY hero_id "
                "ORDER BY games DESC, hero",
                (int(account_id),),
            ).fetchall()
        return [
            {"hero_id": int(row["hero_id"]), "hero": row["hero"], "games": int(row["games"])}
            for row in rows
        ]

    def source_counts(self, account_id: int) -> dict[str, int]:
        """How many matches per parse status (problem report)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT COALESCE(NULLIF(parse_status, ''), 'none') AS status, COUNT(*) AS n "
                "FROM matches WHERE account_id = ? GROUP BY status",
                (int(account_id),),
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def delete_matches(self, account_id: int, match_ids: list[int]) -> int:
        if not match_ids:
            return 0
        marks = ", ".join("?" for _ in match_ids)
        with self._lock:
            cursor = self._conn.execute(
                f"DELETE FROM matches WHERE account_id = ? AND match_id IN ({marks})",
                (int(account_id), *(int(m) for m in match_ids)),
            )
            self._conn.commit()
        return int(cursor.rowcount or 0)

    def mode_rows(self, account_id: int) -> list[dict[str, Any]]:
        """match_id, lobby_type and game_mode of every stored match."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT match_id, lobby_type, game_mode FROM matches WHERE account_id = ?",
                (int(account_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_note(self, account_id: int, match_id: int, note: str | None) -> bool:
        """The player's note on a stored match (None or "" removes it); False when
        the match is not stored."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE matches SET note = ? WHERE account_id = ? AND match_id = ?",
                (note or None, int(account_id), int(match_id)),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def get_match(self, account_id: int, match_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM matches WHERE account_id = ? AND match_id = ?",
                (int(account_id), int(match_id)),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        for column, key in (
            ("opendota_json", "opendota"),
            ("timeline_json", "timeline"),
            ("analysis_json", "analysis"),
        ):
            raw = record.pop(column, None)
            record[key] = json.loads(raw) if raw else None
        record["sources"] = [item for item in (record.get("sources") or "").split(",") if item]
        record["items"] = _item_list(record.get("items"))
        return record

    def matches_for_career(
        self,
        account_id: int,
        *,
        limit: int = 50,
        hero_id: int | None = None,
        before: int | None = None,
    ) -> list[dict[str, Any]]:
        """Newest first, summary columns plus the stored analysis (for trends).
        `before`: only matches started before that time."""
        columns = ", ".join(("match_id", *MATCH_COLUMNS, "sources"))
        where, params = self._filter(account_id, hero_id, None)
        if before is not None:
            where += " AND COALESCE(start_time, 0) < ?"
            params = (*params, int(before))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {columns}, analysis_json FROM matches WHERE {where} "
                "ORDER BY COALESCE(start_time, 0) DESC, match_id DESC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        result = []
        for row in rows:
            record = _summary_row(row)
            raw = row["analysis_json"]
            record["analysis"] = json.loads(raw) if raw else None
            result.append(record)
        return result


def _summary_row(row: sqlite3.Row) -> dict[str, Any]:
    # sqlite3.Row iterates over values, so .keys() is needed here.
    record = {key: row[key] for key in row.keys() if key != "analysis_json"}  # noqa: SIM118
    for flag in ("is_radiant", "win", "parsed", "has_analysis", "has_timeline"):
        if flag in record and record[flag] is not None:
            record[flag] = bool(record[flag])
    record["sources"] = [item for item in (record.get("sources") or "").split(",") if item]
    if "items" in record:
        record["items"] = _item_list(record["items"])
    return record


def _item_list(raw: Any) -> list[str] | None:
    """The stored items column: a JSON list of item keys, else None (unknown)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, list):
        return None
    return [str(key) for key in value if isinstance(key, str) and key][:6]
