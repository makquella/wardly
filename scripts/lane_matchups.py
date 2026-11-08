"""How a core hero's lane goes against each enemy hero, from the open OpenDota
Explorer (league games with parsed lanes), written to data/heroes/lane_matchups/
(read by backend/app/lane_matchup.py, which documents the file and the thresholds):

- the hero in its usual core position (carry / mid / offlane, from its item_stats
  file), games of the last WINDOW_DAYS days with gold and last-hit series;
- the lane: the enemies who stood in the hero's physical lane and did not roam;
  the enemy core is the one with the most last hits at 10:00; the result is the
  gold difference at 10:00 against it (lane_duel.GOLD_MARGIN);
- every enemy of the lane, core or support, gets the lane counted; an opponent
  with fewer than lane_matchup.MIN_LANES lanes is left out.

    python scripts/lane_matchups.py juggernaut              # print a report
    python scripts/lane_matchups.py juggernaut --write      # data/heroes/lane_matchups/
    python scripts/lane_matchups.py --all --write           # every core hero

Read-only, no key. Public games differ from the player's own, and a small sample
is a small sample: the file says what happened, lane_matchup.classify decides
whether it is worth saying.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

EXPLORER = "https://api.opendota.com/api/explorer?sql="
USER_AGENT = "Wardly lane matchups"
STATS_DIR = ROOT / "data" / "heroes" / "item_stats"
OUT_DIR = ROOT / "data" / "heroes" / "lane_matchups"
TIMEOUT = 150
RETRIES = (5, 20, 60)
PAUSE = 2  # seconds between Explorer queries (a shared free service)
LANE_ROLE = {"carry": 1, "mid": 2, "offlane": 3}
WINDOW_DAYS = 365
SOURCE = f"OpenDota Explorer: league games with parsed lanes, last {WINDOW_DAYS} days"


def _get(url: str) -> Any:
    for pause in (*RETRIES, None):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                answer = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            if pause is None:
                raise SystemExit(f"OpenDota: {error}") from None
            time.sleep(pause)
            continue
        if isinstance(answer, dict) and answer.get("err"):
            if pause is None or "timeout" not in str(answer["err"]).lower():
                raise SystemExit(f"OpenDota Explorer: {answer['err']}")
            time.sleep(pause)
            continue
        return answer
    raise SystemExit("OpenDota: no answer")


def explorer(sql: str) -> list[dict]:
    rows = _get(EXPLORER + urllib.parse.quote(sql)).get("rows") or []
    time.sleep(PAUSE)
    return list(rows)


def _where(hero_id: int, lane_role: int, since: int) -> str:
    return (
        f"pm.hero_id={hero_id} AND pm.lane_role={lane_role} AND m.start_time > {since} "
        "AND array_length(pm.gold_t, 1) > 10 AND array_length(pm.lh_t, 1) > 10"
    )


def hero_games(hero_id: int, lane_role: int, since: int) -> list[dict]:
    return explorer(
        "SELECT pm.match_id, pm.player_slot, pm.lane, pm.is_roaming, pm.gold_t[11] AS gold "
        "FROM player_matches pm JOIN matches m USING(match_id) "
        f"WHERE {_where(hero_id, lane_role, since)}"
    )


def lane_mates(hero_id: int, lane_role: int, since: int) -> list[dict]:
    return explorer(
        "SELECT o.match_id, o.player_slot, o.hero_id, o.lane, o.is_roaming, "
        "o.gold_t[11] AS gold, o.lh_t[11] AS lh FROM player_matches o WHERE o.match_id IN "
        "(SELECT pm.match_id FROM player_matches pm JOIN matches m USING(match_id) "
        f"WHERE {_where(hero_id, lane_role, since)})"
    )


def summarize(
    hero_rows: list[dict], other_rows: list[dict], margin: int | None = None
) -> tuple[dict[str, int], dict[int, dict[str, int]]]:
    """(baseline {won, even, lost}, {enemy hero id: {lanes, won, even, lost, diff}})
    from the hero's games and everyone else's rows of those matches."""
    from app.lane_duel import GOLD_MARGIN, LANES

    margin = GOLD_MARGIN if margin is None else margin
    enemies: dict[int, list[dict]] = defaultdict(list)
    for row in other_rows:
        enemies[row["match_id"]].append(row)
    baseline = {"won": 0, "even": 0, "lost": 0}
    table: dict[int, dict[str, int]] = {}
    for game in hero_rows:
        lane, gold = game.get("lane"), game.get("gold")
        if lane not in LANES or game.get("is_roaming") or gold is None:
            continue
        radiant = game["player_slot"] < 128
        laners = [
            e
            for e in enemies.get(game["match_id"], [])
            if (e["player_slot"] < 128) != radiant
            and e.get("lane") == lane
            and not e.get("is_roaming")
            and e.get("gold") is not None
        ]
        if not laners:
            continue
        core = max(laners, key=lambda e: e.get("lh") or 0)
        diff = gold - core["gold"]
        result = "won" if diff >= margin else "lost" if diff <= -margin else "even"
        baseline[result] += 1
        for enemy in laners:
            row = table.setdefault(
                enemy["hero_id"], {"lanes": 0, "won": 0, "even": 0, "lost": 0, "diff": 0}
            )
            row["lanes"] += 1
            row[result] += 1
            row["diff"] += diff
    return baseline, table


def build_file(
    hero: str,
    hero_id: int,
    position: str,
    hero_rows: list[dict],
    other_rows: list[dict],
    generated: str | None = None,
) -> dict[str, Any]:
    """The lane_matchups file of a hero (validated), from Explorer rows."""
    from app.dota_constants import hero_name
    from app.lane_matchup import MIN_LANES, validate

    hero = hero_name(hero_id) or hero  # item_stats files spell some names lowercase
    baseline, table = summarize(hero_rows, other_rows)
    opponents = [
        {
            "hero": hero_name(enemy_id),
            "hero_id": enemy_id,
            "lanes": row["lanes"],
            "won": row["won"],
            "even": row["even"],
            "lost": row["lost"],
            "gold_diff": int(round(row["diff"] / row["lanes"])),
        }
        for enemy_id, row in table.items()
        if row["lanes"] >= MIN_LANES
    ]
    opponents.sort(key=lambda r: (-r["lanes"], r["hero"]))
    data = {
        "hero": hero,
        "hero_id": hero_id,
        "position": position,
        "lane_role": LANE_ROLE[position],
        "window_days": WINDOW_DAYS,
        "generated": generated or datetime.now(UTC).date().isoformat(),
        "source": SOURCE,
        "lanes": sum(baseline.values()),
        "baseline": baseline,
        "opponents": opponents,
    }
    return validate(data, hero)


def core_heroes() -> list[tuple[str, Path, dict[str, Any]]]:
    """[(file key, path, item_stats file)] of every core hero, by name."""
    found = []
    for path in sorted(STATS_DIR.glob("*.json")):
        stats = json.loads(path.read_text(encoding="utf-8"))
        if stats.get("position") in LANE_ROLE:
            found.append((path.stem, path, stats))
    return found


def hero_matchups(stats: dict[str, Any]) -> dict[str, Any]:
    since = int(time.time()) - WINDOW_DAYS * 86400
    role = LANE_ROLE[stats["position"]]
    mine = hero_games(stats["hero_id"], role, since)
    others = lane_mates(stats["hero_id"], role, since)
    return build_file(stats["hero"], stats["hero_id"], stats["position"], mine, others)


def report(data: dict[str, Any]) -> None:
    from app.lane_matchup import classify

    base = data["baseline"]
    total = sum(base.values()) or 1
    print(
        f"{data['hero']} ({data['position']}): {data['lanes']} lanes, "
        f"won {100 * base['won'] / total:.0f}% even {100 * base['even'] / total:.0f}% "
        f"lost {100 * base['lost'] / total:.0f}%"
    )
    for row in data["opponents"]:
        kind = classify(row, base) or "-"
        print(
            f"  {row['hero']:22} {row['lanes']:4} lanes  {row['won']:3}/{row['even']:3}/"
            f"{row['lost']:3}  diff {row['gold_diff']:6}  {kind}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("hero", nargs="?", help="e.g. juggernaut or anti_mage (the file name)")
    parser.add_argument("--all", action="store_true", help="every core hero")
    parser.add_argument("--write", action="store_true", help="write data/heroes/lane_matchups/")
    args = parser.parse_args()
    heroes = core_heroes()
    if args.hero:
        key = args.hero.lower().replace(" ", "_").replace("'", "").replace("-", "_")
        heroes = [h for h in heroes if h[0] == key]
        if not heroes:
            parser.error(f"{args.hero!r} is not a core hero with an item_stats file")
    elif not args.all:
        parser.error("name a hero or pass --all")
    failed = []
    for key, _, stats in heroes:
        try:
            data = hero_matchups(stats)
        except SystemExit as error:
            if len(heroes) == 1:
                raise
            print(f"{key}: failed ({error})", file=sys.stderr)
            failed.append(key)
            continue
        if args.write:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            path = OUT_DIR / f"{key}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(
                f"wrote {path.relative_to(ROOT)} ({data['lanes']} lanes, {len(data['opponents'])} opponents)"
            )
        else:
            report(data)
    if failed:
        print("failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
