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

import hero_insights
import news
import news_telegram
import news_voice as voice

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


def plural_uk(n: int, one: str, few: str, many: str) -> str:
    """«1 герой», «3 герої», «35 героїв»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


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
.head .kicker { color: var(--muted); font: 700 26px/1 Montserrat, sans-serif; letter-spacing: .02em; }
.head h1 { margin: 18px 0 0; font: 800 var(--size, 64px)/1.06 Montserrat, sans-serif; letter-spacing: -.02em; }
.spot { position: absolute; top: 420px; left: 64px; right: 64px; height: 380px; border-radius: 28px;
  overflow: hidden; border: 1px solid rgba(240,85,96,.35);
  background: linear-gradient(120deg, #1b1c21 0%, #1b1c21 45%, rgba(210,58,70,.35) 100%); }
.spot .art { position: absolute; right: -40px; bottom: -60px; height: 500px; width: auto;
  filter: drop-shadow(0 20px 40px rgba(0,0,0,.6)); }
.spot .art.small { right: 36px; bottom: 60px; height: auto; width: 400px; border-radius: 18px; }
.spot .copy { position: absolute; left: 48px; top: 44px; width: 560px; }
.label { display: flex; align-items: center; gap: 12px; color: var(--accent);
  font: 800 22px/1 Montserrat, sans-serif; letter-spacing: .12em; text-transform: uppercase; }
.label .ic { width: 28px; height: 28px; }
.spot h2 { margin: 20px 0 0; font: 800 var(--name, 60px)/1.02 Montserrat, sans-serif; letter-spacing: -.02em; }
.spot .big { margin-top: 24px; font: 800 112px/1 Montserrat, sans-serif; color: var(--accent); letter-spacing: -.03em; }
.spot .big.up { color: var(--green); }
.spot .sub { margin-top: 12px; color: var(--muted); font-size: 26px; }
.cols { position: absolute; top: 840px; left: 64px; right: 64px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }
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
.tile .who { display: flex; align-items: center; gap: 16px; }
.tile .who img, .tile .who .none { width: 96px; height: 54px; border-radius: 10px; object-fit: cover; background: #23242a; }
.tile .n { font: 800 30px/1.1 Montserrat, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tile .big2 { margin-top: 16px; font: 800 52px/1 Montserrat, sans-serif; color: var(--accent); }
.tile.up .big2 { color: var(--green); }
.tile .v { margin-top: 8px; font-size: 21px; color: var(--muted); line-height: 1.3; }
.tops { position: absolute; top: 1110px; left: 64px; right: 64px; display: grid; gap: 12px; }
.topline { display: flex; align-items: center; gap: 12px; font-size: 23px; color: var(--muted);
  white-space: nowrap; overflow: hidden; }
.topline .ic { width: 26px; height: 26px; color: var(--accent); }
.topline b { color: var(--text); font-weight: 600; }
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


def _when(basis: str | None) -> str:
    return "за останні три дні" if basis == "inside" else "за тиждень"


def angle_line(angle: dict[str, Any], seed: str) -> str:
    """One angle of the week (news.meta_angles) as a sentence, without a full stop."""
    row = angle["row"] or {}
    values = {
        "hero": row.get("name", ""),
        "win": news.percent(row["win"], "uk") if row else "",
        "pick": news.percent(row["pick"], "uk") if row else "",
        "weeks": str(angle.get("weeks", "")),
        "patch": angle.get("patch", ""),
        "when": _when(angle.get("basis")),
        "min": news.points(news.MIN_MOVE, "uk").lstrip("+"),
    }
    if "change" in angle or "change" in row:
        change = angle.get("change", row.get("change", 0.0))
        values["delta"] = news.points(abs(change), "uk").lstrip("+")
    return voice.say(angle["kind"], seed, **values)


# What the spotlight says for each angle: (icon, label, the big number, its sub-line).
def _spot(angle: dict[str, Any]) -> tuple[str, str, str, str, str]:
    row, kind = angle["row"], angle["kind"]
    pct = news.percent
    plays = f"перемог · у {pct(row['pick'], 'uk')} матчів тижня"
    if kind == "streak":
        return "trophy", f"{angle['weeks']}-й тиждень на вершині", pct(row["win"], "uk"), plays, ""
    if kind == "trap":
        return "down", "Популярний, але програє", pct(row["win"], "uk"), plays, ""
    if kind == "gem":
        return "spark", "Тихий сильний пік", pct(row["win"], "uk"), plays, ""
    if kind in ("rise", "fall", "patch_rise", "patch_fall"):
        up = row["change"] > 0
        label = "Злетів" if up else "Просів"
        if kind.startswith("patch"):
            label += f" після {angle['patch']}"
        sub = f"перемог {_when(angle.get('basis'))} · зараз {pct(row['win'], 'uk')}"
        return ("up" if up else "down"), label, news.points(row["change"], "uk"), sub, "up" * up
    if kind in ("picked_more", "picked_less"):
        up = kind == "picked_more"
        sub = f"матчів за тиждень · зараз у {pct(row['pick'], 'uk')}"
        label = "Беруть частіше" if up else "Беруть рідше"
        return ("up" if up else "down"), label, news.points(angle["change"], "uk"), sub, ""
    return "trophy", news.TEXT["uk"]["tile_win"], pct(row["win"], "uk"), plays, ""


def _angle_tile(angle: dict[str, Any]) -> str:
    """A smaller angle under the spotlight: the hero, what is special, the number."""
    e = html.escape
    row = angle["row"]
    icon_name, label, number, sub, tone = _spot(angle)
    src = small_picture(row.get("key") or "")
    picture = f'<img src="{src}" alt="">' if src else '<span class="none"></span>'
    return (
        f'<div class="col tile {tone}"><h3>{icon(icon_name)}{e(label)}</h3>'
        f'<div class="who">{picture}<div class="n">{e(row["name"])}</div></div>'
        f'<div class="big2 num">{e(number)}</div><div class="v num">{e(sub)}</div></div>'
    )


def _tops_line(icon_name: str, heading: str, rows: list[dict[str, Any]], value: str) -> str:
    e = html.escape
    items = " · ".join(f"<b>{e(r['name'])}</b> {e(news.percent(r[value], 'uk'))}" for r in rows[:3])
    return f'<div class="topline">{icon(icon_name)}<span>{e(heading)}: {items}</span></div>'


def meta_card(
    post: dict[str, Any],
    data: dict[str, Any],
    workdir: Path,
    angles: list[dict[str, Any]] | None = None,
) -> str:
    """The week's main angle as the headline and the spotlight, the next two angles
    as tiles, the tops in a line each."""
    t = news.TEXT["uk"]
    angles = [a for a in angles or [] if a["row"]] or [{"kind": "top", "row": data["win"][0]}]
    first = angles[0]
    headline = angle_line(first, post["date"])
    row = first["row"]
    art, big = hero_picture(row.get("key") or "", workdir)
    art_tag = f'<img class="art{"" if big else " small"}" src="{art}" alt="">' if art else ""
    size = _name_size(row["name"], 64, ((16, 48), (12, 56)))
    icon_name, label, number, sub, tone = _spot(first)
    tiles = [_angle_tile(a) for a in angles[1:3] if a["kind"] != "top"]
    if tiles:
        middle = (
            f'<section class="layer cols" style="grid-template-columns: repeat({len(tiles)}, 1fr)">'
            f"{''.join(tiles)}</section>"
        )
        tops = [_tops_line("trophy", "Виграють", data["win"], "win")]
        tops.append(_tops_line("flame", "Беруть", data["pick"], "pick"))
        bottom = f'<section class="layer tops">{"".join(tops)}</section>'
    else:  # a first post: no other angle, the lists as before
        cols = [
            ("trophy", t["win_title"], data["win"], "win", ""),
            ("flame", t["pick_title"], data["pick"], "pick", ""),
            ("up", t["up_title"], data["up"], "change", "up"),
            ("down", t["down_title"], data["down"], "change", "down"),
        ]
        shown = [c for c in cols if c[2]][:3]
        middle = (
            f'<section class="layer cols" style="grid-template-columns: repeat({len(shown)}, 1fr)">'
            + "".join(
                f'<div class="col {tone_}"><h3>{icon(name)}{html.escape(heading)}</h3>{_rows(rows, value)}</div>'
                for name, heading, rows, value, tone_ in shown
            )
            + "</section>"
        )
        bottom = ""
    h1_size = 64 if len(headline) <= 44 else 54 if len(headline) <= 64 else 46
    body = f"""
