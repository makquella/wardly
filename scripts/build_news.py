"""News posts: the weekly meta post and the Telegram channel (scripts/news.py).

    python scripts/build_news.py meta                    # a post from OpenDota for today
    python scripts/build_news.py meta --input stats.json --date 2026-10-10
    python scripts/build_news.py telegram-meta [DATE] [--send] [--out DIR]
    python scripts/build_news.py telegram-hero [--date DATE] [--hero NAME] [--send] [--out DIR]
    python scripts/build_news.py telegram-release 0.55.0 [--send] [--out DIR]
    python scripts/build_news.py patch [VERSION]         # Valve's newest patch notes
    python scripts/build_news.py telegram-patch [VERSION] [--send] [--out DIR]

Channel posts are a picture card with a caption (scripts/news_cards.py); without
a browser to draw the card the post goes as text. `--out DIR` writes the card
and the caption there instead of printing the caption.
`--send` posts to the channel named by TELEGRAM_CHANNEL (@name or a numeric id)
with the bot token TELEGRAM_BOT_TOKEN (the bot must be an admin of the channel).
Neither value is ever printed. `telegram-hero --send` also records the hero in
data/news/hero-week.json, so the next weeks pick someone else.
After `meta` or `patch`, run scripts/build_site.py to write the pages.

`patch` writes data/news/patches/<date>-<version>.json from Valve's datafeed
(the notes in Ukrainian and English, with the names of heroes, abilities and
items) for each patch Valve released after the stored ones, one per run, oldest
first, and otherwise rewrites the newest one for
PATCH_REFRESH_DAYS after its release: Valve fixes its notes and adds the
translation later. Under GitHub Actions it sets the step outputs `version`,
`new` and `changed`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import news  # noqa: E402 - after the scripts path
import news_cards as cards  # noqa: E402
import news_release  # noqa: E402

HERO_WEEK = news.ROOT / "data" / "news" / "hero-week.json"

HERO_STATS = "https://api.opendota.com/api/heroStats"
NOTES = news.ROOT / "docs" / "release-notes"
PATCH_REFRESH_DAYS = 7


def fetch_hero_stats() -> list[dict]:
    request = urllib.request.Request(HERO_STATS, headers={"User-Agent": "Wardly news"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def fetch_feed(path: str) -> dict:
    """One answer of Valve's datafeed (https://www.dota2.com/datafeed/<path>)."""
    request = urllib.request.Request(
        f"{news.VALVE_FEED}/{path}", headers={"User-Agent": "Wardly news"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def _feed_rows(name: str, language: str) -> list[dict]:
    """/herolist, /abilitylist and /itemlist: {"result": {"data": {<list>: [rows]}}}."""
    answer = fetch_feed(f"{name}?language={language}")
    data = (answer.get("result") or answer).get("data") or {}
    rows = next(iter(data.values()), []) if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)]


def feed_names(language: str) -> dict:
    """The names behind the patch notes' ids, in one language."""

    def named(rows: list[dict]) -> dict[int, str]:
        return {
            row["id"]: row.get("name_loc") or row.get("name_english_loc")
            for row in rows
            if row.get("name_loc") or row.get("name_english_loc")
        }

    heroes = {}
    for row in _feed_rows("herolist", language):
        key = str(row.get("name") or "").removeprefix("npc_dota_hero_")
        name = row.get("name_loc") or row.get("name_english_loc")
        if name:
            heroes[row["id"]] = {
                "name": name,
                "key": key if re.fullmatch(r"[a-z0-9_]+", key) else "",
            }
    return {
        "heroes": heroes,
        "abilities": named(_feed_rows("abilitylist", language)),
        "items": named(_feed_rows("itemlist", language)),
    }


def patch_list() -> list[tuple[str, str]]:
    """Valve's patches as (release date, version), oldest first."""
    patches = fetch_feed("patchnoteslist?language=english").get("patches") or []
    dated = sorted(
        (p["patch_timestamp"], p["patch_number"])
        for p in patches
        if isinstance(p, dict)
        and isinstance(p.get("patch_timestamp"), int)
        and isinstance(p.get("patch_number"), str)
    )
    if not dated:
        raise SystemExit("Valve's patch list is empty")
    return [(datetime.fromtimestamp(stamp, UTC).date().isoformat(), v) for stamp, v in dated]


def next_patch(stored: list[dict]) -> str:
    """The oldest patch Valve released after the newest stored one and not stored
    yet (two patches between polls: one per run, none skipped), else the newest
    patch. Nothing stored: the newest only, no back catalogue."""
    patches = patch_list()
    if not stored:
        return patches[-1][1]
    known = {p["version"] for p in stored}
    newest = max(p["date"] for p in stored)
    unseen = [v for day, v in patches if v not in known and day >= newest]
    return unseen[0] if unseen else patches[-1][1]


