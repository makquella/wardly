"""A test Short in the dynamic hook format (docs/marketing/shorts-rules.md).

Who threw the game: the argument in chat is the hook, the promise comes before
the brand, every claim plays out on screen (the match number typed in, the
review sections ticked off, the score counting up), one concrete example with
numbers, a second hook in the middle (tips during the match), an objection
answered with a joke, and only a short free-for-Windows ending.

Built by the beta engine (beta.build, `--creative review-who-threw`) on its
own layout (hook_review.css/js). Cards and labels come from the app's own texts
(analysis_texts, post_match_analysis, map_hints, match-texts.js), so the video
says what the app says. The chat lines are a dramatisation, not a feature.
"""

from __future__ import annotations

import copy
import html
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from . import beta_scenes as base
from . import carry_beta

CREATIVE = "review-who-threw"
REVISION = 10
HEROES = ("antimage",)
# The voice is slower than the reference's narrator; the hook format runs up to
# the reference's length rather than cutting the example.
MAX_SECONDS = 34
# Draft storyboards without a voice: seconds per word and per scene.
DRAFT_PACE = (0.4, 0.25)

PHRASES = {
    "uk": [
        "Програв катку|і в чаті сперечаєтесь,|хто злив?",
        "Перевір свою частину.|Це Wardly.",
        "Вставляєш номер матчу —|і він розбирає|твою гру.",
        "Оцінка від нуля до ста,|і перемога|її не рятує.",
        "Ось твій Антимаг:|дев'ять смертей,|п'ять — від однієї|Фантомки.",
        "А в наступній грі|підкаже прямо|під час матчу.",
        "Тімейтам можна не показувати:|це не репорт,|а факти.",
        "Безкоштовно для Windows.|Посилання в описі.",
    ],
    "en": [
        "Lost the game|and arguing in chat|about who threw?",
        "Check your part.|This is Wardly.",
        "Paste your match number,|and it reviews|your game.",
        "Scored from zero to a hundred,|and a win|won't save you.",
        "Here's your Anti-Mage:|nine deaths,|five of them|to one Phantom Assassin.",
        "And next game,|it tips you|during the match.",
        "No need to show your teammates:|it's not a report,|just facts.",
        "Free for Windows.|Link in the description.",
    ],
}

COPY = {
    "uk": {"label": "", "free": "Безкоштовно для Windows", "site": "luhovyimvp.dev"},
    "en": {"label": "", "free": "Free for Windows", "site": "luhovyimvp.dev/en/"},
}

# The example review: Anti-Mage 2/9/4, five of the nine deaths to Phantom
# Assassin (OpenDota's killed_by), a C (62) for the match.
KDA = (2, 9, 4)
KILLER_NPC = "npc_dota_hero_phantom_assassin"
KILLED = 5
MATCH_NUMBER = "8041237615"
# A dramatised all-chat after a lost game; the last line sets up "not a report".
CHAT = {
    "uk": [
        ("pudge", "Pudge", "гг, мід програв лінію"),
        ("crystal_maiden", "Crystal Maiden", "а варди хто ставив?"),
        ("antimage", "Anti-Mage", "я все робив правильно"),
        ("juggernaut", "Juggernaut", "керрі 25 хв без БФ"),
        ("witch_doctor", "Witch Doctor", "репорт піку"),
    ],
    "en": [
        ("pudge", "Pudge", "gg, mid lost the lane"),
        ("crystal_maiden", "Crystal Maiden", "who was warding?"),
        ("antimage", "Anti-Mage", "i did everything right"),
        ("juggernaut", "Juggernaut", "carry 25 min, no BF"),
        ("witch_doctor", "Witch Doctor", "report the picker"),
    ],
}
# Labels the app shows, checked against match-texts.js.
APP_LABELS = {
    "uk": {
        "open": "Відкрити матч за номером",
        "placeholder": "Номер або посилання на матч",
        "button": "Відкрити",
        "loading": "Завантажую матч з OpenDota…",
    },
    "en": {
        "open": "Open a match by its number",
        "placeholder": "Match number or link",
        "button": "Open",
        "loading": "Fetching the match from OpenDota…",
    },
}
# The review sections, in the order the app scores them.
SECTION_KEYS = ("laning", "farm", "survival", "fights", "items")


