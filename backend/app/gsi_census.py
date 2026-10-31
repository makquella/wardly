"""
gsi_census.py - which GSI fields the game really sends, for the problem report.

The coach is built on what Valve's GSI exposes to a *player* (a spectator gets
more), and some of it was only ever seen in synthetic samples. The census
counts, over the backend's run, every field path that arrived (`hero.stunned`,
`items.slot*.can_cast`, `minimap.*.unitname`...) and how often a flag was
true, then checks the paths each coach feature reads (`FEATURES`). It keeps
field names, counts and a few game enums only — never Steam IDs, nicknames or
other values — so `GET /diagnostics` can carry it into a problem report.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.atomic_file import write_json_atomic
from app.diagnostics import record_error

MAX_PATHS = 600
MAX_DEPTH = 4
# Numbered slots collapse into one path: items.slot3.name -> items.slot*.name.
_NUMBERED = re.compile(r"^([a-z_]*?)\d+$")
# Blocks whose keys are ids, not field names (minimap o123, buildings by name).
_ID_KEYED = {"minimap", "buildings", "couriers", "wearables", "neutralitems", "draft"}
# auth carries the token; added / previously are Dota's diff of the last payload.
_SKIP = {"auth", "added", "previously"}
EMPTY_ITEMS = {"", "empty", "item_empty"}
# Item fields only exist on real items: these features are judged over the
# payloads with at least one item in slot0-8, not over every in-game payload.
ITEM_FEATURES = {"item_ready", "item_charges"}
IN_PROGRESS = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
TEAMS = {"radiant": 2, "dire": 3}
HERO_PREFIX = "npc_dota_hero_"

# What each coach feature reads; a feature works when every path of one of
# its alternatives came in most in-game payloads.
FEATURES: list[tuple[str, str, list[list[str]]]] = [
    ("hp_mana", "HP and mana", [["hero.health_percent", "hero.mana_percent"]]),
    (
        "disables",
        "Stun / hex / silence / mute flags",
        [["hero.stunned", "hero.hexed", "hero.silenced", "hero.muted"]],
    ),
    ("item_ready", "Item ready (can_cast, cooldown)", [["items.slot*.can_cast"]]),
    ("item_charges", "Item charges (Magic Wand, regen)", [["items.slot*.charges"]]),
    ("tp_slot", "TP scroll slot", [["items.teleport*.name"]]),
    (
        "abilities",
        "Ability level, cooldown, can_cast",
        [
            [
                "abilities.ability*.level",
                "abilities.ability*.cooldown",
                "abilities.ability*.can_cast",
            ]
        ],
    ),
    ("ultimate", "Ultimate flag", [["abilities.ability*.ultimate"]]),
    ("talents", "Talent fields", [["hero.talent_*"]]),
    ("position", "Hero position", [["hero.xpos", "hero.ypos"]]),
    ("buyback", "Buyback cost and cooldown", [["hero.buyback_cost", "hero.buyback_cooldown"]]),
    ("farm", "Last hits and gold per minute", [["player.last_hits", "player.gpm"]]),
    ("kill_streak", "Kill streak", [["player.kill_streak"]]),
    ("score", "Team kill score", [["map.radiant_score", "map.dire_score"]]),
    ("team", "Player's team", [["player.team_name"]]),
    ("events", "Game events (Roshan, Aegis)", [["events[].event_type"]]),
    ("minimap", "Minimap units", [["minimap.*.unitname", "minimap.*.team"]]),
    ("minimap_positions", "Minimap unit positions", [["minimap.*.xpos", "minimap.*.ypos"]]),
    ("aegis", "Aegis on the hero", [["hero.aegis"], ["items.slot*.name"]]),
]
# Share of in-game payloads a path must come in to count as sent.
PRESENT_SHARE = 0.5
# The census is saved next to the match store (at most every SAVE_EVERY seconds
# while a match sends data, and once when it stops), so a problem report sent
# after the app was restarted still shows what the last match sent.
CENSUS_FILE = "gsi_census.json"
SAVE_EVERY = 30.0


def _part(block: str, depth: int, key: str) -> str:
    if depth == 1 and block in _ID_KEYED:
        return "*"
    match = _NUMBERED.match(key)
    if match and match.group(1):
        return f"{match.group(1)}*"
    return key


class GsiCensus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._save_token = 0
        self.reset()

    def reset(self) -> None:
        self.payloads = 0
        self.in_game = 0
        self.paths: Counter[str] = Counter()
        self.true_flags: Counter[str] = Counter()
        self.event_types: Counter[str] = Counter()
        self.game_states: Counter[str] = Counter()
        self.minimap_payloads = 0
        self.minimap_units_max = 0
        self.own_heroes_max = 0
        self.enemy_hero_payloads = 0
        # Payloads whose minimap had lane creeps / neutral creeps (farm_map.py
        # needs them; a feed without them leaves the farm tip off).
        self.lane_creep_payloads = 0
        self.neutral_payloads = 0
        self.enemy_heroes: set[str] = set()
        self.match_id: str | None = None
        self.matches = 0
        self.item_payloads = 0
        self.own_hero_names_max = 0
        self.hero_images: Counter[str] = Counter()
        self._saved_in_game = 0
        self._saved_at = 0.0
        self._last_in_game: bool | None = None
        self._save_token += 1
        self._pending_save: int | None = None
        self._last_attempt_at: float | None = None
        self._save_failures = 0
        self._last_save_error: str | None = None
        # Values of a Bottle's contains_rune (a game enum: which rune names come).
        self.bottle_runes: Counter[str] = Counter()

    def observe(self, payload: Any) -> None:
        """Count one GSI payload; never raises."""
        if not isinstance(payload, dict):
            return
        try:
            with self._lock:
                self._observe(payload)
        except Exception:  # noqa: BLE001 - the census must never break /gsi
            pass

    def _observe(self, payload: dict[str, Any]) -> None:
        self.payloads += 1
        map_block = payload.get("map") if isinstance(payload.get("map"), dict) else {}
        state = map_block.get("game_state")
        if isinstance(state, str) and len(self.game_states) < 20:
            self.game_states[state[:60]] += 1
        in_game = state == IN_PROGRESS
        self._last_in_game = in_game
        if not in_game:
            return
        self.in_game += 1
        match_id = str(map_block.get("matchid") or "")[:24]
        if match_id != self.match_id:
            # The enemies are those of the current match, not of every match since start.
            self.match_id = match_id
            self.matches += 1
            self.enemy_heroes = set()
        seen: set[str] = set()
        for block, value in payload.items():
            if block in _SKIP or not isinstance(block, str):
                continue
            if block == "items" and isinstance(value, dict):
                value = {
                    slot: item
                    for slot, item in value.items()
                    if not (isinstance(item, dict) and item.get("name") in EMPTY_ITEMS)
                }
                if any(str(slot).startswith("slot") for slot in value):
                    self.item_payloads += 1
                for item in value.values():
                    rune = item.get("contains_rune") if isinstance(item, dict) else None
                    if isinstance(rune, str) and (
                        rune in self.bottle_runes or len(self.bottle_runes) < 20
                    ):
                        self.bottle_runes[rune[:30]] += 1
            self._walk(block, block, value, 0, seen)
        for path in seen:
            if path in self.paths or len(self.paths) < MAX_PATHS:
                self.paths[path] += 1
        self._minimap(payload)

    def _walk(self, block: str, path: str, value: Any, depth: int, seen: set[str]) -> None:
        if isinstance(value, dict) and value and depth < MAX_DEPTH:
            for key, item in value.items():
                part = _part(block, depth + 1, str(key))
                self._walk(block, f"{path}.{part}", item, depth + 1, seen)
            return
        if isinstance(value, list) and depth < MAX_DEPTH:
            seen.add(f"{path}[]")
            for item in value[:20]:
                if isinstance(item, dict):
                    for key, sub in item.items():
                        seen.add(f"{path}[].{key}")
                        if key == "event_type" and isinstance(sub, str):
                            self.event_types[sub[:40]] += 1
            return
        seen.add(path)
        if value is True:
            self.true_flags[path] += 1

    def _minimap(self, payload: dict[str, Any]) -> None:
        minimap = payload.get("minimap")
        if not isinstance(minimap, dict):
            return
        self.minimap_payloads += 1
        self.minimap_units_max = max(self.minimap_units_max, len(minimap))
        player = payload.get("player") if isinstance(payload.get("player"), dict) else {}
        own = TEAMS.get(str(player.get("team_name") or "").lower())
        own_heroes = 0
        own_names: set[str] = set()
        enemy = False
        creeps = neutrals = False
        for unit in minimap.values():
            if not isinstance(unit, dict):
                continue
            name = unit.get("unitname")
            if unit.get("image") in ("minimap_creep", "minimap_siege") and isinstance(name, str):
                creeps = creeps or unit.get("team") in TEAMS.values()
                neutrals = neutrals or unit.get("team") == 4
            if not isinstance(name, str) or not name.startswith(HERO_PREFIX):
                continue
            image = unit.get("image")
            if isinstance(image, str) and (image in self.hero_images or len(self.hero_images) < 20):
                self.hero_images[image[:40]] += 1
            if unit.get("team") == own:
                own_heroes += 1
                own_names.add(name)
            elif own is not None and unit.get("team") in TEAMS.values():
                enemy = True
                if len(self.enemy_heroes) < 10:
                    self.enemy_heroes.add(name[len(HERO_PREFIX) :][:40])
        self.own_heroes_max = max(self.own_heroes_max, own_heroes)
        self.own_hero_names_max = max(self.own_hero_names_max, len(own_names))
        if enemy:
            self.enemy_hero_payloads += 1
        self.lane_creep_payloads += creeps
        self.neutral_payloads += neutrals

    def save_due(self, path: Path, *, now: float | None = None) -> bool:
        """Acknowledge only a successful replacement; failed saves retry after 5s."""
        now = time.monotonic() if now is None else now
        with self._lock:
            fresh = self.in_game > self._saved_in_game
            ended = bool(self.game_states) and self._last_in_game is False
            if not fresh or self._pending_save is not None:
                return False
            if now - self._saved_at < SAVE_EVERY and not ended:
                return False
            if (
                self._last_save_error
                and self._last_attempt_at is not None
                and now - self._last_attempt_at < 5
            ):
                return False
            self._save_token += 1
            token = self._save_token
            self._pending_save = token
            self._last_attempt_at = now
            observed = self.in_game
            data = self._summary_locked()
            data.pop("persistence", None)
        data["saved_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        failure = None
        try:
            write_json_atomic(path, data)
        except (OSError, TypeError, ValueError) as error:
            failure = type(error).__name__
            record_error("gsi-census-save", error, with_trace=False)
        with self._lock:
            if self._pending_save == token:
                self._pending_save = None
                if failure is None:
                    self._saved_in_game = observed
                    self._saved_at = now
                    self._last_save_error = None
                else:
                    self._save_failures += 1
                    self._last_save_error = failure
        return failure is None

    def _share(self, path: str, base: int | None = None) -> float:
        base = self.in_game if base is None else base
        if not base:
            return 0.0
        return self.paths.get(path, 0) / base

    def features(self) -> list[dict[str, Any]]:
        rows = []
        for key, label, alternatives in FEATURES:
            base = self.item_payloads if key in ITEM_FEATURES else self.in_game
            best = max(
                (min(self._share(p, base) for p in paths) for paths in alternatives), default=0.0
            )
            status = "ok" if best >= PRESENT_SHARE else ("rare" if best > 0 else "missing")
            if not base:
                status = "no_data"  # no in-game payload, or no item to read yet
            rows.append({"key": key, "label": label, "status": status, "share": round(best, 2)})
        return rows

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return self._summary_locked()

    def _summary_locked(self) -> dict[str, Any]:
        flags = {
            path: count
            for path, count in self.true_flags.items()
            if path.startswith("hero.") and count
        }
        return {
            "persistence": {
                "acknowledged_in_game": self._saved_in_game,
                "pending": self._pending_save is not None,
                "failures": self._save_failures,
                "last_error": self._last_save_error,
            },
            "payloads": self.payloads,
            "in_game_payloads": self.in_game,
            "matches": self.matches,
            "payloads_with_items": self.item_payloads,
            "game_states": dict(self.game_states),
            "top_level": sorted({p.split(".", 1)[0].split("[", 1)[0] for p in self.paths}),
            "features": self.features(),
            "hero_flags_true": dict(sorted(flags.items())),
            "event_types": dict(self.event_types),
            "bottle_runes": dict(self.bottle_runes),
            "minimap": {
                "payloads": self.minimap_payloads,
                "units_max": self.minimap_units_max,
                "own_heroes_max": self.own_heroes_max,
                "own_hero_names_max": self.own_hero_names_max,
                "hero_images": dict(self.hero_images),
                "payloads_with_enemy_heroes": self.enemy_hero_payloads,
                "payloads_with_lane_creeps": self.lane_creep_payloads,
                "payloads_with_neutrals": self.neutral_payloads,
                "enemy_heroes_seen": sorted(self.enemy_heroes),
            },
            "paths": dict(sorted(self.paths.items())),
        }


def load_previous(path: Path) -> dict[str, Any] | None:
    """The census saved by an earlier run (None: none or unreadable)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


GSI_CENSUS = GsiCensus()
