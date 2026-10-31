"""The hero of the week on the site: one page per pick in data/news/hero-week.json.

.github/workflows/hero-week.yml picks the hero every Thursday (scripts/build_news.py
telegram-hero), sends the card to the Telegram channel and records the pick; the
site then shows the same pick as a news post. The numbers come from the newest
meta post up to that day (data/news/posts), the advice from the hero's own page
(scripts/build_site.py), so the post and the hero page never disagree.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

import hero_insights
import news

HERO_WEEK = news.ROOT / "data" / "news" / "hero-week.json"

TEXT = {
    "uk": {
        "title": "Герой тижня: {hero}",
        "lead": "{archetype}.",
        "lead_stats": "Цього тижня в публічних матчах: {win} перемог, у {pick} матчів.",
        "tile_win": "Перемог цього тижня",
        "tile_pick": "Матчів із ним",
        "tile_role": "Позиція",
        "tips": "Що підкаже Wardly",
        "tips_hint": "Ті самі пороги й предмети, що на сторінці героя і в оверлеї під час гри.",
        "low": "Відходь, коли HP нижче {low} %; нижче {critical} % — негайно.",
        "saves": "Рятує: {saves}.",
        "fight": "У бійці: {fight}.",
        "pace": "До 10:00 — {pace} добивань.",
        "hero_page": "Усе про героя",
        "list_note": "{role} · {win} перемог",
        "list_note_plain": "{role}",
        "source": "Джерело цифр: OpenDota, публічні матчі за {period}.",
        "share_text": "Скиньте героя тижня тіммейту, який на ньому грає.",
    },
    "en": {
        "title": "Hero of the week: {hero}",
        "lead": "{archetype}.",
        "lead_stats": "In this week's public matches: {win} win rate, in {pick} of matches.",
        "tile_win": "Win rate this week",
        "tile_pick": "Matches with the hero",
        "tile_role": "Position",
        "tips": "What Wardly tells you",
        "tips_hint": "The same thresholds and items as on the hero page and in the in-game overlay.",
        "low": "Back off below {low}% HP; below {critical}% — right now.",
        "saves": "Saves you: {saves}.",
        "fight": "In a fight: {fight}.",
        "pace": "By 10:00 — {pace} last hits.",
        "hero_page": "All about the hero",
        "list_note": "{role} · {win} win rate",
        "list_note_plain": "{role}",
        "source": "Numbers: OpenDota, public matches of {period}.",
        "share_text": "Send the hero of the week to a teammate who plays them.",
    },
}


def load_weeks() -> list[dict[str, str]]:
    if not HERO_WEEK.exists():
        return []
    return list(json.loads(HERO_WEEK.read_text(encoding="utf-8")).get("weeks", []))


def entries(site_heroes: list[dict[str, Any]], posts: list[dict[str, Any]]) -> list[dict]:
    """Each recorded pick with a site page: {date, hero, stats, post}, newest first.
    `stats` (win, pick) come from the newest meta post up to that day, else None."""
    by_name = {hero["name"]: hero for hero in site_heroes}
    out = []
    for week in load_weeks():
        hero = by_name.get(week.get("hero", ""))
        day = week.get("date", "")
        if hero is None or not day:
            continue
        post = next((p for p in posts if p["date"] <= day), None)  # posts: newest first
        stats = None
        if post:
            matches = sum(h["picks"] for h in post["heroes"]) / 10 or 1
            found = next((h for h in post["heroes"] if h.get("key") == hero["key"]), None)
            if found and found["picks"]:
                stats = {
                    "win": found["wins"] / found["picks"],
                    "pick": found["picks"] / matches,
                }
        out.append({"date": day, "hero": hero, "stats": stats, "post": post})
    # One page per day: a re-run of the same day keeps the later pick.
    unique = {entry["date"]: entry for entry in out}
    return sorted(unique.values(), key=lambda entry: entry["date"], reverse=True)


def slug(entry: dict[str, Any]) -> str:
    return f"{entry['date']}-hero-{entry['hero']['slug']}"


def facts(hero: dict[str, Any], site: Any, lang: str) -> dict[str, Any]:
    """The hero page's facts in one language (scripts/build_site.py data)."""
    profile = hero["profile"]
    archetype = site.ARCHETYPES[profile["archetype"]][0 if lang == "uk" else 1]
    notes = site.NOTES_UK if lang == "uk" else site.NOTES_EN
    return {
        "role": site.POSITION_NAMES[lang][hero["position"]],
        "archetype": archetype,
        "low": str(profile["low_hp_warning_threshold"]),
        "critical": str(profile["critical_hp_threshold"]),
        "saves": ", ".join(hero["saves"]),
        "fight": ", ".join(profile.get("key_fight_abilities") or []),
        "pace": next((f"{low}–{high}" for minute, low, high in hero["pace"] if minute == 10), ""),
        "note": notes.get(hero["name"], ""),
        "insights": hero_insights.facts(hero["name"], hero["position"]),
    }


