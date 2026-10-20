"""The beta tester page (site/beta.html, site/en/beta.html): who we look for and
the path download → set up → play 3 matches → leave feedback.

Every step names the app's own buttons and settings (renderer/app-texts.js,
renderer/match-texts.js), so the page and the app say the same thing. The
heroes are the carries with a plan of their own (data/heroes/item_plans).
"""

from __future__ import annotations

import html
import json
from typing import Any

import news

PLANS = news.ROOT / "data" / "heroes" / "item_plans"
DOWNLOAD = "https://github.com/makquella/wardly/releases/latest"
CHANNEL = "https://t.me/wardlydota"
MATCHES = 3

TEXT = {
    "uk": {
        "title": "Бета-тест Wardly: керрі до 4к MMR",
        "description": "Шукаємо керрі-гравців до 4000 MMR: встановіть безкоштовний Windows-тренер, зіграйте три матчі й розкажіть, які поради допомогли.",
        "kicker": "Бета-тест · керрі до 4к MMR",
        "lead": "Граєте керрі приблизно до 4000 MMR? Wardly тепер має свій план для {n} керрі: предмети проти драфту, збірку й прокачку з лігових матчів. Допоможіть перевірити, чи це справді допомагає у ваших іграх.",
        "download": "Завантажити для Windows",
        "steps_title": "Чотири кроки",
        "steps": [
            (
                "Завантажте",
                [
                    "Безкоштовно, для Windows 10 і 11.",
                    "Якщо з'явилося синє вікно Windows, натисніть «Докладніше» → «Однаково запустити»: інсталятор поки без платного цифрового підпису, код відкритий.",
                ],
            ),
            (
                "Налаштуйте",
                [
                    "У списку «Перший запуск» натисніть «Підключити» біля «Застосунок підключено до Доти». Потім «Скопіювати» і вставте -gamestateintegration у Steam: правою кнопкою на Dota 2 → Властивості → Параметри запуску.",
                    "Увімкніть «Допомогти покращити підказки» в «Налаштування → Застосунок» (або «Ділитися статистикою», коли застосунок спитає): раз на день — анонімні лічильники, які підказки показувалися й як ви їх оцінили. Без героїв, матчів, ніка, Steam ID і ключів; вимкнути можна будь-коли.",
                ],
            ),
            (
                "Зіграйте {m} матчі на керрі",
                [
                    "Будь-який із героїв нижче, звичайні рейтингові чи нерейтингові матчі.",
                    "Підказки з'являються поверх гри, коли вони потрібні, а після матчу є розбір.",
                ],
            ),
            (
                "Залиште відгук",
                [
                    "У розборі матчу, в «Підказки під час матчу», позначте поради: «Корисно», «Не до речі» або «Повторювалося».",
                    "Напишіть у Telegram-каналі, що допомогло, що запізнилося чи відволікало, де порада була хибною — з героєм і приблизною хвилиною.",
                    "Щось не працює — «Повідомити про проблему» в застосунку: розробник отримає журнал, ключі й паролі з нього вирізаються.",
                ],
            ),
        ],
        "heroes_title": "Керрі з власним планом",
        "heroes_hint": "Інші герої теж працюють, але для цих {n} предмети, збірка й прокачка підібрані окремо.",
        "channel": "Telegram-канал @wardlydota",
        "honest": "Без обіцянок приросту MMR: нам потрібна чесна оцінка, а не реклама.",
        "share_text": "Знаєте керрі-гравця? Надішліть цю сторінку: три матчі й кілька слів відгуку дуже допоможуть.",
    },
    "en": {
        "title": "Wardly beta: carry players under 4K MMR",
        "description": "Looking for carry players under 4,000 MMR: install the free Windows coach, play three matches and tell us which advice helped.",
        "kicker": "Beta test · carry under 4K MMR",
        "lead": "Play carry at around 4,000 MMR or below? Wardly now has a plan of its own for {n} carries: items against the enemy draft, builds and skills from league matches. Help us check whether it actually helps in your games.",
        "download": "Download for Windows",
        "steps_title": "Four steps",
        "steps": [
            (
                "Download",
                [
                    "Free, for Windows 10 and 11.",
                    "If a blue Windows window appears, press “More info” → “Run anyway”: the installer has no paid code signature yet, and the code is open.",
                ],
            ),
            (
                "Set up",
                [
                    "In the “Getting started” list, press “Connect” next to “Connected to Dota”. Then “Copy” and paste -gamestateintegration in Steam: right-click Dota 2 → Properties → Launch options.",
                    "Turn on “Help improve the advice” in Settings → App (or press “Share statistics” when the app asks): once a day, anonymous counts of which advice was shown and how you rated it. No heroes, matches, nickname, Steam ID or keys; you can turn it off any time.",
                ],
            ),
            (
                "Play {m} matches as a carry",
                [
                    "Any hero below, normal ranked or unranked matches.",
                    "Advice appears over the game when it matters, and after the match there is a review.",
                ],
            ),
            (
                "Leave feedback",
                [
                    "In the match review, under “Advice during the match”, mark the advice: “Useful”, “Not to the point” or “Repeated”.",
                    "Tell us in the Telegram channel what helped, what came too late or distracted you, and which advice was wrong, with the hero and the rough minute.",
                    "Something broken? “Report a problem” in the app sends the developer the log, with keys and passwords cut out.",
                ],
            ),
        ],
        "heroes_title": "Carries with a plan of their own",
        "heroes_hint": "Other heroes work too, but for these {n} the items, build and skills are picked one by one.",
        "channel": "Telegram channel @wardlydota",
        "honest": "No promises of MMR gains: we need an honest verdict, not an endorsement.",
        "share_text": "Know a carry player? Send them this page: three matches and a few words of feedback help a lot.",
    },
}


