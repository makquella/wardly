"""The 0.57 release pair (Ukrainian, English): 20 carries with a plan of their own.

Built by the beta engine (beta.build, creative CREATIVE): one continuous Alex
take per language, phrase captions, the same layout, speech and Shorts checks
and the YouTube-only Telegram buttons (beta_campaign=release, then shorts).
Every claim comes from the shipped data: the 20 carry plans in
data/heroes/item_plans, their league games, Naga Siren's Bloodthorn rule and
Drow Ranger's suppressed Monkey King Bar.
"""

from __future__ import annotations

import copy
import html
import json
import re
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from . import beta_scenes as base
from . import media

CREATIVE = "carry-plans-0.57"
REVISION = 7
VERSION = "0.57"
# Valve's idle renders for the motion scenes (beta.prepare_motion).
HEROES = ("phantom_assassin", "naga_siren", "terrorblade")
CARRIES = (
    "antimage",
    "drow_ranger",
    "gyrocopter",
    "juggernaut",
    "kez",
    "life_stealer",
    "luna",
    "medusa",
    "monkey_king",
    "morphling",
    "muerta",
    "naga_siren",
    "phantom_assassin",
    "phantom_lancer",
    "slark",
    "sniper",
    "spectre",
    "sven",
    "terrorblade",
    "ursa",
)
PLANS = base.SITE.parent / "data" / "heroes" / "item_plans"

PHRASES = {
    "uk": [
        "Ті самі предмети|у кожному матчі?",
        "Wardly тепер знає|двадцять керрі.",
        "Проти Phantom Assassin|Naga Siren бере Bloodthorn,|а Drow Ranger нічого:|Marksmanship не промахується.",
        "Збірка й прокачка|з понад десяти тисяч|лігових матчів.",
        "Фармиш швидше?|Wardly веде|темпову збірку.",
        "Безкоштовно для Windows.",
        "Посилання в описі.",
    ],
    "en": [
        "Same items|every single match?",
        "Wardly now knows|twenty carries.",
        "Against Phantom Assassin,|Naga Siren takes Bloodthorn,|Drow Ranger needs nothing:|Marksmanship procs never miss.",
        "Builds and skills|from over ten thousand|league matches.",
        "Farming ahead?|Wardly switches|to the tempo build.",
        "Free for Windows.",
        "Link in the description.",
    ],
}

COPY = {
    "uk": {
        "label": f"ОНОВЛЕННЯ {VERSION}",
        "free": "Безкоштовно для Windows",
        "site": "luhovyimvp.dev",
    },
    "en": {
        "label": f"UPDATE {VERSION}",
        "free": "Free for Windows",
        "site": "luhovyimvp.dev/en/",
    },
}


