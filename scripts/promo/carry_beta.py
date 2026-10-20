"""Two scheduled Shorts pairs (Ukrainian, English) for the carry beta.

- `carry-match-review`: the review after a match (a score from 0 to 100 that
  the result does not change, the last hits against the other carry of the
  match, one thing to fix next game).
- `carry-decisive-moments`: the cards for the moments that decide a game
  (enemy Aegis, a fight at your tower, buyback on the death screen).

Built by the beta engine (beta.build, `--creative`) like the 0.57 release pair,
on its layout (release_carry.css/js). The cards' words come from the app's own
texts (post_match_analysis, analysis_texts, roshan_timer, map_hints,
death_screen, match-texts.js), so the video
and the app say the same thing. Each pair has a publish time (PUBLISH_AT): the
Shorts button registers it with the Worker, and YouTube publishes the video
itself at that time (services/api/src/social.js, private until then).
"""

from __future__ import annotations

import copy
import html
import sys
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from . import beta_scenes as base
from . import release_carry

REVIEW = "carry-match-review"
MOMENTS = "carry-decisive-moments"
CREATIVES = (REVIEW, MOMENTS)
REVISION = {REVIEW: 8, MOMENTS: 9}
# 17:00 in Kyiv (EEST, UTC+3 until 25 October).
PUBLISH_AT = {REVIEW: "2026-10-21T14:00:00Z", MOMENTS: "2026-10-22T14:00:00Z"}
HEROES = {
    REVIEW: ("antimage",),
    MOMENTS: ("sven", "phantom_assassin"),
}
BACKEND = base.SITE.parent / "backend"
RENDERER = base.SITE.parent / "frontend" / "launcher" / "renderer"

PHRASES = {
    REVIEW: {
        "uk": [
            "Програв|і не знаєш чому?",
            "Після матчу Wardly|ставить оцінку|від нуля до ста.",
            "Перемога чи поразка|на неї не впливає.",
            "Порівнює тебе|з іншим керрі матчу:|добивання до десятої хвилини.",
            "І дає одне головне|на наступну гру.",
            "Безкоштовно для Windows.",
            "Посилання в описі.",
        ],
        "en": [
            "Lost|and not sure why?",
            "After the match,|Wardly gives a score|from zero to a hundred.",
            "Winning or losing|does not change it.",
            "It compares you|with the other carry:|last hits by minute ten.",
            "And gives you one thing|to fix next game.",
            "Free for Windows.",
            "Link in the description.",
        ],
    },
    MOMENTS: {
        "uk": [
            "Одна бійка|може вирішити гру.",
            "Вороги забрали Рошана?|Wardly покаже,|до якої хвилини|в них Аегіс.",
            "Бійка біля твоєї вежі?|Скільки там союзників,|скільки ворогів|і чи готовий телепорт.",
            "Помер?|Екран смерті скаже,|скільки бракує на байбек.",
            "Рішення за тобою:|лише те, що видно в грі.",
            "Безкоштовно для Windows.",
            "Посилання в описі.",
        ],
        "en": [
            "One fight|can decide the game.",
            "Enemies took Roshan?|Wardly shows|until what minute|they hold the Aegis.",
            "A fight at your tower?|How many allies,|how many enemies,|and whether your teleport is ready.",
            "Died?|The death screen says|how much your buyback is short.",
            "The call is yours:|only what the game shows.",
            "Free for Windows.",
            "Link in the description.",
        ],
    },
}
EMPHASIS = {
    REVIEW: "wardly|оцінку|score|ста|hundred|впливає|change|керрі|carry|головне|thing|windows",
    MOMENTS: "wardly|рошана|roshan|аегіс|aegis|телепорт|teleport|байбек|buyback|тобою|yours|windows",
}

COPY = {
    "uk": {"label": "БЕТА-ТЕСТ", "free": "Безкоштовно для Windows", "site": "luhovyimvp.dev/beta"},
    "en": {"label": "BETA TEST", "free": "Free for Windows", "site": "luhovyimvp.dev/en/beta"},
}

# The example game behind the cards: the enemy picks up the Aegis at 25:03, a
# fight at the player's mid T2 with 3 allies and 2 enemies, a death at minute
# 27 with buyback off cooldown and 530 gold short.
AEGIS_UNTIL = "30:03"
FIGHT = {
    "tower": {"lane": "mid", "tier": 2, "team": "radiant"},
    "team": "radiant",
    "allies": [1, 2, 3],
    "enemies": [1, 2],
    "tp_cooldown": 0,
    "has_tp": True,
}
DEATH = {"respawn": 42, "cost": 1650, "gold": 1120}
# The example review: a C (62), a lost last-hit race against the other carry.
SCORE = 62
PEER = {"lh10": 31, "peer_lh10": 44, "heroes": "Phantom Assassin"}


