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
# Optional generated b-roll behind three scenes (24 fps frames passed in
# motion["clip:<name>"]; the scene is plain without them): seconds into the
# clip at the scene's start. For "rage" it is the desk slam's second in the
# clip instead: the page starts the clip so that the slam lands on «хто злив».
CLIPS = {"rage": 3.1, "warrior": 0.3, "keys": 1.5}
CLIP_FPS = 24


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
        broll=broll,
        mix=mix,
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

    def scene(body: str, cls: str = "") -> None:
        sections.append(f'<section class="scene s{len(sections)} {cls}">{body}</section>')

    def footage(name: str) -> str:
        """Generated b-roll (motion["clip:<name>"], see CLIPS) behind a scene."""
        frames = motion.get(f"clip:{name}")
        if not frames:
            return ""
        return (
            f'<div class="footage"><img class="clip" data-clip="{name}" '
            f'data-from="{CLIPS[name]:.2f}" src="{frames[0]}"></div><div class="shade"></div>'
        )

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
    rage = footage("rage")
    # With the b-roll the chat pops up over the desk in bubbles the slam knocks away
    # (they start inside the safe area; flying off-screen is the point, so their
    # text is not held to it).
    bubbles = "".join(
        f'<div class="bubble b{i} fx" data-fx="pop" data-at="{0.25 + 0.38 * i:.2f}">'
        f'{portrait(key)}<b class="{"bad" if i == 3 else ""}">{esc(line)}</b></div>'
        for i, (key, _name, line) in enumerate(CHAT[language][1:])
    )
    chat = (
        f'<div class="bubbles">{bubbles}</div>'
        if rage
        else f'<div class="chat fx" data-fx="rise" data-at="0.2"><div class="chat-head" data-safe>{t("ЧАТ · ВСІ", "CHAT · ALL")}</div>{rows}</div>'
    )
    scene(
        rage
        + f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>{t("РОЗБІР МАТЧІВ DOTA 2", "DOTA 2 MATCH REVIEW")}</div>'
        f'<h1 class="headline">{headline}</h1>' + chat,
        "with-footage" if rage else "",
    )
    # 1. The promise, then the brand.
    warrior = footage("warrior")
    scene(
        warrior
        + f'<h1 class="promise fx" data-fx="blur" data-at="0" data-safe>{t("Перевір<br><em>свою частину</em>", "Check<br><em>your part</em>")}</h1>'
        '<div class="burst" data-on="wardly"></div>'
        f'<img class="brand-logo fx" data-fx="pop" data-on="wardly" src="{base.uri(assets / "logo.png")}" data-brand>'
        '<div class="brand-name fx" data-fx="pop" data-on="wardly" data-delay="0.08" data-safe>Wardly</div>',
        "with-footage" if warrior else "",
    )
    # 2. The process: the match number typed in, then the review sections.
    checks = "".join(
        f'<div class="check" data-step="{i}"><i></i><span data-safe>{esc(name)}</span></div>'
        for i, name in enumerate(screen["sections"])
    )
    keys = footage("keys")
    scene(
        keys + f'<div class="kicker fx" data-fx="blur" data-at="0" data-safe><i></i>WARDLY</div>'
        f'<h1 class="title fx" data-fx="blur" data-at="0.05" data-safe>{esc(labels["open"])}</h1>'
        f'<div class="form fx" data-fx="rise" data-at="{0.6 if keys else 0.15}">'
        f'<div class="field"><span class="placeholder" data-safe>{esc(labels["placeholder"])}</span>'
        f'<span class="typed" data-safe data-text="{MATCH_NUMBER}"></span><i class="caret"></i></div>'
        f'<div class="button" data-safe>{esc(labels["button"])}</div></div>'
        f'<div class="status" data-safe><i class="spin"></i>{esc(labels["loading"])}</div>'
        f'<div class="checks"><div class="bar"><i></i></div>{checks}</div>',
        "with-footage keys" if keys else "",
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
    flash = '<div class="flash"></div>'
    return base.document(
        language,
        timeline,
        captions,
        motion,
        '<div class="map"><div class="plane">' + _map() + "</div></div>"
        '<div class="glow"></div><div class="dust"></div>'
        f'<main data-creative="{CREATIVE}">' + "".join(sections) + "</main>" + flash,
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


# --- b-roll and sound for the full cut ----------------------------------------------

# Generated with Higgsfield (Kling 3.0, 9:16, 5 s, native sound), 2026-10-22; the
# keyboard is a pro-mode single-finger take (a two-handed typing take looked fake).
BROLL = {
    "rage": (
        "https://d8j0ntlcm91z4.cloudfront.net/user_3L48PZ0BtANBTDRDPsU5hmY79Dx/"
        "hf_20261022_205701_3a676d30-7a75-489d-811e-f80cb628807c.mp4",
        "edecf94a649fcf33ddbb19f235b9218fc75d86578eb330d61f9524891dd946ea",
    ),
    "warrior": (
        "https://d8j0ntlcm91z4.cloudfront.net/user_3L48PZ0BtANBTDRDPsU5hmY79Dx/"
        "hf_20261022_205701_4dcc1bed-3754-4294-a418-f0bcebcdfbc3.mp4",
        "5e3471e5b5b78d2031ffd24c4208a4555c11dfa9601e3aec3919696823be09a0",
    ),
    "keys": (
        "https://d8j0ntlcm91z4.cloudfront.net/user_3L48PZ0BtANBTDRDPsU5hmY79Dx/"
        "hf_20261022_214134_93819959-d8ab-461e-abc3-c20299ae334a.mp4",
        "e77b3bab6579d0a560760e0a009b42649047718b516e9700c79ef8ea2b7ce634",
    ),
}


def broll(out: Path) -> dict[str, list[str]]:
    """Download the b-roll (hash-checked) and return its frames for the page."""
    import hashlib
    import subprocess
    import urllib.request

    from . import render

    root = out / "broll"
    root.mkdir(parents=True, exist_ok=True)
    frames: dict[str, list[str]] = {}
    for name, (url, sha256) in BROLL.items():
        video = root / f"{name}.mp4"
        if not video.exists() or hashlib.sha256(video.read_bytes()).hexdigest() != sha256:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                video.write_bytes(response.read())
        if hashlib.sha256(video.read_bytes()).hexdigest() != sha256:
            raise ValueError(f"b-roll {name} changed at its source")
        folder = root / name
        folder.mkdir(exist_ok=True)
        if not any(folder.glob("*.jpg")):
            subprocess.run(
                [render.ffmpeg(), "-v", "error", "-y", "-i", str(video),
                 "-vf", f"fps={CLIP_FPS},scale=810:1440", "-q:v", "5", str(folder / "%04d.jpg")],
                check=True,
            )  # fmt: skip
        frames[f"clip:{name}"] = [base.uri(path) for path in sorted(folder.glob("*.jpg"))]
    return frames


def sound_events(
    language: str, timeline: list[dict], captions: list[dict]
) -> tuple[list[tuple], float]:
    """([(seconds, effect, dB)], slam): the ElevenLabs effects (sound_effects.EFFECTS) on the
    moments hook_review.js animates, quiet enough to stay under the voice."""
    uk = language == "uk"
    words = [w for caption in captions for w in caption["words"]]

    def start(scene: int) -> float:
        return timeline[scene]["start"]

    def word(scene: int, fragment: str, fallback: float) -> float:
        span = timeline[scene]
        for w in words:
            if span["start"] - 0.01 <= w["s"] < span["end"] and fragment in w["w"].lower():
                return w["s"] - span["start"]
        return fallback

    events = [(0.0, "hit", -9)]
    events += [(0.05 + 0.13 * i, "tick", -14) for i in range(3)]
    events += [(0.25 + 0.38 * i, "chat", -9) for i in range(4)]
    slam = word(0, "хто" if uk else "who", 2.4) - 0.04
    events += [(slam - 0.03, "slam", -9), (slam, "boom", -12)]
    events += [
        (start(i) - 0.32, "whoosh" if i % 2 else "swipe", -9) for i in range(1, len(timeline))
    ]
    wardly = start(1) + word(1, "wardly", 2.2) - 0.08
    events += [(wardly - 2.0, "riser", -14), (wardly - 0.05, "logo", -8), (wardly, "boom", -13)]
    typed = start(2) + word(2, "номер" if uk else "number", 0.6) + 0.05
    press = typed + 0.12 + 0.045 * len(MATCH_NUMBER)
    checks = max(press + 0.25, start(2) + word(2, "розбирає" if uk else "reviews", 1.6))
    end = timeline[2]["end"] - 0.35
    events += [(typed, "typing", -7), (press, "enter", -8)]
    events += [(checks + (i + 1) * (end - checks) / 5 - 0.05, "check", -11) for i in range(5)]
    row = start(3) + word(3, "перемога" if uk else "win", 1.8) - 0.08
    events += [(start(3) + 0.15, "score", -17), (start(3) + 1.25, "hit", -15)]
    events += [(row, "swipe", -10), (row + 0.18, "swipe", -11)]
    nine = start(4) + word(4, "дев" if uk else "nine", 1.4) - 0.08
    threat = start(4) + word(4, "від" if uk else "five", 2.6) - 0.08 - (0.3 if uk else 0)
    events += [(nine, "sword", -11), (nine + 0.02, "hit", -13), (threat, "glitch", -9)]
    events.append((start(5) + word(5, "підкаже" if uk else "tips", 1.0) - 0.08, "hit", -15))
    report = start(6) + word(6, "репорт" if uk else "report", 1.2)
    events += [(start(6) + 0.45, "hit", -15), (report + 0.1, "glitch", -8)]
    events.append((report + 0.47, "stamp", -6))
    events += [(start(7), "boom", -17), (start(7) + 0.25, "click", -8)]
    events += [(start(7) + 0.5 + 0.14 * i, "check", -12) for i in range(3)]
    return [(max(0.0, at), name, db) for at, name, db in events], slam


def mix(language, timeline, captions, narration: Path, total: float, out: Path, sfx: Path) -> Path:
    """Narration + b-roll sound + effects + a music bed ducked under the voice."""
    import subprocess

    from . import render

    events, slam = sound_events(language, timeline, captions)
    broll_dir = out.parent.parent / "broll"
    inputs = ["-i", str(narration), "-stream_loop", "-1", "-i", str(sfx / "music.mp3")]
    clips = [  # (clip, seconds into it, where, length, dB)
        ("rage", CLIPS["rage"] - slam, 0.0, timeline[0]["end"], -13),
        ("warrior", CLIPS["warrior"], timeline[1]["start"], timeline[1]["end"] - timeline[1]["start"], -16),
        ("keys", CLIPS["keys"], timeline[2]["start"], 1.0, -14),
    ]  # fmt: skip
    inputs += [arg for name, *_ in clips for arg in ("-i", str(broll_dir / f"{name}.mp4"))]
    inputs += [arg for _, name, _ in events for arg in ("-i", str(sfx / f"{name}.mp3"))]
    outro = timeline[-1]["start"]
    parts = [
        f"[0:a]apad,atrim=0:{total},asplit=2[voice][key]",
        f"[1:a]atrim=0:{total},volume=-19dB,afade=t=in:d=0.4,"
        f"afade=t=out:st={total - 1.2}:d=1.2,volume='if(gte(t,{outro}),1.3,1)':eval=frame[music]",
        "[music][key]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=250[bed]",
    ]
    labels = ["[voice]", "[bed]"]
    for i, (_name, offset, at, length, db) in enumerate(clips):
        ms = int(at * 1000)
        parts.append(
            f"[{2 + i}:a]atrim={max(0.0, offset)}:{max(0.0, offset) + length},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={max(0.0, length - 0.25)}:d=0.25,volume={db}dB,adelay={ms}|{ms},"
            f"apad,atrim=0:{total}[c{i}]"
        )
        labels.append(f"[c{i}]")
    first = 2 + len(clips)
    for i, (at, _name, db) in enumerate(events):
        ms = int(at * 1000)
        parts.append(f"[{first + i}:a]volume={db}dB,adelay={ms}|{ms},apad,atrim=0:{total}[e{i}]")
        labels.append(f"[e{i}]")
    # Every track is padded to the full length, so amix divides by the same count
    # throughout and volume undoes it (the workflow's ffmpeg 4.2 has no normalize=0).
    parts.append(
        "".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,"
        f"volume={len(labels)},atrim=0:{total},alimiter=limit=0.89[mix]"
    )
    subprocess.run(
        [render.ffmpeg(), "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts),
         "-map", "[mix]", "-ar", "48000", "-ac", "2", str(out)],
        check=True,
    )  # fmt: skip
    return out
