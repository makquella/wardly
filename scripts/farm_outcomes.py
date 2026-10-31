"""farm_outcomes.py - what the recorded match did after each farm card the
current code would show (farm_map.py): an OFFLINE check, run after the replay,
that reads the future of the recording. Nothing here feeds the live decisions.

The player of the recording never saw these cards, so the words are «the
recorded player went there / did not», never «followed the card». For each
`farm` row of a `replay_recording.py --audit` file:

- went: the hero came within ARRIVE of the target within LOOK_AHEAD seconds;
- travel: the seconds that took, next to the card's estimate;
- there: on arrival, enemy lane creeps (a wave) within ARRIVE of the target,
  or neutrals within CAMP_RADIUS of it (a camp); unknown when he did not go;
- gold: farm gold in the GOLD_AFTER seconds after arrival: lane gold
  (gold_from_creep_kills) plus the rise of the total on seconds without a
  purchase, less income, hero, shared and summon gold; next to the card's
  estimate.

    python scripts/farm_outcomes.py RECORDING.jsonl.gz AUDIT.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
from pathlib import Path
from typing import Any

MAP_CENTER = 16384
ARRIVE = 700
CAMP_RADIUS = 500
LOOK_AHEAD = 60
GOLD_AFTER = 20


def _rows(path: Path) -> list[dict[str, Any]]:
    """One row per game second: position, creeps, neutrals, gold counters."""
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("k") != "gsi":
                continue
            payload = record["p"]
            clock = (payload.get("map") or {}).get("clock_time")
            if not isinstance(clock, int) or (rows and rows[-1]["clock"] == clock):
                continue
            hero, player = payload.get("hero") or {}, payload.get("player") or {}
            team = 2 if str(player.get("team_name")).lower() == "radiant" else 3
            enemy, neutral = [], []
            for unit in (payload.get("minimap") or {}).values():
                if not isinstance(unit, dict) or (
                    unit.get("xpos"),
                    unit.get("ypos"),
                ) == (0, 0):
                    continue
                point = (
                    unit.get("xpos", 0) + MAP_CENTER,
                    unit.get("ypos", 0) + MAP_CENTER,
                )
                if unit.get("image") in {"minimap_creep", "minimap_siege"} and unit.get("team") in (
                    2,
                    3,
                ):
                    if unit["team"] != team:
                        enemy.append(point)
                elif unit.get("team") == 4 and str(unit.get("unitname", "")).startswith(
                    "npc_dota_neutral_"
                ):
                    neutral.append(point)
            items = sorted(
                str(v.get("name"))
                for k, v in (payload.get("items") or {}).items()
                if isinstance(v, dict)
            )
            rows.append(
                {
                    "clock": clock,
                    "x": (hero.get("xpos") or 0) + MAP_CENTER,
                    "y": (hero.get("ypos") or 0) + MAP_CENTER,
                    "enemy": enemy,
                    "neutral": neutral,
                    "gold": (player.get("gold_reliable") or 0)
                    + (player.get("gold_unreliable") or 0),
                    "src": {
                        k: player.get(f"gold_from_{k}") or 0
                        for k in (
                            "creep_kills",
                            "hero_kills",
                            "income",
                            "shared",
                            "summon_kills",
                        )
                    },
                    "items": items,
                }
            )
    return rows


def _farm_gold(rows: list[dict[str, Any]], start: int, end: int) -> float:
    gold = 0.0
    window = [r for r in rows if start <= r["clock"] <= end]
    for before, after in zip(window, window[1:], strict=False):
        gold += max(0, after["src"]["creep_kills"] - before["src"]["creep_kills"])
        if after["items"] == before["items"]:
            other = sum(
                after["src"][k] - before["src"][k]
                for k in (
                    "creep_kills",
                    "hero_kills",
                    "income",
                    "shared",
                    "summon_kills",
                )
            )
            gold += max(0, after["gold"] - before["gold"] - other)
    return gold


def outcome(rows: list[dict[str, Any]], card: dict[str, Any]) -> dict[str, Any]:
    since, tx, ty = card["since"], card["x"], card["y"]
    arrival = next(
        (
            r
            for r in rows
            if since <= r["clock"] <= since + LOOK_AHEAD
            and math.hypot(r["x"] - tx, r["y"] - ty) <= ARRIVE
        ),
        None,
    )
    out: dict[str, Any] = {
        "since": since,
        "target": card.get("target"),
        "ended": card.get("ended"),
        "est_travel": card.get("travel_s"),
        "est_gold": card.get("gold"),
        "went": arrival is not None,
    }
    if arrival is None:
        return out
    if card.get("target") == "camp":
        there = any(math.hypot(x - tx, y - ty) <= CAMP_RADIUS for x, y in arrival["neutral"])
    else:
        there = any(math.hypot(x - tx, y - ty) <= ARRIVE + 300 for x, y in arrival["enemy"])
    out.update(
        travel=arrival["clock"] - since,
        there=there,
        gold=round(_farm_gold(rows, arrival["clock"], arrival["clock"] + GOLD_AFTER)),
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("recording", type=Path)
    parser.add_argument("audit", type=Path)
    args = parser.parse_args()
    rows = _rows(args.recording)
    cards = [
        r
        for r in (json.loads(line) for line in args.audit.read_text("utf-8").splitlines())
        if r.get("kind") == "farm"
    ]
    results = [outcome(rows, card) for card in cards]
    for r in results:
        clock = f"{r['since'] // 60}:{r['since'] % 60:02d}"
        if r["went"]:
            print(
                f"{clock} {r['target']:4} went: travel {r['travel']} s (est {r['est_travel']}), "
                f"{'target there' if r['there'] else 'target GONE'}, farm gold {r['gold']} in {GOLD_AFTER} s (est {r['est_gold']}); ended {r['ended']}"
            )
        else:
            print(
                f"{clock} {r['target']:4} did not go there within {LOOK_AHEAD} s; ended {r['ended']}"
            )
    went = [r for r in results if r["went"]]
    minutes = (rows[-1]["clock"] - 600) / 60 if rows and rows[-1]["clock"] > 600 else 0
    print(
        f"cards {len(results)} ({len(results) / (minutes / 10):.1f} per 10 min after 10:00)"
        if minutes
        else f"cards {len(results)}"
    )
    if went:
        errors = [r["travel"] / max(1, r["est_travel"]) for r in went if r["est_travel"]]
        print(
            f"went {len(went)}/{len(results)}; target there on arrival {sum(r['there'] for r in went)}/{len(went)}; "
            f"actual/estimated travel median {statistics.median(errors):.2f}"
            if errors
            else ""
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
