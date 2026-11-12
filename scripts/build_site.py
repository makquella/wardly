"""Build the generated parts of the site from the coach's own data.

- the hero lists on site/heroes.html (from data/heroes/hero_profiles.json);
- one page per full-advisor hero: site/heroes/<slug>.html (uk) and
  site/en/heroes/<slug>.html (en) — last-hit pace, when to back off, the saves
  the coach names, the key fight ability and the profile's note: the numbers
  the live coach itself uses (hero_profiles, advice_context, live_tools);
- the static English pages site/en/index.html and site/en/heroes.html, made
  from the Ukrainian HTML and the English texts in site/i18n-en.js;
- site/sitemap.xml.

    python scripts/build_site.py          # write the files
    python scripts/build_site.py --check  # fail when a file is out of date (CI)

Run from anywhere; needs the backend's requirements (it imports backend/app).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BASE = "https://luhovyimvp.dev"
sys.path.insert(0, str(ROOT / "backend"))

from app.advice_context import LH_RANGE_POINTS  # noqa: E402 - after the backend path
from app.hero_profiles import POSITION_PACE  # noqa: E402
from app.live_tools import USABLE_SAFETY  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import beta_page  # noqa: E402 - scripts/beta_page.py, after the scripts path
import news  # noqa: E402
import news_hero  # noqa: E402
import news_release  # noqa: E402

# One version for styles.css, app.js and i18n-en.js on every page, hand-written
# (index.html, heroes.html) and generated alike. Separate counters let one page
# reuse a URL that browsers had already cached with older files.
ASSET_VERSION = "28"
POSITIONS = ("carry", "mid", "offlane", "support")
POSITION_NAMES = {
    "uk": {"carry": "Керрі", "mid": "Мід", "offlane": "Хардлайн", "support": "Саппорт"},
    "en": {"carry": "Carry", "mid": "Mid", "offlane": "Offlane", "support": "Support"},
}
ARCHETYPES = {
    "hard_scaling_farmer": (
        "керрі, що фармить і розкривається в пізній грі",
        "a farming carry who comes online late",
    ),
    "tempo_fighting_carry": (
        "керрі, який рано починає битися",
        "a carry who starts fighting early",
    ),
    "ranged_carry": (
        "керрі далекого бою, якому важлива позиція",
        "a ranged carry who lives by positioning",
    ),
    "durable_tempo_core": ("живучий кор, який задає темп", "a durable core who sets the tempo"),
    "mobile_tempo_mid": ("рухливий мідер, який грає від темпу", "a mobile mid who plays for tempo"),
    "ranged_tempo_mid": (
        "мідер далекого бою, який грає від темпу",
        "a ranged mid who plays for tempo",
    ),
    "frontline_initiator": ("хардлайнер, який починає бійки", "an offlaner who starts the fights"),
    "fragile_hard_support": (
        "крихкий саппорт п'ятої позиції, якому найважливіша позиція",
        "a fragile hard support who lives by positioning",
    ),
    "disable_support": (
        "саппорт із контролем, який вирішує, кого спіймати",
        "a support with disables who decides who gets caught",
    ),
    "save_support": ("саппорт, який рятує своїх", "a support who saves the team"),
    "fight_support": (
        "саппорт, який виграє бійки одним закляттям",
        "a support whose one spell wins fights",
    ),
    "durable_support": (
        "живучий саппорт, який може стояти попереду",
        "a durable support who can stand in front",
    ),
    "roaming_support": ("саппорт четвертої позиції, який ходить мапою", "a roaming soft support"),
    "roaming_initiator": (
        "саппорт четвертої позиції, який починає бійки",
        "a soft support who starts the fights",
    ),
    "fragile_nuker": (
        "крихкий саппорт, який завдає багато шкоди здалеку",
        "a fragile support who deals damage from range",
    ),
}
# The profile's note in Ukrainian (the profile keeps it in English); a few English
# notes written for the coach are reworded for players here.
NOTES_UK = {
    "Anti-Mage": "Не лізь уперед, поки Blink на перезарядці.",
    "Juggernaut": "Не нав'язуй розміни, поки Blade Fury на перезарядці.",
    "Lifestealer": "Не стрибай під контроль, поки Rage на перезарядці.",
    "Medusa": "Мана — це твоя живучість, а не лише ресурс на закляття.",
    "Slark": "Не затягуй розміни, коли нічим піти чи скинути із себе ефекти.",
    "Morphling": "Не ризикуй у розмінах, поки Waveform на перезарядці або нічим перелити силу (Attribute Shift).",
    "Phantom Assassin": "Не стрибай уперед, коли піти майже нічим.",
    "Drow Ranger": "Тримай дистанцію, коли нічим захиститися.",
    "Luna": "Не заходь далеко без підтримки команди.",
    "Sven": "Не нав'язуй розміни, поки Warcry на перезарядці й нічим піти.",
    "Kez": "Витрачай ривки обережно й не пірнай за невигідними вбивствами.",
    "Ursa": "Не лізь під контроль, поки Enrage не готовий.",
    "Monkey King": "Не вступай у бійку, якщо з неї нічим вистрибнути.",
    "Spectre": "Фарми безпечно й не витрачай час на невигідні ранні бійки.",
    "Terrorblade": "Не починай бійки без Metamorphosis і без команди.",
    "Phantom Lancer": "Не вступай у бійку, поки Doppelganger на перезарядці.",
    "Naga Siren": "Не фарми небезпечні місця, коли нічим піти.",
    "Sniper": "Стій далі, коли нічим захиститися.",
    "Muerta": "Не стій попереду без прикриття команди.",
    "Gyrocopter": "Рівний фарм важливіший за бійки: не пірнай без підтримки.",
    "Ember Spirit": "Не лізь у невигідні бійки: тримай Sleight of Fist і Flame Guard, щоб піти.",
    "Shadow Fiend": "Власного порятунку немає: думай про Blink чи Black King Bar і бийся за спинами команди.",
    "Storm Spirit": "Ball Lightning рятує, лише поки на нього вистачає мани.",
    "Queen of Pain": "Не стрибай у бійку, поки Blink на перезарядці.",
    "Puck": "Phase Shift рятує від одного удару: бережи його від оглушення, а не від дрібної шкоди.",
    "Templar Assassin": "Без зарядів Refraction вона крихка: відійди й дочекайся їх.",
    "Void Spirit": "Тримай Dissimilate або Astral Step, щоб піти.",
    "Outworld Destroyer": "Власного порятунку немає: тримай дистанцію й Force Staff або Blink.",
    "Dragon Knight": "Живучий, але повільний: не женися далеко від команди без Elder Dragon Form.",
    "Axe": "Починай бійку, коли команда поруч; не стрибай наодинці з малим HP.",
    "Mars": "Бережи Arena of Blood для бійки, у яку команда встигне.",
    "Legion Commander": "Бери Duel, лише коли виграєш його: спершу перевір HP і Blink.",
    "Bristleback": "Повертайся спиною до шкоди й не стій обличчям у програній бійці.",
    "Centaur Warrunner": "Stampede рятує й команду: залиш його на відхід, якщо бійка пішла не так.",
    "Tidehunter": "Ravage виграє бійки: не помирай, поки команда не підійшла.",
    "Slardar": "Guardian Sprint — і зайти, і піти: з малим HP не витрачай його на захід.",
    "Timbersaw": "Timber Chain потрібні дерева: бийся поруч із ними й тримай його на відхід.",
    "Pangolier": "Тримай Swashbuckle або Rolling Thunder на відхід.",
    "Primal Beast": "Onslaught — це захід: не мчи наодинці з малим HP.",
    "Crystal Maiden": "Стій за корами: Freezing Field потрібна безпечна точка, а пізніше — Black King Bar або Glimmer Cape.",
    "Lion": "Тримай Hex на ривок ворога чи його головного героя; з Blink Dagger кожна бійка починається з тебе.",
    "Shadow Shaman": "Shackles тримає тебе на місці: кастуй його, лише коли ворог не може відповісти.",
    "Witch Doctor": "Death Ward не дає рухатися: став його з-за дерев або з готовим Glimmer Cape.",
    "Lich": "Frost Shield — на кора, якого б'ють; Chain Frost найкращий, коли вороги стоять поруч.",
    "Dazzle": "Shallow Grave врятує кора, лише якщо ти поруч: але не будь першим, кого бачить ворог.",
    "Oracle": "Тримай False Promise для кора в біді — або для себе, коли ціль ти.",
    "Warlock": "Chaotic Offering виграє бійки: тримай його на момент, коли ворог уже зайшов.",
    "Jakiro": "Ice Path і Macropyre виграють лінію й вежі: тисни, коли кори поруч.",
    "Vengeful Spirit": "Nether Swap рятує спійманого кора, але ставить на його місце тебе: обмінюйся, лише якщо переживеш.",
    "Disruptor": "Glimpse — на героя, що стрибнув; Kinetic Field і Static Storm замикають бійку.",
    "Ogre Magi": "Огр може стояти попереду, але Bloodlust на корі вартий більше за твої розміни.",
    "Treant Protector": "Living Armor рятує вежі й корів з будь-якої точки мапи; Overgrowth починає бійку.",
    "Rubick": "Не показуйся, поки ворог не витратив своє головне закляття, — і забери його.",
    "Earthshaker": "Echo Slam потрібні Blink Dagger і вороги поруч одне з одним: дочекайся, поки вони зберуться.",
    "Tusk": "Ice Shards відрізає шлях відходу; Snowball бере союзника із собою на вбивство.",
    "Earth Spirit": "Rolling Boulder — ще й твій відхід: тримай його, коли йдеш далеко вперед.",
    "Mirana": "Тримай Leap на відхід; Moonlight Shadow перевертає бійку або рятує всю команду.",
    "Skywrath Mage": "Тебе вб'є будь-хто, хто дотягнеться: кастуй ззаду й тримай Force Staff або Glimmer Cape.",
    "Snapfire": "Firesnap Cookie на себе вистрибує з небезпеки; Mortimer Kisses відрізає місце бійки.",
    "Hoodwink": "Scurry поруч із деревами тримає тебе живим; для Bushwhack потрібне дерево за ворогом.",
    "Spirit Breaker": "Бий Charge по тому, до кого команда встигне; Bulldoze виведе, якщо пішло не так.",
    "Nyx Assassin": "Vendetta ще й ховає: тримай її або Spiked Carapace на випадок, якщо спіймали.",
    "Bounty Hunter": "Track на головного героя ворога — це золото й огляд; Shadow Walk — твій відхід.",
    "Clockwerk": "Hookshot починає бійку: лети, коли команда достатньо близько, щоб устигнути.",
}
NOTES_EN = {
    "Ember Spirit": "Avoid low-value fights: keep Sleight of Fist and Flame Guard for the way out.",
}
FALLBACK_SAVES = "Force Staff, Blink Dagger, Black King Bar, Ghost Scepter, Magic Wand"


# --- data -------------------------------------------------------------------------


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_profiles() -> list[dict]:
    data = json.loads((ROOT / "data" / "heroes" / "hero_profiles.json").read_text(encoding="utf-8"))
    return data["profiles"]


def portrait_keys() -> dict[str, str]:
    text = (ROOT / "frontend" / "launcher" / "renderer" / "dota-data.js").read_text(
        encoding="utf-8"
    )
    data = json.loads(text[text.index("=") + 1 : text.rindex(";")])
    return {name: key for name, key in data["heroes"].values()}


def english_texts() -> dict[str, str]:
    text = (SITE / "i18n-en.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


def saves(profile: dict) -> list[str]:
    names = profile["key_escape_abilities"] + profile["key_defensive_abilities"]
    return [name for name in names if name.lower() in USABLE_SAFETY]


def pace_rows(profile: dict, position: str) -> list[tuple[int, int, int]]:
    """Last hits by minute: the profile's lane targets, then the carry pace scaled by position."""
    rows = [
        (int(m), low, high)
        for m, (low, high) in sorted(
            profile["laning_expected_lh"].items(), key=lambda kv: int(kv[0])
        )
    ]
    factor = POSITION_PACE.get(position, 1.0)
    rows += [
        (m, round(low * factor), round(high * factor))
        for m, low, high in LH_RANGE_POINTS
        if m > rows[-1][0]
    ]
    return rows


