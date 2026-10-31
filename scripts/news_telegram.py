"""A release's Telegram post, written for players: data/news/telegram/<version>.json.

docs/release-notes/v<version>.md is the full list of changes («Що нового»); its
bold headlines name changes for the changelog, not for a channel reader. The
channel gets its own short post instead, in Ukrainian (the channel's language):

    {
      "version": "0.61.0",
      "headline": "the promise, on the card and first in the caption",
      "example": {"title": "...", "body": "..."},   # optional: a hint as the overlay shows it
      "scene": "forest",                             # optional: site/assets/game/<scene>.jpg behind it
      "text": "the caption's body: **bold**, *italic*, [text](https://...) and blank lines"
    }

Every minor release (0.X.0) has one (scripts/bump_version.py --check); a fix
(0.X.Y) is not posted unless it has one. scripts/build_news.py telegram-release
draws the card (news_cards.release_card) and sends the caption.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

import news

POSTS = news.ROOT / "data" / "news" / "telegram"
# Telegram's caption limit for a photo, counted without the HTML tags.
CAPTION_LIMIT = 1024
HEADLINE_LIMIT = 70
EXAMPLE_LIMIT = 90
URL = re.compile(r"https://[^\s)]+")
SCENES = news.ROOT / "site" / "assets" / "game"


def path(version: str, root: Path | None = None) -> Path:
    folder = POSTS if root is None else root / "data" / "news" / "telegram"
    return folder / f"{version}.json"


def load(version: str, root: Path | None = None) -> dict[str, Any] | None:
    file = path(version, root)
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None


def is_fix(version: str) -> bool:
    """0.61.1 is a fix; 0.61.0 is a minor release."""
    return not version.endswith(".0")


def markup(text: str) -> str:
    """The post's text as Telegram HTML: **bold**, *italic*, [text](https://...)."""
    out = html.escape(text, quote=False)
    out = re.sub(
        r"\[([^\]]+)\]\((https://[^)\s]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        out,
    )
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    return re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", out)


def visible_length(text: str) -> int:
    """What Telegram counts toward the caption limit: the text without the HTML tags."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


def links(post: dict[str, Any], release_post: dict[str, Any] | None = None) -> list[str]:
    """The caption's tail: where to get it and where to read more."""
    version = html.escape(post["version"], quote=False)
    parts = [f'⬇️ <a href="{news.BASE}/?ref=tg">Завантажити</a>']
    if release_post:
        import news_release

        parts.append(f'<a href="{news_release.page_url(release_post)}?ref=tg">Докладніше</a>')
    parts.append(f'<a href="{news.BASE}/changelog.html?ref=tg#v{version}">Усі зміни</a>')
    return [
        " · ".join(parts),
        "<i>Встановлений Wardly оновиться сам, щойно закриєте Доту.</i>",
    ]


def caption(post: dict[str, Any], release_post: dict[str, Any] | None = None) -> str:
    lines = [
        f"<b>{html.escape(post['headline'], quote=False)}</b>",
        "",
        markup(post["text"].strip()),
        "",
        *links(post, release_post),
    ]
    return "\n".join(lines)


def validate(post: Any, version: str | None = None) -> list[str]:
    """What is wrong with a post (empty when it is fine to send)."""
    if not isinstance(post, dict):
        return ["the post is not a JSON object"]
    problems = []
    for key in ("version", "headline", "text"):
        if not isinstance(post.get(key), str) or not post[key].strip():
            problems.append(f"«{key}» must be a nonempty string")
    if problems:
        return problems
    if version is not None and post["version"] != version:
        problems.append(f"«version» is {post['version']!r}, the file is for {version!r}")
    if len(post["headline"]) > HEADLINE_LIMIT:
        problems.append(f"«headline» is over {HEADLINE_LIMIT} characters: it must fit the card")
    example = post.get("example")
    if example is not None:
        if not isinstance(example, dict) or not all(
            isinstance(example.get(k), str) and example[k].strip() for k in ("title", "body")
        ):
            problems.append("«example» needs a nonempty «title» and «body»")
        elif max(len(example["title"]), len(example["body"])) > EXAMPLE_LIMIT:
            problems.append(f"«example» lines are over {EXAMPLE_LIMIT} characters")
    scene = post.get("scene")
    if scene is not None and (
        not isinstance(scene, str)
        or not re.fullmatch(r"[a-z]+", scene)
        or not (SCENES / f"{scene}.jpg").is_file()
    ):
        problems.append(f"«scene» must name a picture in {SCENES.relative_to(news.ROOT)}")
    unknown = set(post) - {"version", "headline", "example", "scene", "text"}
    if unknown:
        problems.append(f"unknown fields: {', '.join(sorted(unknown))}")
    if any(
        not url.startswith(news.BASE) and "t.me/" not in url for url in URL.findall(post["text"])
    ):
        problems.append(f"links in «text» go to {news.BASE} or t.me only")
    # The longest caption: with the release news post's link too.
    longest = caption(post, {"date": "2000-01-01", "version": post["version"]})
    if visible_length(longest) > CAPTION_LIMIT:
        problems.append(
            f"the caption is {visible_length(longest)} characters; Telegram allows {CAPTION_LIMIT}"
        )
    return problems