<section class="layer head"><div class="kicker">{html.escape(news.period(post, "uk"))} · {html.escape(news.matches_text(data["matches"], "uk"))} публічних матчів</div>
<h1 style="--size: {h1_size}px">{html.escape(headline)}</h1></section>
<section class="layer spot">{art_tag}
  <div class="copy"><div class="label">{icon(icon_name)}{html.escape(label)}</div>
  <h2 style="--name: {size}px">{html.escape(row["name"])}</h2>
  <div class="big num {tone}">{html.escape(number)}</div>
  <div class="sub num">{html.escape(sub)}</div></div>
</section>
{middle}
{bottom}"""
    return page(body, META_CSS).replace("{pill}", _pill("trophy", "Мета тижня"))


def meta_caption(
    post: dict[str, Any], data: dict[str, Any], angles: list[dict[str, Any]] | None = None
) -> str:
    """The week's angle first, two more in a line each, then the tops in one line each."""
    e = escape
    seed = post["date"]
    angles = angles or [{"kind": "top", "row": data["win"][0]}]
    lines = [f"📊 <b>{e(angle_line(angles[0], seed))}</b>"]
    more = [angle_line(a, seed) for a in angles[1:3] if a["kind"] != "top"]
    if more:
        lines += ["", *(f"{e(line)}." for line in more)]

    def tops(emoji: str, heading: str, rows: list[dict[str, Any]], value: str) -> str | None:
        if not rows:
            return None
        items = [f"{e(r['name'])} {e(news.percent(r[value], 'uk'))}" for r in rows[:3]]
        return f"{emoji} {heading}: " + " · ".join(items)

    lines.append("")
    for item in (
        tops("🏆", "Виграють", data["win"], "win"),
        tops("🔥", "Беруть", data["pick"], "pick"),
    ):
        if item:
            lines.append(item)
    lines += [
        f"<i>{e(news.period(post, 'uk'))} · {e(news.matches_text(data['matches'], 'uk'))} "
        "публічних матчів, OpenDota</i>",
        "",
        e(voice.say("meta_cta", seed)),
        f'👉 <a href="{news.BASE}/news/{news.slug(post)}.html?ref=tg">Уся таблиця</a> · '
        f'<a href="{news.BASE}/?ref=tg">Wardly</a> · #мета_тижня',
    ]
    return fit("\n".join(lines), keep_tail=3)


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
.tips .hook { margin: 4px 0 18px; padding-bottom: 18px; border-bottom: 1px solid var(--line);
  font: 700 31px/1.28 Montserrat, sans-serif; color: var(--text); }