def heroes() -> list[dict]:
    keys = portrait_keys()
    out = []
    for profile in load_profiles():
        name = profile["hero"]
        position = profile.get("position", "carry")
        if name not in keys:
            raise SystemExit(f"no portrait key for {name} in dota-data.js")
        if name not in NOTES_UK:
            raise SystemExit(f"no Ukrainian note for {name} in scripts/build_site.py")
        out.append(
            {
                "name": name,
                "slug": slug(name),
                "key": keys[name],
                "position": position,
                "profile": profile,
                "saves": saves(profile),
                "pace": pace_rows(profile, position),
            }
        )
    return sorted(out, key=lambda h: (POSITIONS.index(h["position"]), h["name"]))


# --- the hero lists on heroes.html -------------------------------------------------


def hero_card(hero: dict) -> str:
    small = f"<small>{html.escape(', '.join(hero['saves']))}</small>" if hero["saves"] else ""
    return (
        f'              <li><a href="heroes/{hero["slug"]}.html"><img src="assets/heroes/{hero["key"]}.webp" alt="" '
        f'width="256" height="144" loading="lazy" /><span><b>{html.escape(hero["name"])}</b>{small}</span></a></li>'
    )


def with_hero_lists(page: str, all_heroes: list[dict]) -> str:
    for position in POSITIONS:
        group = [h for h in all_heroes if h["position"] == position]
        cards = "\n".join(hero_card(h) for h in group)
        page, count = re.subn(
            rf'(<ul class="heroes" aria-labelledby="heroes-{position}">\n).*?(\n\s*</ul>)',
            lambda m, cards=cards: m.group(1) + cards + m.group(2),
            page,
            count=1,
            flags=re.DOTALL,
        )
        if not count:
            raise SystemExit(f"heroes.html: no list for {position}")
        page = re.sub(
            rf'(id="heroes-{position}">.*?</span> · )\d+(</h3>)',
            rf"\g<1>{len(group)}\2",
            page,
            count=1,
            flags=re.DOTALL,
        )
    return page


