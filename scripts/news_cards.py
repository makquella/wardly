"""Picture posts for the Telegram channel: a card and a short caption.

Each post is a 1080×1350 PNG card in the site's style (dark, the logo's red,
Montserrat and Inter from site/assets/fonts) with a caption of at most 1024
characters, Telegram's limit for a photo. The card is HTML drawn by headless
Chrome (`CHROME`, else Chrome or Chromium found on the machine; GitHub's Ubuntu
and Windows runners have Chrome). Without a browser, or when drawing fails,
scripts/build_news.py sends the old text post instead.

Hero pictures: the big transparent renders from Valve's CDN, else the small
picture in site/assets/heroes.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request
import zlib
from pathlib import Path
from typing import Any

import news

SITE = news.ROOT / "site"
FONTS = SITE / "assets" / "fonts"
WIDTH, HEIGHT = 1080, 1350
# Headless Chrome's page is shorter than its window (by 87 px in Chrome 141), so the
# window is taller by this much and the screenshot is cut back to HEIGHT.
WINDOW_EXTRA = 240
CAPTION_LIMIT = 1024
CHANNEL = "@wardlydota"
RENDER_URL = (
    "https://cdn.cloudflare.steamstatic.com/apps/dota2/videos/dota_react/heroes/renders/{key}.png"
)
# A hero of the week is picked in at least this share of matches, and not one of
# the last HERO_REPEAT heroes.
HERO_MIN_PICK = 0.03
HERO_REPEAT = 8
WINDOWS_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

ICON = dict(news._ICON)
ICON.update(
    {
        "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />',
        "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />',
        "coins": '<circle cx="8" cy="8" r="6" /><path d="M18.09 10.37A6 6 0 1 1 10.34 18" /><path d="M7 6h1v4" /><path d="m16.71 13.88.7.71-2.82 2.82" />',
        "spark": '<path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z" />',
        "check": '<circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" />',
    }
)


def escape(text: str) -> str:
    """Telegram HTML: only <, > and & need escaping in text."""
    return html.escape(text, quote=False)


def icon(name: str) -> str:
    return (
        '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICON[name]}</svg>'
    )


# --- drawing ---------------------------------------------------------------------------


def find_chrome() -> str | None:
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return next((path for path in WINDOWS_CHROME if Path(path).exists()), None)


def render(page: str, out: Path) -> bool:
    """Draw the card into `out` (PNG); False when there is no browser or it failed."""
    chrome = find_chrome()
    if not chrome:
        print("no Chrome for the card: the post goes as text")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "card.html"
        source.write_text(page, encoding="utf-8")
        command = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={WIDTH},{HEIGHT + WINDOW_EXTRA}",
            "--virtual-time-budget=8000",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--screenshot={out.resolve()}",
            source.as_uri(),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=120)  # noqa: S603 - our own HTML
        except (OSError, subprocess.SubprocessError) as error:
            print(f"the card was not drawn ({type(error).__name__}): the post goes as text")
            return False
    return out.exists() and crop_png(out, HEIGHT)


def crop_png(path: Path, height: int) -> bool:
    """Keep the top `height` rows of an 8-bit, non-interlaced PNG. Each row only
    refers to the rows above it, so the first rows of the image data stay valid
    as they are: no decoding of pixels is needed."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    chunks, pos = [], 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks.append((kind, data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    head = chunks[0][1]
    width, full, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", head)
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color)
    if depth != 8 or interlace or channels is None or full < height:
        return False
    rows = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    kept = rows[: height * (1 + width * channels)]

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    path.write_bytes(
        data[:8]
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(kept, 9))
        + chunk(b"IEND", b"")
    )
    return True