def kyiv(at: str) -> str:
    """«21.10.2026 17:00» for a UTC publish time."""
    moment = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Kyiv"))
    return moment.strftime("%d.%m.%Y %H:%M")


def _backend():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def cards(language: str) -> dict[str, tuple[str, str]]:
    """The three cards of the decisive-moments video, as the app words them."""
    _backend()
    from app import death_screen, roshan_timer
    from app.map_hints import TIPS, fight_params

    title, body = roshan_timer.TEXT["enemy_aegis"][language]
    fight_title, fight_body = TIPS["fight"][language]
    params = fight_params(FIGHT, language)
    death = death_screen.TEXT[language]
    short = death_screen._no_buyback(DEATH["gold"], DEATH["cost"], 0, 27, False)
    assert short == {"cost": 1650, "gold": 1120, "need": 530}
    return {
        "aegis": (title.format(until=AEGIS_UNTIL), body),
        "fight": (fight_title.format(**params), fight_body.format(**params)),
        "death": (
            death["title"].format(s=DEATH["respawn"]),
            death["no_buyback"].format(**short),
        ),
    }


def review(language: str) -> dict[str, tuple[str, ...]]:
    """The review screens of the match-review video, as the app words them."""
    _backend()
    from app.analysis_texts import FINDINGS, PEER_ROLES
    from app.post_match_analysis import _grade

    texts = (RENDERER / "match-texts.js").read_text(encoding="utf-8")
    labels = {
        "uk": ("Оцінка", "Головне на наступну гру", "можна програти з 80 і виграти з 30"),
        "en": ("Score", "Focus for the next game", "you can lose with 80 and win with 30"),
    }[language]
    assert all(label in texts for label in labels), "review labels changed in match-texts.js"
    finding = FINDINGS["peer_lh10_behind"][language]
    body = finding["text"].format(role_label=PEER_ROLES["carry"][language], **PEER)
    return {
        "score": (str(SCORE), _grade(SCORE), labels[0]),
        "result": (_grade(80), _grade(30)),
        "finding": (finding["title"], body),
        "focus": (labels[1], finding["title"], finding["drill"]),
    }


def verify(creative: str) -> dict:
    """The video's claims against the app and its data; raises on a mismatch."""
    _backend()
    from app import death_screen, fight_summary, roshan_timer

    if creative == REVIEW:
        for language in ("uk", "en"):
            screens = review(language)
        assert screens["score"][1] == "C" and screens["result"] == ("A", "D")
        return {"score": SCORE, "grade": screens["score"][1]}
    # The Aegis lasts 5 minutes: picked up at 25:03, it is gone by 30:03.
    assert roshan_timer._settings()["aegis"] == 300
    assert fight_summary.MIN_ALLIES >= 2 and fight_summary.MIN_ENEMIES >= 2
    assert death_screen.NO_BUYBACK_MINUTE <= 27
    for language in ("uk", "en"):
        cards(language)
    return {"aegis_seconds": 300, "no_buyback_from_minute": death_screen.NO_BUYBACK_MINUTE}