# --- Ukrainian HTML → static English page --------------------------------------------

VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


def _english_url(url: str, depth: int) -> str:
    """A relative URL of a Ukrainian page as seen from its English copy `depth` levels down."""
    if not url or re.match(r"^(#|/|[a-z]+:|//)", url):
        return url
    # Pages with an English copy stay inside /en/; everything else is shared.
    if url in ("./",) or url.startswith(("./#", "heroes.html", "heroes/")):
        return url
    return "../" * depth + url


class _Translator(HTMLParser):
    def __init__(self, en: dict[str, str], page: dict) -> None:
        super().__init__(convert_charrefs=False)
        self.en = en
        self.page = page
        self.out: list[str] = []
        self.skip: list = []  # [tag, depth] while an element's Ukrainian content is replaced
        self.in_title = False
        self.in_ld = False
        self.missing: list[str] = []

    def text(self, key: str) -> str:
        if key not in self.en:
            self.missing.append(key)
            return ""
        return self.en[key]

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool) -> str:
        parts = [tag]
        for name, value in attrs:
            parts.append(name if value is None else f'{name}="{html.escape(value, quote=True)}"')
        return "<" + " ".join(parts) + (" />" if close else ">")

    def _rewrite(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> tuple[list, str | None, bool]:
        """(attributes, replacement content, is html) for one start tag."""
        a = dict(attrs)
        depth = self.page["depth"]
        content = None
        is_html = False
        new: list[tuple[str, str | None]] = []
        for name, value in attrs:
            if name in ("src", "href") and value is not None:
                value = _english_url(value, depth)
            elif name == "style" and value:
                value = re.sub(r"url\((?!['\"]?(?:[a-z]+:|/|#))", "url(" + "../" * depth, value)
            new.append((name, value))
        if tag == "html":
            new = [(n, v) for n, v in new if n not in ("lang", "data-static", "data-alt-en")]
            new = [
                ("lang", "en"),
                ("data-static", "en"),
                ("data-alt-uk", self.page["alt_uk"]),
            ] + new
        if tag == "meta":
            if a.get("name") == "description" or a.get("property") in ("og:description",):
                key = (
                    self.page["description"]
                    if a.get("name") == "description"
                    else self.page["og_description"]
                )
                new = [(n, self.text(key) if n == "content" else v) for n, v in new]
            elif a.get("property") == "og:title":
                new = [(n, self.text(self.page["title"]) if n == "content" else v) for n, v in new]
            elif a.get("property") == "og:url":
                new = [(n, self.page["url"] if n == "content" else v) for n, v in new]
        if tag == "link" and a.get("rel") == "canonical":
            new = [(n, self.page["url"] if n == "href" else v) for n, v in new]
        if "data-i18n-aria" in a:
            new = [(n, self.text(a["data-i18n-aria"]) if n == "aria-label" else v) for n, v in new]
        if "data-i18n-alt" in a:
            new = [(n, self.text(a["data-i18n-alt"]) if n == "alt" else v) for n, v in new]
        pictures = {
            "data-img": "assets/app/en/{}.jpg?v={v}",
            "data-ov": "assets/overlay/en/{}.webp?v={v}",
            "data-game": "assets/game/{}-en.jpg?v={v}",
            "data-shot": "assets/shots/en/{}.jpg?v={v}",
        }
        for attr, pattern in pictures.items():
            if attr in a:
                src = "../" * depth + pattern.format(a[attr], v=self.page["shots"])
                new = [(n, src if n == "src" else v) for n, v in new]
        if "data-i18n" in a:
            content = html.escape(self.text(a["data-i18n"]), quote=False)
        elif "data-i18n-html" in a:
            content, is_html = self.text(a["data-i18n-html"]), True
        return new, content, is_html

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] += 1
            return
        new, content, _ = self._rewrite(tag, attrs)
        self.out.append(self._tag(tag, new, False))
        if tag == "title":
            self.in_title = True
            self.out.append(html.escape(self.text(self.page["title"]), quote=False))
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.in_ld = True
        if content is not None and tag not in VOID:
            self.out.append(content)
            self.skip = [tag, 1]

    def handle_startendtag(self, tag, attrs):
        if self.skip:
            return
        new, _, _ = self._rewrite(tag, attrs)
        self.out.append(self._tag(tag, new, True))

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[0]:
                self.skip[1] -= 1
                if self.skip[1] == 0:
                    self.skip = []
                    self.out.append(f"</{tag}>")
            return
        if tag == "title":
            self.in_title = False
        if tag == "script":
            self.in_ld = False
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip or self.in_title:
            return
        if self.in_ld and data.strip():
            ld = json.loads(data)
            ld["description"] = self.text(self.page["description"])
            ld["url"] = self.page["url"]
            ld["inLanguage"] = "en"
            ld["alternateName"] = "Wardly — a Dota 2 coach"
            data = (
                "\n    "
                + json.dumps(ld, ensure_ascii=False, indent=2).replace("\n", "\n    ")
                + "\n    "
            )
        self.out.append(data)

    def handle_entityref(self, name):
        if not (self.skip or self.in_title):
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not (self.skip or self.in_title):
            self.out.append(f"&#{name};")

    def handle_comment(self, data):
        if not self.skip:
            self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.out.append(f"<!{decl}>")


