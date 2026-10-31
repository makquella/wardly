"""Bilingual beta recruitment storyboard; rendered by the existing promo renderer."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
from pathlib import Path
from typing import Any

from .scenes import SITE

COPY = {
    "uk": {
        "label": "БЕТА · WINDOWS",
        "free": "Безкоштовно для Windows",
        "site": "luhovyimvp.dev",
        "cta": "БЕТА",
        "titles": [
            "Свен?\nДо 4к MMR?",
            "Підказки в матчі.\nРозбір після.",
            "Також шукаємо\nцих героїв.",
            "Кілька матчів.\nЧесний відгук.",
            "Що варто змінити?",
            "Покращимо\nWardly разом.",
            "Напиши «БЕТА»\nу коментарях",
        ],
        "voice": [
            "Граєш на Свені? До чотирьох тисяч MMR?",
            "Перевір Wardly: підказки в матчі та розбір після гри.",
            "Безкоштовно для Windows. Шукаємо також Джагернаута й Терорблейда.",
            "Кілька матчів. Чесний відгук.",
            "Що допомогло? Що запізнилося чи відволікало? Де помилка?",
            "Покращимо поради разом.",
            "Напиши «БЕТА» в коментарях.",
        ],
        "heroes": ["Свен", "Джагернаут", "Терорблейд"],
        "live": "ПІД ЧАС МАТЧУ",
        "review": "ПІСЛЯ ГРИ",
        "interface": "Реальний інтерфейс Wardly",
        "volunteers": "Добровільне бета-тестування",
        "feedback": [
            "Що допомогло?",
            "Що запізнилось / відволікало?",
            "Де порада була хибною?",
        ],
        "goals": ["Точніше", "Вчасніше", "Корисніше"],
        "join": "Долучайся до бета-тестування",
    },
    "en": {
        "label": "BETA · WINDOWS",
        "free": "Free for Windows",
        "site": "luhovyimvp.dev/en/",
        "cta": "BETA",
        "titles": [
            "Play Sven?\nUnder 4K MMR?",
            "In-game tips.\nPost-match reviews.",
            "These players,\ntoo.",
            "A few matches.\nHonest feedback.",
            "What should change?",
            "Let's improve\nWardly together.",
            "Comment “BETA”\nbelow",
        ],
        "voice": [
            "Play Sven under four thousand MMR?",
            "Try Wardly: in-game tips and post-match reviews.",
            "Free for Windows. Juggernaut and Terrorblade players, too.",
            "A few matches. Honest feedback.",
            "What helped? What came late or distracted you? What was wrong?",
            "Help improve the advice.",
            "Comment BETA to join.",
        ],
        "heroes": ["Sven", "Juggernaut", "Terrorblade"],
        "live": "DURING THE MATCH",
        "review": "AFTER THE GAME",
        "interface": "Actual Wardly interface",
        "volunteers": "Volunteer beta testing",
        "feedback": [
            "What helped?",
            "What was late / distracting?",
            "Which advice was wrong?",
        ],
        "goals": ["More accurate", "Better timed", "More useful"],
        "join": "Join the beta test",
    },
}
HEROES = ("sven", "juggernaut", "terrorblade")
ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M5 19 19 5M5 5h14v14"/></svg>'
ICONS = (
    '<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M12 6v8m0 2v2"/>',
)


def uri(path: Path) -> str:
    """Self-contained frames work in cloud browsers without file:// navigation."""
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


# Editorial phrase boundaries preserve every spoken word, without dangling
# articles/prepositions or the generic renderer's arbitrary character cuts.
PHRASES = {
    "uk": [
        "Граєш на Свені?|До чотирьох тисяч MMR?",
        "Перевір Wardly:|підказки в матчі|та розбір після гри.",
        "Безкоштовно для Windows.|Шукаємо також|Джагернаута й Терорблейда.",
        "Кілька матчів.|Чесний відгук.",
        "Що допомогло?|Що запізнилося|чи відволікало?|Де помилка?",
        "Покращимо поради разом.",
        "Напиши «БЕТА»|в коментарях.",
    ],
    "en": [
        "Play Sven|under four thousand MMR?",
        "Try Wardly:|in-game tips|and post-match reviews.",
        "Free for Windows.|Juggernaut and Terrorblade|players, too.",
        "A few matches.|Honest feedback.",
        "What helped?|What came late|or distracted you?|What was wrong?",
        "Help improve the advice.",
        "Comment BETA to join.",
    ],
}


