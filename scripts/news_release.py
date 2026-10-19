"""A Wardly release as a news post: one page per file in data/news/releases.

The file (<date>-<version>.json) holds the post's own words in both languages,
written for players, while docs/release-notes/v<version>.md stays the full list
of changes («Що нового», the changelog). The release Telegram post links here
when the version has a page (scripts/news_cards.release_caption).
"""

from __future__ import annotations

import html
import json
from typing import Any

import news

RELEASES = news.ROOT / "data" / "news" / "releases"


def load_releases() -> list[dict[str, Any]]:
    """Every release post, newest first."""
    posts = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(RELEASES.glob("*.json"))
    ]
    return sorted(posts, key=lambda post: post["date"], reverse=True)


def find(version: str) -> dict[str, Any] | None:
    return next((post for post in load_releases() if post["version"] == version), None)


def slug(post: dict[str, Any]) -> str:
    return f"{post['date']}-release-{post['version'].replace('.', '-')}"


def page_url(post: dict[str, Any], lang: str = "uk") -> str:
    return f"{news.BASE}{'' if lang == 'uk' else '/en'}/news/{slug(post)}.html"


def _number(value: int, lang: str) -> str:
    text = f"{value:,}"
    return text.replace(",", " ") if lang == "uk" else text


def _hero_strip(
    post: dict[str, Any], heroes: dict[str, dict[str, Any]], home: str, up: str, images: set[str]
) -> str:
    e = html.escape
    items = []
    for name in post["heroes"]:
        hero = heroes.get(name)
        row = {"name": name, "key": hero["key"] if hero else ""}
        picture = news._picture(row, up, images, "sm")
        label = f"{picture}<span>{e(name)}</span>"
        items.append(
            f'                <li><a href="{home}heroes/{hero["slug"]}.html">{label}</a></li>'
            if hero
            else f"                <li>{label}</li>"
        )
    return (
        '              <ul class="release-heroes">\n' + "\n".join(items) + "\n              </ul>"
    )


def post_main(
    post: dict[str, Any],
    lang: str,
    heroes: dict[str, dict[str, Any]],
    home: str,
    up: str = "../",
    images: set[str] | None = None,
) -> str:
    t, nt = post[lang], news.TEXT[lang]
    e = html.escape
    images = images or set()
    tiles = "\n".join(
        [
            news._tile("swords", t["tiles"]["heroes"], "", str(len(post["heroes"])), ""),
            news._tile("trophy", t["tiles"]["games"], "", e(_number(post["games"], lang)), ""),
            news._tile("flame", t["tiles"]["patch"], "", "7.41f", "Valve"),
        ]
    )
    cards = "\n".join(
        news._patch_card(
            section["heading"],
            [
                f'              <p class="mode-note news-hint">{e(section["hint"])}</p>',
                news._patch_notes([{"text": item, "level": 1} for item in section["items"]]),
            ],
        )
        for section in t["sections"]
    )
    strip = news._patch_card(
        t["heroes_title"],
        [
            f'              <p class="mode-note news-hint">{e(t["heroes_hint"])}</p>',
            _hero_strip(post, heroes, home, up, images),
        ],
    )
    changelog = (
        f'          <p class="note"><a href="{up}changelog.html#v{e(post["version"])}">'
        f"{e(t['changelog'])}</a></p>"
    )
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <p class="mode-tag"><a href="{home}news.html">{e(nt["list_title"])}</a> · <time datetime="{post["date"]}">{e(news.long_date(post["date"], lang))}</time></p>
          <h1>{e(t["title"])}</h1>
          <p class="lead">{e(t["lead"])}</p>
          <div class="news-tiles">
{tiles}
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <div class="news-cards patch-cards">
{cards}
{strip}
          </div>
{changelog}
        </div>
      </section>

{news._actions(lang, page_url(post, lang), t["title"], t["share_text"])}
    </main>"""


def list_item(post: dict[str, Any], lang: str) -> str:
    """The entry in the news list (news.list_main's `extra`)."""
    t = post[lang]
    e = html.escape
    return f"""            <a class="mode news-item" href="news/{slug(post)}.html">
              <span class="hero-pic hero-pic-lg patch-badge" aria-hidden="true"><small>{e(t["badge"])}</small>{e(post["version"])}</span>
              <span class="news-item-text">
                <span class="mode-tag"><time datetime="{post["date"]}">{e(news.long_date(post["date"], lang))}</time></span>
                <span class="news-item-title">{e(t["title"])}</span>
                <span class="mode-note">{e(t["lead"].split(". ")[0].rstrip(".") + ".")}</span>
              </span>
            </a>"""