def plans() -> dict[str, dict]:
    """The shipped carry plans by hero name."""
    found = {}
    for path in sorted(PLANS.glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if "carry" in plan["positions"]:
            found[plan["hero"]] = plan
    return found


def verify() -> dict:
    """The video's claims against the data it describes; raises on a mismatch."""
    shipped = plans()
    assert len(shipped) == 20, f"{len(shipped)} carry plans, the video says twenty"
    games = sum(
        int(re.search(r"(\d+) (?:league )?games", p["sources"]["games"]).group(1))
        for p in shipped.values()
    )
    assert games > 10000, f"{games} league games, the video says over ten thousand"
    naga = next(r for r in shipped["Naga Siren"]["rules"] if r["enemy"] == "evasion")
    assert naga["item"] == "bloodthorn"
    assert "evasion" in shipped["Drow Ranger"]["suppress"]
    assert "Marksmanship" in shipped["Drow Ranger"]["suppress"]["evasion"]
    assert shipped["Terrorblade"]["tempo"]["net_worth"][0] == [20, 12000]
    return {"carries": len(shipped), "league_games": games}


def metadata(language: str) -> dict:
    uk = language == "uk"
    url = f"https://luhovyimvp.dev/{'' if uk else 'en/'}?ref=shorts-carry-{language}"
    news = (
        "https://luhovyimvp.dev/news/2026-10-19-release-0-57-0.html"
        if uk
        else "https://luhovyimvp.dev/en/news/2026-10-19-release-0-57-0.html"
    )
    if uk:
        return {
            "title": "Ті самі предмети щоматчу? Wardly знає 20 керрі | Dota 2",
            "description": (
                "Wardly 0.57: свій план для 20 керрі. Предмети проти ворожого драфту "
                "тепер залежать від твого героя: проти Phantom Assassin Naga Siren бере "
                "Bloodthorn, а Drow Ranger обходиться без Monkey King Bar. Збірка, "
                "прокачка й таланти — з понад 10 000 лігових матчів (OpenDota), "
                "механіки — з даних Valve 7.41f.\n\n"
                f"Що нового: {news}\n"
                f"Безкоштовно для Windows: {url}\n\n"
                "#Dota2 #ДотаУкраїнською #Wardly"
            ),
            "tags": [
                "Dota 2",
                "дота 2",
                "Wardly",
                "Dota 2 українською",
                "керрі",
                "збірка",
                "Naga Siren",
                "Drow Ranger",
                "Phantom Assassin",
                "тренер Dota 2",
            ],
        }
    return {
        "title": "Same items every match? Wardly now knows 20 carries | Dota 2",
        "description": (
            "Wardly 0.57: a plan of their own for 20 carries. Items against the enemy "
            "draft now depend on your hero: against Phantom Assassin, Naga Siren takes "
            "Bloodthorn while Drow Ranger skips Monkey King Bar. Builds, skills and "
            "talents from over 10,000 league matches (OpenDota), mechanics from Valve's "
            "7.41f data.\n\n"
            f"What's new: {news}\n"
            f"Free for Windows: {url}\n\n"
            "#Dota2 #Dota2Coach #Wardly"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Dota 2 coach",
            "carry",
            "item build",
            "Naga Siren",
            "Drow Ranger",
            "Phantom Assassin",
            "Dota 2 Windows app",
        ],
    }


def profile() -> SimpleNamespace:
    verify()
    localized = copy.deepcopy(COPY)
    for language in ("uk", "en"):
        localized[language]["voice"] = [s.replace("|", " ") for s in PHRASES[language]]
    return SimpleNamespace(
        COPY=localized,
        HEROES=HEROES,
        phrase_captions=partial(base.phrase_captions, phrases=PHRASES),
        page=page,
    )


def _item(key: str) -> str:
    """Valve's item icon as a data URI (media cache); the name alone offline."""
    path = media.download(
        media.ITEM_ICON.format(item=key),
        Path.home() / ".cache" / "wardly-promo" / f"{key}.png",
    )
    return base.uri(path) if path else ""


def page(language, timeline, captions, motion=None):
    uk = language == "uk"

    def t(ukrainian: str, english: str) -> str:
        return ukrainian if uk else english

    esc = html.escape
    assets = base.SITE / "assets"
    motion = motion or {}

    def hero(key: str, cls: str) -> str:
        frames = motion.get(key)
        source = frames[0] if frames else base.uri(assets / "heroes" / f"{key}.webp")
        return f'<img class="{cls}" data-hero="{key}" src="{source}">'

    def portrait(key: str) -> str:
        return f'<img class="portrait" src="{base.uri(assets / "heroes" / f"{key}.webp")}">'

    def icon(key: str, name: str, cls: str = "") -> str:
        src = _item(key)
        inner = f'<img src="{src}">' if src else f"<b>{esc(name)}</b>"
        return f'<span class="item {cls}">{inner}</span>'

    mkb = icon("monkey_king_bar", "Monkey King Bar")
    grid = "".join(
        f'<div class="cell" style="--i:{i}">{portrait(key)}</div>' for i, key in enumerate(CARRIES)
    )
    sections = []

    def scene(index: int, body: str) -> None:
        sections.append(f'<section class="scene s{index}">{body}</section>')

    scene(
        0,
        f'<div class="eyebrow enter" data-safe>DOTA 2 · {t("КЕРРІ", "CARRY")}</div>'
        f'<h1 class="big-title enter" data-safe>{t("Ті самі<br>предмети?", "Same items<br>again?")}</h1>'
        f'<div class="hook-hero">{hero("phantom_assassin", "hook-art")}</div>'
        '<div class="same-row">'
        + "".join(
            f'<div class="same enter" style="--d:{0.25 + 0.2 * i}s">{mkb}<span data-safe>{t("Матч", "Match")} {i + 1}</span></div>'
            for i in range(3)
        )
        + "</div>",
    )
    scene(
        1,
        f'<div class="eyebrow enter" data-safe>WARDLY {VERSION}</div>'
        f'<h1 class="big-title enter" data-safe><em>20</em> {t("керрі", "carries")}</h1>'
        f'<div class="carry-grid">{grid}</div>'
        f'<div class="note enter" data-safe>{t("Свій план для кожного", "A plan of their own each")}</div>',
    )
    rows = (
        f'<div class="answer enter" style="--d:.2s">{portrait("naga_siren")}<b data-safe>Naga Siren</b>'
        f'<span class="arrow">→</span>{icon("bloodthorn", "Bloodthorn", "good")}</div>'
        f'<div class="answer enter" style="--d:.9s">{portrait("drow_ranger")}<b data-safe>Drow Ranger</b>'
        f'<span class="arrow">→</span>{icon("monkey_king_bar", "Monkey King Bar", "crossed")}</div>'
    )
    scene(
        2,
        f'<div class="eyebrow enter" data-safe>{t("ПРОТИ", "AGAINST")} PHANTOM ASSASSIN</div>'
        f'<h1 class="mid-title enter" data-safe>{t("Різні герої.<br><em>Різні відповіді.</em>", "Different heroes.<br><em>Different answers.</em>")}</h1>'
        f'<div class="answers">{rows}</div>'
        f'<div class="note low enter" style="--d:1.4s" data-safe>{t("Marksmanship не промахується", "Marksmanship procs never miss")}</div>',
    )
    plan_card = base.uri(assets / "overlay" / language / "plan.webp")
    scene(
        3,
        f'<div class="eyebrow enter" data-safe>{t("З ЛІГОВИХ МАТЧІВ · OPENDOTA", "FROM LEAGUE MATCHES · OPENDOTA")}</div>'
        f'<h1 class="mid-title enter" data-safe>{t("Збірка.<br><em>Прокачка.</em>", "Builds.<br><em>Skills.</em>")}</h1>'
        f'<div class="stat enter" style="--d:.3s" data-safe><b>10 451</b><span>{t("лігових матчів", "league matches")}</span></div>'
        f'<div class="card-shot enter" style="--d:.6s"><img src="{plan_card}"></div>'
        f'<div class="note low enter" style="--d:.8s" data-safe>{t("Картка «План на гру» у Wardly", "The Wardly «Game plan» card")}</div>',
    )
    scene(
        4,
        f'<div class="eyebrow enter" data-safe>{t("ТЕМП", "TEMPO")} · TERRORBLADE</div>'
        f'<h1 class="mid-title enter" data-safe>{t("Фармиш<br><em>швидше?</em>", "Farming<br><em>ahead?</em>")}</h1>'
        f'<div class="tempo-hero">{hero("terrorblade", "tempo-art")}</div>'
        f'<div class="tempo enter" style="--d:.4s" data-safe><b>12 000</b><span>{t("до 20:00 → темпова збірка", "by 20:00 → tempo build")}</span></div>',
    )
    scene(
        5,
        '<div class="eyebrow enter" data-safe>WARDLY</div>'
        f'<h1 class="mid-title enter" data-safe>{t("Безкоштовно.<br><em>Для Windows.</em>", "Free.<br><em>For Windows.</em>")}</h1>'
        '<div class="window-art"><i></i><i></i><i></i><i></i></div>',
    )
    c = COPY[language]
    scene(
        6,
        '<div class="end-orbit"></div>'
        f'<div class="end-version enter" data-safe>Wardly <em>{VERSION}</em></div>'
        f'<div class="end-line enter" style="--d:.2s" data-safe>{t("Свій план для 20 керрі", "A plan for 20 carries")}</div>'
        f'<div class="end-link enter" style="--d:.4s" data-safe>{t("Посилання в описі", "Link in the description")}</div>'
        f'<div class="address" data-safe>{c["site"]}</div>'
        f'<div class="free" data-safe><span class="windows" aria-hidden="true"><i></i><i></i><i></i><i></i></span>{c["free"]}</div>',
    )
    root = Path(__file__).parent
    return base.document(
        language,
        timeline,
        captions,
        motion,
        f'<main data-creative="{CREATIVE}">' + "".join(sections) + "</main>",
        c,
        extra_css=(root / "release_carry.css").read_text(encoding="utf-8"),
        javascript=(root / "release_carry.js").read_text(encoding="utf-8"),
    )