def title(entry: dict[str, Any], lang: str) -> str:
    return TEXT[lang]["title"].format(hero=entry["hero"]["name"])


def lead(entry: dict[str, Any], fact: dict[str, Any], lang: str) -> str:
    t = TEXT[lang]
    archetype = fact["archetype"]
    text = t["lead"].format(archetype=archetype[:1].upper() + archetype[1:])
    if entry["stats"]:
        text += " " + t["lead_stats"].format(
            win=news.percent(entry["stats"]["win"], lang),
            pick=news.percent(entry["stats"]["pick"], lang),
        )
    return text


def post_main(
    entry: dict[str, Any],
    fact: dict[str, Any],
    lang: str,
    home: str,
    up: str = "../",
    images: set[str] | None = None,
) -> str:
    t, nt = TEXT[lang], news.TEXT[lang]
    e = html.escape
    hero = entry["hero"]
    row = {"name": hero["name"], "key": hero["key"]}
    picture = news._picture(row, up, images or set(), "lg")
    tiles = [news._tile("swords", t["tile_role"], picture, e(hero["name"]), fact["role"])]
    if entry["stats"]:
        tiles += [
            news._tile(
                "trophy", t["tile_win"], "", e(news.percent(entry["stats"]["win"], lang)), ""
            ),
            news._tile(
                "flame", t["tile_pick"], "", e(news.percent(entry["stats"]["pick"], lang)), ""
            ),
        ]
    found = fact["insights"]
    if found:
        # What wins on the hero, in numbers (the same rows as the Telegram card).
        heading, hint = hero_insights.TEXT[lang]["heading"], hero_insights.source(found, lang)
        notes = [
            {"text": html.unescape(re.sub(r"</?b>", "", text)), "info": sub, "level": 1}
            for _kind, text, sub in hero_insights.rows(found, lang)
        ]
    else:
        tips = [t["low"].format(low=fact["low"], critical=fact["critical"])]
        for key in ("saves", "fight", "pace"):
            if fact[key]:
                tips.append(t[key].format(**{key: fact[key]}))
        if fact["note"]:
            tips.append(fact["note"])
        heading, hint = t["tips"], t["tips_hint"]
        notes = [{"text": tip, "level": 1} for tip in tips]
    card = news._patch_card(
        heading,
        [
            f'              <p class="mode-note news-hint">{e(hint)}</p>',
            news._patch_notes(notes),
            f'              <div class="cta-row"><a class="btn btn-outline btn-lg" '
            f'href="{home}heroes/{hero["slug"]}.html">{e(t["hero_page"])} →</a></div>',
        ],
    )
    source = (
        f'\n          <p class="mode-note news-source">'
        f"{e(t['source'].format(period=news.period(entry['post'], lang)))}</p>"
        if entry["stats"] and entry["post"]
        else ""
    )
    page_url = f"{news.BASE}{'' if lang == 'uk' else '/en'}/news/{slug(entry)}.html"
    tiles_html = "\n".join(tiles)
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <p class="mode-tag"><a href="{home}news.html">{e(nt["list_title"])}</a> · <time datetime="{entry["date"]}">{e(news.long_date(entry["date"], lang))}</time></p>
          <h1>{e(title(entry, lang))}</h1>
          <p class="lead">{e(lead(entry, fact, lang))}</p>
          <div class="news-tiles">
{tiles_html}
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
{card}{source}
        </div>
      </section>

{news._actions(lang, page_url, title(entry, lang), t["share_text"])}
    </main>"""


def list_item(
    entry: dict[str, Any], fact: dict[str, Any], lang: str, up: str, images: set[str]
) -> str:
    """The entry in the news list (news.list_main's `extra`)."""
    t = TEXT[lang]
    e = html.escape
    hero = entry["hero"]
    note = (
        t["list_note"].format(role=fact["role"], win=news.percent(entry["stats"]["win"], lang))
        if entry["stats"]
        else t["list_note_plain"].format(role=fact["role"])
    )
    picture = news._picture({"name": hero["name"], "key": hero["key"]}, up, images, "lg")
    return f"""            <a class="mode news-item" href="news/{slug(entry)}.html">
              {picture}
              <span class="news-item-text">
                <span class="mode-tag"><time datetime="{entry["date"]}">{e(news.long_date(entry["date"], lang))}</time></span>
                <span class="news-item-title">{e(title(entry, lang))}</span>
                <span class="mode-note">{e(note)}</span>
              </span>
            </a>"""
