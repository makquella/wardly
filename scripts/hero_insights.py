"""What wins on a hero, in numbers: the hero of the week's post (Telegram card,
caption, site page) from the hero's own plan and its stats (data/heroes/item_plans,
data/heroes/item_stats, scripts/hero_item_stats.py).

Only what those files hold: the skill order the winners max and how the usual
alternative did, the net worth a won game has by a minute, the core item a fast
game gets earlier, and the counter items with their record against that kind of
lineup. A hero without a plan gets None, and the post falls back to the hero page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "data" / "heroes" / "item_plans"
STATS = ROOT / "data" / "heroes" / "item_stats"

# A record is shown only on enough games and a clear gap.
MIN_GAMES = 15
MIN_GAP = 10.0
MAX_COUNTERS = 2

# Who the counter item is against (a plan rule's `enemy`), and its stats group.
AGAINST = {
    "evasion": ("evasion", "ухилення", "evasion"),
    "evasion_break": ("evasion_break", "ухилення від здатності", "evasion from an ability"),
    "illusions": ("illusions", "ілюзій", "illusions"),
    "healing": ("healing", "лікування", "healing"),
    "break": ("break", "сильних пасивок", "strong passives"),
    "magic": ("magic_lineup", "магічної шкоди", "magic damage"),
    "jumpers": ("jumpers", "стрибунів", "jumpers"),
    "targeted_jumpers": ("jumpers", "стрибунів", "jumpers"),
}


def games_uk(n: int) -> str:
    """«1 гра», «3 гри», «12 ігор»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} гра"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} гри"
    return f"{n} ігор"


def games_text(n: int, lang: str) -> str:
    return games_uk(n) if lang == "uk" else f"{n} game{'s' if n != 1 else ''}"