def english_page(source: str, en: dict[str, str], page: dict) -> str:
    translator = _Translator(en, page)
    translator.feed(source)
    translator.close()
    if translator.missing:
        raise SystemExit(f"site/i18n-en.js lacks: {', '.join(sorted(set(translator.missing)))}")
    return "".join(translator.out)


# --- hero pages --------------------------------------------------------------------

T = {
    "uk": {
        "skip": "Перейти до вмісту",
        "nav": [
            ("#ingame", "У грі"),
            ("#how", "Як це працює"),
            ("#review", "Розбір"),
            ("#profile", "Профіль"),
        ],
        "heroes": "Герої",
        "news": "Новини",
        "menu": "Меню",
        "faq": "Запитання",
        "download": "Завантажити",
        "download_long": "Завантажити для Windows",
        "lang": "Мова",
        "title": "{name} у Dota 2: скільки добивати й коли відходити — Wardly",
        "description": "{name} ({position}): темп добивань за хвилинами, коли відходити й чим рятуватися — цифри, за якими безкоштовний тренер Wardly підказує просто в матчі.",
        "lead": "{name} — {archetype}. Нижче цифри, за якими Wardly підказує на цьому герої просто в матчі: скільки добивати, коли відходити й чим рятуватися.",
        "pace_title": "Темп добивань",
        "pace_minute": "Хвилина",
        "pace_lh": "Добивання",
        "pace_note": "Відстаєш від нижньої цифри — тренер скаже про це просто в матчі й покаже, який темп добрий на цій хвилині.",
        "pace_note_support": "Саппортові не потрібно багато добивати: цифри — орієнтир, а не мета. Якщо почнеш забирати кріпів у керрі, тренер нагадає.",
        "survive_title": "Коли відходити",
        "hp": "Коли HP нижче {low} %, тренер підкаже відійти, нижче {critical} % — терміново, одразу, без паузи.",
        "saves": "Порятунок: {saves} — тренер назве його, коли він готовий, і нагадає, якщо ти загинув, не натиснувши його.",
        "no_saves": "Власного порятунку немає: тренер назве готовий предмет — {items}.",
        "mana": "Мана тут — це порятунок: тренер попередить, коли її менше {mana} %.",
        "fight_title": "У бійці",
        "fight": "Головне в бійці: {abilities}.",
        "note": "Порада тренера: {note}",
        "more_title": "Що ще підкаже Wardly",
        "more": {
            "carry": [
                "План на гру з піку: мета за добиваннями до 10:00 і ключовий предмет.",
                "Наступний предмет збірки й скільки золота до нього.",
                "Немає ТП понад хвилину — нагадає. Після 30-ї хвилини залишить золото на байбек.",
            ],
            "mid": [
                "Перевірки добивань на 5:00 і 8:00 і нагадування про Bottle.",
                "Руни за 20 секунд, а з 6-го рівня — коли йти на іншу лінію.",
                "Наступний предмет збірки й скільки золота до нього.",
            ],
            "offlane": [
                "Програна лінія — підкаже стягнути великий табір.",
                "Темп фарму хардлайнера, а не керрі: цілі нижчі на 30 %.",
                "Ключовий предмет вчасно чи пізно — і коли твоє вікно для бійки.",
            ],
            "support": [
                "Стаки на :53 і пули малого табору на легкій лінії — за 10 секунд до часу.",
                "Немає вардів або вард надто довго лежить у сумці — нагадає поставити.",
                "Немає рятівного предмета до 12-ї хвилини — підкаже Glimmer Cape або Force Staff.",
            ],
        },
        "after": "Після матчу — розбір: оцінка, мапа смертей, збірка проти статистики OpenDota.",
        "cta_title": "Спробуй у наступній грі",
        "cta_text": "Безкоштовно, для Windows 10 і 11. Офіційна інтеграція Valve — без ризику для акаунта.",
        "others": "Інші герої · {position}",
        "all": "Усі герої",
        "footer_label": "Посилання",
        "releases": "Версії",
        "issues": "Повідомити про проблему",
        "changelog": "Що нового",
        "privacy": "Конфіденційність",
        "terms": "Умови використання",
        "legal": "Dota 2 — товарний знак Valve Corporation. Проєкт не пов'язаний із Valve і не схвалений нею. Портрети героїв — Valve.",
    },
    "en": {
        "skip": "Skip to content",
        "nav": [
            ("#ingame", "In game"),
            ("#how", "How it works"),
            ("#review", "Review"),
            ("#profile", "Profile"),
        ],
        "heroes": "Heroes",
        "news": "News",
        "menu": "Menu",
        "faq": "FAQ",
        "download": "Download",
        "download_long": "Download for Windows",
        "lang": "Language",
        "title": "{name} in Dota 2: last hits by minute and when to back off — Wardly",
        "description": "{name} ({position}): last hits by minute, when to back off and what saves you — the numbers the free Wardly coach uses to advise you during the match.",
        "lead": "{name} is {archetype}. These are the numbers Wardly uses on this hero during the match: how many last hits, when to back off and what saves you.",
        "pace_title": "Last-hit pace",
        "pace_minute": "Minute",
        "pace_lh": "Last hits",
        "pace_note": "Below the lower number, the coach tells you during the match and shows a good pace for that minute.",
        "pace_note_support": "A support does not need many last hits: the numbers are a guide, not a goal. If you start taking the carry's creeps, the coach reminds you.",
        "survive_title": "When to back off",
        "hp": "Under {low}% HP the coach tells you to leave; under {critical}% it is urgent and comes at once.",
        "saves": "Your save: {saves}. The coach names it when it is ready and reminds you if you died without pressing it.",
        "no_saves": "No save of your own: the coach names a ready item — {items}.",
        "mana": "Mana is your escape here: the coach warns you under {mana}%.",
        "fight_title": "In a fight",
        "fight": "Your key fight ability: {abilities}.",
        "note": "Coach's tip: {note}",
        "more_title": "What else Wardly tells you",
        "more": {
            "carry": [
                "A plan from the pick: a last-hit target for 10:00 and the key item.",
                "The next item of the build and the gold still needed for it.",
                "No TP for a minute — a reminder. After minute 30 it keeps your buyback gold.",
            ],
            "mid": [
                "Last-hit checks at 5:00 and 8:00 and a Bottle reminder.",
                "Runes 20 seconds ahead, and from level 6 when to go to a side lane.",
                "The next item of the build and the gold still needed for it.",
            ],
            "offlane": [
                "A lost lane — a hint to pull the big camp.",
                "An offlaner's farm pace, not a carry's: targets 30% lower.",
                "Your key item on time or late — and when your window to fight is.",
            ],
            "support": [
                "Stacks at :53 and small-camp pulls in the safe lane, 10 seconds ahead.",
                "No wards, or a ward kept in the bag too long — a reminder to place it.",
                "No save item by minute 12 — a hint for Glimmer Cape or Force Staff.",
            ],
        },
        "after": "After the match — a review: a score, a map of your deaths, the build against OpenDota statistics.",
        "cta_title": "Try it in your next game",
        "cta_text": "Free, for Windows 10 and 11. Valve's official integration — no risk for your account.",
        "others": "Other heroes · {position}",
        "all": "All heroes",
        "footer_label": "Links",
        "releases": "Releases",
        "issues": "Report a problem",
        "changelog": "What's new",
        "privacy": "Privacy",
        "terms": "Terms of service",
        "legal": "Dota 2 is a trademark of Valve Corporation. This project is not affiliated with or endorsed by Valve. Hero portraits are Valve's.",
    },
}