def fetch_patch(version: str) -> dict:
    """A patch post from Valve's notes; a language Valve does not answer in falls
    back to English."""
    feeds, names = {}, {}
    for lang, language in news.FEED_LANGUAGES.items():
        try:
            feed = fetch_feed(f"patchnotes?version={version}&language={language}")
            if not feed.get("success", True):
                raise ValueError("no success")
            feeds[lang], names[lang] = feed, feed_names(language)
        except (OSError, ValueError) as error:
            if lang == "en":
                raise SystemExit(f"no patch notes for {version}: {error}") from None
            print(f"no {language} patch notes for {version}: English instead")
    feeds.setdefault("uk", feeds["en"])
    names.setdefault("uk", names["en"])
    return news.patch_post(feeds, names)


def write_patch(version: str | None, today: date) -> tuple[dict, bool, bool]:
    """(post, new, changed): the newest patch (or `version`) in data/news/patches."""
    patches = news.load_patches()
    target = version or next_patch(patches)
    stored = next((p for p in patches if p["version"] == target), None)
    if stored and not version:
        age = (today - date.fromisoformat(stored["date"])).days
        if age > PATCH_REFRESH_DAYS:
            print(f"patch {target} is already there")
            return stored, False, False
    post = fetch_patch(target)
    news.PATCHES.mkdir(parents=True, exist_ok=True)
    path = news.PATCHES / f"{post['date']}-{post['version']}.json"
    if stored and stored["date"] != post["date"]:  # Valve moved the patch's date
        (news.PATCHES / f"{stored['date']}-{stored['version']}.json").unlink(missing_ok=True)
    text = json.dumps(post, ensure_ascii=False, indent=1) + "\n"
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(news.ROOT) if news.ROOT in path.parents else path}")
    else:
        print(f"patch {target} has not changed")
    return post, stored is None, changed


def dump(post: dict) -> str:
    """The post as JSON, one hero per line (a readable weekly diff)."""
    head = {key: value for key, value in post.items() if key != "heroes"}
    lines = [json.dumps(hero, ensure_ascii=False) for hero in post["heroes"]]
    body = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    return body + ',\n "heroes": [\n  ' + ",\n  ".join(lines) + "\n ]\n}\n"


def write_meta(stats: list[dict], today: date) -> Path:
    post = news.meta_post(stats, today)
    news.POSTS.mkdir(parents=True, exist_ok=True)
    path = news.POSTS / f"{news.slug(post)}.json"
    path.write_text(dump(post), encoding="utf-8")
    # A new hero has no picture yet: the page shows their initials until one is added.
    posts = news.load_posts()
    data = news.summary(post, news.previous_of(post, posts))
    have = {image.stem for image in news.HERO_IMAGES.glob("*.webp")}
    for key in sorted(news.image_keys(data) - have):
        print(f"no picture site/assets/heroes/{key}.webp: the page shows initials")
    return path


def _telegram() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = os.environ.get("TELEGRAM_CHANNEL", "")
    if not token or not channel:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL are needed to send")
    return token, channel