"""


def pick_hero(
    post: dict[str, Any], site_heroes: list[dict[str, Any]], history: list[str]
) -> tuple[dict[str, Any], dict[str, float] | None]:
    """The week's hero: the best win rate among heroes with a site page, picked in
    at least HERO_MIN_PICK of matches and not among the last HERO_REPEAT heroes;
    a hero with a plan (hero_insights: numbers that win) comes first."""
    matches = sum(h["picks"] for h in post["heroes"]) / 10 or 1
    # By the picture key: the site and OpenDota may name a hero differently.
    stats = {
        h["key"]: {"win": h["wins"] / h["picks"], "pick": h["picks"] / matches}
        for h in post["heroes"]
        if h["picks"] and h.get("key")
    }
    recent = set(history[-HERO_REPEAT:])
    known = [h for h in site_heroes if h["key"] in stats]
    with_plan = {h["name"] for h in known if hero_insights.facts(h["name"], h.get("position", ""))}
    ranked = sorted(known, key=lambda h: stats[h["key"]]["win"], reverse=True)
    for wanted in (
        lambda h: (
            stats[h["key"]]["pick"] >= HERO_MIN_PICK
            and h["name"] not in recent
            and h["name"] in with_plan
        ),
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


def hero_facts(hero: dict[str, Any], site: Any) -> dict[str, Any]:
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
        "insights": hero_insights.facts(hero["name"], hero["position"]),
    }


def hero_hook(
    hero: dict[str, Any], facts: dict[str, Any], stats: dict[str, float] | None, seed: str
) -> tuple[str, tuple[str, str] | None]:
    """(the post's opening line, the insight row it uses): the clearest number the
    hero's plan holds — a counter item's record, then a skill order against the
    usual alternative, then the tempo line; else the week's numbers."""
    found = facts.get("insights") or {}
    name, pct = hero["name"], hero_insights.pct
    records = [c for c in found.get("counters", []) if c["record"]]
    if records:
        best = max(records, key=lambda c: c["record"]["with"] - c["record"]["without"])
        record = best["record"]
        line = voice.say(
            "hero_counter",
            seed,
            hero=name,
            item=best["item"],
            against=hero_insights.AGAINST[best["against"]][1],
            with_=pct(record["with"], "uk"),
            without=pct(record["without"], "uk"),
        )
        return line, ("counter", best["item"])
    skills = found.get("skills")
    if skills and skills.get("alternative"):
        alternative = skills["alternative"]
        line = voice.say(
            "hero_skills",
            seed,
            hero=name,
            top=skills["order"][0],
            win=pct(skills["win"], "uk"),
            first=alternative["first"],
            alt=pct(alternative["win"], "uk"),
        )
        return line, ("skills", "")
    tempo = found.get("tempo")
    if tempo:
        line = voice.say(
            "hero_tempo",
            seed,
            hero=name,
            net_worth=hero_insights.money(tempo["net_worth"]),
            minute=str(tempo["minute"]),
            win=pct(tempo["win"], "uk"),
        )
        return line, ("tempo", "")
    if stats:
        line = voice.say(
            "hero_plain",
            seed,
            hero=name,
            win=news.percent(stats["win"], "uk"),
            pick=news.percent(stats["pick"], "uk"),
        )
        return line, None
    return "", None


def _without_hook(
    rows: list[tuple[str, str, str]], used: tuple[str, str] | None
) -> list[tuple[str, str, str]]:
    """The plan's rows but the one the opening line already says."""
    if used is None:
        return rows
    kind, item = used
    for index, (row_kind, title, _sub) in enumerate(rows):
        if row_kind == kind and (not item or f"<b>{escape(item)}</b>" in title):
            return rows[:index] + rows[index + 1 :]
    return rows


def hero_card(
    hero: dict[str, Any],
    facts: dict[str, Any],
    stats: dict[str, float] | None,
    workdir: Path,
    seed: str = "",
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
    hook, used = hero_hook(hero, facts, stats, seed or hero["name"])
    found = facts.get("insights")
    if found:
        rows = "".join(
            f'<div class="tip">{icon(hero_insights.ICONS[kind])}<div>{title}<small>{e(sub)}</small></div></div>'
            for kind, title, sub in _without_hook(hero_insights.rows(found, "uk"), used)[:4]
        )
        heading = hero_insights.TEXT["uk"]["heading"]
    else:
        rows, heading = _hero_tips(facts), "Що підкаже Wardly"
    hook_html = f'<p class="hook">{e(hook)}</p>' if hook and used else ""
    body = f"""{art_tag}<div class="fade"></div>
<section class="copy"><span class="role">{e(facts["role"])}</span>
<h1 style="--name: {size}px">{e(hero["name"])}</h1>
<p>{e(facts["archetype"][0].upper() + facts["archetype"][1:])}</p>{chips}</section>
<section class="tips">{hook_html}<h3>{e(heading)}</h3>{rows}</section>"""
    return page(body, HERO_CSS).replace("{pill}", _pill("swords", "Герой тижня"))


def _hero_tips(facts: dict[str, Any]) -> str:
    """The hero page's thresholds and items, for a hero without a plan."""
    e = escape
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
    return "".join(
        f'<div class="tip">{icon(name)}<div>{text}{f"<small>{e(sub)}</small>" if sub else ""}</div></div>'
        for name, text, sub in tips[:5]
    )


def hero_caption(
    hero: dict[str, Any], facts: dict[str, Any], stats: dict[str, float] | None, seed: str = ""
) -> str:
    """The clearest number first, then the rest of the plan as short lines."""
    e = escape
    seed = seed or hero["name"]
    role, archetype = facts["role"], facts["archetype"]
    kind = archetype if archetype.lower().startswith(role.lower()) else f"{role} — {archetype}"
    hook, used = hero_hook(hero, facts, stats, seed)
    lines = [f"⚔️ <b>Герой тижня: {e(hero['name'])}</b>"]
    if hook:
        lines += ["", e(hook)]
    found = facts.get("insights")
    if found:
        rest = _without_hook(hero_insights.rows(found, "uk"), used)
        if rest:
            lines.append("")
            lines += [f"• {title} · {e(sub)}" for _kind, title, sub in rest]
        play = voice.say("hero_cta", seed)
    else:
        lines += [
            "",
            f"• Відходьте, коли HP нижче <b>{facts['low']} %</b>; нижче <b>{facts['critical']} %</b> — негайно",
        ]
        if facts["saves"]:
            lines.append(f"• Рятує: <b>{e(facts['saves'])}</b>")
        if facts["fight"]:
            lines.append(f"• У бійці: <b>{e(facts['fight'])}</b>")
        if facts["pace"]:
            lines.append(f"• До 10:00 — <b>{e(facts['pace'])}</b> добивань")
        lines.append(f"• {e(facts['note'])}")
        play = voice.say("hero_cta_plain", seed)
    # «Керрі, що фармить…» rather than «Керрі — керрі, що фармить…».
    about = kind[0].upper() + kind[1:]
    if stats and used is not None:
        about += (
            f" · цього тижня {news.percent(stats['win'], 'uk')} перемог "
            f"у {news.percent(stats['pick'], 'uk')} матчів"
        )
    lines += ["", f"<i>{e(about)}</i>"]
    if found:
        lines.append(f"<i>{e(hero_insights.source(found, 'uk'))}</i>")
    lines += [
        "",
        e(play),
        f'📖 <a href="{news.BASE}/heroes/{hero["slug"]}.html?ref=tg">Усе про героя</a> · '
        f'<a href="{news.BASE}/?ref=tg">Wardly</a> · #герой_тижня',
    ]
    return fit("\n".join(lines), keep_tail=3)


# --- a new version ---------------------------------------------------------------------

RELEASE_CSS = """
.head { position: absolute; top: 200px; left: 64px; right: 64px; }
.kicker { color: var(--muted); font: 700 30px/1 Montserrat, sans-serif; }
.head h1 { margin: 22px 0 0; font: 800 var(--size, 84px)/1.04 Montserrat, sans-serif; letter-spacing: -.025em; }
.scene { position: absolute; z-index: 1; left: 64px; right: 64px; top: 500px; height: 690px; border-radius: 28px;
  overflow: hidden; border: 1px solid var(--line); background: #15161a center / cover no-repeat;
  box-shadow: 0 30px 80px rgba(0,0,0,.55); }
.scene::after { content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(12,13,15,.05) 30%, rgba(12,13,15,.55) 100%); }
.scene .tag { position: absolute; z-index: 2; left: 28px; top: 26px; padding: 10px 16px; border-radius: 12px;
  background: rgba(12,13,16,.72); color: var(--muted); font: 700 20px/1 Montserrat, sans-serif;
  letter-spacing: .1em; text-transform: uppercase; }
.hint { position: absolute; z-index: 2; left: 40px; right: 40px; bottom: 40px; padding: 28px 34px;
  border-radius: 18px; border: 1px solid rgba(255,255,255,.12); background: rgba(12,13,16,.88);
  box-shadow: inset 6px 0 0 var(--cream), 0 20px 50px rgba(0,0,0,.5); }
.hint b { display: block; font: 700 34px/1.25 Inter, sans-serif; }
.hint span { display: block; margin-top: 10px; color: var(--muted); font-size: 28px; line-height: 1.3; }
.shot { position: absolute; z-index: 1; left: 300px; top: 860px; width: 980px; border-radius: 18px;
  border: 1px solid var(--line); box-shadow: 0 -10px 60px rgba(0,0,0,.6); opacity: .9; }
"""


def release_card(post: dict[str, Any]) -> str:
    """The release post's promise in big letters and, when the post has one, a
    hint as the overlay shows it in the game."""
    e = html.escape
    version = post["version"]
    short = version if news_telegram.is_fix(version) else ".".join(version.split(".")[:2])
    headline = post["headline"]
    # «Wardly 0.61: …» — the version is already in the pill.
    prefix = f"Wardly {short}: "
    if headline.startswith(prefix):
        headline = headline[len(prefix) :]
    headline = headline[:1].upper() + headline[1:]
    size = 84 if len(headline) <= 34 else 72 if len(headline) <= 48 else 60
    example = post.get("example")
    if example:
        scene = (SITE / "assets" / "game" / f"{post.get('scene') or 'forest'}.jpg").as_uri()
        shown = f"""<section class="scene" style="background-image: url('{scene}')">
  <div class="tag">Так це виглядає в грі</div>
  <div class="hint"><b>{e(example["title"])}</b><span>{e(example["body"])}</span></div></section>"""
    else:
        shot = (SITE / "assets" / "app" / "uk" / "review.jpg").as_uri()
        shown = f'<img class="shot" src="{shot}" alt="">'
    body = f"""{shown}
<section class="layer head"><div class="kicker">Нова версія Wardly</div>
<h1 style="--size: {size}px">{e(headline)}</h1></section>"""
    return page(body, RELEASE_CSS).replace("{pill}", _pill("spark", f"Оновлення {short}"))


def release_caption(post: dict[str, Any], release_post: dict[str, Any] | None = None) -> str:
    """The release post's own words (data/news/telegram), linking to the release's
    news page when it has one (news_release.py)."""
    return news_telegram.caption(post, release_post)


# --- a Dota 2 patch ---------------------------------------------------------------------

PATCH_CSS = """
.head { position: absolute; top: 150px; left: 64px; right: 64px; }
.kicker { color: var(--muted); font: 700 30px/1 Montserrat, sans-serif; }
.ver { margin-top: 8px; font: 800 140px/1 Montserrat, sans-serif; letter-spacing: -.04em;
  background: linear-gradient(90deg, #fff 0%, var(--cream) 40%, var(--accent) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.counts { display: flex; gap: 14px; margin-top: 22px; }
.count { padding: 12px 18px; border-radius: 16px; background: rgba(23,24,28,.88); border: 1px solid var(--line); }
.count b { font: 800 36px/1 Montserrat, sans-serif; color: var(--accent); margin-right: 10px; }
.count span { color: var(--muted); font-size: 22px; }
.most { position: absolute; top: 500px; left: 64px; right: 64px; }
.most h3, .items h3 { margin: 0 0 14px; color: var(--accent); font: 800 22px/1 Montserrat, sans-serif;
  letter-spacing: .12em; text-transform: uppercase; }
.change { display: grid; grid-template-columns: 176px 1fr; gap: 22px; align-items: center; padding: 16px 20px;
  margin-bottom: 14px; border-radius: 20px; background: rgba(23,24,28,.92); border: 1px solid var(--line); }
.change img, .change .none { width: 176px; height: 99px; border-radius: 12px; object-fit: cover; background: #23242a; }
.change b { display: block; font: 800 30px/1.1 Montserrat, sans-serif; }
.change span { display: block; margin-top: 8px; color: var(--muted); font-size: 23px; line-height: 1.3; }
.faces { position: absolute; top: 992px; left: 64px; right: 64px; display: grid;
  grid-template-columns: repeat(8, 1fr); gap: 10px; }
.face img, .face .none { display: block; width: 100%; aspect-ratio: 16 / 9; border-radius: 8px; object-fit: cover;
  background: #23242a; border: 1px solid var(--line); }
.face.more { display: flex; align-items: center; justify-content: center; aspect-ratio: 16 / 9; border-radius: 8px;
  background: rgba(240,85,96,.14); border: 1px solid rgba(240,85,96,.45); color: var(--accent);
  font: 800 26px/1 Montserrat, sans-serif; }
.items { position: absolute; top: 1084px; left: 64px; right: 64px; display: flex; flex-wrap: wrap; gap: 10px;
  max-height: 140px; overflow: hidden; }
.items h3 { flex-basis: 100%; margin-bottom: 4px; }
.chip { padding: 8px 14px; border-radius: 12px; background: var(--card); border: 1px solid var(--line); font-size: 21px; }
"""
# Below the three most changed heroes the card shows one row of this many faces (the
# last tile says how many there are beyond them).
PATCH_FACES = 8


def patch_card(patch: dict[str, Any]) -> str:
    """The three most changed heroes with their first change, the other faces and
    the changed items below."""
    e = html.escape
    counts = news.patch_counts(patch)
    top = news.patch_highlights(patch, limit=90)
    changes = []
    for row in top["heroes"]:
        src = small_picture(row["key"])
        picture = f'<img src="{src}" alt="">' if src else '<span class="none"></span>'
        changes.append(
            f'<div class="change">{picture}<div><b>{e(row["name"])}</b><span>{e(row["line"])}</span></div></div>'
        )
    shown_names = {row["name"] for row in top["heroes"]}
    others = sorted(
        (h for h in patch["languages"]["uk"]["heroes"] if h["name"] not in shown_names),
        key=lambda hero: hero["name"],
    )
    faces_shown = others if len(others) <= PATCH_FACES else others[: PATCH_FACES - 1]
    faces = []
    for hero in faces_shown:
        src = small_picture(hero["key"])
        picture = f'<img src="{src}" alt="">' if src else '<span class="none"></span>'
        faces.append(f'<div class="face">{picture}</div>')
    if len(faces_shown) < len(others):
        faces.append(f'<div class="face more num">+{len(others) - len(faces_shown)}</div>')
    items = news.patch_names(patch, "items") + news.patch_names(patch, "neutral")
    chips = "".join(f'<span class="chip">{e(name)}</span>' for name in items[:10])
    items_html = (
        f'<section class="layer items"><h3>{e(news.TEXT["uk"]["patch_items_title"])}</h3>{chips}</section>'
        if items
        else ""
    )
    count_html = "".join(
        f'<div class="count num"><b>{counts[key]}</b><span>{e(plural_uk(counts[key], *forms).split(" ", 1)[1])}</span></div>'
        for key, forms in (
            ("heroes", ("герой", "герої", "героїв")),
            ("items", ("предмет", "предмети", "предметів")),
            ("general", ("загальний розділ", "загальні розділи", "загальних розділів")),
        )
        if counts[key]
    )
    most = (
        f'<section class="layer most"><h3>{e(voice.say("patch_most", patch["version"]))}</h3>{"".join(changes)}</section>'
        if changes
        else ""
    )
    body = f"""
<section class="layer head"><div class="kicker">Оновлення Dota 2 · {e(news.long_date(patch["date"], "uk"))}</div>
<div class="ver num">{e(patch["version"])}</div><div class="counts">{count_html}</div></section>
{most}
<section class="layer faces">{"".join(faces)}</section>
{items_html}"""
    return page(body, PATCH_CSS).replace("{pill}", _pill("spark", "Патч"))


def patch_caption(patch: dict[str, Any]) -> str:
    """What changed most, in Valve's words, then the rest by name."""
    e = escape
    seed = patch["version"]
    counts = news.patch_counts(patch)
    top = news.patch_highlights(patch)
    items_count = counts["items"] + counts["neutral"]
    numbers = [
        plural_uk(counts["heroes"], "герой", "герої", "героїв") if counts["heroes"] else "",
        plural_uk(items_count, "предмет", "предмети", "предметів") if items_count else "",
    ]
    lines = [
        f"🛠 <b>{e(voice.say('patch_head', seed, version=patch['version']))}</b>",
        f"<i>{e(news.long_date(patch['date'], 'uk'))} · "
        + e(", ".join(n for n in numbers if n) or "загальні зміни")
        + "</i>",
    ]
    if top["heroes"]:
        lines += ["", f"<b>{e(voice.say('patch_most', seed))}:</b>"]
        lines += [f"• <b>{e(row['name'])}</b> — {e(row['line'])}" for row in top["heroes"]]
    if top["items"]:
        lines += ["", "<b>Предмети:</b>"]
        lines += [f"• <b>{e(row['name'])}</b> — {e(row['line'])}" for row in top["items"]]
    general = [group["title"] for group in patch["languages"]["uk"]["general"] if group["title"]]
    if general:
        lines += ["", f"Загальне: {e(', '.join(general))}"]
    tail = [
        "",
        f'👉 <a href="{news.BASE}/news/{news.patch_slug(patch)}.html?ref=tg">Усі зміни</a> · '
        f'<a href="{news.VALVE_PATCH_PAGE.format(version=e(patch["version"]))}">нотатки Valve</a> · #патч',
    ]
    shown = {row["name"] for row in top["heroes"]}
    rest = [name for name in news.patch_names(patch, "heroes") if name not in shown]
    # The other heroes by name, as many as fit.
    for limit in range(min(len(rest), 15), 0, -1):
        more = f" та ще {len(rest) - limit}" if len(rest) > limit else ""
        names = ["", f"Також змінили: {e(', '.join(rest[:limit]))}{more}"]
        if visible_length("\n".join(lines + names + tail)) <= CAPTION_LIMIT:
            lines += names
            break
    return fit("\n".join(lines + tail), keep_tail=2)


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