ICONS = """    <svg width="0" height="0" style="position: absolute" aria-hidden="true">
      <defs>
        <symbol id="i-windows" viewBox="0 0 24 24"><path d="M3 5.5 10.5 4.4v7.1H3zM11.5 4.3 21 3v8.5h-9.5zM3 12.5h7.5v7.1L3 18.5zM11.5 12.5H21V21l-9.5-1.3z" fill="currentColor" stroke="none" /></symbol>
        <symbol id="i-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></symbol>
      </defs>
    </svg>"""


DOWNLOAD = "https://github.com/makquella/wardly/releases/latest"


def site_header(lang: str, up: str, home: str) -> str:
    """The top bar of a generated page; `up` leads to the site root, `home` to
    this language's home page."""
    t = T[lang]
    e = html.escape
    nav = "\n".join(
        f'          <a href="{home}{anchor}">{e(label)}</a>' for anchor, label in t["nav"]
    )
    return f"""    <header class="nav" id="top">
      <div class="wrap nav-inner">
        <a class="brand" href="{home}" aria-label="Wardly">
          <img class="brand-mark" src="{up}assets/logo-mark.png" alt="" width="28" height="28" />
          <span class="brand-name">Wardly</span>
        </a>
        <nav class="nav-links" id="site-menu" aria-label="{e(t["footer_label"])}">
{nav}
          <a href="{home}heroes.html">{e(t["heroes"])}</a>
          <a href="{home}news.html">{e(t["news"])}</a>
          <a href="{home}#faq">{e(t["faq"])}</a>
        </nav>
        <div class="nav-actions">
          <div class="lang" role="group" aria-label="{e(t["lang"])}">
            <button type="button" data-lang="uk" aria-pressed="{str(lang == "uk").lower()}">UK</button>
            <button type="button" data-lang="en" aria-pressed="{str(lang == "en").lower()}">EN</button>
          </div>
          <a class="btn btn-primary btn-sm js-download" href="{DOWNLOAD}">
            <svg class="i" aria-hidden="true"><use href="#i-windows" /></svg>
            <span>{e(t["download"])}</span>
          </a>
          <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-menu" aria-label="{e(t["menu"])}">
            <span></span><span></span><span></span>
          </button>
        </div>
      </div>
    </header>"""