def pct(value: float, lang: str) -> str:
    return f"{round(value)} %" if lang == "uk" else f"{round(value)}%"


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def load(name: str, position: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(plan, stats) for the hero at this position, or None."""
    for path in sorted(PLANS.glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if _key(plan["hero"]) != _key(name) or position not in plan["positions"]:
            continue
        stats_path = STATS / path.name
        if not stats_path.exists():
            return None
        return plan, json.loads(stats_path.read_text(encoding="utf-8"))
    return None


def planned(names: list[str]) -> set[str]:
    """The names among these that have a plan (any position)."""
    keys = {_key(json.loads(p.read_text(encoding="utf-8"))["hero"]) for p in PLANS.glob("*.json")}
    return {name for name in names if _key(name) in keys}


def facts(name: str, position: str) -> dict[str, Any] | None:
    """The numbers behind the post, language-free; None without a plan."""
    found = load(name, position)
    if found is None:
        return None
    plan, stats = found
    out: dict[str, Any] = {"games": stats["games"], "patch": plan["patch"]}
    names = plan["skills"]["names"]
    orders = [o for o in stats["skills"]["orders"] if len(o["order"]) == 3]
    if orders:
        top = max(orders, key=lambda o: o["games"])
        alternative = next(
            (
                o
                for o in sorted(orders, key=lambda o: o["games"], reverse=True)
                if o is not top
                and o["order"][0] != top["order"][0]
                and o["games"] >= MIN_GAMES
                and top["win"] - o["win"] >= MIN_GAP
            ),
            None,
        )
        out["skills"] = {
            "order": [names.get(key, key) for key in top["order"]],
            "win": top["win"],
            "games": top["games"],
            "alternative": (
                {
                    "first": names.get(alternative["order"][0], alternative["order"][0]),
                    "win": alternative["win"],
                    "games": alternative["games"],
                }
                if alternative
                else None
            ),
        }
    tempo = plan.get("tempo")
    if tempo:
        minute, net_worth = tempo["net_worth"][0]
        line = stats.get("tempo_line", {}).get(str(minute))
        if line:
            out["tempo"] = {
                "minute": minute,
                "net_worth": net_worth,
                "win": line["win"],
                "games": line["games"],
            }
        usual = {row["item"]: row["minute"] for row in stats.get("usual_build", [])}
        fast = {row["item"]: row["minute"] for row in stats.get("tempo_build", [])}
        for item in tempo["items"]:
            key = item["item"]
            # A core item a fast game gets clearly earlier, not a minute's noise.
            if key in usual and key in fast and usual[key] >= 8 and usual[key] - fast[key] >= 1.5:
                out["fast"] = {
                    "item": item["name"],
                    "fast": round(fast[key]),
                    "usual": round(usual[key]),
                }
                break
    counters, seen = [], set()
    for rule in plan["rules"]:
        against = AGAINST.get(rule.get("enemy", ""))
        if against is None or rule["item"] in seen or against[0] in seen:
            continue
        group = stats.get("counters", {}).get(against[0], {})
        record = next((i for i in group.get("items", []) if i["item"] == rule["item"]), None)
        strong = (
            record is not None
            and group.get("games", 0) >= MIN_GAMES
            and record.get("win_with") is not None
            and record.get("win_without") is not None
            and record["win_with"] - record["win_without"] >= MIN_GAP
        )
        seen |= {rule["item"], against[0]}
        counters.append(
            {
                "against": rule["enemy"],
                "item": rule["name"],
                "minute": rule["minute"],
                "record": (
                    {
                        "with": record["win_with"],
                        "without": record["win_without"],
                        "games": group["games"],
                    }
                    if strong and record
                    else None
                ),
            }
        )
    # The ones with a record first, then the plan's order.
    counters.sort(key=lambda c: c["record"] is None)
    out["counters"] = counters[:MAX_COUNTERS]
    return out


TEXT = {
    "uk": {
        "heading": "Що виграє на цьому герої",
        "skills": "Прокачка: <b>{order}</b>",
        "skills_sub": "{win} перемог ({games})",
        "skills_alt": "; першим {first} — {win}",
        "tempo": "<b>{net_worth}</b> нетворсу на {minute}:00",
        "tempo_sub": "такі ігри виграють у {win}",
        "fast": "У темпових іграх — <b>{item}</b> на {fast}-й хв",
        "fast_sub": "зазвичай — на {usual}-й",
        "counter": "Проти {against} — <b>{item}</b>",
        "counter_sub": "з ним {with_} перемог, без — {without} ({games} проти них)",
        "counter_plain": "до ~{minute}-ї хвилини",
        "source": "Цифри: лігові матчі патча {patch}, усього {games} (OpenDota).",
    },
    "en": {
        "heading": "What wins on this hero",
        "skills": "Skills: <b>{order}</b>",
        "skills_sub": "{win} win rate ({games})",
        "skills_alt": "; {first} first — {win}",
        "tempo": "<b>{net_worth}</b> net worth at {minute}:00",
        "tempo_sub": "such games are won {win} of the time",
        "fast": "In tempo games: <b>{item}</b> at minute {fast}",
        "fast_sub": "usually at minute {usual}",
        "counter": "Against {against}: <b>{item}</b>",
        "counter_sub": "{with_} win rate with it, {without} without ({games} against them)",
        "counter_plain": "by minute ~{minute}",
        "source": "Numbers: {games} league matches on patch {patch} (OpenDota).",
    },
}
EMOJI = {"skills": "🎯", "tempo": "💰", "fast": "⚡", "counter": "🛡"}
ICONS = {"skills": "spark", "tempo": "coins", "fast": "check", "counter": "shield"}


def rows(found: dict[str, Any], lang: str) -> list[tuple[str, str, str]]:
    """[(kind, title with <b>, sub)] in display order; the title's only markup is <b>
    around escaped names, so it works for the card, the caption and the site."""
    from functools import partial
    from html import escape

    escape = partial(escape, quote=False)

    t = TEXT[lang]
    out = []
    skills = found.get("skills")
    if skills:
        sub = t["skills_sub"].format(
            win=pct(skills["win"], lang), games=games_text(skills["games"], lang)
        )
        alternative = skills["alternative"]
        if alternative:
            sub += t["skills_alt"].format(
                first=alternative["first"], win=pct(alternative["win"], lang)
            )
        out.append(("skills", t["skills"].format(order=escape(" → ".join(skills["order"]))), sub))
    tempo = found.get("tempo")
    if tempo:
        out.append(
            (
                "tempo",
                t["tempo"].format(net_worth=money(tempo["net_worth"]), minute=tempo["minute"]),
                t["tempo_sub"].format(win=pct(tempo["win"], lang)),
            )
        )
    fast = found.get("fast")
    if fast:
        out.append(
            (
                "fast",
                t["fast"].format(item=escape(fast["item"]), fast=fast["fast"]),
                t["fast_sub"].format(usual=fast["usual"]),
            )
        )
    for counter in found.get("counters", []):
        against = AGAINST[counter["against"]][1 if lang == "uk" else 2]
        record = counter["record"]
        sub = (
            t["counter_sub"].format(
                with_=pct(record["with"], lang),
                without=pct(record["without"], lang),
                games=games_text(record["games"], lang),
            )
            if record
            else t["counter_plain"].format(minute=counter["minute"])
        )
        out.append(
            ("counter", t["counter"].format(against=against, item=escape(counter["item"])), sub)
        )
    return out


def source(found: dict[str, Any], lang: str) -> str:
    return TEXT[lang]["source"].format(games=found["games"], patch=found["patch"])