def screens(language: str) -> dict:
    """Every app text on screen for one language; raises if the app changed."""
    carry_beta._backend()
    from app.analysis_texts import FINDINGS, SECTIONS
    from app.dota_constants import hero_name_from_npc

    texts = (carry_beta.RENDERER / "match-texts.js").read_text(encoding="utf-8")
    labels = APP_LABELS[language]
    missing = [value for value in labels.values() if value not in texts]
    assert not missing, f"match-texts.js changed: {missing}"
    killer = hero_name_from_npc(KILLER_NPC)
    finding = FINDINGS["killed_by_one"][language]
    review = carry_beta.review(language)
    return {
        "labels": labels,
        "sections": [SECTIONS[key][language] for key in SECTION_KEYS],
        "score": review["score"],
        "result": review["result"],
        "killer": killer,
        "finding": (
            finding["title"].format(hero=killer),
            finding["text"].format(hero=killer, count=KILLED, deaths=KDA[1]),
        ),
        "tip": carry_beta.cards(language)["fight"],
    }


def verify() -> dict:
    """The video's claims against the app; raises on a mismatch."""
    for language in ("uk", "en"):
        screen = screens(language)
    # post_match_analysis reports killed_by_one at 3+ deaths and 40%+ of them.
    assert KILLED >= 3 and KILLED / KDA[1] >= 0.4
    assert screen["killer"] == "Phantom Assassin"
    assert screen["score"][1] == "C" and screen["result"] == ("A", "D")
    return {"killed_by": KILLED, "deaths": KDA[1], "grade": screen["score"][1]}