def send(text: str) -> None:
    token, channel = _telegram()
    body = urllib.parse.urlencode(
        {
            "chat_id": channel,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode()
    _post(
        urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=body, method="POST"
        )
    )


def send_photo(picture: Path, caption: str) -> None:
    """The card with its caption, as multipart/form-data."""
    token, channel = _telegram()
    boundary = "wardly-card-boundary"
    parts = []
    for name, value in (("chat_id", channel), ("caption", caption), ("parse_mode", "HTML")):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="card.png"\r\n'
        "Content-Type: image/png\r\n\r\n".encode()
        + picture.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    _post(
        urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=b"".join(parts),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    )


def _post(request: urllib.request.Request) -> None:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - Telegram API
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # The API's own description says why (never the URL: it holds the token).
        detail = json.loads(error.read().decode("utf-8") or "{}").get("description", "")
        raise SystemExit(f"Telegram refused the post: HTTP {error.code} {detail}") from None
    if not answer.get("ok"):
        raise SystemExit(f"Telegram refused the post: {answer.get('description', '')}")
    print("sent to the Telegram channel")


def publish(
    card: str, caption: str, fallback: str, send_it: bool, out: str | None, name: str
) -> None:
    """Draw the card; send it (or the text post when it cannot be drawn), save it
    with its caption to `out`, or print the caption."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(out) / f"{name}.png" if out else Path(tmp) / f"{name}.png"
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / f"{name}.txt").write_text(caption + "\n", encoding="utf-8")
        drawn = (send_it or bool(out)) and cards.render(card, target)
        if send_it:
            if drawn:
                send_photo(target, caption)
            else:
                send(fallback)
        elif out:
            print(f"wrote {target if drawn else 'no card'} and {Path(out) / f'{name}.txt'}")
        else:
            print(caption)


def load_history() -> list[dict]:
    if not HERO_WEEK.exists():
        return []
    return json.loads(HERO_WEEK.read_text(encoding="utf-8")).get("weeks", [])


def save_history(weeks: list[dict]) -> None:
    HERO_WEEK.write_text(
        json.dumps({"weeks": weeks}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("meta", help="write this week's meta post")
    meta.add_argument("--input", help="a saved /heroStats response instead of fetching it")
    meta.add_argument("--date", help="the post date (YYYY-MM-DD), today by default")
    tg_meta = sub.add_parser("telegram-meta", help="the channel post of a meta post")
    tg_meta.add_argument("date", nargs="?", help="the post date; the newest post by default")
    tg_hero = sub.add_parser("telegram-hero", help="the hero of the week")
    tg_hero.add_argument("--date", help="today by default; uses the newest meta post up to it")
    tg_hero.add_argument("--hero", help="this hero (a name on the site) instead of the pick")
    tg_release = sub.add_parser("telegram-release", help="the channel post of a release")
    tg_release.add_argument("version")
    patch = sub.add_parser("patch", help="write Valve's newest patch notes")
    patch.add_argument("version", nargs="?", help="this patch (e.g. 7.41f) instead of the newest")
    patch.add_argument("--date", help="today (YYYY-MM-DD) for the refresh window")
    tg_patch = sub.add_parser("telegram-patch", help="the channel post of a patch")
    tg_patch.add_argument("version", nargs="?", help="the newest patch by default")
    for command in (tg_meta, tg_hero, tg_release, tg_patch):
        command.add_argument("--send", action="store_true")
        command.add_argument("--out", help="write the card and its caption to this folder")
    args = parser.parse_args()

    if args.command == "meta":
        stats = (
            json.loads(Path(args.input).read_text(encoding="utf-8"))
            if args.input
            else fetch_hero_stats()
        )
        today = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
        path = write_meta(stats, today)
        print(f"wrote {path.relative_to(news.ROOT)}")
        return 0

    if args.command == "patch":
        today = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
        post, new, changed = write_patch(args.version, today)
        outputs = os.environ.get("GITHUB_OUTPUT")
        if outputs:
            with open(outputs, "a", encoding="utf-8") as out:
                out.write(f"version={post['version']}\nnew={str(new).lower()}\n")
                out.write(f"changed={str(changed).lower()}\n")
        return 0

    if args.command == "telegram-patch":
        patches = news.load_patches()
        post = (
            next((p for p in patches if p["version"] == args.version), None)
            if args.version
            else (patches[0] if patches else None)
        )
        if post is None:
            raise SystemExit("no such patch in data/news/patches")
        publish(
            cards.patch_card(post),
            cards.patch_caption(post),
            news.telegram_patch(post),
            args.send,
            args.out,
            f"patch-{post['version']}",
        )
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if args.command == "telegram-meta":
            posts = news.load_posts()
            post = next((p for p in posts if p["date"] == args.date), None) if args.date else None
            post = post or (posts[0] if posts and not args.date else None)
            if post is None:
                raise SystemExit("no such post in data/news/posts")
            data = news.summary(post, news.previous_of(post, posts))
            publish(
                cards.meta_card(post, data, work),
                cards.meta_caption(post, data),
                news.telegram_meta(post, data),
                args.send,
                args.out,
                f"meta-{post['date']}",
            )
        elif args.command == "telegram-hero":
            import build_site as site  # the hero pages' data (needs the backend packages)

            today = args.date or datetime.now(UTC).date().isoformat()
            posts = [p for p in news.load_posts() if p["date"] <= today]
            if not posts:
                raise SystemExit("no meta post up to this date in data/news/posts")
            heroes = site.heroes()
            weeks = load_history()
            if args.hero:
                hero = next((h for h in heroes if h["name"] == args.hero), None)
                if hero is None:
                    raise SystemExit(f"no hero page for {args.hero}")
                found = {h["key"]: h for h in posts[0]["heroes"]}.get(hero["key"])
                matches = sum(h["picks"] for h in posts[0]["heroes"]) / 10 or 1
                stats = (
                    {"win": found["wins"] / found["picks"], "pick": found["picks"] / matches}
                    if found and found["picks"]
                    else None
                )
            else:
                hero, stats = cards.pick_hero(posts[0], heroes, [w["hero"] for w in weeks])
            facts = cards.hero_facts(hero, site)
            caption = cards.hero_caption(hero, facts, stats)
            publish(
                cards.hero_card(hero, facts, stats, work),
                caption,
                caption,
                args.send,
                args.out,
                f"hero-{today}",
            )
            if args.send:
                save_history([*weeks, {"date": today, "hero": hero["name"]}])
        else:
            notes = NOTES / f"v{args.version}.md"
            if not notes.exists():
                raise SystemExit(f"no release notes: {notes.relative_to(news.ROOT)}")
            text = notes.read_text(encoding="utf-8")
            points = cards.release_points(text)
            post = news_release.find(args.version)
            if post:
                # The card lists the release post's sections, the caption links to it.
                title = post["uk"]["title"].split(": ", 1)[-1]
                points = [(title[:1].upper() + title[1:], "")]
                points += [(s["heading"], "") for s in post["uk"]["sections"]]
            publish(
                cards.release_card(args.version, points),
                cards.release_caption(args.version, points, post),
                news.telegram_release(args.version, text),
                args.send,
                args.out,
                f"release-{args.version}",
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