def site_footer(lang: str, up: str, home: str) -> str:
    t = T[lang]
    e = html.escape
    return f"""    <footer class="footer">
      <div class="wrap footer-inner">
        <a class="brand" href="{home}" aria-label="Wardly">
          <img class="brand-mark" src="{up}assets/logo-mark.png" alt="" width="24" height="24" />
          <span class="brand-name">Wardly</span>
        </a>
        <nav class="footer-links" aria-label="{e(t["footer_label"])}">
          <a href="https://github.com/makquella/wardly" rel="noopener">GitHub</a>
          <a href="https://t.me/wardlydota" rel="noopener">Telegram</a>
          <a href="https://github.com/makquella/wardly/releases" rel="noopener">{e(t["releases"])}</a>
          <a href="https://github.com/makquella/wardly/issues" rel="noopener">{e(t["issues"])}</a>
          <a href="{home}heroes.html">{e(t["heroes"])}</a>
          <a href="{home}news.html">{e(t["news"])}</a>
          <a href="{up}changelog.html">{e(t["changelog"])}</a>
          <a href="{up}privacy.html">{e(t["privacy"])}</a>
          <a href="{up}terms.html">{e(t["terms"])}</a>
          <a href="{up}code-signing.html">Code signing policy</a>
        </nav>
        <p class="footer-legal">{e(t["legal"])}</p>
      </div>
    </footer>"""


def hero_page(hero: dict, all_heroes: list[dict], lang: str) -> str:
    t = T[lang]
    e = html.escape
    name, position, profile = hero["name"], hero["position"], hero["profile"]
    up = "../" if lang == "uk" else "../../"  # to the site root
    home = "../"  # to this language's home page
    uk_url = f"{BASE}/heroes/{hero['slug']}.html"
    en_url = f"{BASE}/en/heroes/{hero['slug']}.html"
    url = uk_url if lang == "uk" else en_url
    alt = (
        f'data-alt-en="../en/heroes/{hero["slug"]}.html"'
        if lang == "uk"
        else f'data-alt-uk="../../heroes/{hero["slug"]}.html"'
    )
    position_name = POSITION_NAMES[lang][position]
    archetype = ARCHETYPES[profile["archetype"]][0 if lang == "uk" else 1]
    title = t["title"].format(name=name)
    description = t["description"].format(name=name, position=position_name.lower())
    note = NOTES_UK[name] if lang == "uk" else NOTES_EN.get(name, profile["notes"])
    if lang == "uk" and re.match(r"[А-ЯІЇЄҐ][а-яіїєґ]", note):
        note = note[0].lower() + note[1:]  # after «Порада тренера:», unless it starts with a name

    rows = "\n".join(
        f"                  <tr><td>{minute}:00</td><td>{low}–{high}</td></tr>"
        for minute, low, high in hero["pace"]
    )
    survive = [
        t["hp"].format(
            low=profile["low_hp_warning_threshold"], critical=profile["critical_hp_threshold"]
        )
    ]
    survive.append(
        t["saves"].format(saves=", ".join(hero["saves"]))
        if hero["saves"]
        else t["no_saves"].format(items=FALLBACK_SAVES)
    )
    if profile.get("survival_resource") == "mana":
        survive.append(t["mana"].format(mana=profile["mana_warning_threshold"]))

    def checks(items: list[str]) -> str:
        return "\n".join(
            f'                  <li><svg class="i" aria-hidden="true"><use href="#i-check" /></svg><span>{e(item)}</span></li>'
            for item in items
        )

    fight = [
        t["fight"].format(abilities=", ".join(profile["key_fight_abilities"])),
        t["note"].format(note=note),
    ]
    more = t["more"][position] + [t["after"]]
    others = "\n".join(
        f'            <a class="chip" href="{h["slug"]}.html"><img src="{up}assets/heroes/{h["key"]}.webp" alt="" width="256" height="144" loading="lazy" />{e(h["name"])}</a>'
        for h in all_heroes
        if h["position"] == position and h is not hero
    )
    download = DOWNLOAD
    return f"""<!doctype html>
<html lang="{lang}" data-static="{lang}" {alt}>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{e(title)}</title>
    <meta name="description" content="{e(description)}" />
    <meta name="theme-color" content="#0c0d0f" />
    <meta property="og:type" content="article" />
    <meta property="og:title" content="{e(title)}" />
    <meta property="og:description" content="{e(description)}" />
    <link rel="canonical" href="{url}" />
    <link rel="alternate" hreflang="uk" href="{uk_url}" />
    <link rel="alternate" hreflang="en" href="{en_url}" />
    <link rel="alternate" hreflang="x-default" href="{uk_url}" />
    <meta property="og:url" content="{url}" />
    <meta property="og:image" content="{BASE}/assets/og.jpg?v=7" />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="icon" href="{up}assets/favicon.png" type="image/png" />
    <link rel="stylesheet" href="{up}styles.css?v={ASSET_VERSION}" />
  </head>
  <body>
    <a class="skip" href="#main">{e(t["skip"])}</a>

{site_header(lang, up, home)}

    <main id="main">
      <section class="page-head">
        <div class="wrap hero-head">
          <img class="hero-portrait" src="{up}assets/heroes/{hero["key"]}.webp" alt="{e(name)}" width="256" height="144" />
          <div>
            <p class="mode-tag"><a href="{home}heroes.html">{e(position_name)}</a></p>
            <h1>{e(name)}</h1>
            <p class="lead">{e(t["lead"].format(name=name, archetype=archetype))}</p>
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <div class="modes">
            <article class="mode">
              <h2>{e(t["pace_title"])}</h2>
              <table class="pace">
                <thead><tr><th>{e(t["pace_minute"])}</th><th>{e(t["pace_lh"])}</th></tr></thead>
                <tbody>
{rows}
                </tbody>
              </table>
              <p class="mode-note">{e(t["pace_note_support" if position == "support" else "pace_note"])}</p>
            </article>
            <article class="mode">
              <h2>{e(t["survive_title"])}</h2>
              <ul class="checks">
{checks(survive)}
              </ul>
            </article>
            <article class="mode">
              <h2>{e(t["fight_title"])}</h2>
              <ul class="checks">
{checks(fight)}
              </ul>
            </article>
          </div>
        </div>
      </section>

      <section class="section section-alt">
        <div class="wrap hero-more">
          <div>
            <h2>{e(t["more_title"])}</h2>
            <ul class="checks">
{checks(more)}
            </ul>
          </div>
          <div class="hero-cta">
            <h2>{e(t["cta_title"])}</h2>
            <p>{e(t["cta_text"])}</p>
            <a class="btn btn-primary btn-lg js-download" href="{download}">
              <svg class="i" aria-hidden="true"><use href="#i-windows" /></svg>
              <span>{e(t["download_long"])}</span>
            </a>
          </div>
        </div>
      </section>

      <section class="section section-tight">
        <div class="wrap">
          <h2 class="heroes-group first">{e(t["others"].format(position=position_name))}</h2>
          <nav class="chips" aria-label="{e(t["others"].format(position=position_name))}">
{others}
          </nav>
          <p class="note"><a href="{home}heroes.html">{e(t["all"])} →</a></p>
        </div>
      </section>
    </main>

{site_footer(lang, up, home)}

{ICONS}

    <script src="{up}i18n-en.js?v={ASSET_VERSION}" defer></script>
    <script src="{up}app.js?v={ASSET_VERSION}" defer></script>
  </body>
</html>
"""


