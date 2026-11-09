"""A value-first community post from the lane matchup data (data/heroes/lane_matchups):
which lanes are hard and which are easy for the 39 core heroes, by gold at 10:00.

It is not an advertisement: the body is the data and the method, the app is named
once at the end as the author's disclosure, without a link. Every number comes from
the files and the hard/easy call is the app's own (lane_matchup.classify), so the
post says what the app would say in a draft. Nothing is posted from here.

    python -m scripts.promo.lane_post                     # English, for Reddit (r/learndota2)
    python -m scripts.promo.lane_post --lang uk           # Ukrainian, for Telegram communities
    python -m scripts.promo.lane_post --out post.md
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

POSITIONS = ("carry", "mid", "offlane")
# A hero is named in a row with at most this many hard and easy lanes.
PER_ROW = 3
# The headline lists this many of the most one-sided lanes and lane bullies.
HEADLINE = 5

TEXT = {
    "en": {
        "title": "I counted {lanes} lanes from league games: which lanes are actually hard"
        " for {heroes} cores (gold at 10:00)",
        "intro": "Laning advice is usually «X counters Y» from someone's memory. I wanted numbers,"
        " so I went through every league game with parsed lanes on OpenDota from the last"
        " {days} days and counted how each core's lane went against every hero that stood in it.",
        "how": "**How a lane is counted**",
        "method": [
            "The hero in its usual position (carry, mid or offlane); a mid Juggernaut is not"
            " counted as a carry Juggernaut.",
            "The lane is the enemies who stood in that physical lane and did not roam away;"
            " supports count too, so «Snapfire» means «Snapfire was in your lane».",
            "Won or lost by the gold difference at 10:00 against the enemy core of the lane:"
            " {margin}+ gold ahead is won, {margin}+ behind is lost, anything between is even.",
            "A lane is called hard only with at least {min_lanes} lanes, a share of lost lanes"
            " {gap} points above the hero's own usual share, more lost than won, and a"
            " one-sided 95% Wilson lower bound still above that usual share. Easy is the"
            " same with won lanes. Everything else is left out: most pairs are just even.",
        ],
        "caveats": "League games are not your pubs, the lane is not the game, and {min_lanes}"
        " lanes is still a small sample. Treat this as «expect a harder lane», not «you lose».",
        "bullies": "**Who makes lanes hard most often** (named hard for this many cores)",
        "one_sided": "**The most one-sided lanes**",
        "one_sided_row": "{hero} ({position}) vs {enemy}: lost {lost}% of {n} lanes"
        " (usually {base}%), {gold} gold at 10:00 on average",
        "table": "**All {heroes} cores**",
        "head": "| Hero | Usually lost | Hard lanes (% lost) | Easy lanes (% won) |",
        "positions": {"carry": "Carries", "mid": "Mids", "offlane": "Offlaners"},
        "none": "none clear",
        "disclosure": "Disclosure: I'm the developer of Wardly, a free open-source Dota 2 coach"
        " that warns about a hard lane like these during the draft. Not linking it here; the"
        " numbers above stand on their own. Happy to answer questions about the method or"
        " run a hero that's missing.",
        "source": "Data: OpenDota Explorer, league games with parsed lanes, last {days} days;"
        " {heroes} heroes; generated {generated}.",
    },
    "uk": {
        "title": "Які лінії справді важкі для корів: лігові матчі, золото на 10:00"
        " (ліній у вибірці: {lanes})",
        "intro": "Поради про лінію зазвичай звучать як «X контрить Y» з пам'яті. Хотілося цифр,"
        " тож я пройшов усі лігові матчі з розібраними лініями на OpenDota за останні {days}"
        " днів і порахував, як ішла лінія кожного кора проти кожного героя, що стояв на ній.",
        "how": "**Як рахується лінія**",
        "method": [
            "Герой на своїй звичній позиції (керрі, мід чи хардлайн): мідовий Juggernaut не"
            " рахується як керрі.",
            "Лінія — вороги, які стояли на ній і не пішли роумити; саппорти теж, тож"
            " «Snapfire» означає «на твоїй лінії був Snapfire».",
            "Виграна чи програна за різницею золота на 10:00 проти ворожого кора лінії:"
            " +{margin} і більше — виграна, −{margin} і більше — програна, між ними — рівна.",
            "Важкою лінія зветься лише з {min_lanes}+ лініями, часткою програних на {gap}"
            " пунктів вищою за звичну для героя, програних більше, ніж виграних, і нижньою"
            " межею Вілсона (95%, одностороння) не нижче звичної частки. Легка — так само з"
            " виграними. Решту не названо: більшість пар просто рівні.",
        ],
        "caveats": "Лігові матчі — не твої паби, лінія — не вся гра, а {min_lanes} ліній — ще"
        " мала вибірка. Читай це як «чекай важчої лінії», а не «програєш».",
        "bullies": "**Хто найчастіше робить лінію важкою** (скільком корам)",
        "one_sided": "**Найбільш однобічні лінії**",
        "one_sided_row": "{hero} ({position}) проти {enemy}: програно {lost}% з {n} ліній"
        " (зазвичай {base}%), у середньому {gold} золота на 10:00",
        "table": "**Усі кори ({heroes})**",
        "head": "| Герой | Зазвичай програє | Важкі лінії (% програних) | Легкі лінії (% виграних) |",
        "positions": {"carry": "Керрі", "mid": "Мід", "offlane": "Хардлайн"},
        "none": "чітких немає",
        "disclosure": "Чесно: я розробник Wardly — безкоштовного тренера з відкритим кодом, який"
        " попереджає про такі лінії під час драфту. Посилання тут не даю: цифри важать самі"
        " по собі. Питайте про метод або героя, якого бракує.",
        "source": "Дані: OpenDota Explorer, лігові матчі з розібраними лініями за {days} днів;"
        " героїв: {heroes}; зібрано {generated}.",
    },
}
POSITION_NAMES = {
    "en": {"carry": "carry", "mid": "mid", "offlane": "offlane"},
    "uk": {"carry": "керрі", "mid": "мід", "offlane": "хардлайн"},
}


def _backend() -> Any:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app import lane_duel, lane_matchup

    return lane_duel, lane_matchup


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def collect(files: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One row per hero file: its usual share of lost lanes and the lanes the app calls
    hard or easy, the clearest first."""
    _, lane_matchup = _backend()
    files = lane_matchup.load_matchups() if files is None else files
    rows = []
    for data in files.values():
        baseline = data["baseline"]
        total = sum(baseline[k] for k in lane_matchup.RESULTS)
        hard, easy = [], []
        for opponent in data["opponents"]:
            kind = lane_matchup.classify(opponent, baseline)
            if kind == "hard":
                hard.append(opponent)
            elif kind == "easy":
                easy.append(opponent)
        hard.sort(key=lambda o: (-o["lost"] / o["lanes"], o["hero"]))
        easy.sort(key=lambda o: (-o["won"] / o["lanes"], o["hero"]))
        rows.append(
            {
                "hero": data["hero"],
                "position": data["position"],
                "lanes": data["lanes"],
                "base_lost": _pct(baseline["lost"], total),
                "hard": hard,
                "easy": easy,
            }
        )
    rows.sort(key=lambda r: (POSITIONS.index(r["position"]), r["hero"]))
    return rows


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value).replace("-", "−")


