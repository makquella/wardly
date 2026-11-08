"""
lane_matchup.py - how a hero's lane usually goes against a given enemy, from
public games (data/heroes/lane_matchups, written by scripts/lane_matchups.py).

The player's own past lanes (lane_duel.lane_records) are few for most players;
this is the same question asked of league games with parsed lanes (OpenDota
Explorer): the hero in its usual core position (carry / mid / offlane), the
enemies who stood in its physical lane, and the lane's result by the gold
difference at 10:00 against the enemy core of that lane (lane_duel.GOLD_MARGIN,
the rule of the review's «Лінія» card). Every enemy hero of the lane, core or
support, gets the lane counted.

One file per hero, for one position:

    {"hero", "hero_id", "position" (carry | mid | offlane), "lane_role",
     "window_days", "generated" (YYYY-MM-DD), "source", "lanes",
     "baseline": {"won", "even", "lost"} (all the hero's lanes with an enemy core),
     "opponents": [{"hero", "hero_id", "lanes", "won", "even", "lost",
                    "gold_diff" (average at 10:00, the hero minus the enemy core)}]}

A matchup is called only with MIN_LANES+ lanes and a share of lost (won) lanes
KIND_GAP above the hero's own baseline, with more lost than won (or the other
way): «hard» / «easy». Anything else is not known and says nothing. The data
is about the hero in a position: played elsewhere (a mid Juggernaut) it does
not apply.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

LANE_MATCHUPS_DIR = DATA_DIR / "heroes" / "lane_matchups"
POSITIONS = ("carry", "mid", "offlane")
RESULTS = ("won", "even", "lost")
# A matchup needs this many lanes before it is called hard or easy.
MIN_LANES = 15
# ... and a share of lost (won) lanes this far above the hero's own baseline.
KIND_GAP = 0.12


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate(data: Any, name: str = "lane matchups") -> dict[str, Any]:
    """The file as loaded, or ValueError naming what is wrong."""
    if not isinstance(data, dict):
        raise ValueError(f"{name}: not an object")
    for key in ("hero", "source", "generated"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"{name}: {key} must be a non-empty string")
    if data.get("position") not in POSITIONS:
        raise ValueError(f"{name}: position must be one of {', '.join(POSITIONS)}")
    for key in ("hero_id", "lanes", "window_days"):
        if not _count(data.get(key)):
            raise ValueError(f"{name}: {key} must be a non-negative integer")
    baseline = data.get("baseline")
    if not isinstance(baseline, dict) or not all(_count(baseline.get(k)) for k in RESULTS):
        raise ValueError(f"{name}: baseline needs won, even and lost counts")
    opponents = data.get("opponents")
    if not isinstance(opponents, list):
        raise ValueError(f"{name}: opponents must be a list")
    seen: set[int] = set()
    for row in opponents:
        if not isinstance(row, dict) or not isinstance(row.get("hero"), str):
            raise ValueError(f"{name}: an opponent needs a hero name")
        counts = [row.get(k) for k in (*RESULTS, "lanes", "hero_id")]
        if not all(_count(v) for v in counts):
            raise ValueError(f"{name}: {row.get('hero')}: counts must be non-negative integers")
        if row["won"] + row["even"] + row["lost"] != row["lanes"]:
            raise ValueError(f"{name}: {row['hero']}: won + even + lost must equal lanes")
        if row["hero_id"] in seen:
            raise ValueError(f"{name}: {row['hero']} is listed twice")
        seen.add(row["hero_id"])
        diff = row.get("gold_diff")
        if diff is not None and (not isinstance(diff, int) or isinstance(diff, bool)):
            raise ValueError(f"{name}: {row['hero']}: gold_diff must be an integer or null")
    return data


@lru_cache(maxsize=1)
def load_matchups(directory: Path = LANE_MATCHUPS_DIR) -> dict[int, dict[str, Any]]:
    """{hero id: file} for every file; a broken file raises (tests and CI load
    them all). No directory → nothing is known."""
    files: dict[int, dict[str, Any]] = {}
    if not directory.is_dir():
        return files
    for path in sorted(directory.glob("*.json")):
        data = validate(json.loads(path.read_text(encoding="utf-8")), path.name)
        if data["hero_id"] in files:
            raise ValueError(f"{path.name}: a second file for {data['hero']}")
        files[data["hero_id"]] = data
    return files


def classify(row: dict[str, Any], baseline: dict[str, Any]) -> str | None:
    """«hard», «easy» or None (too few lanes, or no clear difference)."""
    lanes = row.get("lanes") or 0
    total = sum(baseline.get(k) or 0 for k in RESULTS)
    if lanes < MIN_LANES or total <= 0:
        return None
    lost, won = row["lost"] / lanes, row["won"] / lanes
    if lost >= baseline["lost"] / total + KIND_GAP and row["lost"] > row["won"]:
        return "hard"
    if won >= baseline["won"] / total + KIND_GAP and row["won"] > row["lost"]:
        return "easy"
    return None


def _hero_id(value: Any) -> int | None:
    from app.dota_constants import hero_id_from_any

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return hero_id_from_any(value)


def matchup(
    hero: Any,
    position: str | None,
    enemy: Any,
    files: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """{hero (the enemy), hero_id, lanes, won, even, lost, gold_diff, kind,
    baseline_lost, baseline_won (shares, 0..1), source: "public"} for `hero`
    played in `position` against `enemy`; None when the hero has no file for
    that position or the enemy no row (kind None: a row without a clear call)."""
    files = load_matchups() if files is None else files
    hero_id, enemy_id = _hero_id(hero), _hero_id(enemy)
    data = files.get(hero_id) if hero_id is not None else None
    if data is None or enemy_id is None or position != data["position"]:
        return None
    row = next((r for r in data["opponents"] if r["hero_id"] == enemy_id), None)
    if row is None:
        return None
    baseline = data["baseline"]
    total = sum(baseline[k] for k in RESULTS)
    return {
        "hero": row["hero"],
        "hero_id": enemy_id,
        "lanes": row["lanes"],
        "won": row["won"],
        "even": row["even"],
        "lost": row["lost"],
        "gold_diff": row.get("gold_diff"),
        "kind": classify(row, baseline),
        "baseline_lost": round(baseline["lost"] / total, 3) if total else None,
        "baseline_won": round(baseline["won"] / total, 3) if total else None,
        "source": "public",
    }


def lane_matchup_for(
    hero: Any,
    position: str | None,
    opponents: list[str],
    files: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The lane opponent to name: a hard one first (the highest share of lost
    lanes), else an easy one (the highest share won); None when no opponent
    has a clear call. The shape of lane_duel.lane_record_for (hero, kind, won,
    even, lost, games) plus `source: "public"` and `gold_diff`."""
    rows = [matchup(hero, position, enemy, files) for enemy in opponents]
    called = [row for row in rows if row and row["kind"] in ("hard", "easy")]
    if not called:
        return None
    hard = [row for row in called if row["kind"] == "hard"]
    if hard:
        best = max(hard, key=lambda row: row["lost"] / row["lanes"])
    else:
        best = max(called, key=lambda row: row["won"] / row["lanes"])
    return {
        "hero": best["hero"],
        "kind": best["kind"],
        "won": best["won"],
        "even": best["even"],
        "lost": best["lost"],
        "games": best["lanes"],
        "gold_diff": best["gold_diff"],
        "source": "public",
    }