def phrase_captions(
    language: str,
    words: list[dict[str, Any]],
    end: float,
    *,
    phrases: dict | None = None,
) -> list[dict[str, Any]]:
    lines = [p for scene in (phrases or PHRASES)[language] for p in scene.split("|")]
    if " ".join(lines) != " ".join(w["word"] for w in words):
        raise ValueError("Editorial captions must preserve the complete narration")
    result, at = [], 0
    for phrase in lines:
        count = len(phrase.split())
        group = words[at : at + count]
        at += count
        stop = words[at]["start"] if at < len(words) else end
        result.append(
            {
                "text": phrase,
                "start": group[0]["start"],
                "end": max(group[-1]["end"], stop),
                "words": [
                    {"w": w["word"], "s": w["start"], "e": w["end"]} for w in group
                ],
            }
        )
    return result


def page(
    language: str,
    timeline: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    motion: dict[str, list[str]] | None = None,
) -> str:
    copy = COPY[language]
    uk = language == "uk"
    esc = html.escape
    assets = SITE / "assets"
    images = {
        "logo": uri(assets / "logo.png"),
        "game": uri(assets / "game" / f"ingame-{language}.jpg"),
        "review": uri(assets / "app" / language / "review.jpg"),
    }
    motion = motion or {}
    posters = {key: uri(assets / "heroes" / (key + ".webp")) for key in HEROES}

    def hero(key: str, cls: str) -> str:
        frames = motion.get(key)
        source = frames[0] if frames else posters[key]
        return (
            f'<img class="{cls} {"animated" if frames else "poster"}" '
            f'data-hero="{key}" src="{source}">'
        )

    cards = "".join(
        f'<div class="hero-card h{i}">{hero(key, "hero-art")}'
        f'<div class="hero-name" data-safe>{esc(name)}</div></div>'
        for i, (key, name) in enumerate(zip(HEROES, copy["heroes"], strict=True))
        if i > 0
    )
    questions = (
        ["Допомогло?", "Запізно / відволікає?", "Хибна порада?"]
        if uk
        else ["Helpful?", "Late / distracting?", "Wrong advice?"]
    )
    feedback = "".join(
        f'<div class="question q{i}"><span class="question-icon"><svg viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.5">{symbol}</svg></span>'
        f"<b data-safe>{esc(text)}</b></div>"
        for i, (text, symbol) in enumerate(zip(questions, ICONS, strict=True))
    )
    goals = "".join(
        f'<div class="goal g{i}" data-safe>{esc(text)}<span>{ARROW}</span></div>'
        for i, text in enumerate(copy["goals"])
    )
    player = "ТАКОЖ ШУКАЄМО ГРАВЦІВ" if uk else "THESE PLAYERS, TOO"
    steps = (
        ("Кілька матчів.", "Чесний відгук.")
        if uk
        else ("A few matches.", "Honest feedback.")
    )
    improve = (
        "Твій відгук.<br>Кращі поради." if uk else "Your feedback.<br>Better advice."
    )
    want = "Хочеш долучитися?" if uk else "Want to help?"
    comment = "Напиши в коментарях" if uk else "Comment to join"
    # The in-game image and review crop keep their original pixels. The review
    # crop excludes the sidebar logo, so branding appears only once in a frame.
    sections = f"""
<section class="scene s0">
  <div class="hook-halo"></div>
  <div class="eyebrow" data-safe>DOTA 2</div>
  <h1 class="hook-title" data-safe>{"Свен?" if uk else "Play Sven?"}</h1>
  <div class="hook-rating" data-safe>0–4 000 <span>MMR</span></div>
  <div class="hook-heroes">{hero("sven", "hook-main")}</div>
</section>
<section class="scene s1">
  <div class="eyebrow" data-safe>{esc(copy["free"])}</div>
  <div class="product-title live-title" data-safe>{"Підказки<br><em>у грі.</em>" if uk else "Tips.<br><em>In the game.</em>"}</div>
  <div class="product-title review-title" data-safe>{"Розбір.<br><em>Після матчу.</em>" if uk else "Reviews.<br><em>After the match.</em>"}</div>
  <div class="screen live-screen"><img class="game-context" src="{images["game"]}"><div class="live-closeup"><img src="{images["game"]}"></div></div>
  <div class="screen review-screen"><img src="{images["review"]}"></div>
  <div class="screen-note" data-safe>{esc(copy["interface"])} · {esc(copy["heroes"][1])}</div>
</section>
<section class="scene s2">
  <div class="eyebrow" data-safe>{player}</div>
  <div class="product-title" data-safe>{"Джагернаут.<br><em>Терорблейд.</em>" if uk else "Juggernaut.<br><em>Terrorblade.</em>"}</div>
  <div class="hero-deck">{cards}</div>
  <div class="hero-foot" data-safe>{esc(copy["free"])}</div>
</section>
<section class="scene s3">
  <div class="eyebrow" data-safe>{"ДОБРОВІЛЬНЕ ТЕСТУВАННЯ" if uk else "VOLUNTEER BETA TEST"}</div>
  <div class="steps" data-safe><span>{steps[0]}</span><b>{ARROW}</b><em>{steps[1]}</em></div>
  <div class="review-detail"><img src="{images["review"]}"></div>
  <div class="screen-note" data-safe>{esc(copy["interface"])}</div>
</section>
<section class="scene s4">
  <div class="eyebrow" data-safe>{"СКАЖИ ЧЕСНО" if uk else "TELL US HONESTLY"}</div>
  <div class="questions">{feedback}</div>
</section>
<section class="scene s5">
  <div class="eyebrow" data-safe>{"РОБИМО WARDLY КРАЩИМ РАЗОМ" if uk else "MAKE WARDLY BETTER TOGETHER"}</div>
  <h1 class="improve" data-safe>{improve}</h1>
  <div class="goals">{goals}</div>
</section>
<section class="scene s6">
  <div class="end-orbit"></div>
  <div class="invite" data-safe>{want}</div>
  <div class="comment-card"><div class="comment-symbol" aria-hidden="true"></div><b data-safe>{copy["cta"]}</b></div>
  <div class="comment-label" data-safe>{comment}</div>
  <div class="address" data-safe>{copy["site"]}</div>
  <div class="free" data-safe><span class="windows" aria-hidden="true"><i></i><i></i><i></i><i></i></span>{copy["free"]}</div>
</section>"""
    return document(language, timeline, captions, motion, sections, copy)