def hero_picture(key: str, workdir: Path) -> tuple[str, bool]:
    """(file URI, is_render): Valve's big render, else the small site picture."""
    target = workdir / f"{key}.png"
    try:
        request = urllib.request.Request(
            RENDER_URL.format(key=key), headers={"User-Agent": "Wardly news"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
            target.write_bytes(response.read())
        return target.as_uri(), True
    except OSError:
        small = news.HERO_IMAGES / f"{key}.webp"
        return (small.as_uri() if small.exists() else ""), False


def small_picture(key: str) -> str:
    path = news.HERO_IMAGES / f"{key}.webp"
    return path.as_uri() if path.exists() else ""


STYLE = """
@font-face { font-family: Montserrat; font-weight: 100 900; src: url("{fonts}/montserrat-cyrillic-wght-normal.woff2") format("woff2"); unicode-range: U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116; }
@font-face { font-family: Montserrat; font-weight: 100 900; src: url("{fonts}/montserrat-latin-wght-normal.woff2") format("woff2"); }
@font-face { font-family: Inter; font-weight: 100 900; src: url("{fonts}/inter-cyrillic-wght-normal.woff2") format("woff2"); unicode-range: U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116; }
@font-face { font-family: Inter; font-weight: 100 900; src: url("{fonts}/inter-latin-wght-normal.woff2") format("woff2"); }
:root { --bg: #0c0d0f; --card: #17181c; --line: rgba(255,255,255,.08); --text: #f3f3f4; --muted: #a0a2a9;
  --faint: #6d7078; --accent: #f05560; --fill: #d23a46; --cream: #efe5d4; --green: #4ade80; }
* { box-sizing: border-box; }
html { background: #0c0d0f; }
body { margin: 0; width: 1080px; height: 1350px; overflow: hidden; }
body { position: relative; background: var(--bg); color: var(--text); font: 400 28px/1.35 Inter, sans-serif;
  -webkit-font-smoothing: antialiased; }
.glow { position: absolute; inset: 0; z-index: 0;
  background: radial-gradient(900px 700px at 92% 8%, rgba(240,85,96,.30), transparent 60%),
              radial-gradient(700px 600px at -10% 105%, rgba(239,229,212,.07), transparent 60%); }
.grain { position: absolute; inset: 0; z-index: 0; opacity: .5;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 54px 54px; mask-image: linear-gradient(180deg, #000 0%, transparent 70%); }
.layer { position: relative; z-index: 2; }
.top { position: absolute; top: 0; left: 0; right: 0; z-index: 5; height: 128px; padding: 0 64px;
  display: flex; align-items: center; justify-content: space-between; }
.brand { display: flex; align-items: center; gap: 16px; font: 800 36px/1 Montserrat, sans-serif; letter-spacing: -.01em; }
.brand img { width: 52px; height: 52px; }
.pill { display: inline-flex; align-items: center; gap: 10px; padding: 12px 22px; border-radius: 999px;
  background: rgba(240,85,96,.14); border: 1px solid rgba(240,85,96,.45); color: var(--accent);
  font: 800 22px/1 Montserrat, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.pill .ic { width: 24px; height: 24px; }
.ic { width: 32px; height: 32px; flex: none; }
.foot { position: absolute; left: 0; right: 0; bottom: 0; z-index: 5; height: 112px; padding: 0 64px;
  display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--line);
  background: rgba(12,13,15,.86); color: var(--muted); font-size: 24px; }
.foot b { color: var(--text); font-weight: 600; }
.foot .site { color: var(--accent); font: 700 26px/1 Montserrat, sans-serif; }
.num { font-variant-numeric: tabular-nums; }
"""


def page(body: str, css: str) -> str:
    logo = (SITE / "assets" / "logo-mark.png").as_uri()
    base = STYLE.replace("{fonts}", FONTS.as_uri())
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><style>{base}{css}</style></head>
<body><div class="glow"></div><div class="grain"></div>
<header class="top"><div class="brand"><img src="{logo}" alt="">Wardly</div>{{pill}}</header>
{body}
<footer class="foot"><span><b>Безкоштовний тренер для Dota 2</b> · підказки просто в матчі</span><span class="site">luhovyimvp.dev</span></footer>
</body></html>"""


def _pill(name: str, text: str) -> str:
    return f'<div class="pill">{icon(name)}{html.escape(text)}</div>'


def _name_size(name: str, large: int, steps: tuple[tuple[int, int], ...]) -> int:
    for length, size in steps:
        if len(name) > length:
            return size
    return large


# --- the meta of the week --------------------------------------------------------------

META_CSS = """
.head { position: absolute; top: 150px; left: 64px; right: 64px; }
.head h1 { margin: 0; font: 800 84px/1 Montserrat, sans-serif; letter-spacing: -.02em; }
.head p { margin: 16px 0 0; color: var(--muted); font-size: 28px; }
.spot { position: absolute; top: 340px; left: 64px; right: 64px; height: 420px; border-radius: 28px;
  overflow: hidden; border: 1px solid rgba(240,85,96,.35);
  background: linear-gradient(120deg, #1b1c21 0%, #1b1c21 45%, rgba(210,58,70,.35) 100%); }
.spot .art { position: absolute; right: -40px; bottom: -40px; height: 520px; width: auto;
  filter: drop-shadow(0 20px 40px rgba(0,0,0,.6)); }
.spot .art.small { right: 36px; bottom: 60px; height: auto; width: 420px; border-radius: 18px; }
.spot .copy { position: absolute; left: 48px; top: 48px; width: 540px; }
.label { display: flex; align-items: center; gap: 12px; color: var(--accent);
  font: 800 22px/1 Montserrat, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.label .ic { width: 28px; height: 28px; }
.spot h2 { margin: 22px 0 0; font: 800 var(--name, 64px)/1.02 Montserrat, sans-serif; letter-spacing: -.02em; }
.spot .big { margin-top: 30px; font: 800 128px/1 Montserrat, sans-serif; color: var(--accent); letter-spacing: -.03em; }
.spot .sub { margin-top: 14px; color: var(--muted); font-size: 26px; }
.cols { position: absolute; top: 800px; left: 64px; right: 64px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
.col { padding: 26px 24px 18px; border-radius: 22px; background: var(--card); border: 1px solid var(--line); }
.col h3 { display: flex; align-items: center; gap: 10px; margin: 0 0 18px; font: 800 24px/1.1 Montserrat, sans-serif; }
.col h3 .ic { width: 28px; height: 28px; color: var(--accent); }
.col.up h3 .ic { color: var(--green); }
.row { display: grid; grid-template-columns: 72px 1fr; gap: 14px; align-items: center; padding: 10px 0;
  border-top: 1px solid var(--line); }
.row img, .row .none { width: 72px; height: 41px; border-radius: 8px; object-fit: cover; background: #23242a; }
.row .n { font-size: 22px; font-weight: 600; line-height: 1.15; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row .v { font-size: 22px; color: var(--muted); margin-top: 2px; }
.col.up .v { color: var(--green); }
.col.down .v { color: var(--accent); }
.cta { position: absolute; left: 64px; right: 64px; top: 1150px; display: flex; align-items: center; gap: 14px;
  color: var(--muted); font-size: 26px; }
.cta .ic { color: var(--accent); }
.cta b { color: var(--text); }
"""


def _rows(rows: list[dict[str, Any]], value: str, lang: str = "uk") -> str:
    out = []
    for row in rows[:3]:
        if value == "change":
            shown = news.points(row["change"], lang)
        else:
            shown = news.percent(row[value], lang)
        src = small_picture(row.get("key") or "")
        picture = f'<img src="{src}" alt="">' if src else '<span class="none"></span>'
        out.append(
            f'<div class="row num">{picture}<div><div class="n">{html.escape(row["name"])}</div>'
            f'<div class="v">{html.escape(shown)}</div></div></div>'
        )
    return "".join(out)


def meta_card(post: dict[str, Any], data: dict[str, Any], workdir: Path) -> str:
    t = news.TEXT["uk"]
    top = data["win"][0]
    art, big = hero_picture(top.get("key") or "", workdir)
    art_tag = f'<img class="art{"" if big else " small"}" src="{art}" alt="">' if art else ""
    size = _name_size(top["name"], 72, ((16, 54), (12, 62)))
    cols = [
        ("flame", t["pick_title"], data["pick"], "pick", ""),
        ("up", t["up_title"], data["up"], "change", "up"),
        ("down", t["down_title"], data["down"], "change", "down"),
    ]
    shown = [c for c in cols if c[2]]  # a first post may have no movers
    columns = "".join(
        f'<div class="col {tone}"><h3>{icon(name)}{html.escape(heading)}</h3>{_rows(rows, value)}</div>'
        for name, heading, rows, value, tone in shown
    )
    body = f"""
<section class="layer head"><h1>{html.escape(news.period(post, "uk"))}</h1>
<p>{html.escape(news.matches_text(data["matches"], "uk"))} публічних матчів · дані OpenDota, усі ранги</p></section>
<section class="layer spot">{art_tag}
  <div class="copy"><div class="label">{icon("trophy")}{html.escape(t["tile_win"])}</div>
  <h2 style="--name: {size}px">{html.escape(top["name"])}</h2>
  <div class="big num">{html.escape(news.percent(top["win"], "uk"))}</div>
  <div class="sub num">перемог · у {html.escape(news.percent(top["pick"], "uk"))} матчів тижня</div></div>
</section>
<section class="layer cols" style="grid-template-columns: repeat({len(shown)}, 1fr)">{columns}</section>
<section class="layer cta">{icon("spark")}<span>Граєте на цих героях? <b>Wardly</b> підкаже темп і предмети просто в матчі</span></section>"""
    return page(body, META_CSS).replace("{pill}", _pill("trophy", "Мета тижня"))


def meta_caption(post: dict[str, Any], data: dict[str, Any]) -> str:
    t = news.TEXT["uk"]
    e = escape

    def line(emoji: str, heading: str, rows: list[dict[str, Any]], value: str) -> str | None:
        if not rows:
            return None
        if value == "change":
            items = [f"{e(r['name'])} {e(news.points(r['change'], 'uk'))}" for r in rows[:3]]
        else:
            items = [f"{e(r['name'])} {e(news.percent(r[value], 'uk'))}" for r in rows[:3]]
        return f"{emoji} <b>{e(heading)}:</b> " + " · ".join(items)

    lines = [
        f"📊 <b>Мета тижня · {e(news.period(post, 'uk'))}</b>",
        f"<i>{e(news.matches_text(data['matches'], 'uk'))} публічних матчів, дані OpenDota</i>",
        "",
    ]
    for item in (
        line("🏆", t["win_title"], data["win"], "win"),
        line("🔥", t["pick_title"], data["pick"], "pick"),
        line("📈", t["up_title"], data["up"], "change"),
        line("📉", t["down_title"], data["down"], "change"),
    ):
        if item:
            lines.append(item)
    lines += [
        "",
        f'👉 <a href="{news.BASE}/news/{news.slug(post)}.html?ref=tg">Повна таблиця на сайті</a>',
        f'🎮 <a href="{news.BASE}/?ref=tg">Wardly</a> — безкоштовний тренер, що підказує просто в матчі',
        "",
        "#мета_тижня #dota2",
    ]
    return fit("\n".join(lines))


# --- the hero of the week --------------------------------------------------------------

HERO_CSS = """
.art { position: absolute; z-index: 1; right: -170px; top: 70px; width: 980px; height: auto;
  filter: drop-shadow(0 30px 60px rgba(0,0,0,.65));
  -webkit-mask-image: linear-gradient(180deg, #000 58%, transparent 80%); }
.art.small { right: 64px; top: 190px; width: 520px; border-radius: 24px; }
.halo { position: absolute; z-index: 0; right: -120px; top: 120px; width: 900px; height: 900px; border-radius: 50%;
  background: radial-gradient(circle, rgba(240,85,96,.42) 0%, rgba(240,85,96,.10) 45%, transparent 70%); }
.fade { position: absolute; z-index: 1; left: 0; right: 0; top: 560px; height: 260px;
  background: linear-gradient(180deg, transparent, var(--bg) 85%); }
.copy { position: absolute; z-index: 3; left: 64px; top: 160px; width: 560px; }
.role { display: inline-block; padding: 10px 18px; border-radius: 12px; background: rgba(255,255,255,.08);
  color: var(--cream); font: 700 24px/1 Montserrat, sans-serif; letter-spacing: .06em; text-transform: uppercase; }
.copy h1 { margin: 22px 0 0; font: 800 var(--name, 104px)/.98 Montserrat, sans-serif; letter-spacing: -.03em;
  text-shadow: 0 6px 30px rgba(0,0,0,.6); }
.copy p { margin: 22px 0 0; color: var(--muted); font-size: 30px; line-height: 1.35; text-shadow: 0 2px 12px rgba(0,0,0,.8); }
.stats { display: flex; gap: 14px; margin-top: 30px; }
.stat { padding: 16px 20px; border-radius: 16px; background: rgba(23,24,28,.88); border: 1px solid var(--line); }
.stat b { display: block; font: 800 44px/1 Montserrat, sans-serif; color: var(--accent); }
.stat span { display: block; margin-top: 8px; color: var(--muted); font-size: 20px; }
.tips { position: absolute; z-index: 3; left: 64px; right: 64px; top: 700px; padding: 28px 34px 16px;
  border-radius: 26px; background: rgba(23,24,28,.92); border: 1px solid var(--line);
  box-shadow: 0 20px 60px rgba(0,0,0,.45); }
.tips h3 { margin: 0 0 8px; color: var(--accent); font: 800 22px/1 Montserrat, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.tip { display: grid; grid-template-columns: 48px 1fr; gap: 16px; align-items: start; padding: 13px 0; border-top: 1px solid var(--line); }
.tip:first-of-type { border-top: 0; }
.tip .ic { width: 34px; height: 34px; color: var(--accent); margin-top: 2px; }
.tip div { font-size: 27px; line-height: 1.3; }
.tip b { color: var(--text); }
.tip small { display: block; color: var(--muted); font-size: 22px; margin-top: 2px; }
"""


def pick_hero(
    post: dict[str, Any], site_heroes: list[dict[str, Any]], history: list[str]
) -> tuple[dict[str, Any], dict[str, float] | None]:
    """The week's hero: the best win rate among heroes with a site page, picked in
    at least HERO_MIN_PICK of matches and not among the last HERO_REPEAT heroes."""
    matches = sum(h["picks"] for h in post["heroes"]) / 10 or 1
    # By the picture key: the site and OpenDota may name a hero differently.
    stats = {
        h["key"]: {"win": h["wins"] / h["picks"], "pick": h["picks"] / matches}
        for h in post["heroes"]
        if h["picks"] and h.get("key")
    }
    recent = set(history[-HERO_REPEAT:])
    known = [h for h in site_heroes if h["key"] in stats]
    ranked = sorted(known, key=lambda h: stats[h["key"]]["win"], reverse=True)
    for wanted in (
        lambda h: stats[h["key"]]["pick"] >= HERO_MIN_PICK and h["name"] not in recent,
        lambda h: h["name"] not in recent,
        lambda h: True,
    ):
        found = next((h for h in ranked if wanted(h)), None)
        if found:
            return found, stats[found["key"]]
    hero = next(h for h in site_heroes if h["name"] not in recent) if site_heroes else None
    if hero is None:
        raise SystemExit("no heroes with a site page")
    return hero, None


def hero_facts(hero: dict[str, Any], site: Any) -> dict[str, str]:
    """The hero page's numbers, short: role, archetype, HP, saves, fight, pace, tip."""
    profile = hero["profile"]
    pace = next((f"{low}–{high}" for minute, low, high in hero["pace"] if minute == 10), "")
    return {
        "role": site.POSITION_NAMES["uk"][hero["position"]],
        "archetype": site.ARCHETYPES[profile["archetype"]][0],
        "low": str(profile["low_hp_warning_threshold"]),
        "critical": str(profile["critical_hp_threshold"]),
        "saves": ", ".join(hero["saves"]),
        "fight": ", ".join(profile["key_fight_abilities"]),
        "pace": pace,
        "note": site.NOTES_UK[hero["name"]],
    }


def hero_card(
    hero: dict[str, Any], facts: dict[str, str], stats: dict[str, float] | None, workdir: Path
) -> str:
    e = escape
    art, big = hero_picture(hero["key"], workdir)
    art_tag = (
        f'<div class="halo"></div><img class="art{"" if big else " small"}" src="{art}" alt="">'
        if art
        else ""
    )
    size = _name_size(hero["name"], 104, ((16, 66), (12, 78), (9, 92)))
    chips = ""
    if stats:
        chips = (
            f'<div class="stats num"><div class="stat"><b>{e(news.percent(stats["win"], "uk"))}</b><span>перемог цього тижня</span></div>'
            f'<div class="stat"><b>{e(news.percent(stats["pick"], "uk"))}</b><span>матчів із ним</span></div></div>'
        )
    tips = [
        (
            "heart",
            f"Відходь, коли HP нижче <b>{facts['low']} %</b>",
            f"нижче {facts['critical']} % — тренер скаже «терміново»",
        ),
    ]
    if facts["saves"]:
        tips.append(
            ("shield", f"Рятує: <b>{e(facts['saves'])}</b>", "тренер назве, коли воно готове")
        )
    if facts["fight"]:
        tips.append(("swords", f"У бійці: <b>{e(facts['fight'])}</b>", ""))
    if facts["pace"]:
        tips.append(
            ("coins", f"До 10:00 — <b>{e(facts['pace'])}</b> добивань", "темп для цієї позиції")
        )
    tips.append(("spark", e(facts["note"]), ""))
    rows = "".join(
        f'<div class="tip">{icon(name)}<div>{text}{f"<small>{e(sub)}</small>" if sub else ""}</div></div>'
        for name, text, sub in tips[:5]
    )
    body = f"""{art_tag}<div class="fade"></div>
<section class="copy"><span class="role">{e(facts["role"])}</span>
<h1 style="--name: {size}px">{e(hero["name"])}</h1>
<p>{e(facts["archetype"][0].upper() + facts["archetype"][1:])}</p>{chips}</section>
<section class="tips"><h3>Що підкаже Wardly</h3>{rows}</section>"""
    return page(body, HERO_CSS).replace("{pill}", _pill("swords", "Герой тижня"))


def hero_caption(
    hero: dict[str, Any], facts: dict[str, str], stats: dict[str, float] | None
) -> str:
    e = escape
    lines = [
        f"⚔️ <b>Герой тижня: {e(hero['name'])}</b>",
        f"<i>{e(facts['role'])} — {e(facts['archetype'])}</i>",
        "",
    ]
    if stats:
        lines += [
            f"📊 Цього тижня: <b>{e(news.percent(stats['win'], 'uk'))}</b> перемог, "
            f"у <b>{e(news.percent(stats['pick'], 'uk'))}</b> матчів",
            "",
        ]
    lines.append(
        f"❤️ Відходь, коли HP нижче <b>{facts['low']} %</b>; нижче <b>{facts['critical']} %</b> — негайно"
    )
    if facts["saves"]:
        lines.append(f"🛡 Рятує: <b>{e(facts['saves'])}</b>")
    if facts["fight"]:
        lines.append(f"💥 У бійці: <b>{e(facts['fight'])}</b>")
    if facts["pace"]:
        lines.append(f"🌾 До 10:00 — <b>{e(facts['pace'])}</b> добивань")
    lines.append(f"💡 {e(facts['note'])}")
    lines += [
        "",
        f'📖 <a href="{news.BASE}/heroes/{hero["slug"]}.html?ref=tg">Усе про героя на сайті</a>',
        f'🎮 <a href="{news.BASE}/?ref=tg">Wardly</a> підкаже це просто в грі — безкоштовно',
        "",
        "#герой_тижня #dota2",
    ]
    return fit("\n".join(lines))


# --- a new version ---------------------------------------------------------------------

RELEASE_CSS = """
.head { position: absolute; top: 170px; left: 64px; right: 64px; }
.kicker { color: var(--muted); font: 700 34px/1 Montserrat, sans-serif; }
.ver { margin-top: 10px; font: 800 168px/1 Montserrat, sans-serif; letter-spacing: -.04em;
  background: linear-gradient(90deg, #fff 0%, var(--cream) 40%, var(--accent) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.list { position: absolute; top: 470px; left: 64px; right: 64px; display: grid; gap: 18px; }
.item { display: grid; grid-template-columns: 44px 1fr; gap: 18px; align-items: start; padding: 22px 26px;
  border-radius: 20px; background: rgba(23,24,28,.92); border: 1px solid var(--line); }
.item .ic { width: 36px; height: 36px; color: var(--accent); }
.item b { display: block; font: 700 32px/1.2 Montserrat, sans-serif; }
.shot { position: absolute; z-index: 1; left: 300px; top: 980px; width: 980px; border-radius: 18px;
  border: 1px solid var(--line); box-shadow: 0 -10px 60px rgba(0,0,0,.6); opacity: .9; }
"""


def release_points(notes: str) -> list[tuple[str, str]]:
    """(headline, first sentence) of each bullet in the Ukrainian part of the notes."""
    uk = notes.split("\n---", 1)[0]
    out = []
    for raw in uk.splitlines():
        match = re.match(r"-\s+\*\*(.+?)\*\*\s*(.*)", raw.strip())
        if match:
            head = match.group(1).rstrip(".")
            rest = re.sub(
                r"\*\*([^*]+)\*\*|`([^`]+)`", lambda m: m.group(1) or m.group(2), match.group(2)
            )
            first = re.split(r"(?<=[.!?])\s", rest, maxsplit=1)[0]
            out.append((head, first))
    return out


def release_card(version: str, points: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<div class="item">{icon("check")}<b>{html.escape(head)}</b></div>'
        for head, _ in points[:4]
    )
    shot = (SITE / "assets" / "app" / "uk" / "review.jpg").as_uri()
    body = f"""<img class="shot" src="{shot}" alt="">
<section class="layer head"><div class="kicker">Нова версія</div><div class="ver num">{html.escape(version)}</div></section>
<section class="layer list">{items}</section>"""
    return page(body, RELEASE_CSS).replace("{pill}", _pill("spark", "Оновлення"))


def release_caption(
    version: str, points: list[tuple[str, str]], post: dict[str, Any] | None = None
) -> str:
    """The release card's caption: the notes' headlines, or with a release news
    post (news_release.py) its title, lead, sections and heroes, linking to it."""
    e = escape
    lines = [f"🚀 <b>Wardly {e(version)} вже тут</b>", ""]
    more = ""
    if post:
        import news_release

        uk = post["uk"]
        title = uk["title"].split(": ", 1)[-1]
        lines += [f"<b>{e(title[:1].upper() + title[1:])}</b>", e(uk["lead"]), ""]
        lines += [f"✅ {e(section['heading'])}" for section in uk["sections"]]
        lines += ["", f"🦸 {e(', '.join(post['heroes']))}"]
        more = f' · 📰 <a href="{news_release.page_url(post)}?ref=tg">Докладніше</a>'
    else:
        lines += [f"✅ {e(head)}" for head, _ in points]
    lines += [
        "",
        f'⬇️ <a href="{news.BASE}/?ref=tg">Завантажити</a>{more} · 📝 <a href="{news.BASE}/changelog.html?ref=tg#v{e(version)}">Усі зміни</a>',
        "Встановлена версія оновиться сама, коли Дота буде закрита.",
    ]
    return fit("\n".join(lines), keep_tail=3)


# --- a Dota 2 patch ---------------------------------------------------------------------

PATCH_CSS = """
.head { position: absolute; top: 160px; left: 64px; right: 64px; }
.kicker { color: var(--muted); font: 700 34px/1 Montserrat, sans-serif; }
.ver { margin-top: 10px; font: 800 168px/1 Montserrat, sans-serif; letter-spacing: -.04em;
  background: linear-gradient(90deg, #fff 0%, var(--cream) 40%, var(--accent) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.counts { display: flex; gap: 14px; margin-top: 26px; }
.count { padding: 14px 20px; border-radius: 16px; background: rgba(23,24,28,.88); border: 1px solid var(--line); }
.count b { font: 800 40px/1 Montserrat, sans-serif; color: var(--accent); margin-right: 10px; }
.count span { color: var(--muted); font-size: 24px; }
.faces { position: absolute; top: 560px; left: 64px; right: 64px; display: grid;
  grid-template-columns: repeat(5, 1fr); gap: 16px 14px; }
.face { min-width: 0; }
.face img, .face .none { display: block; width: 100%; aspect-ratio: 16 / 9; border-radius: 12px; object-fit: cover;
  background: #23242a; border: 1px solid var(--line); }
.face div { margin-top: 8px; font-size: 20px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.face.more { display: flex; align-items: center; justify-content: center; aspect-ratio: 16 / 9; border-radius: 12px;
  background: rgba(240,85,96,.14); border: 1px solid rgba(240,85,96,.45); color: var(--accent);
  font: 800 40px/1 Montserrat, sans-serif; }
.items { position: absolute; top: 1040px; left: 64px; right: 64px; display: flex; flex-wrap: wrap; gap: 10px;
  max-height: 152px; overflow: hidden; }
.items h3 { flex-basis: 100%; margin: 0 0 4px; color: var(--accent); font: 800 22px/1 Montserrat, sans-serif;
  letter-spacing: .12em; text-transform: uppercase; }
.chip { padding: 10px 16px; border-radius: 12px; background: var(--card); border: 1px solid var(--line); font-size: 22px; }
"""
# The card shows this many heroes (the last tile says how many more there are).
PATCH_FACES = 15


def patch_card(patch: dict[str, Any]) -> str:
    e = html.escape
    t = news.TEXT["uk"]
    counts = news.patch_counts(patch)
    heroes = sorted(patch["languages"]["uk"]["heroes"], key=lambda hero: hero["name"])
    shown = heroes if len(heroes) <= PATCH_FACES else heroes[: PATCH_FACES - 1]
    faces = []
    for hero in shown:
        src = small_picture(hero["key"])
        picture = f'<img src="{src}" alt="">' if src else '<span class="none"></span>'
        faces.append(f'<div class="face">{picture}<div>{e(hero["name"])}</div></div>')
    if len(shown) < len(heroes):
        faces.append(f'<div class="face more num">+{len(heroes) - len(shown)}</div>')
    items = news.patch_names(patch, "items") + news.patch_names(patch, "neutral")
    chips = "".join(f'<span class="chip">{e(name)}</span>' for name in items[:12])
    items_html = (
        f'<section class="layer items"><h3>{e(t["patch_items_title"])}</h3>{chips}</section>'
        if items
        else ""
    )
    count_html = "".join(
        f'<div class="count num"><b>{counts[key]}</b><span>{e(label)}</span></div>'
        for key, label in (
            ("heroes", "героїв"),
            ("items", "предметів"),
            ("general", "загальних розділів"),
        )
        if counts[key]
    )
    body = f"""
<section class="layer head"><div class="kicker">Оновлення Dota 2 · {e(news.long_date(patch["date"], "uk"))}</div>
<div class="ver num">{e(patch["version"])}</div><div class="counts">{count_html}</div></section>
<section class="layer faces">{"".join(faces)}</section>
{items_html}"""
    return page(body, PATCH_CSS).replace("{pill}", _pill("spark", "Патч"))


def patch_caption(patch: dict[str, Any]) -> str:
    e = escape
    t = news.TEXT["uk"]
    lines = [
        f"🛠 <b>{e(news.patch_title(patch, 'uk'))}</b>",
        f"<i>Valve оновили Dota 2 · {e(news.long_date(patch['date'], 'uk'))}</i>",
        "",
    ]
    for emoji, heading, key, limit in (
        ("⚔️", t["patch_heroes_title"], "heroes", 20),
        ("🗡", t["patch_items_title"], "items", 12),
        ("💎", t["patch_neutral_title"], "neutral", 8),
    ):
        names = news.patch_names(patch, key)
        if names:
            more = f" та ще {len(names) - limit}" if len(names) > limit else ""
            lines.append(
                f"{emoji} <b>{e(heading)} ({len(names)}):</b> {e(', '.join(names[:limit]))}{more}"
            )
    general = [group["title"] for group in patch["languages"]["uk"]["general"] if group["title"]]
    if general:
        lines.append(f"🌍 <b>{e(t['patch_general'])}:</b> {e(', '.join(general))}")
    lines += [
        "",
        f'👉 <a href="{news.BASE}/news/{news.patch_slug(patch)}.html?ref=tg">Усі зміни на сайті</a>',
        f'📜 <a href="{news.VALVE_PATCH_PAGE.format(version=e(patch["version"]))}">Офіційні нотатки Valve</a>',
        f'🎮 <a href="{news.BASE}/?ref=tg">Wardly</a> — безкоштовний тренер, що підказує просто в матчі',
        "",
        "#патч #dota2",
    ]
    return fit("\n".join(lines), keep_tail=6)


# --- captions --------------------------------------------------------------------------


def visible_length(text: str) -> int:
    """What Telegram counts toward the caption limit: the text without the HTML tags."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))


def fit(text: str, keep_tail: int = 5) -> str:
    """Drop body lines from the end (never the last `keep_tail` lines: links and tags)
    until the caption fits Telegram's limit."""
    lines = text.split("\n")
    while visible_length("\n".join(lines)) > CAPTION_LIMIT and len(lines) > keep_tail + 3:
        lines.pop(len(lines) - keep_tail - 1)
    return "\n".join(lines)
