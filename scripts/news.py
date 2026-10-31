"""News («Новини»): the weekly meta post and Dota 2 patches, their site pages and
the numbers behind their Telegram posts (scripts/news_cards.py).

A patch is a JSON file in data/news/patches/ written by `scripts/build_news.py
patch` from Valve's datafeed: the notes in Ukrainian and English as Valve gives
them, with the names of the heroes, abilities and items they refer to by id.
.github/workflows/patch.yml looks for a new patch every few hours.

A post is a JSON file in data/news/posts/ written by `scripts/build_news.py meta`
from OpenDota's public hero statistics (the last 7 days of public matches, all
ranks): every hero's picks and wins for that week, day by day. Everything shown —
the highlights, the hero lists, who rose and who fell, the Ukrainian and English
texts — is computed here from those numbers, so a page and its Telegram post
always say the same thing. scripts/build_site.py writes the pages (site/news.html,
site/news/<slug>.html and their /en/ copies); .github/workflows/news.yml makes a
post every Monday and sends it to the Telegram channel.

Who changed: against the previous post when it covers the week right before this
one (no shared days), else inside the week — the last three days against the
first three.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data" / "news" / "posts"
PATCHES = ROOT / "data" / "news" / "patches"
HERO_IMAGES = ROOT / "site" / "assets" / "heroes"
BASE = "https://luhovyimvp.dev"
CHANNEL = "https://t.me/wardlydota"
# A hero picked in fewer matches is left out of the lists (a few lucky games).
MIN_PICK_RATE = 0.02
TOP = 5
MOVERS = 3
# A change under this many percentage points is noise, not news.
MIN_MOVE = 0.5
# Inside the week: each half needs this many picks of the hero to compare.
HALF_MIN_PICKS = 2000
# The win-rate bars start here, so that 52 % and 55 % look different.
WIN_BAR_FLOOR = 0.45
# Valve's patch notes: the list of patches, each patch's notes, and the names
# behind their ids (heroes, abilities, items) — https://www.dota2.com/datafeed.
VALVE_FEED = "https://www.dota2.com/datafeed"
VALVE_PATCH_PAGE = "https://www.dota2.com/patches/{version}"
# The site's languages and Valve's names for them.
FEED_LANGUAGES = {"uk": "ukrainian", "en": "english"}

MONTHS_UK = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)
MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

TEXT = {
    "uk": {
        "title": "Мета тижня: {period}",
        "lead": "За останні 7 днів у публічних матчах Dota 2 зіграно близько {matches} ігор (дані OpenDota, усі ранги).",
        "lead_more": "Хто виграє найчастіше, кого беруть найбільше і хто змінився за тиждень.",
        "lead_short": "Хто виграє найчастіше і кого беруть найбільше.",
        "tile_win": "Найсильніший тижня",
        "tile_pick": "Найпопулярніший",
        "tile_up": "Злетів за тиждень",
        "tile_matches": "Ігор за тиждень",
        "tile_win_value": "{v} перемог",
        "tile_pick_value": "у {v} матчів",
        "tile_up_value": "{v} перемог",
        "tile_matches_value": "публічні матчі, усі ранги",
        "win_title": "Найчастіше виграють",
        "pick_title": "Найпопулярніші",
        "up_title": "Ростуть",
        "down_title": "Падають",
        "win_hint": "Відсоток перемог серед героїв, яких брали хоча б у {min} % матчів.",
        "pick_hint": "У скількох матчах тижня був цей герой.",
        "moves_week": "Відсоток перемог порівняно з минулим тижнем.",
        "moves_inside": "Відсоток перемог за останні три дні порівняно з першими трьома днями тижня.",
        "source": "Джерело: OpenDota, публічні матчі за {period}.",
        "cta_title": "Граєте на цих героях?",
        "cta_text": "Wardly підказує просто в матчі: темп добивань проти вашого суперника, предмети проти вражеського драфту, таймери й прокачку. Безкоштовно для Windows.",
        "download": "Завантажити для Windows",
        "share_title": "Поділіться з тіммейтами",
        "share_text": "Скиньте мету друзям перед вечором у Доті: з одного допису видно, кого брати й кого банити.",
        "share_tg": "Надіслати в Telegram",
        "channel": "Канал @wardlydota",
        "list_title": "Новини",
        "list_lead": "Мета тижня щопонеділка: хто виграє, кого беруть і хто змінився. Герой тижня щочетверга. І кожен новий патч Dota 2: що змінили Valve. Ті самі дописи й нові версії — у нашому Telegram-каналі.",
        "list_channel": "Підписатися на канал @wardlydota",
        "list_top": "Найсильніший: {hero}, {v}",
        "changelog": "Що нового в застосунку →",
        "pp": "п. п.",
        "million": "{n} млн",
        "thousand": "{n} тис.",
        "patch_title": "Патч {version}",
        "patch_lead": "Усе, що змінили Valve: герої, предмети й загальні правила. Дані з офіційних нотаток до патча.",
        "patch_heroes": "Героїв змінено",
        "patch_items": "Предметів змінено",
        "patch_neutral": "Нейтральних предметів",
        "patch_general": "Загальні зміни",
        "patch_general_value": "розділів",
        "patch_count_value": "у нотатках Valve",
        "patch_items_title": "Предмети",
        "patch_neutral_title": "Нейтральні предмети",
        "patch_creeps_title": "Нейтральні крипи",
        "patch_heroes_title": "Герої",
        "patch_talents": "Таланти",
        "patch_source": "Джерело: офіційні нотатки Valve до патча {version}",
        "patch_share": "Скиньте друзям, що змінилося в патчі: усі герої й предмети на одній сторінці.",
        "patch_list": "Героїв змінено: {heroes} · предметів: {items}",
        "patch_badge": "Патч",
    },
    "en": {
        "title": "Meta of the week: {period}",
        "lead": "About {matches} public Dota 2 matches were played over the last 7 days (OpenDota data, all ranks).",
        "lead_more": "Who wins most, who is picked most and who changed this week.",
        "lead_short": "Who wins most and who is picked most.",
        "tile_win": "Strongest this week",
        "tile_pick": "Most picked",
        "tile_up": "Biggest riser",
        "tile_matches": "Games this week",
        "tile_win_value": "{v} win rate",
        "tile_pick_value": "in {v} of matches",
        "tile_up_value": "{v} win rate",
        "tile_matches_value": "public matches, all ranks",
        "win_title": "Highest win rate",
        "pick_title": "Most picked",
        "up_title": "Rising",
        "down_title": "Falling",
        "win_hint": "Win rate of heroes picked in at least {min}% of matches.",
        "pick_hint": "How many of the week's matches had the hero.",
        "moves_week": "Win rate against the previous week.",
        "moves_inside": "Win rate of the last three days against the first three days of the week.",
        "source": "Source: OpenDota, public matches of {period}.",
        "cta_title": "Playing these heroes?",
        "cta_text": "Wardly tells you during the match: your last-hit pace against this opponent, items against the enemy draft, timers and skills. Free for Windows.",
        "download": "Download for Windows",
        "share_title": "Share it with your teammates",
        "share_text": "Send the meta to your friends before tonight's games: one post shows whom to pick and whom to ban.",
        "share_tg": "Send in Telegram",
        "channel": "Channel @wardlydota",
        "list_title": "News",
        "list_lead": "The meta of the week every Monday: who wins, who is picked and who changed. The hero of the week every Thursday. And every new Dota 2 patch: what Valve changed. The same posts and new versions go to our Telegram channel.",
        "list_channel": "Follow @wardlydota on Telegram",
        "list_top": "Strongest: {hero}, {v}",
        "changelog": "What's new in the app →",
        "pp": "pp",
        "million": "{n} million",
        "thousand": "{n} thousand",
        "patch_title": "Patch {version}",
        "patch_lead": "Everything Valve changed: heroes, items and the general rules. From the official patch notes.",
        "patch_heroes": "Heroes changed",
        "patch_items": "Items changed",
        "patch_neutral": "Neutral items",
        "patch_general": "General changes",
        "patch_general_value": "sections",
        "patch_count_value": "in Valve's notes",
        "patch_items_title": "Items",
        "patch_neutral_title": "Neutral items",
        "patch_creeps_title": "Neutral creeps",
        "patch_heroes_title": "Heroes",
        "patch_talents": "Talents",
        "patch_source": "Source: Valve's official notes for patch {version}",
        "patch_share": "Tell your friends what the patch changed: every hero and item on one page.",
        "patch_list": "Heroes changed: {heroes} · items: {items}",
        "patch_badge": "Patch",
    },
}


# --- data ---------------------------------------------------------------------------


def load_posts() -> list[dict[str, Any]]:
    """Every post, newest first."""
    posts = [json.loads(path.read_text(encoding="utf-8")) for path in POSTS.glob("*.json")]
    return sorted(posts, key=lambda post: post["date"], reverse=True)


def slug(post: dict[str, Any]) -> str:
    return f"{post['date']}-meta"


def _days(values: Any) -> list[int] | None:
    if not isinstance(values, list) or len(values) != 7:
        return None
    try:
        days = [int(n or 0) for n in values]
    except (TypeError, ValueError):
        return None
    return days if all(n >= 0 for n in days) else None


def meta_post(hero_stats: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """A post from OpenDota's /heroStats: each hero's public picks and wins of the
    last 7 days, day by day (`pub_pick_trend` / `pub_win_trend`)."""
    heroes = []
    for row in hero_stats:
        picks_days, wins_days = _days(row.get("pub_pick_trend")), _days(row.get("pub_win_trend"))
        name = row.get("localized_name")
        if not isinstance(name, str) or picks_days is None or wins_days is None:
            continue
        picks, wins = sum(picks_days), sum(wins_days)
        if picks <= 0 or not 0 <= wins <= picks:
            continue
        key = str(row.get("name") or "").removeprefix("npc_dota_hero_")
        heroes.append(
            {
                "id": int(row["id"]),
                "name": name,
                "key": key if re.fullmatch(r"[a-z0-9_]+", key) else "",
                "picks": picks,
                "wins": wins,
                "picks_days": picks_days,
                "wins_days": wins_days,
            }
        )
    if len(heroes) < 50:
        raise ValueError(f"OpenDota returned {len(heroes)} heroes with picks: too few")
    start = date.fromordinal(today.toordinal() - 6)
    return {
        "kind": "meta",
        "date": today.isoformat(),
        "from": start.isoformat(),
        "to": today.isoformat(),
        "source": "OpenDota /api/heroStats (pub_pick_trend, pub_win_trend)",
        "heroes": sorted(heroes, key=lambda hero: hero["id"]),
    }


def _win_rates(post: dict[str, Any]) -> dict[str, float]:
    matches = sum(hero["picks"] for hero in post["heroes"]) / 10
    return {
        hero["name"]: hero["wins"] / hero["picks"]
        for hero in post["heroes"]
        if hero["picks"] / matches >= MIN_PICK_RATE
    }


def _inside_week(post: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """{hero: (win rate of the first three days, of the last three)}."""
    halves = {}
    for hero in post["heroes"]:
        picks, wins = hero.get("picks_days"), hero.get("wins_days")
        if not picks or not wins:
            continue
        early_picks, late_picks = sum(picks[:3]), sum(picks[4:])
        if min(early_picks, late_picks) < HALF_MIN_PICKS:
            continue
        halves[hero["name"]] = (sum(wins[:3]) / early_picks, sum(wins[4:]) / late_picks)
    return halves


def summary(post: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """What a post shows: matches, top win rate, most picked, who rose and fell,
    and `moves` — "week" (against the previous post), "inside" (inside the week)
    or None when neither can be told."""
    heroes = post["heroes"]
    matches = sum(hero["picks"] for hero in heroes) / 10
    rows = {
        hero["name"]: {
            "name": hero["name"],
            "key": hero.get("key") or "",
            "win": hero["wins"] / hero["picks"],
            "pick": hero["picks"] / matches,
        }
        for hero in heroes
    }
    eligible = [row for row in rows.values() if row["pick"] >= MIN_PICK_RATE]
    top_win = sorted(eligible, key=lambda row: (-row["win"], row["name"]))[:TOP]
    top_pick = sorted(rows.values(), key=lambda row: (-row["pick"], row["name"]))[:TOP]
    moves: list[dict[str, Any]] = []
    basis = None
    if previous is not None and _week_before(previous, post):
        before = _win_rates(previous)
        moves = [
            {**row, "change": (row["win"] - before[row["name"]]) * 100}
            for row in eligible
            if row["name"] in before
        ]
        basis = "week" if moves else None
    if basis is None:
        halves = _inside_week(post)
        moves = [
            {**row, "change": (halves[row["name"]][1] - halves[row["name"]][0]) * 100}
            for row in eligible
            if row["name"] in halves
        ]
        basis = "inside" if moves else None
    up = sorted(
        (m for m in moves if m["change"] >= MIN_MOVE), key=lambda m: (-m["change"], m["name"])
    )[:MOVERS]
    down = sorted(
        (m for m in moves if m["change"] <= -MIN_MOVE), key=lambda m: (m["change"], m["name"])
    )[:MOVERS]
    return {
        "matches": matches,
        "win": top_win,
        "pick": top_pick,
        "up": up,
        "down": down,
        "moves": basis if up or down else None,
    }


def _week_before(previous: dict[str, Any], post: dict[str, Any]) -> bool:
    """The previous post covers the week right before this one: it ended before
    this one started (no shared days), at most a week earlier."""
    gap = date.fromisoformat(post["from"]) - date.fromisoformat(previous["to"])
    return 1 <= gap.days <= 7


def previous_of(post: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    older = [p for p in posts if p["date"] < post["date"]]
    return max(older, key=lambda p: p["date"]) if older else None


# The meta's angles (meta_angles): a popular hero under this win rate is a trap,
# a hero picked under GEM_PICK with a top win rate is a quiet strong pick, a change
# in pick rate under PICK_MOVE points is noise, and a patch explains a move for
# PATCH_WEEKS after its release.
TRAP_WIN = 0.49
TRAP_TOP = 5
GEM_PICK = 0.05
PICK_MOVE = 1.0
PATCH_WEEKS = 3


def _top_win(post: dict[str, Any]) -> str | None:
    rows = summary(post, None)["win"]
    return rows[0]["name"] if rows else None


def win_streak(post: dict[str, Any], posts: list[dict[str, Any]]) -> int:
    """How many weeks in a row (this one included) the same hero has the best win
    rate. A post overlapping a newer one is skipped; a gap of over a week ends it."""
    top = _top_win(post)
    if top is None:
        return 0
    weeks, cursor = 1, post
    for older in sorted(posts, key=lambda p: p["date"], reverse=True):
        if older["date"] >= cursor["date"]:
            continue
        gap = (date.fromisoformat(cursor["from"]) - date.fromisoformat(older["to"])).days
        if gap < 1:
            continue  # shares days with the newer post
        if gap > 7 or _top_win(older) != top:
            break
        weeks, cursor = weeks + 1, older
    return weeks


def _pick_rates(post: dict[str, Any]) -> dict[str, float]:
    matches = sum(hero["picks"] for hero in post["heroes"]) / 10 or 1
    return {hero["name"]: hero["picks"] / matches for hero in post["heroes"]}


def _patched(post: dict[str, Any], patches: list[dict[str, Any]]) -> tuple[str, set[str]] | None:
    """(version, hero names) of the newest patch released before the post's week
    ended and at most PATCH_WEEKS before it."""
    end = date.fromisoformat(post["to"])
    for patch in sorted(patches, key=lambda p: p["date"], reverse=True):
        days = (end - date.fromisoformat(patch["date"])).days
        if days < 0:
            continue
        if days > PATCH_WEEKS * 7:
            return None
        names = {hero["name"] for hero in patch["languages"]["en"]["heroes"]}
        return patch["version"], names
    return None


def meta_angles(
    post: dict[str, Any],
    data: dict[str, Any],
    posts: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """What the week says, most telling first: [{"kind", "row", ...numbers}].

    streak (the same best win rate for weeks), patch_rise/patch_fall (a mover the
    latest patch changed), trap (a top pick that loses), picked_more/picked_less
    (pick rate against the week before), gem (a top win rate few pick), rise/fall
    (the biggest win-rate move), quiet (nobody moved), top (the best win rate).
    Only numbers from the posts and patch files; a hero appears once."""
    angles: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, row: dict[str, Any] | None, **extra: Any) -> None:
        name = row["name"] if row else ""
        if row is not None and name in seen:
            return
        seen.add(name)
        angles.append({"kind": kind, "row": row, **extra})

    win, pick = data["win"], data["pick"]
    weeks = win_streak(post, posts) if win else 0
    if weeks >= 2:
        add("streak", win[0], weeks=weeks)
    movers = sorted(data["up"] + data["down"], key=lambda m: -abs(m["change"]))
    patched = _patched(post, patches)
    if patched:
        version, names = patched
        for mover in movers:
            if mover["name"] in names:
                kind = "patch_rise" if mover["change"] > 0 else "patch_fall"
                add(kind, mover, patch=version, basis=data["moves"])
                break
    for row in pick[:TRAP_TOP]:
        if row["win"] < TRAP_WIN:
            add("trap", row)
            break
    previous = previous_of(post, posts)
    if previous is not None and _week_before(previous, post):
        before, now = _pick_rates(previous), _pick_rates(post)
        rows = {row["name"]: row for row in pick}
        changes = sorted(
            (((now[name] - before[name]) * 100, name) for name in now if name in before),
            key=lambda c: (-abs(c[0]), c[1]),
        )
        largest = next((c for c in changes if c[1] not in seen), None)
        if largest and abs(largest[0]) >= PICK_MOVE:
            change, name = largest
            hero = next(h for h in post["heroes"] if h["name"] == name)
            row = rows.get(name) or {
                "name": name,
                "key": hero.get("key") or "",
                "win": hero["wins"] / hero["picks"] if hero["picks"] else 0.0,
                "pick": now[name],
            }
            add("picked_more" if change > 0 else "picked_less", row, change=change)
    for row in win[:3]:
        if row["pick"] < GEM_PICK:
            add("gem", row)
            break
    if movers:
        mover = movers[0]
        add("rise" if mover["change"] > 0 else "fall", mover, basis=data["moves"])
    elif previous is not None and _week_before(previous, post):
        add("quiet", None)
    if win:
        add("top", win[0])
    return angles


def image_keys(data: dict[str, Any]) -> set[str]:
    """The heroes whose pictures a post's page shows."""
    rows = data["win"] + data["pick"] + data["up"] + data["down"]
    return {row["key"] for row in rows if row.get("key")}