# --- news pages -----------------------------------------------------------------------


def _page(
    lang: str, *, up: str, home: str, path: str, title: str, description: str, main: str
) -> str:
    """A generated page around `main`; `path` is the page's path under each
    language's root (`news.html`, `news/<slug>.html`)."""
    e = html.escape
    uk_url, en_url = f"{BASE}/{path}", f"{BASE}/en/{path}"
    url = uk_url if lang == "uk" else en_url
    depth = path.count("/")
    alt = (
        f'data-alt-en="{"../" * depth}en/{path}"'
        if lang == "uk"
        else f'data-alt-uk="{"../" * (depth + 1)}{path}"'
    )
    return f"""<!doctype html>
<html lang="{lang}" data-static="{lang}" {alt}>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{e(title)}</title>
    <meta name="description" content="{e(description)}" />
    <meta name="theme-color" content="#0c0d0f" />
    <meta property="og:type" content="article" />
    <meta property="og:title" content="{e(title)}" />
    <meta property="og:description" content="{e(description)}" />
    <link rel="canonical" href="{url}" />
    <link rel="alternate" hreflang="uk" href="{uk_url}" />
    <link rel="alternate" hreflang="en" href="{en_url}" />
    <link rel="alternate" hreflang="x-default" href="{uk_url}" />
    <meta property="og:url" content="{url}" />
    <meta property="og:image" content="{BASE}/assets/og.jpg?v=7" />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="icon" href="{up}assets/favicon.png" type="image/png" />
    <link rel="stylesheet" href="{up}styles.css?v={ASSET_VERSION}" />
  </head>
  <body>
    <a class="skip" href="#main">{e(T[lang]["skip"])}</a>

{site_header(lang, up, home)}

{main}

{site_footer(lang, up, home)}

{ICONS}

    <script src="{up}i18n-en.js?v={ASSET_VERSION}" defer></script>
    <script src="{up}app.js?v={ASSET_VERSION}" defer></script>
  </body>
</html>
"""


def news_pages(all_heroes: list[dict]) -> dict[Path, str]:
    """site/news.html, site/news/<slug>.html and their /en/ copies (scripts/news.py):
    the meta posts, the patches, the heroes of the week (news_hero.py) and the
    Wardly releases (news_release.py)."""
    posts = news.load_posts()
    patches = news.load_patches()
    weeks = news_hero.entries(all_heroes, posts)
    releases = news_release.load_releases()
    by_name = {hero["name"]: hero for hero in all_heroes}
    site = sys.modules[__name__]
    links = {hero["name"]: hero["slug"] for hero in all_heroes}
    images = {path.stem for path in news.HERO_IMAGES.glob("*.webp")}
    files: dict[Path, str] = {}
    for lang in ("uk", "en"):
        root = SITE if lang == "uk" else SITE / "en"
        up_list = "" if lang == "uk" else "../"
        t = news.TEXT[lang]
        heroes_week = []
        for entry in weeks:
            fact = news_hero.facts(entry["hero"], site, lang)
            name = f"news/{news_hero.slug(entry)}.html"
            files[root / name] = _page(
                lang,
                up=up_list + "../",
                home="../",
                path=name,
                title=f"{news_hero.title(entry, lang)} — Wardly",
                description=news_hero.lead(entry, fact, lang),
                main=news_hero.post_main(entry, fact, lang, "../", up_list + "../", images),
            )
            heroes_week.append(
                (entry["date"], news_hero.list_item(entry, fact, lang, up_list, images))
            )
        for release in releases:
            name = f"news/{news_release.slug(release)}.html"
            files[root / name] = _page(
                lang,
                up=up_list + "../",
                home="../",
                path=name,
                title=f"{release[lang]['title']} — Wardly",
                description=release[lang]["lead"],
                main=news_release.post_main(release, lang, by_name, "../", up_list + "../", images),
            )
            heroes_week.append((release["date"], news_release.list_item(release, lang)))
        files[root / "news.html"] = _page(
            lang,
            up=up_list,
            home="./",
            path="news.html",
            title=f"{t['list_title']} — Wardly",
            description=t["list_lead"],
            main=news.list_main(posts, lang, "./", up_list, images, patches, heroes_week),
        )
        for post in posts:
            data = news.summary(post, news.previous_of(post, posts))
            files[root / "news" / f"{news.slug(post)}.html"] = _page(
                lang,
                up=up_list + "../",
                home="../",
                path=f"news/{news.slug(post)}.html",
                title=f"{news.title(post, lang)} — Wardly",
                description=news.lead(post, data, lang),
                main=news.post_main(post, data, lang, links, "../", up_list + "../", images),
            )
        for patch in patches:
            files[root / "news" / f"{news.patch_slug(patch)}.html"] = _page(
                lang,
                up=up_list + "../",
                home="../",
                path=f"news/{news.patch_slug(patch)}.html",
                title=f"{news.patch_title(patch, lang)} — Wardly",
                description=t["patch_lead"],
                main=news.patch_main(patch, lang, links, "../", up_list + "../", images),
            )
    return files


