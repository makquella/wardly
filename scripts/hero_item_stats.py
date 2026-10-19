"""High-rank numbers for hero item plans (docs/HERO_ITEM_PLANS.md), from the open
OpenDota Explorer (league games with parsed gold timelines and purchase logs),
for a hero in its usual position:

- the win rate by the hero's gold at 20, 25 and 30 minutes and the gold where it
  first reaches the hero's tempo target (the plan's tempo curve; net worth is
  ~0.96 of that gold): 85%, else 80% or 75% for a hero who never wins 85% of
  his farmed games at two of those minutes (--win fixes one);
- the item order in all won games (the usual build) and in those over the
  20-minute line (the tempo build);
- the skill build: the order the basic abilities are maxed, the first point and
  each talent row's picks, with win rates;
- for every enemy group (hero_items.groups, and 3+ magic damage heroes) every
  item bought there: its share against the group and elsewhere, the lift, and
  the win rate with and without it; `candidates` are the items bought at least
  CANDIDATE_LIFT times as often against the group (a plan rule to consider).

    python scripts/hero_item_stats.py terrorblade              # print a report
    python scripts/hero_item_stats.py terrorblade --write      # data/heroes/item_stats/
    python scripts/hero_item_stats.py --all --write            # every supported hero
    python scripts/hero_item_stats.py terrorblade --draft      # a plan skeleton from the file

Read-only, no key. A hero with fewer than --min-games games in the patch is read
from the previous patch on too. Small samples and «a bought item means a farmed
hero» apply: the numbers check a plan, they do not write it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

EXPLORER = "https://api.opendota.com/api/explorer?sql="
CONSTANTS = "https://api.opendota.com/api/constants/"
PATCHES = "https://api.opendota.com/api/constants/patch"
USER_AGENT = "Wardly hero item stats"
OUT_DIR = ROOT / "data" / "heroes" / "item_stats"
NET_WORTH_SHARE = 0.96  # final net worth / gold earned, Terrorblade 7.41 games
TIMEOUT = 150
RETRIES = (5, 20, 60)
PAUSE = 2  # seconds between Explorer queries (a shared free service)
# OpenDota lane_role of a hero's usual position; supports are not filtered.
LANE_ROLE = {"carry": 1, "mid": 2, "offlane": 3}
MIN_LINE_GAMES = 10
BUILD_SHARE = 0.2
CANDIDATE_LIFT = 2.0
CANDIDATE_MIN_GAMES = 20
CANDIDATE_MIN_SHARE = 0.15
MAGIC_LINEUP = 3
# A counter is a real item, not a part of one or a consumable.
CANDIDATE_MIN_COST = 1500


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


_CONSTANTS: dict[str, Any] = {}


def constants(name: str) -> dict:
    if name not in _CONSTANTS:
        _CONSTANTS[name] = dict(_get(CONSTANTS + name))
    return _CONSTANTS[name]


def patch_starts() -> list[tuple[str, int]]:
    rows = _get(PATCHES)
    return [
        (r["name"], int(datetime.fromisoformat(r["date"].replace("Z", "+00:00")).timestamp()))
        for r in rows
    ]


def rate(group: list[dict]) -> float | None:
    return round(100 * sum(g["win"] for g in group) / len(group), 1) if group else None


def _filter(hero_id: int, since: int, lane: int | None) -> str:
    where = f"pm.hero_id={hero_id} AND m.start_time > {since}"
    return where + (f" AND pm.lane_role={lane}" if lane else "")


def games(hero_id: int, since: int, lane: int | None) -> list[dict]:
    rows = explorer(
        "SELECT pm.match_id, pm.player_slot, m.radiant_win, pm.gold_t[21] AS g20, "
        "pm.gold_t[26] AS g25, pm.gold_t[31] AS g30, pm.purchase_log, "
        "pm.ability_upgrades_arr AS ups FROM player_matches pm JOIN matches m USING(match_id) "
        f"WHERE {_filter(hero_id, since, lane)} AND array_length(pm.gold_t, 1) > 20"
    )
    for row in rows:
        row["win"] = row["radiant_win"] == (row["player_slot"] < 128)
    return rows


def lineups(hero_id: int, since: int, lane: int | None, rows: list[dict]) -> dict[int, set[str]]:
    from app.dota_constants import hero_name

    side = {r["match_id"]: r["player_slot"] < 128 for r in rows}
    enemies: dict[int, set[str]] = defaultdict(set)
    for r in explorer(
        "SELECT o.match_id, o.player_slot, o.hero_id FROM player_matches o WHERE o.match_id IN "
        "(SELECT pm.match_id FROM player_matches pm JOIN matches m USING(match_id) "
        f"WHERE {_filter(hero_id, since, lane)})"
    ):
        if r["match_id"] in side and (r["player_slot"] < 128) != side[r["match_id"]]:
            enemies[r["match_id"]].add(hero_name(r["hero_id"]))
    return enemies


def built_items() -> set[str]:
    items = constants("items")
    return {k for k, v in items.items() if isinstance(v, dict) and v.get("components")} | {
        "aghanims_shard"
    }


def bought(game: dict, built: set[str]) -> dict[str, float]:
    """{item: first minute} of the assembled items the game bought."""
    first: dict[str, float] = {}
    for p in game.get("purchase_log") or []:
        key = p.get("key")
        if key in built and key not in first:
            first[key] = p.get("time", 0) / 60
    return first


def order(group: list[dict], built: set[str]) -> list[dict]:
    """Items bought in BUILD_SHARE+ of `group`, by median minute."""
    share: Counter[str] = Counter()
    minutes: dict[str, list[float]] = defaultdict(list)
    for game in group:
        for key, minute in bought(game, built).items():
            share[key] += 1
            minutes[key].append(minute)
    rows = [
        {
            "item": key,
            "share": round(count / len(group), 3),
            "minute": round(statistics.median(minutes[key]), 1),
        }
        for key, count in share.items()
        if group and count / len(group) >= BUILD_SHARE
    ]
    return sorted(rows, key=lambda r: r["minute"])


# The tempo target per hero: the first of these win rates whose line holds at
# MIN_LINE_POINTS of the three minutes (Luna never reaches 85%).
WIN_TARGETS = (85.0, 80.0, 75.0)
MIN_LINE_POINTS = 2


def tempo_target(rows: list[dict], win: float | None) -> tuple[float, dict[str, Any]]:
    """(win target, line): `win` when given, else the first of WIN_TARGETS
    with a line at MIN_LINE_POINTS minutes (the last one tried otherwise)."""
    target, line = WIN_TARGETS[-1], {}
    for target in (win,) if win else WIN_TARGETS:
        line = tempo_line(rows, target)
        if len(line) >= MIN_LINE_POINTS:
            break
    return target, line


def tempo_line(rows: list[dict], win: float) -> dict[str, Any]:
    line: dict[str, Any] = {}
    for minute, key in ((20, "g20"), (25, "g25"), (30, "g30")):
        known = [r for r in rows if r.get(key)]
        for gold in range(6000, 45001, 500):
            over = [r for r in known if r[key] >= gold]
            if len(over) < MIN_LINE_GAMES:
                break
            if 100 * sum(r["win"] for r in over) / len(over) >= win:
                line[str(minute)] = {
                    "gold": gold,
                    "net_worth": int(round(gold * NET_WORTH_SHARE, -2)),
                    "games": len(over),
                    "win": rate(over),
                }
                break
    return line


def skills(rows: list[dict], npc: str) -> dict[str, Any]:
    ids = constants("ability_ids")
    abilities = constants("abilities")
    hero = constants("hero_abilities").get(npc) or {}
    tiers = {t["name"]: (10, 15, 20, 25)[t["level"] - 1] for t in hero.get("talents") or []}
    orders: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    openings: dict[str, list[dict]] = defaultdict(list)
    talents: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    counted = 0
    for game in rows:
        names = [n for n in (ids.get(str(a)) for a in game.get("ups") or []) if n]
        if not names:
            continue
        counted += 1
        counts: Counter[str] = Counter()
        maxed = []
        for name in names:
            if name.startswith("special_bonus"):
                continue
            counts[name] += 1
            if counts[name] == 4:
                maxed.append(name)
        orders[tuple(maxed)].append(game)
        first = next((n for n in names if not n.startswith("special_bonus")), None)
        if first:
            openings[first].append(game)
        for level in (10, 15, 20, 25):
            talent = next((n for n in names if tiers.get(n) == level), None)
            if talent:
                talents[level][talent].append(game)

    def label(name: str) -> str:
        from app.skill_build import talent_label

        return talent_label(str((abilities.get(name) or {}).get("dname") or name))

    return {
        "games": counted,
        "orders": [
            {"order": list(o), "games": len(g), "win": rate(g)}
            for o, g in sorted(orders.items(), key=lambda kv: -len(kv[1]))[:5]
        ],
        "openings": [
            {"name": n, "games": len(g), "win": rate(g)}
            for n, g in sorted(openings.items(), key=lambda kv: -len(kv[1]))[:4]
        ],
        "talents": {
            str(level): [
                {
                    "name": n,
                    "label": label(n),
                    "picked": len(g),
                    "games": sum(len(v) for v in picks.values()),
                    "win": rate(g),
                }
                for n, g in sorted(picks.items(), key=lambda kv: -len(kv[1]))
            ]
            for level, picks in sorted(talents.items())
        },
    }


def counters(
    rows: list[dict], lineup: dict[int, set[str]], built: set[str]
) -> tuple[dict[str, Any], list[dict]]:
    from app.draft_analysis import MAGIC_DAMAGE
    from app.hero_items import groups

    sets = {name: set(heroes) for name, heroes in groups().items()}
    tests = {name: (lambda e, h=heroes: bool(e & h)) for name, heroes in sets.items()}
    tests["magic_lineup"] = lambda e: len(e & MAGIC_DAMAGE) >= MAGIC_LINEUP
    purchases = {r["match_id"]: bought(r, built) for r in rows}
    table: dict[str, Any] = {}
    candidates: list[dict] = []
    for name, test in tests.items():
        inside = [r for r in rows if test(lineup[r["match_id"]])]
        outside = [r for r in rows if not test(lineup[r["match_id"]])]
        if not inside:
            continue
        items = []
        keys = {k for r in inside for k in purchases[r["match_id"]]}
        for key in keys:
            yes = [r for r in inside if key in purchases[r["match_id"]]]
            share = len(yes) / len(inside)
            elsewhere = sum(key in purchases[r["match_id"]] for r in outside) / max(1, len(outside))
            if share < 0.1:
                continue
            row = {
                "item": key,
                "share": round(share, 3),
                "elsewhere": round(elsewhere, 3),
                "lift": round(share / elsewhere, 2) if elsewhere else None,
                "win_with": rate(yes),
                "win_without": rate([r for r in inside if key not in purchases[r["match_id"]]]),
            }
            items.append(row)
            lift = row["lift"]
            if (
                len(inside) >= CANDIDATE_MIN_GAMES
                and share >= CANDIDATE_MIN_SHARE
                and (lift is None or lift >= CANDIDATE_LIFT)
            ):
                candidates.append({"group": name, "games": len(inside), **row})
        table[name] = {
            "games": len(inside),
            "win": rate(inside),
            "items": sorted(items, key=lambda r: -(r["lift"] or 99))[:12],
        }
    items = constants("items")

    def cost(key: str) -> int:
        return int((items.get(key) or {}).get("cost") or 0)

    def part_of_another(row: dict) -> bool:
        return any(
            row["item"] in ((items.get(other["item"]) or {}).get("components") or [])
            for other in candidates
            if other["group"] == row["group"] and other is not row
        )

    candidates = [
        c for c in candidates if cost(c["item"]) >= CANDIDATE_MIN_COST and not part_of_another(c)
    ]
    candidates.sort(key=lambda r: (-(r["lift"] or 99), -r["share"]))
    return table, candidates


def hero_stats(
    hero: str, since_name: str | None, min_games: int, win: float | None = None
) -> dict[str, Any]:
    from app.dota_constants import hero_id_from_name, hero_npc_name
    from app.hero_profiles import get_hero_position

    hero_id = hero_id_from_name(hero)
    if hero_id is None:
        raise SystemExit(f"unknown hero {hero!r}")
    position = get_hero_position(hero)
    lane = LANE_ROLE.get(position or "")
    patches = patch_starts()
    names = [n for n, _ in patches]
    index = names.index(since_name) if since_name in names else len(patches) - 1
    since_label, since = patches[index]
    rows = games(hero_id, since, lane)
    if len(rows) < min_games and index > 0:
        since_label, since = patches[index - 1]
        rows = games(hero_id, since, lane)
    built = built_items()
    won = [r for r in rows if r["win"]]
    win, line = tempo_target(rows, win)
    # The tempo build: the won games over the earliest line found.
    first = min(line, key=int) if line else None
    rich = [r for r in won if first and (r.get(f"g{first}") or 0) >= line[first]["gold"]]
    table, candidates = counters(rows, lineups(hero_id, since, lane, rows), built)
    return {
        "hero": hero,
        "hero_id": hero_id,
        "position": position,
        "lane_role": lane,
        "since_patch": since_label,
        "generated": datetime.now(UTC).date().isoformat(),
        "source": "OpenDota Explorer: league games with parsed gold timelines",
        "games": len(rows),
        "win": rate(rows),
        "tempo_line": line,
        "tempo_win_target": win,
        "usual_build": order(won, built),
        "tempo_build": order(rich, built),
        "skills": skills(rows, hero_npc_name(hero_id)),
        "counters": table,
        "candidates": candidates[:25],
    }


DRAFT_SHARE = 0.25
DRAFT_MIN_COST = 1000
# A part bought this many minutes before its listed upgrade is its own step
# (Slark's Diffusal Blade ~12 min, the Disperser ~36), not just the recipe.
DRAFT_PART_GAP = 6


def _listed(rows: list[dict]) -> list[dict]:
    """Build rows worth naming: real items (1000+ gold) in DRAFT_SHARE+ of the
    games, without the parts bought on the way to another listed item, as
    {item, name}."""
    items = constants("items")

    def parts(key: str, depth: int = 0) -> set[str]:
        found: set[str] = set()
        for part in (items.get(key) or {}).get("components") or []:
            if part and depth < 4:
                found |= {part, *parts(part, depth + 1)}
        return found

    keep = [
        r
        for r in rows
        if r["share"] >= DRAFT_SHARE
        and (
            int((items.get(r["item"]) or {}).get("cost") or 0) >= DRAFT_MIN_COST
            or r["item"] == "aghanims_shard"
        )
    ]
    minute = {r["item"]: r["minute"] for r in keep}
    inside = {
        part
        for r in keep
        for part in parts(r["item"])
        if part in minute and r["minute"] - minute[part] < DRAFT_PART_GAP
    }
    return [
        {"item": r["item"], "name": (items.get(r["item"]) or {}).get("dname") or r["item"]}
        for r in keep
        if r["item"] not in inside
    ]


def ability_names(keys: list[str]) -> dict[str, str]:
    """{ability key: in-game name} from the OpenDota constants, for the texts."""
    abilities = constants("abilities")
    return {
        key: str((abilities.get(key) or {}).get("dname"))
        for key in dict.fromkeys(keys)
        if (abilities.get(key) or {}).get("dname")
    }


def draft(stats: dict[str, Any]) -> dict[str, Any]:
    """A plan skeleton from a stats file: positions, sources, build, tempo and
    skills; the rules are left for the review (docs/HERO_ITEM_PLANS.md)."""
    sk = stats["skills"]
    top = sk["orders"][0] if sk["orders"] else None
    opening = sk["openings"][0] if sk["openings"] else None
    plan: dict[str, Any] = {
        "schema": 1,
        "hero": (constants("heroes").get(str(stats["hero_id"])) or {}).get("localized_name")
        or stats["hero"],
        "positions": [stats["position"]],
        "patch": stats["since_patch"],
        "checked": stats["generated"],
        "sources": {
            "games": f"{stats['games']} league games since {stats['since_patch']} "
            f"(data/heroes/item_stats), win {stats['win']}%.",
        },
        "rules": [],
        "build": _listed(stats["usual_build"]),
        "build_basis": "Assembled items bought in 25%+ of the won games, by median minute: "
        + ", ".join(
            f"{r['item']} {round(100 * r['share'])}% ({round(r['minute'])})"
            for r in stats["usual_build"]
        )
        + ".",
    }
    line = stats["tempo_line"]
    if line:
        plan["tempo"] = {
            "net_worth": [
                [int(m), row["net_worth"]]
                for m, row in sorted(line.items(), key=lambda kv: int(kv[0]))
            ],
            "items": _listed(stats["tempo_build"]),
            "basis": "Gold lines where the hero wins "
            f"{stats['tempo_win_target']}%+: "
            + ", ".join(
                f"{m}:00 {r['gold']} ({r['games']} games, {r['win']}%)" for m, r in line.items()
            )
            + "; net worth ~0.96 of that gold.",
            "reason": {"en": "", "uk": ""},
        }
    if top and opening:
        plan["skills"] = {
            "order": [n for n in top["order"]],
            "games": sk["games"],
            "first_agree": sum(
                o["games"] for o in sk["orders"] if o["order"][:1] == top["order"][:1]
            ),
            "opening": {"name": opening["name"], "agree": opening["games"]},
            "names": ability_names([*top["order"], opening["name"]]),
            "talents": {
                level: {k: picks[0][k] for k in ("name", "label", "picked", "games")}
                for level, picks in sk["talents"].items()
                if picks
            },
            "basis": f"{sk['games']} games: maxed "
            + ", ".join(
                f"{' > '.join(o['order'])} {o['games']} (win {o['win']}%)" for o in sk["orders"][:3]
            )
            + "; talents "
            + "; ".join(
                f"{lvl}: "
                + ", ".join(f"{t['label']} {t['picked']}/{t['games']} ({t['win']}%)" for t in picks)
                for lvl, picks in sk["talents"].items()
            )
            + ".",
        }
    return plan


def report(stats: dict[str, Any]) -> None:
    print(
        f"{stats['hero']} ({stats['position']}): {stats['games']} games since "
        f"{stats['since_patch']}, win {stats['win']}%"
    )
    for minute, row in stats["tempo_line"].items():
        print(
            f"  {minute}:00  {row['gold']}+ gold: {row['games']} games, win {row['win']}%"
            f"  -> net worth ~{row['net_worth']}"
        )
    for title, key in (("usual build", "usual_build"), ("tempo build", "tempo_build")):
        print(f"\n{title} (share, median minute):")
        for row in stats[key]:
            print(f"  {row['item']:22} {100 * row['share']:3.0f}%  {row['minute']:4.0f}")
    sk = stats["skills"]
    print(f"\nskill build ({sk['games']} games):")
    for row in sk["orders"]:
        print(f"  {' > '.join(row['order']) or '-'}: {row['games']} games, win {row['win']}%")
    for row in sk["openings"]:
        print(f"  first point {row['name']}: {row['games']} games, win {row['win']}%")
    for level, picks in sk["talents"].items():
        for t in picks:
            print(f"  {level}: {t['label']} — {t['picked']} of {t['games']}, win {t['win']}%")
    print("\ncandidates (group: item, share here / elsewhere, win with / without):")
    for c in stats["candidates"]:
        print(
            f"  {c['group']:18} {c['item']:20} {100 * c['share']:3.0f}% / "
            f"{100 * c['elsewhere']:3.0f}%  win {c['win_with']} / {c['win_without']}"
            f"  ({c['games']} games)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("hero", nargs="?", help="e.g. terrorblade or 'Phantom Lancer'")
    parser.add_argument("--all", action="store_true", help="every supported hero")
    parser.add_argument("--write", action="store_true", help="write data/heroes/item_stats/")
    parser.add_argument("--draft", action="store_true", help="print a plan skeleton from the file")
    parser.add_argument("--patch", default=None, help="from this patch on (default: the latest)")
    parser.add_argument("--min-games", type=int, default=300, help="else the patch before too")
    parser.add_argument(
        "--win", type=float, default=None, help="the tempo line's win %% (default: per hero)"
    )
    args = parser.parse_args()
    if args.all:
        from app.schemas import _SUPPORTED_HERO_LOOKUP

        heroes = sorted(set(_SUPPORTED_HERO_LOOKUP.values()))
    elif args.hero:
        from app.dota_constants import hero_id_from_name

        # «anti_mage» → «Anti-Mage»: the name as typed, else with spaces or hyphens.
        typed = [args.hero, args.hero.replace("_", " "), args.hero.replace("_", "-")]
        heroes = [next((h for h in typed if hero_id_from_name(h) is not None), typed[1])]
    else:
        parser.error("name a hero or pass --all")
    for hero in heroes:
        if args.draft:
            key = hero.lower().replace(" ", "_").replace("'", "").replace("-", "_")
            stats = json.loads((OUT_DIR / f"{key}.json").read_text(encoding="utf-8"))
            print(json.dumps(draft(stats), ensure_ascii=False, indent=2))
            continue
        stats = hero_stats(hero, args.patch, args.min_games, args.win)
        if args.write:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            key = stats["hero"].lower().replace(" ", "_").replace("'", "").replace("-", "_")
            path = OUT_DIR / f"{key}.json"
            path.write_text(
                json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            print(f"wrote {path.relative_to(ROOT)} ({stats['games']} games)")
        else:
            report(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