# --- patches -------------------------------------------------------------------------


def load_patches() -> list[dict[str, Any]]:
    """Every patch post, newest first."""
    patches = [json.loads(path.read_text(encoding="utf-8")) for path in PATCHES.glob("*.json")]
    return sorted(patches, key=lambda patch: (patch["date"], patch["version"]), reverse=True)


def patch_slug(patch: dict[str, Any]) -> str:
    return f"{patch['date']}-patch-{patch['version'].replace('.', '-')}"


def _clean(value: Any) -> str:
    """A note as plain text: Valve's notes carry <font>, <span> and <br> tags."""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def _notes(raw: Any) -> list[dict[str, Any]]:
    """[{"level": 1.., "text": ..., "info"?: ...}] without the empty spacer lines."""
    notes = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("note"))
        if not text:
            continue
        try:
            level = max(1, min(4, int(item.get("indent_level") or 1)))
        except (TypeError, ValueError):
            level = 1
        note: dict[str, Any] = {"level": level, "text": text}
        info = _clean(item.get("info"))
        if info:
            note["info"] = info
        notes.append(note)
    return notes


def _entries(raw: Any, names: dict[int, str]) -> list[dict[str, Any]]:
    """Items or neutral items: a named item with its notes, or a group of general
    notes ({"group": title}) such as «Enchantment Changes»."""
    entries = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        notes = _notes(item.get("ability_notes"))
        label = _clean(item.get("title"))
        item_id = item.get("ability_id")
        if item.get("is_general_note") or not isinstance(item_id, int) or item_id < 0:
            if label:
                entries.append({"group": label, "notes": notes})
            continue
        name = names.get(item_id) or label
        if not name or not notes:
            continue
        entry: dict[str, Any] = {"name": name, "notes": notes}
        if label and label != name:
            entry["label"] = label
        entries.append(entry)
    return entries