def render(lang: str = "en", files: dict[int, dict[str, Any]] | None = None) -> str:
    """The post as Markdown (a Reddit table renders as one)."""
    lane_duel, lane_matchup = _backend()
    files = lane_matchup.load_matchups() if files is None else files
    if not files:
        raise SystemExit("no lane matchup files")
    t = TEXT[lang]
    rows = collect(files)
    first = next(iter(files.values()))
    numbers = {
        "lanes": f"{sum(d['lanes'] for d in files.values()):,}".replace(
            ",", "," if lang == "en" else "\u00a0"
        ),
        "heroes": len(files),
        "days": first["window_days"],
        "margin": lane_duel.GOLD_MARGIN,
        "min_lanes": lane_matchup.MIN_LANES,
        "gap": round(lane_matchup.KIND_GAP * 100),
        "generated": max(d["generated"] for d in files.values()),
    }
    out = [f"# {t['title'].format(**numbers)}", "", t["intro"].format(**numbers), "", t["how"], ""]
    out += [f"- {line.format(**numbers)}" for line in t["method"]]
    out += ["", t["caveats"].format(**numbers), ""]

    bullies = Counter(o["hero"] for r in rows for o in r["hard"])
    out += [t["bullies"], ""]
    out += [f"- {hero}: {count}" for hero, count in bullies.most_common(HEADLINE)]

    one_sided = sorted(
        ((r, o) for r in rows for o in r["hard"]),
        key=lambda pair: (-(pair[1]["lost"] / pair[1]["lanes"]), pair[0]["hero"]),
    )[:HEADLINE]
    out += ["", t["one_sided"], ""]
    for row, o in one_sided:
        out.append(
            "- "
            + t["one_sided_row"].format(
                hero=row["hero"],
                position=POSITION_NAMES[lang][row["position"]],
                enemy=o["hero"],
                lost=_pct(o["lost"], o["lanes"]),
                n=o["lanes"],
                base=row["base_lost"],
                gold=_signed(o["gold_diff"]),
            )
        )

    out += ["", t["table"].format(**numbers)]
    for position in POSITIONS:
        out += ["", f"*{t['positions'][position]}*", "", t["head"], "|---|---|---|---|"]
        for row in (r for r in rows if r["position"] == position):
            hard = ", ".join(
                f"{o['hero']} {_pct(o['lost'], o['lanes'])}%" for o in row["hard"][:PER_ROW]
            )
            easy = ", ".join(
                f"{o['hero']} {_pct(o['won'], o['lanes'])}%" for o in row["easy"][:PER_ROW]
            )
            out.append(
                f"| {row['hero']} | {row['base_lost']}% | {hard or t['none']}"
                f" | {easy or t['none']} |"
            )
    out += ["", t["source"].format(**numbers), "", "---", "", t["disclosure"], ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--lang", choices=sorted(TEXT), default="en")
    parser.add_argument("--out", type=Path, help="write here instead of printing")
    args = parser.parse_args()
    text = render(args.lang)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