def metadata(creative: str, language: str) -> dict:
    uk = language == "uk"
    short = "review" if creative == REVIEW else "moments"
    url = f"https://luhovyimvp.dev/{'' if uk else 'en/'}beta.html?ref=shorts-{short}-{language}"
    if creative == REVIEW:
        if uk:
            return {
                "title": "Програв і не знаєш чому? Розбір матчу з оцінкою | Dota 2",
                "description": (
                    "Після кожного матчу Wardly ставить оцінку від 0 до 100: лінія, фарм, "
                    "виживання, бійки, предмети. Перемога чи поразка на неї не впливають. "
                    "Порівнює вас із гравцем вашої ролі в тому ж матчі — добивання до 10:00, "
                    "золото за хвилину, смерті — і дає одне головне на наступну гру.\n\n"
                    "Безкоштовний Windows-тренер для Dota 2. Шукаємо керрі до 4000 MMR "
                    f"для бета-тесту: {url}\n\n"
                    "#Dota2 #ДотаУкраїнською #Wardly"
                ),
                "tags": [
                    "Dota 2",
                    "дота 2",
                    "Wardly",
                    "Dota 2 українською",
                    "розбір матчу",
                    "керрі",
                    "добивання",
                    "тренер Dota 2",
                ],
            }
        return {
            "title": "Lost and not sure why? A match review with a score | Dota 2",
            "description": (
                "After every match Wardly scores it from 0 to 100: lane, farm, survival, "
                "fights, items. A win or a loss does not change it. It compares you with "
                "the player of your role in the same match (last hits by 10:00, gold per "
                "minute, deaths) and gives you one thing to fix next game.\n\n"
                "A free Windows coach for Dota 2. Looking for carry players under 4,000 "
                f"MMR for the beta: {url}\n\n"
                "#Dota2 #Dota2Coach #Wardly"
            ),
            "tags": [
                "Dota 2",
                "dota2",
                "Wardly",
                "Dota 2 coach",
                "match review",
                "carry",
                "last hits",
                "Dota 2 Windows app",
            ],
        }
    if uk:
        return {
            "title": "Аегіс, бійка, байбек: коли гра вирішується | Dota 2",
            "description": (
                "Wardly показує в матчі те, що видно в грі: до якої хвилини Аегіс у "
                "ворогів, скільки союзників і ворогів у бійці біля вашої вежі й чи "
                "готовий ТП, а на екрані смерті — скільки бракує на байбек. Рішення "
                "лишається за вами й командою.\n\n"
                "Безкоштовний Windows-тренер для Dota 2. Шукаємо керрі до 4000 MMR "
                f"для бета-тесту: {url}\n\n"
                "#Dota2 #ДотаУкраїнською #Wardly"
            ),
            "tags": [
                "Dota 2",
                "дота 2",
                "Wardly",
                "Dota 2 українською",
                "Аегіс",
                "Рошан",
                "байбек",
                "керрі",
                "тренер Dota 2",
            ],
        }
    return {
        "title": "Aegis, fights, buyback: when the game is decided | Dota 2",
        "description": (
            "Wardly shows in the match what the game shows: until when the enemy holds "
            "the Aegis, how many allies and enemies are in a fight at your tower and "
            "whether your TP is ready, and on the death screen how much your buyback "
            "is short. The call stays yours and your team's.\n\n"
            "A free Windows coach for Dota 2. Looking for carry players under 4,000 "
            f"MMR for the beta: {url}\n\n"
            "#Dota2 #Dota2Coach #Wardly"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Dota 2 coach",
            "Aegis",
            "Roshan",
            "buyback",
            "carry",
            "Dota 2 Windows app",
        ],
    }


def profile(creative: str) -> SimpleNamespace:
    verify(creative)
    localized = copy.deepcopy(COPY)
    for language in ("uk", "en"):
        localized[language]["voice"] = [s.replace("|", " ") for s in PHRASES[creative][language]]
    return SimpleNamespace(
        COPY=localized,
        HEROES=HEROES[creative],
        phrase_captions=partial(base.phrase_captions, phrases=PHRASES[creative]),
        page=partial(page, creative),
    )