def _hero_entries(
    raw: Any, heroes: dict[int, dict[str, str]], abilities: dict[int, str]
) -> list[dict[str, Any]]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("hero_id") not in heroes:
            continue
        hero = heroes[item["hero_id"]]
        changed = []
        for ability in item.get("abilities") or []:
            if not isinstance(ability, dict):
                continue
            notes = _notes(ability.get("ability_notes"))
            ability_id = ability.get("ability_id")
            name = abilities.get(ability_id) if isinstance(ability_id, int) else None
            if notes and name:
                changed.append({"name": name, "notes": notes})
        entry = {
            "id": item["hero_id"],
            "name": hero["name"],
            "key": hero["key"],
            "notes": _notes(item.get("hero_notes")),
            "abilities": changed,
            "talents": _notes(item.get("talent_notes")),
        }
        if entry["notes"] or entry["abilities"] or entry["talents"]:
            out.append(entry)
    return out


def patch_language(feed: dict[str, Any], names: dict[str, Any]) -> dict[str, Any]:
    """One language of a patch post from Valve's /patchnotes answer.

    `names` resolves the feed's ids: {"heroes": {id: {"name", "key"}},
    "abilities": {id: name}, "items": {id: name}} (from /herolist, /abilitylist
    and /itemlist in the same language). The feed has no names of its own."""
    general = []
    for group in feed.get("general_notes") or []:
        if isinstance(group, dict):
            notes = _notes(group.get("generic"))
            if notes:
                general.append({"title": _clean(group.get("title")), "notes": notes})
    neutral_names = {**names["abilities"], **names["items"]}
    creeps = []
    for creep in feed.get("neutral_creeps") or []:
        if isinstance(creep, dict):
            notes = _notes(creep.get("neutral_creep_notes"))
            name = _clean(creep.get("localized_name"))
            if notes and name:
                creeps.append({"name": name, "notes": notes})
    return {
        "general": general,
        "items": _entries(feed.get("items"), names["items"]),
        "neutral": _entries(feed.get("neutral_items"), neutral_names),
        "heroes": _hero_entries(feed.get("heroes"), names["heroes"], names["abilities"]),
        "creeps": creeps,
    }