def beta_pages(all_heroes: list[dict]) -> dict[Path, str]:
    """site/beta.html and site/en/beta.html: the beta test path (beta_page.py)."""
    by_name = {hero["name"]: hero for hero in all_heroes}
    images = {path.stem for path in news.HERO_IMAGES.glob("*.webp")}
    files: dict[Path, str] = {}
    for lang in ("uk", "en"):
        root = SITE if lang == "uk" else SITE / "en"
        up = "" if lang == "uk" else "../"
        text = beta_page.TEXT[lang]
        files[root / "beta.html"] = _page(
            lang,
            up=up,
            home="./",
            path="beta.html",
            title=f"{text['title']} — Wardly",
            description=text["description"],
            main=beta_page.main(lang, by_name, up, images),
        )
    return files


# --- sitemap -----------------------------------------------------------------------


def sitemap(all_heroes: list[dict]) -> str:
    pairs = [("/", "/en/"), ("/heroes.html", "/en/heroes.html"), ("/news.html", "/en/news.html")]
    pairs.append(("/beta.html", "/en/beta.html"))
    pairs += [(f"/heroes/{h['slug']}.html", f"/en/heroes/{h['slug']}.html") for h in all_heroes]
    posts = news.load_posts()
    for page in (
        [f"/news/{news.slug(post)}.html" for post in posts]
        + [f"/news/{news.patch_slug(patch)}.html" for patch in news.load_patches()]
        + [f"/news/{news_hero.slug(entry)}.html" for entry in news_hero.entries(all_heroes, posts)]
        + [f"/news/{news_release.slug(post)}.html" for post in news_release.load_releases()]
    ):
        pairs.append((page, f"/en{page}"))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for uk, en in pairs:
        for loc in (uk, en):
            lines.append(
                f"  <url><loc>{BASE}{loc}</loc>"
                f'<xhtml:link rel="alternate" hreflang="uk" href="{BASE}{uk}" />'
                f'<xhtml:link rel="alternate" hreflang="en" href="{BASE}{en}" /></url>'
            )
    for page in ("/changelog.html", "/privacy.html", "/terms.html", "/code-signing.html"):
        lines.append(f"  <url><loc>{BASE}{page}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


# --- all files ----------------------------------------------------------------------


def shots_version() -> str:
    match = re.search(
        r'const SHOTS_VERSION = "(\d+)"', (SITE / "app.js").read_text(encoding="utf-8")
    )
    return match.group(1) if match else "1"


def build() -> dict[Path, str]:
    all_heroes = heroes()
    en = english_texts()
    files: dict[Path, str] = {}
    heroes_uk = with_hero_lists((SITE / "heroes.html").read_text(encoding="utf-8"), all_heroes)
    files[SITE / "heroes.html"] = heroes_uk
    shots = shots_version()
    files[SITE / "en" / "index.html"] = english_page(
        (SITE / "index.html").read_text(encoding="utf-8"),
        en,
        {
            "depth": 1,
            "alt_uk": "../",
            "url": f"{BASE}/en/",
            "title": "title",
            "description": "metaDescription",
            "og_description": "ogDescription",
            "shots": shots,
        },
    )
    files[SITE / "en" / "heroes.html"] = english_page(
        heroes_uk,
        en,
        {
            "depth": 1,
            "alt_uk": "../heroes.html",
            "url": f"{BASE}/en/heroes.html",
            "title": "heroesPageTitle",
            "description": "heroesMetaDescription",
            "og_description": "heroesOgDescription",
            "shots": shots,
        },
    )
    for hero in all_heroes:
        files[SITE / "heroes" / f"{hero['slug']}.html"] = hero_page(hero, all_heroes, "uk")
        files[SITE / "en" / "heroes" / f"{hero['slug']}.html"] = hero_page(hero, all_heroes, "en")
    files.update(news_pages(all_heroes))
    files.update(beta_pages(all_heroes))
    files[SITE / "sitemap.xml"] = sitemap(all_heroes)
    return files


def check_asset_versions() -> None:
    """Fail when a hand-written page loads shared assets with another version."""
    assets = ("styles.css", "app.js", "i18n-en.js")
    for name in ("index.html", "heroes.html"):
        text = (SITE / name).read_text(encoding="utf-8")
        urls = re.findall(r'(?:href|src)="([^"]*)"', text)
        for asset in assets:
            found = [url for url in urls if url.split("?")[0] == asset]
            if not found:
                raise SystemExit(f"site/{name}: does not load {asset}")
            for url in found:
                if url != f"{asset}?v={ASSET_VERSION}":
                    raise SystemExit(
                        f"site/{name}: {url}, expected {asset}?v={ASSET_VERSION} (ASSET_VERSION)"
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="fail when a generated file is out of date"
    )
    args = parser.parse_args()
    check_asset_versions()
    files = build()
    generated_dirs = [SITE / "heroes", SITE / "en" / "heroes", SITE / "news", SITE / "en" / "news"]
    stray = [p for d in generated_dirs if d.exists() for p in d.glob("*.html") if p not in files]
    if args.check:
        stale = [
            p
            for p, text in files.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        if stale or stray:
            for path in stale:
                print(f"out of date: {path.relative_to(ROOT)}")
            for path in stray:
                print(f"not generated (remove it): {path.relative_to(ROOT)}")
            print("Run: python scripts/build_site.py")
            return 1
        print(f"site up to date ({len(files)} generated files)")
        return 0
    for path in stray:
        path.unlink()
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