def metadata(language: str) -> dict:
    uk = language == "uk"
    url = f"https://luhovyimvp.dev/{'' if uk else 'en/'}beta.html?ref=shorts-whothrew-{language}"
    if uk:
        return {
            "title": "Хто злив катку? Перевір свою частину | Dota 2",
            "description": (
                "Вставте номер свого матчу: Wardly бере дані з OpenDota й розбирає вашу "
                "гру — оцінка від 0 до 100 (перемога її не рятує), смерті й головна "
                "загроза, одне головне на наступну гру. А в матчі — підказки прямо під "
                "час гри.\n\n"
                f"Безкоштовний Windows-тренер для Dota 2: {url}\n\n"
                "#Dota2 #ДотаУкраїнською #Wardly"
            ),
            "tags": [
                "Dota 2",
                "дота 2",
                "Wardly",
                "Dota 2 українською",
                "розбір матчу",
                "хто злив",
                "тренер Dota 2",
            ],
        }
    return {
        "title": "Who threw the game? Check your part | Dota 2",
        "description": (
            "Paste your match number: Wardly pulls the data from OpenDota and reviews "
            "your game — a score from 0 to 100 (a win does not save it), your deaths "
            "and the main threat, one thing to fix next game. And during the match, "
            "tips right in the game.\n\n"
            f"A free Windows coach for Dota 2: {url}\n\n"
            "#Dota2 #Dota2Coach #Wardly"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Dota 2 coach",
            "match review",
            "who threw",
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
        MAX_SECONDS=MAX_SECONDS,
        DRAFT_PACE=DRAFT_PACE,
        phrase_captions=partial(base.phrase_captions, phrases=PHRASES),
        page=page,
    )


def page(language, timeline, captions, motion=None):
    uk = language == "uk"

    def t(ukrainian: str, english: str) -> str:
        return ukrainian if uk else english

    esc = html.escape
    assets = base.SITE / "assets"
    motion = motion or {}
    screen = screens(language)
    labels = screen["labels"]

    def portrait(key: str, cls: str = "face") -> str:
        return f'<img class="{cls}" src="{base.uri(assets / "heroes" / f"{key}.webp")}">'

    def hero(key: str, cls: str) -> str:
        frames = motion.get(key)
        source = frames[0] if frames else base.uri(assets / "heroes" / f"{key}.webp")
        kind = "animated" if frames else "poster"
        return f'<img class="{cls} {kind}" data-hero="{key}" src="{source}">'

    sections: list[str] = []

    def scene(body: str) -> None:
        sections.append(f'<section class="scene s{len(sections)}">{body}</section>')

    # 0. The hook: the argument in all-chat after a lost game.
    rows = "".join(
        f'<div class="chat-row fx" data-fx="slide" data-at="{0.3 + 0.24 * i:.2f}">'
        f"{portrait(key)}<div><span data-safe>{esc(name)}</span>"
        f'<b data-safe class="{"bad" if i == len(CHAT[language]) - 1 else ""}">{esc(line)}</b></div></div>'
        for i, (key, name, line) in enumerate(CHAT[language])
    )
    words = t("Хто злив катку?", "Who threw the game?").split()
    headline = "".join(
        f'<span class="word fx" data-fx="blur" data-at="{0.05 + 0.13 * i:.2f}" data-safe>{esc(w)}</span> '
        for i, w in enumerate(words)
    )
    scene(
        f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>{t("РОЗБІР МАТЧІВ DOTA 2", "DOTA 2 MATCH REVIEW")}</div>'
        f'<h1 class="headline">{headline}</h1>'
        f'<div class="chat fx" data-fx="rise" data-at="0.2"><div class="chat-head" data-safe>{t("ЧАТ · ВСІ", "CHAT · ALL")}</div>{rows}</div>'
    )
    # 1. The promise, then the brand.
    scene(
        f'<h1 class="promise fx" data-fx="blur" data-at="0" data-safe>{t("Перевір<br><em>свою частину</em>", "Check<br><em>your part</em>")}</h1>'
        '<div class="burst" data-on="wardly"></div>'
        f'<img class="brand-logo fx" data-fx="pop" data-on="wardly" src="{base.uri(assets / "logo.png")}" data-brand>'
        '<div class="brand-name fx" data-fx="pop" data-on="wardly" data-delay="0.08" data-safe>Wardly</div>'
    )
    # 2. The process: the match number typed in, then the review sections.
    checks = "".join(
        f'<div class="check" data-step="{i}"><i></i><span data-safe>{esc(name)}</span></div>'
        for i, name in enumerate(screen["sections"])
    )
    scene(
        f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>WARDLY</div>'
        f'<h1 class="title fx" data-fx="blur" data-at="0.05" data-safe>{esc(labels["open"])}</h1>'
        '<div class="form fx" data-fx="rise" data-at="0.15">'
        f'<div class="field"><span class="placeholder" data-safe>{esc(labels["placeholder"])}</span>'
        f'<span class="typed" data-safe data-text="{MATCH_NUMBER}"></span><i class="caret"></i></div>'
        f'<div class="button" data-safe>{esc(labels["button"])}</div></div>'
        f'<div class="status" data-safe><i class="spin"></i>{esc(labels["loading"])}</div>'
        f'<div class="checks"><div class="bar"><i></i></div>{checks}</div>'
    )
    # 3. The score counts up; the result does not save it.
    number, grade, label = screen["score"]
    won, lost = screen["result"]
    scene(
        f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>{esc(label.upper())} · 0–100</div>'
        '<div class="gauge fx" data-fx="pop" data-at="0.05"><svg viewBox="0 0 200 200">'
        '<circle class="track" cx="100" cy="100" r="86"/><circle class="arc" cx="100" cy="100" r="86"/></svg>'
        f'<b class="count" data-safe data-to="{number}">0</b><span class="grade" data-safe>{grade}</span></div>'
        f'<div class="result fx" data-fx="slide" data-on="{t("перемога", "win")}"><span data-safe>{t("Поразка", "Loss")}</span><b class="good" data-safe>80 · {won}</b></div>'
        f'<div class="result r2 fx" data-fx="slide" data-on="{t("перемога", "win")}" data-delay="0.18"><span data-safe>{t("Перемога", "Win")}</span><b class="bad" data-safe>30 · {lost}</b></div>'
    )
    # 4. The example: Anti-Mage, nine deaths, five to one hero.
    title, body = screen["finding"]
    kda = " / ".join(
        f'<span class="{"bad" if i == 1 else ""}">{n}</span>' for i, n in enumerate(KDA)
    )
    scene(
        f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>{t("ПРИКЛАД РОЗБОРУ", "REVIEW EXAMPLE")}</div>'
        f'<div class="example-hero">{hero("antimage", "example-art")}</div>'
        f'<div class="kda fx" data-fx="pop" data-on="{t("дев", "nine")}" data-safe>{kda}</div>'
        f'<div class="kda-label fx" data-fx="blur" data-on="{t("дев", "nine")}" data-delay="0.1" data-safe>{t("ВБИВСТВА · СМЕРТІ · ДОПОМОГА", "KILLS · DEATHS · ASSISTS")}</div>'
        f'<div class="finding fx" data-fx="rise" data-on="{t("від", "five")}" data-delay="{t("-0.3", "0")}">{portrait("phantom_assassin", "threat")}'
        f"<div><b data-safe>{esc(title)}</b><p data-safe>{esc(body)}</p></div></div>"
    )
    # 5. The second hook: the tips during the next match.
    tip_title, tip_body = screen["tip"]
    scene(
        f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>{t("НАСТУПНА ГРА", "NEXT GAME")}</div>'
        f'<h1 class="title fx" data-fx="blur" data-at="0.05" data-safe>{t("Прямо<br><em>під час матчу</em>", "Right<br><em>in the match</em>")}</h1>'
        f'<div class="monitor fx" data-fx="rise" data-at="0.1"><img src="{base.uri(assets / "game" / f"ingame-{language}.jpg")}"></div>'
        f'<div class="tip fx" data-fx="slam" data-on="{t("підкаже", "tips")}">'
        f'<div class="tip-kicker" data-safe>{t("Підказка Wardly", "Wardly tip")}</div>'
        f"<b data-safe>{esc(tip_title)}</b><p data-safe>{esc(tip_body)}</p></div>"
    )
    # 6. The objection, answered: not a report, facts.
    scene(
        f'<h1 class="aside fx" data-fx="blur" data-at="0" data-safe>{t("Тімейтам —<br><em>можна не показувати</em>", "Your teammates —<br><em>don&#x27;t need to see it</em>")}</h1>'
        f'<div class="report fx" data-fx="pop" data-at="0.45" data-safe>{t("РЕПОРТ", "REPORT")}<i class="strike"></i></div>'
        f'<div class="stamp fx" data-fx="slam" data-on="{t("репорт", "report")}" data-delay="0.55" data-safe>{t("ФАКТИ З МАТЧУ", "FACTS FROM THE MATCH")} ✓</div>'
    )
    # 7. The ending: free, the address, what is inside.
    features = (
        (
            t("Розбір матчу", "Match review"),
            t("оцінка 0–100, смерті, головне", "score 0–100, deaths, focus"),
        ),
        (t("Підказки в грі", "In-game tips"), t("прямо під час матчу", "right during the match")),
        (t("Плани героїв", "Hero plans"), t("предмети й прокачка", "items and skills")),
    )
    cards = "".join(
        f'<div class="feature fx" data-fx="slide" data-at="{0.5 + 0.14 * i:.2f}"><i>{i + 1}</i>'
        f"<div><b data-safe>{esc(name)}</b><span data-safe>{esc(note)}</span></div></div>"
        for i, (name, note) in enumerate(features)
    )
    c = COPY[language]
    scene(
        '<div class="wordmark fx" data-fx="pop" data-at="0" data-safe><i></i>Wardly</div>'
        f'<div class="slogan fx" data-fx="blur" data-at="0.1" data-safe>{t("Факти, а не репорт.", "Facts, not a report.")}</div>'
        f'<div class="address fx" data-fx="pop" data-at="0.25" data-safe>{c["site"]}</div>'
        f'<div class="free fx" data-fx="blur" data-at="0.35" data-safe>{t("БЕЗКОШТОВНО · WINDOWS", "FREE · WINDOWS")}</div>'
        f'<div class="features">{cards}</div>'
    )
    root = Path(__file__).parent
    return base.document(
        language,
        timeline,
        captions,
        motion,
        '<div class="map"><div class="plane">' + _map() + "</div></div>"
        '<div class="glow"></div><div class="dust"></div>'
        f'<main data-creative="{CREATIVE}">' + "".join(sections) + "</main>",
        c,
        extra_css=(root / "hook_review.css").read_text(encoding="utf-8"),
        javascript=(root / "hook_review.js").read_text(encoding="utf-8"),
        header=False,
    )


def _map() -> str:
    """The schematic Dota map behind every scene: Radiant bottom left, Dire top
    right, the river across, three lanes and their towers."""
    towers = []
    for x, y, side in (
        (60, 640, "r"),
        (60, 420, "r"),
        (60, 210, "d"),
        (360, 940, "r"),
        (580, 940, "r"),
        (790, 940, "d"),
        (330, 670, "r"),
        (430, 570, "r"),
        (570, 430, "d"),
        (670, 330, "d"),
        (940, 360, "d"),
        (940, 580, "d"),
        (210, 60, "r"),
        (420, 60, "d"),
        (640, 60, "d"),
    ):
        towers.append(
            f'<rect class="tower {side}" x="{x - 14}" y="{y - 14}" width="28" height="28" rx="4"/>'
        )
    return (
        '<svg viewBox="0 0 1000 1000">'
        '<rect class="land" x="0" y="0" width="1000" height="1000" rx="40"/>'
        '<path class="river" d="M0 330 C 260 420, 420 520, 520 560 S 820 700, 1000 680 L 1000 760 '
        'C 820 780, 560 660, 470 620 S 230 500, 0 410 Z"/>'
        '<path class="lane" d="M60 940 L60 60 L940 60"/>'
        '<path class="lane" d="M60 940 L940 940 L940 60"/>'
        '<path class="lane" d="M90 910 L910 90"/>'
        '<circle class="base r" cx="90" cy="910" r="60"/><circle class="base d" cx="910" cy="90" r="60"/>'
        + "".join(towers)
        + "</svg>"
    )
