"""
opendota.py - small OpenDota API client for match history and full-match data.

OpenDota (https://docs.opendota.com) serves public Dota match data. Matches
it has "parsed" (downloaded and processed the replay) carry per-minute last
hits/gold/XP, the purchase log, the kills log, lane efficiency, benchmarks, …
which is what the post-match review needs. Parsing a fresh match is requested
with POST /request/{match_id} and takes a few minutes.

Only public data is available: the player must enable "Expose Public Match
Data" in Dota's settings for their matches to appear.

The client is synchronous (it runs on the background worker, never on the GSI
path), rate-limited to stay under the free tier (60 requests/minute) and
raises OpenDotaError with a stable `code` for the UI.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Any

import requests

from app.dota_constants import hero_name, hero_npc_name
from app.lane_duel import lane_snapshot

# Seconds to connect / to wait for the answer. A player's history can take
# OpenDota half a minute on a cold cache (measured 13-35 s), so reading waits
# long, and a timed-out request is asked once more (the second is usually fast).
DEFAULT_TIMEOUT_SECONDS: tuple[float, float] = (10, 60)
TIMEOUT_RETRIES = 1
MIN_REQUEST_INTERVAL_SECONDS = 1.1
# With a (paid) API key OpenDota allows far more calls per minute.
KEYED_REQUEST_INTERVAL_SECONDS = 0.25

# Reference data (hero stats, items, per-hero timings) is read from Wardly's
# shared cache first (services/api/src/opendota-cache.js, refreshed daily from
# OpenDota). The cache is a convenience: short timeouts, no retries, and a body
# older than CACHE_MAX_AGE_SECONDS is only used when OpenDota itself fails.
CACHE_TIMEOUT_SECONDS: tuple[float, float] = (3.05, 15)
CACHE_MAX_AGE_SECONDS = 3 * 24 * 3600

RECENT_MATCH_FIELDS = (
    "hero_id",
    "start_time",
    "duration",
    "player_slot",
    "radiant_win",
    "kills",
    "deaths",
    "assists",
    "gold_per_min",
    "xp_per_min",
    "last_hits",
    "denies",
    "hero_damage",
    "lane_role",
    "game_mode",
    "lobby_type",
    "version",
    "leaver_status",
)

# Per-player fields kept from /matches/{id} (the full response is ~1 MB).
_PLAYER_FIELDS = (
    "account_id",
    "player_slot",
    "hero_id",
    "personaname",
    "isRadiant",
    "win",
    "kills",
    "deaths",
    "assists",
    "last_hits",
    "denies",
    "gold_per_min",
    "xp_per_min",
    "net_worth",
    "level",
    "hero_damage",
    "tower_damage",
    "hero_healing",
    "lane",
    "lane_role",
    "is_roaming",
    "lane_efficiency_pct",
    "teamfight_participation",
    "stuns",
    "life_state_dead",
    "actions_per_min",
    "obs_placed",
    "sen_placed",
    "camps_stacked",
    "rune_pickups",
    "buyback_count",
    "rank_tier",
    "item_0",
    "item_1",
    "item_2",
    "item_3",
    "item_4",
    "item_5",
    "item_neutral",
    "backpack_0",
    "backpack_1",
    "backpack_2",
    "benchmarks",
)
# Heavy per-minute/log fields, kept for the reviewed player only.
_TIMELINE_FIELDS = (
    "times",
    "lh_t",
    "dn_t",
    "gold_t",
    "xp_t",
    "purchase_log",
    "kills_log",
    "buyback_log",
    "killed_by",
    "damage_taken",
    # Positions (parsed replays): wards placed and where the hero stood in the lane.
    "obs_log",
    "sen_log",
    "lane_pos",
    # Ability ids in the order the player levelled them (the skill review).
    "ability_upgrades_arr",
)
_MATCH_FIELDS = (
    "match_id",
    "start_time",
    "duration",
    "radiant_win",
    "radiant_score",
    "dire_score",
    "game_mode",
    "lobby_type",
    "version",
    "patch",
    "region",
    "first_blood_time",
)


class OpenDotaError(RuntimeError):
    """code: offline | not_found | rate_limited | private | bad_response | disabled"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OpenDotaClient:
    def __init__(
        self,
        base_url: str = "https://api.opendota.com/api",
        *,
        api_key: str = "",
        session: requests.Session | None = None,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        cache_url: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # "" = no shared cache. Only reference data goes through it (_reference_get).
        self.cache_url = cache_url.strip().rstrip("/")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0

    def set_api_key(self, api_key: str) -> None:
        """Use (or stop using) a key; a key also lifts the free-tier pacing."""
        self.api_key = api_key.strip()
        self.min_interval = (
            KEYED_REQUEST_INTERVAL_SECONDS if self.api_key else MIN_REQUEST_INTERVAL_SECONDS
        )

    # --- endpoints ------------------------------------------------------------

    def player(self, account_id: int) -> dict[str, Any]:
        data = self._get(f"/players/{int(account_id)}")
        profile = data.get("profile") if isinstance(data, dict) else None
        if not isinstance(profile, dict):
            raise OpenDotaError("private", "OpenDota has no public profile for this account.")
        return {
            "account_id": int(account_id),
            "persona_name": profile.get("personaname"),
            "avatar_url": profile.get("avatarfull") or profile.get("avatar"),
            "steam_id64": profile.get("steamid"),
            "rank_tier": data.get("rank_tier"),
        }

    def recent_matches(self, account_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        params: list[tuple[str, Any]] = [("limit", int(limit)), ("significant", 0)]
        params += [("project", field) for field in RECENT_MATCH_FIELDS]
        data = self._get(f"/players/{int(account_id)}/matches", params=params)
        if not isinstance(data, list):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for matches.")
        return [summary_from_recent(item) for item in data if isinstance(item, dict)]

    def match(self, match_id: int) -> dict[str, Any]:
        data = self._get(f"/matches/{int(match_id)}")
        if not isinstance(data, dict) or not data.get("players"):
            raise OpenDotaError("not_found", "OpenDota does not have this match yet.")
        return data

    def request_parse(self, match_id: int) -> None:
        self._request("POST", f"/request/{int(match_id)}")

    # --- meta data for build advice and rank comparison (cached by the caller) --

    def item_constants(self) -> dict[str, Any]:
        """/constants/items -> {"by_id": {id: key},
        "items": {key: {name, cost, assembled, components}}} (components: item keys)."""
        data = self._reference_get("/constants/items", dict)
        if not isinstance(data, dict):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for items.")
        by_id: dict[str, str] = {}
        items: dict[str, dict[str, Any]] = {}
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            if item.get("id") is not None:
                by_id[str(item["id"])] = key
            items[key] = {
                "name": item.get("dname") or key,
                "cost": item.get("cost") or 0,
                "assembled": bool(item.get("components")),
                "components": [c for c in item.get("components") or [] if isinstance(c, str)],
            }
        return {"by_id": by_id, "items": items}

    def item_popularity(self, hero_id: int) -> dict[str, dict[str, int]]:
        """/heroes/{id}/itemPopularity (professional matches): {phase: {item_id: count}}."""
        data = self._reference_get(f"/heroes/{int(hero_id)}/itemPopularity", dict)
        if not isinstance(data, dict):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for item popularity.")
        return {
            phase: {str(k): int(v) for k, v in (data.get(phase) or {}).items()}
            for phase in (
                "start_game_items",
                "early_game_items",
                "mid_game_items",
                "late_game_items",
            )
        }

    def item_timings(self, hero_id: int) -> list[dict[str, Any]]:
        """/scenarios/itemTimings (public matches): games/wins per item and time bucket."""
        data = self._reference_get(
            "/scenarios/itemTimings", list, params=[("hero_id", int(hero_id))]
        )
        if not isinstance(data, list):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for item timings.")
        rows = []
        for row in data:
            try:
                rows.append(
                    {
                        "item": str(row["item"]),
                        "time": int(row["time"]),
                        "games": int(row["games"]),
                        "wins": int(row["wins"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    def hero_matchups(self, hero_id: int) -> dict[str, list[int]]:
        """/heroes/{id}/matchups: {enemy hero id: [games, wins of hero_id]}."""
        data = self._reference_get(f"/heroes/{int(hero_id)}/matchups", list)
        if not isinstance(data, list):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for matchups.")
        result: dict[str, list[int]] = {}
        for row in data:
            try:
                result[str(int(row["hero_id"]))] = [int(row["games_played"]), int(row["wins"])]
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def pro_skill_orders(self, hero_id: int) -> dict[str, Any]:
        """How pro players levelled the hero lately: {"orders": [[ability name, …]],
        "names": {ability name: in-game name}, "ids": {ability id: name},
        "talents": {talent name: hero level of its row}}
        from the `ability_upgrades_arr` of up to skill_build.MAX_GAMES recent pro
        matches (/heroes/{id}/matches, then /matches/{id}; unparsed ones skipped)."""
        from app.dota_constants import hero_npc_name
        from app.skill_build import MAX_GAMES, MAX_TRIES, TALENT_LEVELS, talent_label, upgrade_names

        hero = int(hero_id)
        ids = self._get("/constants/ability_ids")
        recent = self._get(f"/heroes/{hero}/matches")
        if not isinstance(ids, dict) or not isinstance(recent, list):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for pro matches.")
        orders: list[list[str]] = []
        used: set[str] = set()
        for row in recent[:MAX_TRIES]:
            if len(orders) >= MAX_GAMES:
                break
            match_id = row.get("match_id") if isinstance(row, dict) else None
            if not isinstance(match_id, int):
                continue
            try:
                match = self.match(match_id)
            except OpenDotaError:
                continue
            for player in match.get("players") or []:
                if isinstance(player, dict) and player.get("hero_id") == hero:
                    upgrades = player.get("ability_upgrades_arr")
                    names = upgrade_names(upgrades, ids)
                    if names:
                        orders.append(names)
                        used.update(str(i) for i in upgrades if str(i) in ids)
                    break
        # In-game names ("Presence of the Dark Lord", not nevermore_dark_lord),
        # only for the abilities of these games (the constants are 1.3 MB).
        names: dict[str, str] = {}
        talents: dict[str, int] = {}
        if orders:
            # Names and talent rows are extras: the order stands without them.
            constants = heroes = None
            with contextlib.suppress(OpenDotaError):
                constants = self._get("/constants/abilities")
            with contextlib.suppress(OpenDotaError):
                # The hero's talents with their row (level 1-4 → hero level 10/15/20/25).
                heroes = self._get("/constants/hero_abilities")
            hero_entry = heroes.get(hero_npc_name(hero)) if isinstance(heroes, dict) else None
            for talent in (hero_entry or {}).get("talents") or []:
                row = talent.get("level") if isinstance(talent, dict) else None
                if not isinstance(row, int):
                    continue
                if 1 <= row <= len(TALENT_LEVELS):  # the row (what OpenDota sends now)
                    talents[str(talent.get("name"))] = TALENT_LEVELS[row - 1]
                elif row in TALENT_LEVELS:  # or the hero level itself
                    talents[str(talent.get("name"))] = row
            if isinstance(constants, dict):
                for name in {n for order in orders for n in order}:
                    entry = constants.get(name)
                    label = entry.get("dname") if isinstance(entry, dict) else None
                    if not isinstance(label, str) or not label:
                        continue
                    if not name.startswith("special_bonus_"):
                        names[name] = label
                    elif name in talents and talent_label(label):
                        names[name] = talent_label(label)
        # The hero's ability ids, so a review can read the player's own upgrades.
        return {
            "orders": orders,
            "names": names,
            "ids": {i: ids[i] for i in sorted(used)},
            "talents": talents,
        }

    def hero_stats(self) -> list[dict[str, Any]]:
        """/heroStats: picks and wins per rank bracket 1 (Herald) .. 8 (Immortal)."""
        data = self._reference_get("/heroStats", list)
        if not isinstance(data, list):
            raise OpenDotaError("bad_response", "Unexpected OpenDota response for hero stats.")
        rows = []
        for hero in data:
            if not isinstance(hero, dict) or hero.get("id") is None:
                continue
            rows.append(
                {
                    "hero_id": int(hero["id"]),
                    "roles": [str(r) for r in hero.get("roles") or [] if isinstance(r, str)],
                    "brackets": {
                        str(b): [int(hero.get(f"{b}_pick") or 0), int(hero.get(f"{b}_win") or 0)]
                        for b in range(1, 9)
                    },
                }
            )
        return rows

    # --- transport ------------------------------------------------------------

    def _masked(self, error: Exception) -> str:
        # requests puts the full URL (with ?api_key=…) into its messages.
        return str(error).replace(self.api_key, "[key]") if self.api_key else str(error)

    def _get(self, path: str, params: list[tuple[str, Any]] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _reference_get(
        self,
        path: str,
        expect: type,
        params: list[tuple[str, Any]] | None = None,
    ) -> Any:
        """Public reference data: Wardly's shared cache first, then OpenDota.

        The cache request carries only the path and the hero number: never the
        player's API key, account or anything else. A fresh body is used as is;
        a stale one only if OpenDota fails too. Player and match endpoints do
        not come through here.
        """
        cached = self._cache_read(path, expect, params)
        if cached is not None and cached[1]:
            return cached[0]
        try:
            return self._get(path, params=params)
        except OpenDotaError:
            if cached is not None:
                return cached[0]
            raise

    def _cache_read(
        self, path: str, expect: type, params: list[tuple[str, Any]] | None
    ) -> tuple[Any, bool] | None:
        """(body, fresh) from the shared cache, or None when it has nothing usable."""
        if not self.cache_url:
            return None
        try:
            response = self.session.request(
                "GET",
                f"{self.cache_url}{path}",
                params=list(params or []),
                timeout=CACHE_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            if response.status_code != 200:
                return None
            body = response.json()
            fetched_ms = int(response.headers.get("x-fetched-at", ""))
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            # No usable answer: bad JSON, no x-fetched-at (age unknown) or the
            # server is down. The caller asks OpenDota.
            return None
        if not isinstance(body, expect):
            return None
        return body, time.time() - fetched_ms / 1000 <= CACHE_MAX_AGE_SECONDS

    def _request(self, method: str, path: str, params: list[tuple[str, Any]] | None = None) -> Any:
        query = list(params or [])
        if self.api_key:
            query.append(("api_key", self.api_key))
        for attempt in range(TIMEOUT_RETRIES + 1):
            with self._lock:
                wait = self.min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    time.sleep(wait)
                self._last_request = time.monotonic()
            try:
                response = self.session.request(
                    method, f"{self.base_url}{path}", params=query, timeout=self.timeout
                )
                break
            except requests.Timeout as error:
                if attempt < TIMEOUT_RETRIES:
                    continue
                raise OpenDotaError(
                    "offline", f"OpenDota did not answer in time: {self._masked(error)}"
                ) from error
            except requests.RequestException as error:
                raise OpenDotaError(
                    "offline", f"OpenDota is unreachable: {self._masked(error)}"
                ) from error
        if response.status_code == 404:
            raise OpenDotaError("not_found", "OpenDota does not know this match or player.")
        if response.status_code == 429:
            raise OpenDotaError("rate_limited", "OpenDota rate limit reached; try again later.")
        if response.status_code >= 400:
            raise OpenDotaError("bad_response", f"OpenDota answered HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as error:
            raise OpenDotaError("bad_response", "OpenDota returned invalid JSON.") from error


# --- shaping ------------------------------------------------------------------


def is_radiant_slot(player_slot: Any) -> bool:
    try:
        return int(player_slot) < 128
    except (TypeError, ValueError):
        return True


def summary_from_recent(item: dict[str, Any]) -> dict[str, Any]:
    """Row of /players/{id}/matches -> match table columns."""
    radiant = is_radiant_slot(item.get("player_slot"))
    radiant_win = item.get("radiant_win")
    return {
        "match_id": item.get("match_id"),
        "start_time": item.get("start_time"),
        "duration": item.get("duration"),
        "hero_id": item.get("hero_id"),
        "hero": hero_name(item.get("hero_id")),
        "is_radiant": radiant,
        "win": None if radiant_win is None else bool(radiant_win) == radiant,
        "kills": item.get("kills"),
        "deaths": item.get("deaths"),
        "assists": item.get("assists"),
        "gpm": item.get("gold_per_min"),
        "xpm": item.get("xp_per_min"),
        "last_hits": item.get("last_hits"),
        "denies": item.get("denies"),
        "hero_damage": item.get("hero_damage"),
        "lane_role": item.get("lane_role"),
        "game_mode": item.get("game_mode"),
        "lobby_type": item.get("lobby_type"),
        "parsed": item.get("version") is not None,
    }


# Bump when trim_match keeps more: parsed matches stored by an older version are
# fetched again on the next sync (PlayerService).
TRIM_VERSION = 4  # 4: every player's first ten minutes (lane_t)


def _my_teamfights(match: dict[str, Any], index: int | None) -> list[dict[str, Any]]:
    """Where the reviewed player died in each team fight of a parsed replay:
    [{start, end, deaths_pos: {x: {y: count}}}] (cells), fights without a death skipped."""
    fights = []
    if index is None or not isinstance(match.get("teamfights"), list):
        return fights
    for fight in match["teamfights"]:
        players = fight.get("players") if isinstance(fight, dict) else None
        if not isinstance(players, list) or index >= len(players):
            continue
        mine = players[index] if isinstance(players[index], dict) else {}
        if mine.get("deaths") and isinstance(mine.get("deaths_pos"), dict) and mine["deaths_pos"]:
            fights.append(
                {
                    "start": fight.get("start"),
                    "end": fight.get("end"),
                    "deaths_pos": mine["deaths_pos"],
                }
            )
    return fights


def trim_match(match: dict[str, Any], account_id: int) -> dict[str, Any]:
    """Keep the match header, a light scoreboard and the reviewed player's logs."""
    raw_players = match.get("players")
    players = (
        [p for p in raw_players if isinstance(p, dict)] if isinstance(raw_players, list) else []
    )
    me = next((p for p in players if p.get("account_id") == int(account_id)), None)
    trimmed: dict[str, Any] = {key: match.get(key) for key in _MATCH_FIELDS}
    trimmed["parsed"] = match.get("version") is not None
    trimmed["trim_version"] = TRIM_VERSION
    trimmed["teamfights"] = _my_teamfights(
        match, next((i for i, p in enumerate(players) if p is me), None)
    )
    trimmed["players"] = []
    for player in players:
        entry = {key: player.get(key) for key in _PLAYER_FIELDS if player.get(key) is not None}
        entry["hero"] = hero_name(player.get("hero_id"))
        entry["hero_npc"] = hero_npc_name(player.get("hero_id"))
        entry["isRadiant"] = bool(
            player.get("isRadiant", is_radiant_slot(player.get("player_slot")))
        )
        # Laning numbers for everyone (rank comparison); full series only for "me".
        for key, series_key in (("lh_10", "lh_t"), ("dn_10", "dn_t"), ("gold_10", "gold_t")):
            series = player.get(series_key)
            if isinstance(series, list) and len(series) > 10:
                entry[key] = series[10]
        if player is not me:
            # The first ten minutes of everyone's lane (lane_duel.py).
            lane = lane_snapshot(player)
            if lane:
                entry["lane_t"] = lane
        if player is me:
            entry["me"] = True
            for key in _TIMELINE_FIELDS:
                if player.get(key) is not None:
                    entry[key] = player[key]
        else:
            # Needed to find when this player killed us.
            kills_log = player.get("kills_log")
            if isinstance(kills_log, list):
                entry["kills_log"] = kills_log
        trimmed["players"].append(entry)
    trimmed["found_player"] = me is not None
    return trimmed


def my_player(trimmed: dict[str, Any]) -> dict[str, Any] | None:
    return next((p for p in trimmed.get("players") or [] if p.get("me")), None)


def summary_from_match(trimmed: dict[str, Any]) -> dict[str, Any]:
    """Trimmed /matches/{id} -> match table columns for the reviewed player."""
    me = my_player(trimmed) or {}
    radiant = bool(me.get("isRadiant", True))
    radiant_win = trimmed.get("radiant_win")
    lh_t: list[Any] = me["lh_t"] if isinstance(me.get("lh_t"), list) else []
    return {
        "start_time": trimmed.get("start_time"),
        "duration": trimmed.get("duration"),
        "hero_id": me.get("hero_id"),
        "hero": me.get("hero"),
        "is_radiant": radiant,
        "win": None if radiant_win is None else bool(radiant_win) == radiant,
        "kills": me.get("kills"),
        "deaths": me.get("deaths"),
        "assists": me.get("assists"),
        "gpm": me.get("gold_per_min"),
        "xpm": me.get("xp_per_min"),
        "last_hits": me.get("last_hits"),
        "denies": me.get("denies"),
        "lh_10": lh_t[10] if len(lh_t) > 10 else None,
        "net_worth": me.get("net_worth"),
        "hero_damage": me.get("hero_damage"),
        "lane_role": me.get("lane_role"),
        "game_mode": trimmed.get("game_mode"),
        "lobby_type": trimmed.get("lobby_type"),
        "parsed": bool(trimmed.get("parsed")),
    }