def carries() -> list[str]:
    """The heroes with a carry plan, by name."""
    names = []
    for path in sorted(PLANS.glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if "carry" in plan.get("positions", []):
            names.append(plan["hero"])
    return sorted(names)


def main(lang: str, heroes: dict[str, dict[str, Any]], up: str, images: set[str]) -> str:
    """The page body; `heroes` maps a site hero name to {key, slug}."""
    t = TEXT[lang]
    e = html.escape
    names = carries()
    n = len(names)
    steps = "\n".join(
        f"""            <li class="beta-step">
              <span class="beta-num" aria-hidden="true">{i}</span>
              <div>
                <h3>{e(head.format(m=MATCHES))}</h3>
{"".join(f"                <p>{e(line)}</p>{chr(10)}" for line in lines)}              </div>
            </li>"""
        for i, (head, lines) in enumerate(t["steps"], 1)
    )
    strip = []
    for name in names:
        hero = heroes.get(name)
        picture = news._picture(
            {"name": name, "key": hero["key"] if hero else ""}, up, images, "sm"
        )
        label = f"{picture}<span>{e(name)}</span>"
        strip.append(
            f'              <li><a href="heroes/{hero["slug"]}.html">{label}</a></li>'
            if hero
            else f"              <li>{label}</li>"
        )
    page_url = f"{news.BASE}{'' if lang == 'uk' else '/en'}/beta.html"
    return f"""    <main id="main">
      <section class="page-head">
        <div class="wrap">
          <p class="mode-tag">{e(t["kicker"])}</p>
          <h1>{e(t["title"])}</h1>
          <p class="lead">{e(t["lead"].format(n=n))}</p>
          <div class="cta-row">
            <a class="btn btn-primary btn-lg js-download" href="{DOWNLOAD}">
              <svg class="i" aria-hidden="true"><use href="#i-windows" /></svg>
              <span>{e(t["download"])}</span>
            </a>
            <a class="btn btn-outline btn-lg" href="{CHANNEL}" rel="noopener">{e(t["channel"])}</a>
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <h2>{e(t["steps_title"])}</h2>
          <ol class="beta-steps">
{steps}
          </ol>
          <p class="note">{e(t["honest"])}</p>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <h2>{e(t["heroes_title"])}</h2>
          <p class="mode-note news-hint">{e(t["heroes_hint"].format(n=n))}</p>
          <ul class="release-heroes">
{chr(10).join(strip)}
          </ul>
        </div>
      </section>

{news._actions(lang, page_url, t["title"], t["share_text"])}
    </main>"""