def patch_post(
    feeds: dict[str, dict[str, Any]], names: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """A patch post: Valve's notes in each site language ({"uk": ..., "en": ...}),
    with names for every hero, ability and item."""
    english = feeds["en"]
    version = english.get("patch_number") or english.get("patch_name")
    stamp = english.get("patch_timestamp")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+[a-z]?", version):
        raise ValueError(f"Valve's patch notes have no version: {version!r}")
    if not isinstance(stamp, int) or stamp <= 0:
        raise ValueError(f"Valve's patch notes for {version} have no date")
    languages = {lang: patch_language(feeds[lang], names[lang]) for lang in FEED_LANGUAGES}
    if not any(languages["en"].values()):
        raise ValueError(f"Valve's patch notes for {version} are empty")
    return {
        "kind": "patch",
        "version": version,
        "date": datetime.fromtimestamp(stamp, UTC).date().isoformat(),
        "source": "Valve datafeed /patchnotes, /herolist, /abilitylist, /itemlist",
        "languages": languages,
    }


def _first_line(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;:") + "…"


def patch_highlights(
    patch: dict[str, Any], lang: str = "uk", heroes: int = 3, items: int = 3, limit: int = 110
) -> dict[str, list[dict[str, Any]]]:
    """The patch's most changed heroes and items, each with its first change as
    Valve wrote it: {"heroes": [{"name", "key", "changes", "line"}], "items": [...]}.
    Most notes first, then by name; a change line is cut at `limit` characters."""
    language = patch["languages"][lang]

    def hero_row(hero: dict[str, Any]) -> dict[str, Any]:
        notes = hero["notes"] + hero["talents"]
        count = len(notes) + sum(len(a["notes"]) for a in hero["abilities"])
        if hero["abilities"]:
            ability = hero["abilities"][0]
            line = f"{ability['name']}: {ability['notes'][0]['text']}"
        elif hero["notes"]:
            line = hero["notes"][0]["text"]
        else:
            line = f"{TEXT[lang]['patch_talents']}: {hero['talents'][0]['text']}"
        return {
            "name": hero["name"],
            "key": hero["key"],
            "changes": count,
            "line": _first_line(line, limit),
        }

    def item_row(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": item["name"],
            "changes": len(item["notes"]),
            "line": _first_line(item["notes"][0]["text"], limit),
        }

    hero_rows = sorted(
        (hero_row(h) for h in language["heroes"]), key=lambda r: (-r["changes"], r["name"])
    )
    item_rows = sorted(
        (item_row(i) for i in language["items"] + language["neutral"] if "name" in i),
        key=lambda r: (-r["changes"], r["name"]),
    )
    return {"heroes": hero_rows[:heroes], "items": item_rows[:items]}


def patch_counts(patch: dict[str, Any]) -> dict[str, int]:
    notes = patch["languages"]["en"]
    return {
        "heroes": len(notes["heroes"]),
        "items": sum(1 for entry in notes["items"] if "name" in entry),
        "neutral": sum(1 for entry in notes["neutral"] if "name" in entry),
        "general": len(notes["general"]),
    }


# --- words and numbers -----------------------------------------------------------------


def period(post: dict[str, Any], lang: str) -> str:
    start, end = date.fromisoformat(post["from"]), date.fromisoformat(post["to"])
    months = MONTHS_UK if lang == "uk" else MONTHS_EN
    if start.month == end.month:
        return f"{start.day}–{end.day} {months[end.month - 1]}"
    return f"{start.day} {months[start.month - 1]} – {end.day} {months[end.month - 1]}"


def long_date(value: str, lang: str) -> str:
    day = date.fromisoformat(value)
    months = MONTHS_UK if lang == "uk" else MONTHS_EN
    return f"{day.day} {months[day.month - 1]} {day.year}"


def percent(value: float, lang: str, digits: int = 1) -> str:
    text = f"{value * 100:.{digits}f}"
    return f"{text.replace('.', ',')} %" if lang == "uk" else f"{text}%"


def points(value: float, lang: str) -> str:
    text = f"{value:+.1f}".replace("-", "−")
    return (
        f"{text.replace('.', ',')} {TEXT[lang]['pp']}"
        if lang == "uk"
        else f"{text} {TEXT[lang]['pp']}"
    )


def matches_text(matches: float, lang: str) -> str:
    t = TEXT[lang]
    if matches >= 1_000_000:
        n = f"{matches / 1_000_000:.1f}"
        return t["million"].format(n=n.replace(".", ",") if lang == "uk" else n)
    return t["thousand"].format(n=round(matches / 1000))


def title(post: dict[str, Any], lang: str) -> str:
    return TEXT[lang]["title"].format(period=period(post, lang))


def lead(post: dict[str, Any], data: dict[str, Any], lang: str) -> str:
    t = TEXT[lang]
    more = t["lead_more"] if data.get("moves") else t["lead_short"]
    return f"{t['lead'].format(matches=matches_text(data['matches'], lang))} {more}"


# --- site pages ------------------------------------------------------------------------

_ICON = {
    "trophy": '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22M18 2H6v7a6 6 0 0 0 12 0V2Z" />',
    "flame": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5Z" />',
    "up": '<path d="m22 7-8.5 8.5-5-5L2 17" /><path d="M16 7h6v6" />',
    "down": '<path d="m22 17-8.5-8.5-5 5L2 7" /><path d="M16 17h6v-6" />',
    "swords": '<path d="M14.5 17.5 3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2M9.5 6.5 21 18M14.5 6.5 18 3h3v3l-3.5 3.5M5 14l4 4M7 17l-3 3M3 19l2 2" />',
    "send": '<path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" />',
}


def _icon(name: str) -> str:
    return (
        '<svg class="news-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{_ICON[name]}</svg>"
    )


def _picture(row: dict[str, Any], up: str, images: set[str], size: str) -> str:
    """The hero's picture from site/assets/heroes, else their initials."""
    key = row.get("key") or ""
    if key in images:
        return (
            f'<img class="hero-pic hero-pic-{size}" src="{up}assets/heroes/{key}.webp" '
            f'alt="" width="256" height="144" loading="lazy" />'
        )
    initials = "".join(word[0] for word in row["name"].split()[:2])
    return f'<span class="hero-pic hero-pic-{size} hero-pic-none" aria-hidden="true">{html.escape(initials)}</span>'


def _name(row: dict[str, Any], links: dict[str, str], home: str) -> str:
    name = html.escape(row["name"])
    if row["name"] in links:
        return f'<a href="{home}heroes/{links[row["name"]]}.html">{name}</a>'
    return name


def _bar(value: str, width: float, tone: str = "") -> str:
    width = max(4.0, min(100.0, width))
    return (
        f'<span class="bar{(" bar-" + tone) if tone else ""}" aria-hidden="true">'
        f'<span style="width: {width:.0f}%"></span></span>'
        f'<span class="row-value">{html.escape(value)}</span>'
    )


def _rows(
    rows: list[dict[str, Any]],
    lang: str,
    kind: str,
    links: dict[str, str],
    home: str,
    up: str,
    images: set[str],
) -> str:
    if kind == "win":
        floor, top = WIN_BAR_FLOOR, max(row["win"] for row in rows)
        measured = [
            ((row["win"] - floor) / max(top - floor, 1e-9), percent(row["win"], lang))
            for row in rows
        ]
    elif kind == "pick":
        top = max(row["pick"] for row in rows)
        measured = [(row["pick"] / top, percent(row["pick"], lang)) for row in rows]
    else:
        top = max(abs(row["change"]) for row in rows)
        measured = [(abs(row["change"]) / top, points(row["change"], lang)) for row in rows]
    tone = kind if kind in ("up", "down") else ""
    items = "\n".join(
        f"""                <li class="hero-row">
                  <span class="row-rank">{index}</span>
                  {_picture(row, up, images, "sm")}
                  <span class="row-name">{_name(row, links, home)}</span>
                  {_bar(value, share * 100, tone)}
                </li>"""
        for index, (row, (share, value)) in enumerate(zip(rows, measured, strict=True), 1)
    )
    return f'              <ol class="hero-rows">\n{items}\n              </ol>'


def _card(icon: str, heading: str, hint: str, body: str, extra: str = "") -> str:
    e = html.escape
    return f"""            <article class="mode news-card{extra}">
              <h2 class="news-card-title">{_icon(icon)}<span>{e(heading)}</span></h2>
              <p class="mode-note news-hint">{e(hint)}</p>
{body}
            </article>"""


def _tile(icon: str, label: str, picture: str, name: str, value: str, tone: str = "") -> str:
    e = html.escape
    # No picture: no line for it (a blank one would end in spaces).
    picture_line = f"              {picture}\n" if picture else ""
    return f"""            <div class="news-tile{(" news-tile-" + tone) if tone else ""}">
{picture_line}              <div class="news-tile-text">
                <p class="news-tile-label">{_icon(icon)}{e(label)}</p>
                <p class="news-tile-name">{name}</p>
                <p class="news-tile-value">{e(value)}</p>
              </div>
            </div>"""


def post_main(
    post: dict[str, Any],
    data: dict[str, Any],
    lang: str,
    links: dict[str, str],
    home: str,
    up: str = "../",
    images: set[str] | None = None,
) -> str:
    """The <main> of a post page; `home` leads to this language's home page and
    `up` to the site root; `images` are the hero pictures the site has."""
    t = TEXT[lang]
    e = html.escape
    images = images or set()
    page_url = f"{BASE}{'' if lang == 'uk' else '/en'}/news/{slug(post)}.html"
    best, popular = data["win"][0], data["pick"][0]
    tiles = [
        _tile(
            "trophy",
            t["tile_win"],
            _picture(best, up, images, "lg"),
            _name(best, links, home),
            t["tile_win_value"].format(v=percent(best["win"], lang)),
        ),
        _tile(
            "flame",
            t["tile_pick"],
            _picture(popular, up, images, "lg"),
            _name(popular, links, home),
            t["tile_pick_value"].format(v=percent(popular["pick"], lang)),
        ),
    ]
    if data["up"]:
        riser = data["up"][0]
        tiles.append(
            _tile(
                "up",
                t["tile_up"],
                _picture(riser, up, images, "lg"),
                _name(riser, links, home),
                f"{points(riser['change'], lang)} · {t['tile_up_value'].format(v=percent(riser['win'], lang))}",
                "up",
            )
        )
    else:
        tiles.append(
            _tile(
                "swords",
                t["tile_matches"],
                "",
                e(matches_text(data["matches"], lang)),
                t["tile_matches_value"],
            )
        )
    min_rate = f"{MIN_PICK_RATE * 100:.0f}"
    cards = [
        _card(
            "trophy",
            t["win_title"],
            t["win_hint"].format(min=min_rate),
            _rows(data["win"], lang, "win", links, home, up, images),
        ),
        _card(
            "flame",
            t["pick_title"],
            t["pick_hint"],
            _rows(data["pick"], lang, "pick", links, home, up, images),
        ),
    ]
    moves_hint = t["moves_week"] if data.get("moves") == "week" else t["moves_inside"]
    if data["up"]:
        cards.append(
            _card(
                "up",
                t["up_title"],
                moves_hint,
                _rows(data["up"], lang, "up", links, home, up, images),
                " news-card-up",
            )
        )
    if data["down"]:
        cards.append(
            _card(
                "down",
                t["down_title"],
                moves_hint,
                _rows(data["down"], lang, "down", links, home, up, images),
                " news-card-down",
            )
        )
    tiles_html = "\n".join(tiles)
    cards_html = "\n".join(cards)
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <p class="mode-tag"><a href="{home}news.html">{e(t["list_title"])}</a> · <time datetime="{post["date"]}">{e(long_date(post["date"], lang))}</time></p>
          <h1>{e(title(post, lang))}</h1>
          <p class="lead">{e(lead(post, data, lang))}</p>
          <div class="news-tiles">
{tiles_html}
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <div class="news-cards">
{cards_html}
          </div>
          <p class="mode-note news-source">{e(t["source"].format(period=period(post, lang)))}</p>
        </div>
      </section>

{_actions(lang, page_url, title(post, lang), t["share_text"])}
    </main>"""


def _actions(lang: str, page_url: str, heading: str, share_text: str) -> str:
    """Share the page in Telegram, follow the channel, download the app."""
    t = TEXT[lang]
    e = html.escape
    share = e(
        "https://t.me/share/url?" + urlencode({"url": f"{page_url}?ref=tg-share", "text": heading})
    )
    return f"""      <section class="section section-alt">
        <div class="wrap news-actions">
          <div class="hero-cta">
            <h2>{e(t["share_title"])}</h2>
            <p>{e(share_text)}</p>
            <div class="cta-row">
              <a class="btn btn-primary btn-lg" href="{share}" rel="noopener">{_icon("send")}<span>{e(t["share_tg"])}</span></a>
              <a class="btn btn-outline btn-lg" href="{CHANNEL}" rel="noopener">{e(t["channel"])}</a>
            </div>
          </div>
          <div class="hero-cta">
            <h2>{e(t["cta_title"])}</h2>
            <p>{e(t["cta_text"])}</p>
            <div class="cta-row">
              <a class="btn btn-primary btn-lg js-download" href="https://github.com/makquella/wardly/releases/latest">
                <svg class="i" aria-hidden="true"><use href="#i-windows" /></svg>
                <span>{e(t["download"])}</span>
              </a>
            </div>
          </div>
        </div>
      </section>"""


def patch_title(patch: dict[str, Any], lang: str) -> str:
    return TEXT[lang]["patch_title"].format(version=patch["version"])


def _patch_notes(notes: list[dict[str, Any]]) -> str:
    e = html.escape
    items = "\n".join(
        f'                <li class="patch-note patch-note-{note["level"]}">{e(note["text"])}'
        + (f'<span class="patch-info">{e(note["info"])}</span>' if note.get("info") else "")
        + "</li>"
        for note in notes
    )
    return f'              <ul class="patch-notes">\n{items}\n              </ul>'


def _patch_card(heading: str, body: list[str], extra: str = "", head: str = "") -> str:
    """A card of notes; `head` replaces the plain heading (a hero with a picture)."""
    title = head or f'<h2 class="news-card-title"><span>{html.escape(heading)}</span></h2>'
    inner = "\n".join(body)
    return f"""            <article class="mode news-card patch-card{extra}">
              {title}
{inner}
            </article>"""


def _patch_entries(entries: list[dict[str, Any]]) -> list[str]:
    e = html.escape
    out = []
    for entry in entries:
        if "group" in entry:
            out.append(f'              <h3 class="patch-group">{e(entry["group"])}</h3>')
        else:
            label = f" <small>{e(entry['label'])}</small>" if entry.get("label") else ""
            out.append(f'              <h3 class="patch-name">{e(entry["name"])}{label}</h3>')
        if entry["notes"]:
            out.append(_patch_notes(entry["notes"]))
    return out


def _patch_hero(
    hero: dict[str, Any], lang: str, links: dict[str, str], home: str, up: str, images: set[str]
) -> str:
    e = html.escape
    body = []
    if hero["notes"]:
        body.append(_patch_notes(hero["notes"]))
    for ability in hero["abilities"]:
        body.append(f'              <h3 class="patch-name">{e(ability["name"])}</h3>')
        body.append(_patch_notes(ability["notes"]))
    if hero["talents"]:
        body.append(f'              <h3 class="patch-name">{e(TEXT[lang]["patch_talents"])}</h3>')
        body.append(_patch_notes(hero["talents"]))
    head = (
        f'<h2 class="news-card-title patch-hero">{_picture(hero, up, images, "lg")}'
        f"<span>{_name(hero, links, home)}</span></h2>"
    )
    return _patch_card(hero["name"], body, head=head)


def patch_main(
    patch: dict[str, Any],
    lang: str,
    links: dict[str, str],
    home: str,
    up: str = "../",
    images: set[str] | None = None,
) -> str:
    """The <main> of a patch page: Valve's notes in this language, the general
    changes and items first, then every hero that changed."""
    t = TEXT[lang]
    e = html.escape
    images = images or set()
    notes = patch["languages"][lang]
    counts = patch_counts(patch)
    page_url = f"{BASE}{'' if lang == 'uk' else '/en'}/news/{patch_slug(patch)}.html"
    valve = VALVE_PATCH_PAGE.format(version=patch["version"])
    tiles = [
        _tile("swords", t["patch_heroes"], "", str(counts["heroes"]), t["patch_count_value"]),
        _tile("flame", t["patch_items"], "", str(counts["items"]), t["patch_count_value"]),
    ]
    if counts["general"]:
        tiles.append(
            _tile(
                "trophy",
                t["patch_general"],
                "",
                str(counts["general"]),
                t["patch_general_value"],
            )
        )
    else:
        tiles.append(
            _tile("trophy", t["patch_neutral"], "", str(counts["neutral"]), t["patch_count_value"])
        )
    cards = [
        _patch_card(group["title"], [_patch_notes(group["notes"])], " patch-wide")
        for group in notes["general"]
    ]
    for key, heading in (
        ("items", t["patch_items_title"]),
        ("neutral", t["patch_neutral_title"]),
        ("creeps", t["patch_creeps_title"]),
    ):
        if notes[key]:
            body = (
                _patch_entries(notes[key])
                if key != "creeps"
                else _patch_entries([{"name": c["name"], "notes": c["notes"]} for c in notes[key]])
            )
            cards.append(_patch_card(heading, body))
    heroes = sorted(notes["heroes"], key=lambda hero: hero["name"])
    hero_cards = "\n".join(_patch_hero(hero, lang, links, home, up, images) for hero in heroes)
    tiles_html = "\n".join(tiles)
    cards_html = "\n".join(cards)
    rules = (
        f"""      <section class="section section-tight">
        <div class="wrap">
          <div class="news-cards patch-cards">
{cards_html}
          </div>
        </div>
      </section>

"""
        if cards
        else ""
    )
    hero_section = (
        f"""      <section class="section section-tight">
        <div class="wrap">
          <h2 class="patch-section-title">{e(t["patch_heroes_title"])}</h2>
          <div class="news-cards patch-cards">
{hero_cards}
          </div>
        </div>
      </section>

"""
        if heroes
        else ""
    )
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <p class="mode-tag"><a href="{home}news.html">{e(t["list_title"])}</a> · <time datetime="{patch["date"]}">{e(long_date(patch["date"], lang))}</time></p>
          <h1>{e(patch_title(patch, lang))}</h1>
          <p class="lead">{e(t["patch_lead"])}</p>
          <div class="news-tiles">
{tiles_html}
          </div>
        </div>
      </section>

{rules}{hero_section}      <section class="section section-tight">
        <div class="wrap">
          <p class="mode-note news-source"><a href="{valve}" rel="noopener">{e(t["patch_source"].format(version=patch["version"]))}</a></p>
        </div>
      </section>

{_actions(lang, page_url, patch_title(patch, lang), t["patch_share"])}
    </main>"""


def list_main(
    posts: list[dict[str, Any]],
    lang: str,
    home: str,
    up: str,
    images: set[str] | None = None,
    patches: list[dict[str, Any]] | None = None,
    extra: list[tuple[str, str]] | None = None,
) -> str:
    """The news list: meta posts, patches and `extra` (date, item) entries such as
    the heroes of the week (news_hero.py) together, newest first."""
    t = TEXT[lang]
    e = html.escape
    images = images or set()
    entries: list[tuple[str, int, str]] = []
    for post in posts:
        data = summary(post, previous_of(post, posts))
        best = data["win"][0]
        entries.append(
            (
                post["date"],
                0,
                f"""            <a class="mode news-item" href="news/{slug(post)}.html">
              {_picture(best, up, images, "lg")}
              <span class="news-item-text">
                <span class="mode-tag"><time datetime="{post["date"]}">{e(long_date(post["date"], lang))}</time></span>
                <span class="news-item-title">{e(title(post, lang))}</span>
                <span class="mode-note">{e(t["list_top"].format(hero=best["name"], v=percent(best["win"], lang)))}</span>
              </span>
            </a>""",
            )
        )
    for patch in patches or []:
        counts = patch_counts(patch)
        entries.append(
            (
                patch["date"],
                1,
                f"""            <a class="mode news-item" href="news/{patch_slug(patch)}.html">
              <span class="hero-pic hero-pic-lg patch-badge" aria-hidden="true"><small>{e(t["patch_badge"])}</small>{e(patch["version"])}</span>
              <span class="news-item-text">
                <span class="mode-tag"><time datetime="{patch["date"]}">{e(long_date(patch["date"], lang))}</time></span>
                <span class="news-item-title">{e(patch_title(patch, lang))}</span>
                <span class="mode-note">{e(t["patch_list"].format(**counts))}</span>
              </span>
            </a>""",
            )
        )
    entries += [(day, 2, item) for day, item in extra or []]
    items = [html_ for _, _, html_ in sorted(entries, key=lambda item: item[:2], reverse=True)]
    items_html = "\n".join(items)
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <h1>{e(t["list_title"])}</h1>
          <p class="lead">{e(t["list_lead"])}</p>
          <div class="cta-row news-list-cta">
            <a class="btn btn-primary btn-lg" href="{CHANNEL}" rel="noopener">{_icon("send")}<span>{e(t["list_channel"])}</span></a>
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <div class="news-list">
{items_html}
          </div>
          <p class="note"><a href="{up}changelog.html">{e(t["changelog"])}</a></p>
        </div>
      </section>
    </main>"""


# --- the Telegram posts (scripts/news_cards.py) -----------------------------------------


def patch_names(patch: dict[str, Any], key: str, lang: str = "uk") -> list[str]:
    """The names of a patch's changed heroes ("heroes") or items ("items", "neutral")."""
    entries = patch["languages"][lang][key]
    names = [entry["name"] for entry in entries if "name" in entry]
    return sorted(names) if key == "heroes" else names