def page(creative, language, timeline, captions, motion=None):
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

    def advice(kicker: str, title: str, body: str, icon: str = "") -> str:
        return (
            f'<div class="advice enter" style="--d:.35s">'
            f'<div class="advice-kicker" data-safe>{esc(kicker)}</div>'
            f'<div class="advice-row">{icon}<b data-safe>{esc(title)}</b></div>'
            f"<p data-safe>{esc(body)}</p></div>"
        )

    sections: list[str] = []

    def scene(body: str) -> None:
        sections.append(f'<section class="scene s{len(sections)}">{body}</section>')

    c = COPY[language]
    if creative == REVIEW:
        screen = review(language)
        number, grade, label = screen["score"]
        scene(
            f'<div class="eyebrow enter" data-safe>DOTA 2 · {t("КЕРРІ", "CARRY")}</div>'
            f'<h1 class="big-title enter" data-safe>{t("Програв?<br><em>Чому?</em>", "Lost?<br><em>Why?</em>")}</h1>'
            f'<div class="hook-hero">{hero("antimage", "hook-art")}</div>'
        )
        scale = "".join(
            f'<span class="grade-chip enter" style="--d:{0.6 + 0.15 * i}s" data-safe><b>{g}</b> {at}</span>'
            for i, (g, at) in enumerate((("A", "80+"), ("B", "65+"), ("C", "50+"), ("D", "<50")))
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("РОЗБІР МАТЧУ", "MATCH REVIEW")}</div>'
            f'<h1 class="mid-title enter" data-safe>{esc(label)}<br><em>0–100</em></h1>'
            f'<div class="score-card enter" style="--d:.3s"><b data-safe>{number}</b>'
            f'<span class="grade" data-safe>{grade}</span></div>'
            f'<div class="grades">{scale}</div>'
        )
        won, lost = screen["result"]
        rows = (
            f'<div class="result-row enter" style="--d:.3s"><span data-safe>{t("Поразка", "Loss")}</span>'
            f"<b data-safe>80 · {won}</b></div>"
            f'<div class="result-row enter" style="--d:.7s"><span data-safe>{t("Перемога", "Win")}</span>'
            f"<b data-safe>30 · {lost}</b></div>"
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("ОЦІНКА", "SCORE")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Не за<br><em>результатом</em>", "Not by<br><em>the result</em>")}</h1>'
            f'<div class="results">{rows}</div>'
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("ІНШИЙ КЕРРІ МАТЧУ", "THE OTHER CARRY")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Добивання<br><em>до 10:00</em>", "Last hits<br><em>by 10:00</em>")}</h1>'
            + advice(t("Розбір Wardly", "Wardly review"), *screen["finding"])
        )
        focus, title, drill = screen["focus"]
        scene(
            f'<div class="eyebrow enter" data-safe>{t("ОДНЕ ГОЛОВНЕ", "ONE THING")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("На наступну<br><em>гру</em>", "For the next<br><em>game</em>")}</h1>'
            + advice(focus, title, drill)
        )
        scene(
            '<div class="eyebrow enter" data-safe>WARDLY</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Безкоштовно.<br><em>Для Windows.</em>", "Free.<br><em>For Windows.</em>")}</h1>'
            '<div class="window-art"><i></i><i></i><i></i><i></i></div>'
        )
        scene(
            '<div class="end-orbit"></div>'
            '<div class="end-version enter" data-safe>Wardly</div>'
            f'<div class="end-line enter" style="--d:.2s" data-safe>{t("Розбір після кожного матчу", "A review after every match")}</div>'
            f'<div class="end-link enter" style="--d:.4s" data-safe>{t("Посилання в описі", "Link in the description")}</div>'
            f'<div class="address" data-safe>{c["site"]}</div>'
            f'<div class="free" data-safe><span class="windows" aria-hidden="true"><i></i><i></i><i></i><i></i></span>{c["free"]}</div>'
        )
    else:
        card = cards(language)
        aegis = release_carry._item("aegis")
        aegis_icon = f'<span class="item small"><img src="{aegis}"></span>' if aegis else ""
        scene(
            f'<div class="eyebrow enter" data-safe>DOTA 2 · {t("КЕРРІ", "CARRY")}</div>'
            f'<h1 class="big-title enter" data-safe>{t("Одна бійка<br><em>вирішує</em>", "One fight<br><em>decides</em>")}</h1>'
            f'<div class="tempo-hero">{hero("sven", "tempo-art")}</div>'
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("РОШАН", "ROSHAN")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Аегіс<br><em>у ворогів</em>", "Enemy<br><em>Aegis</em>")}</h1>'
            + advice(t("Підказка Wardly", "Wardly tip"), *card["aegis"], icon=aegis_icon)
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("БІЙКА", "FIGHT")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Біля твоєї<br><em>вежі</em>", "At your<br><em>tower</em>")}</h1>'
            + advice(t("Підказка Wardly", "Wardly tip"), *card["fight"])
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("ЕКРАН СМЕРТІ", "DEATH SCREEN")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Байбек:<br><em>скільки бракує</em>", "Buyback:<br><em>how much short</em>")}</h1>'
            + advice("Wardly", *card["death"])
        )
        scene(
            f'<div class="eyebrow enter" data-safe>{t("ЛИШЕ ТЕ, ЩО ВИДНО", "ONLY WHAT THE GAME SHOWS")}</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Рішення —<br><em>за тобою</em>", "The call<br><em>is yours</em>")}</h1>'
            f'<div class="tempo-hero">{hero("phantom_assassin", "tempo-art")}</div>'
        )
        scene(
            '<div class="eyebrow enter" data-safe>WARDLY</div>'
            f'<h1 class="mid-title enter" data-safe>{t("Безкоштовно.<br><em>Для Windows.</em>", "Free.<br><em>For Windows.</em>")}</h1>'
            '<div class="window-art"><i></i><i></i><i></i><i></i></div>'
        )
        scene(
            '<div class="end-orbit"></div>'
            '<div class="end-version enter" data-safe>Wardly</div>'
            f'<div class="end-line enter" style="--d:.2s" data-safe>{t("Коли гра вирішується", "When the game is decided")}</div>'
            f'<div class="end-link enter" style="--d:.4s" data-safe>{t("Посилання в описі", "Link in the description")}</div>'
            f'<div class="address" data-safe>{c["site"]}</div>'
            f'<div class="free" data-safe><span class="windows" aria-hidden="true"><i></i><i></i><i></i><i></i></span>{c["free"]}</div>'
        )
    root = Path(__file__).parent
    css = (root / "release_carry.css").read_text(encoding="utf-8") + (
        root / "carry_beta.css"
    ).read_text(encoding="utf-8")
    return base.document(
        language,
        timeline,
        captions,
        motion,
        f'<main data-creative="{creative}" data-emphasis="{EMPHASIS[creative]}">'
        + "".join(sections)
        + "</main>",
        c,
        extra_css=css,
        javascript=(root / "release_carry.js").read_text(encoding="utf-8"),
    )