def document(
    language,
    timeline,
    captions,
    motion,
    sections,
    copy,
    *,
    extra_css="",
    javascript=None,
    header=True,
):
    assets = SITE / "assets"
    fonts = {
        name: uri(assets / "fonts" / f"{name}-wght-normal.woff2")
        for name in (
            "montserrat-cyrillic",
            "montserrat-latin",
            "inter-cyrillic",
            "inter-latin",
        )
    }
    css = (Path(__file__).with_name("beta_style.css")).read_text(
        encoding="utf-8"
    ) + extra_css
    js = javascript or (Path(__file__).with_name("beta_motion.js")).read_text(
        encoding="utf-8"
    )
    logo = uri(assets / "logo.png")
    top = (
        f'<header><img src="{logo}" data-brand><b data-safe>Wardly</b>'
        f"<span data-safe>{copy['label']}</span></header>"
        if header
        else ""
    )
    return f'''<!doctype html><html lang="{language}"><meta charset="utf-8">
<style>
@font-face{{font-family:Montserrat;src:url("{fonts["montserrat-cyrillic"]}");font-weight:100 900;unicode-range:U+0400-045F,U+0490-0491}}
@font-face{{font-family:Montserrat;src:url("{fonts["montserrat-latin"]}");font-weight:100 900}}
@font-face{{font-family:Inter;src:url("{fonts["inter-cyrillic"]}");font-weight:100 900;unicode-range:U+0400-045F,U+0490-0491}}
@font-face{{font-family:Inter;src:url("{fonts["inter-latin"]}");font-weight:100 900}}
{css}
</style><body>
<div class="ambient"></div><div class="edge-light"></div>
{sections}
{top}
<div class="captions" data-safe></div>
<script>
const timeline={json.dumps(timeline, ensure_ascii=False)}, captions={json.dumps(captions, ensure_ascii=False)};
const motion={json.dumps(motion)}, language={json.dumps(language)};
{js}
</script></body></html>'''
