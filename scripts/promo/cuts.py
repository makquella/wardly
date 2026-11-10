"""Wardly Cuts: short vertical videos made of motion, type and the project's own numbers.

No generated pictures and no screen recording: every frame is a page drawn by
cuts.js (kinetic type, Valve's hero renders, a still of the game, the app's
own overlay card), the sound is synthesised here (cuts_sound.py), the voice is
ElevenLabs with one voice per video, so the videos also compare voices.

Four videos, Ukrainian and English:

  lanes-top5   the five most one-sided lanes of league games, counted down
  lane-bully   the hero who makes the lane hard for the most cores
  hero-lanes   one hero: its hard and its easy lane, and the app's own card
  stun-bkb     stunned with Black King Bar ready: the card the app shows

Every number comes from data/heroes/lane_matchups through the app's own rule
(lane_matchup.classify, as scripts/promo/lane_post.py); every card is worded by
the app (map_hints.TIPS, the real advice pipeline through coach_demo). `facts()`
raises when a claim stops being true, so a video never says what the app or
the data does not.

The end card shows an address to type (luhovyimvp.dev/tt, /yt, /ig): links in a
Short's or a TikTok's description cannot be clicked, and each address counts
its own visits (scripts/build_site.py SHORT_ADDRESSES). The body is rendered
once and each network gets its own ending.

    python -m scripts.promo.cuts --out promo-out/cuts                 # all, with voice
    python -m scripts.promo.cuts --out promo-out/cuts --only stun-bkb --lang uk
    python -m scripts.promo.cuts --out promo-out/cuts --draft --stills  # no voice: frames only
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import render as frames
from . import voice as tts

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
HERE = Path(__file__).resolve().parent
SITE = ROOT / "site"
FPS = 60
WIDTH, HEIGHT = 1080, 1920
REVISION = 1
CONCEPTS = ("lanes-top5", "lane-bully", "hero-lanes", "stun-bkb")
LANGUAGES = ("uk", "en")
# The end card's address per network (scripts/build_site.py SHORT_ADDRESSES).
NETWORKS = {"tt": "tiktok", "yt": "youtube", "ig": "instagram"}
MAX_SECONDS = 34
# The visual cut comes a little before the first word of a beat.
LEAD = 0.1
# A pause between two beats is cut down to this (the voice leaves longer ones),
# and a pause inside a beat to that.
MAX_GAP = 0.16
MAX_INNER = 0.18
# The take: silences longer than this are cut to it (cuts.tighten), measured this
# far below the take's loudest moment; then the take is played this much faster.
SILENCE_KEEP = 0.11
SILENCE_DB = -34
TEMPO = 1.08
# The end card stays this long after the last word, for the address to be read.
TAIL = 1.4
CDN = "https://cdn.cloudflare.steamstatic.com/apps/dota2"
RENDER_PNG = CDN + "/videos/dota_react/heroes/renders/{key}.png"
RENDER_VIDEO = CDN + "/videos/dota_react/heroes/renders/{key}.webm"
ITEM_ICON = CDN + "/images/dota_react/items/{key}.png"
SEQUENCE_FPS = 24
# The picture: constant quality, the frame of the cover, browsers drawing at once.
CRF = 21
COVER_FRAME = FPS
WORKERS = min(4, os.cpu_count() or 1)
SEQUENCE_SIZE = 900

# One voice per video (ElevenLabs voice ids from the account's library), so the
# eight videos are also a comparison of eight voices.
VOICES = {
    "ihor": ("HzwYrDmvbdseqvhVjJVs", "Ihor Sydoreko"),
    "taras": ("11JUpgNlQsWfppULB2T8", "Taras Vovk - Tactical Game NPC"),
    "illia": ("YCBNvFrJ61cZtOtAFMzZ", "Illia - energetic, positive, persuasive"),
    "alex": ("9Sj8ugvpK1DmcAXyvi3a", "Alex Nekrasov - Confident and Clear"),
    "liam": ("TX3LPaxmHKxFdv7VOQHJ", "Liam - Energetic, Social Media Creator"),
    "callum": ("N2lVS1w4EtoT3dr4eOWO", "Callum - Husky Trickster"),
    "charlie": ("IKne3meq5aSn9XLyUdCD", "Charlie - Deep, Confident, Energetic"),
    "adam": ("pNInz6obpgDQGcFmaJgB", "Adam - Dominant, Firm"),
}
CAST = {
    ("lanes-top5", "uk"): "ihor",
    ("lane-bully", "uk"): "taras",
    ("hero-lanes", "uk"): "illia",
    ("stun-bkb", "uk"): "alex",
    ("lanes-top5", "en"): "liam",
    ("lane-bully", "en"): "callum",
    ("hero-lanes", "en"): "charlie",
    ("stun-bkb", "en"): "adam",
}
VOICE_MODEL = "eleven_v4"
VOICE_SETTINGS = {"stability": 0.45, "speed": 1.15}
VOICE_API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
# The hero of hero-lanes and the one stunned in stun-bkb.
LANE_HERO = "Phantom Assassin"
STUN_HERO = ("Juggernaut", "juggernaut", "carry")
STUN_ITEM = "black_king_bar"


@dataclass
class Beat:
    """One scene: what is said (| breaks the caption lines) and what is shown."""

    say: str
    scene: str
    data: dict[str, Any] = field(default_factory=dict)
    captions: bool = True
    # A named moment of the scene: the index of the said word it lands on.
    cues: dict[str, int] = field(default_factory=dict)
    # Silence before the beat's first word, on top of the voice's own.
    pause: float = 0.0
    # A beat without words lasts this long.
    hold: float = 0.0


# --- numbers as words ------------------------------------------------------------

_UK_ONES = [
    "нуль",
    "один",
    "два",
    "три",
    "чотири",
    "п'ять",
    "шість",
    "сім",
    "вісім",
    "дев'ять",
    "десять",
    "одинадцять",
    "дванадцять",
    "тринадцять",
    "чотирнадцять",
    "п'ятнадцять",
    "шістнадцять",
    "сімнадцять",
    "вісімнадцять",
    "дев'ятнадцять",
]
_UK_TENS = [
    "_",
    "_",
    "двадцять",
    "тридцять",
    "сорок",
    "п'ятдесят",
    "шістдесят",
    "сімдесят",
    "вісімдесят",
    "дев'яносто",
]
_EN_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(number: int, language: str) -> str:
    """0..99 in words, nominative."""
    if not 0 <= number <= 99:
        raise ValueError(number)
    ones, tens = (_UK_ONES, _UK_TENS) if language == "uk" else (_EN_ONES, _EN_TENS)
    if number < 20:
        return ones[number]
    joiner = " " if language == "uk" else "-"
    return tens[number // 10] + (joiner + ones[number % 10] if number % 10 else "")


def plural(number: int, forms: tuple[str, str, str]) -> str:
    """Ukrainian noun after a number: 1 відсоток, 2 відсотки, 5 відсотків."""
    last, teens = number % 10, number % 100
    if last == 1 and teens != 11:
        return forms[0]
    if 2 <= last <= 4 and not 12 <= teens <= 14:
        return forms[1]
    return forms[2]


def percent_words(number: int, language: str) -> str:
    if language == "uk":
        return f"{words(number, 'uk')} {plural(number, ('відсоток', 'відсотки', 'відсотків'))}"
    return f"{words(number, 'en')} percent"


def thousands_words(number: int, language: str) -> str:
    """54 883 -> «п'ятдесят п'ять тисяч» / «fifty-five thousand» (rounded)."""
    rounded = round(number / 1000)
    if language == "uk":
        return f"{words(rounded, 'uk')} {plural(rounded, ('тисяча', 'тисячі', 'тисяч'))}"
    return f"{words(rounded, 'en')} thousand"


# --- the facts ---------------------------------------------------------------------


def _backend() -> None:
    for path in (BACKEND, BACKEND / "scripts"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _key(hero_id: int) -> str:
    _backend()
    from app.dota_constants import hero_npc_name

    return hero_npc_name(hero_id).replace("npc_dota_hero_", "")


def lane_facts() -> dict[str, Any]:
    """The lane numbers of all three lane videos, by the app's own rule."""
    _backend()
    from app import lane_matchup
    from app.dota_constants import hero_id_from_name

    from . import lane_post

    files = lane_matchup.load_matchups()
    rows = lane_post.collect(files)
    if len(rows) < 30:
        raise SystemExit("lane matchups: too few heroes for the videos")
    keys = {data["hero"]: _key(data["hero_id"]) for data in files.values()}

    def key(name: str, hero_id: int | None = None) -> str:
        found = hero_id if hero_id is not None else hero_id_from_name(name)
        if found is None:
            raise SystemExit(f"unknown hero: {name}")
        return keys.get(name) or _key(found)

    one_sided = sorted(
        ((row, o) for row in rows for o in row["hard"]),
        key=lambda pair: (-(pair[1]["lost"] / pair[1]["lanes"]), pair[0]["hero"]),
    )[:5]
    top = [
        {
            "hero": row["hero"],
            "hero_key": key(row["hero"]),
            "enemy": o["hero"],
            "enemy_key": key(o["hero"], o["hero_id"]),
            "pct": _pct(o["lost"], o["lanes"]),
            "lost": o["lost"],
            "lanes": o["lanes"],
            "base": row["base_lost"],
        }
        for row, o in one_sided
    ]
    bullies = Counter()
    victims: dict[str, list[str]] = {}
    enemy_ids: dict[str, int] = {}
    for row in rows:
        for o in row["hard"]:
            bullies[o["hero"]] += 1
            victims.setdefault(o["hero"], []).append(row["hero"])
            enemy_ids[o["hero"]] = o["hero_id"]
    podium = [
        {"hero": name, "key": key(name, enemy_ids[name]), "count": count}
        for name, count in sorted(bullies.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]
    if podium[0]["count"] == podium[1]["count"]:
        raise SystemExit("lane-bully: no single hero leads")
    # Two heroes the viewer would guess: named hard for several cores, not the leader.
    guesses = [
        {"hero": name, "key": key(name, enemy_ids[name]), "count": count}
        for name, count in sorted(bullies.items(), key=lambda item: (-item[1], item[0]))[3:8]
        if name in ("Viper", "Huskar", "Jakiro", "Axe", "Pudge")
    ][:2]
    if len(guesses) < 2:
        raise SystemExit("lane-bully: no two known guesses below the podium")
    hero = next(row for row in rows if row["hero"] == LANE_HERO)
    if len(hero["hard"]) < 2 or not hero["easy"]:
        raise SystemExit(f"hero-lanes: {LANE_HERO} needs two hard lanes and an easy one")
    baseline = next(d for d in files.values() if d["hero"] == LANE_HERO)["baseline"]
    return {
        "lanes": sum(d["lanes"] for d in files.values()),
        "cores": len(rows),
        "days": next(iter(files.values()))["window_days"],
        "generated": max(d["generated"] for d in files.values()),
        "tiles": [key(row["hero"]) for row in rows],
        "top": top,
        "podium": podium,
        "guesses": guesses,
        "victims": [key(name) for name in victims[podium[0]["hero"]]],
        "hero": {
            "name": hero["hero"],
            "key": key(hero["hero"]),
            "position": hero["position"],
            "base": hero["base_lost"],
            "base_won": _pct(baseline["won"], sum(baseline.values())),
            "hard": [
                {**o, "key": key(o["hero"], o["hero_id"]), "pct": _pct(o["lost"], o["lanes"])}
                for o in hero["hard"][:2]
            ],
            "easy": {
                **hero["easy"][0],
                "key": key(hero["easy"][0]["hero"], hero["easy"][0]["hero_id"]),
                "pct": _pct(hero["easy"][0]["won"], hero["easy"][0]["lanes"]),
            },
        },
    }


def lane_card(facts: dict[str, Any], language: str) -> dict[str, str]:
    """The live «Hard lane» card for the hero's hardest lane, in the app's words."""
    _backend()
    from app.map_hints import TIPS

    hard = facts["hero"]["hard"][0]
    title, body = TIPS["lane_public_hard"][language]
    return {
        "label": "Порада" if language == "uk" else "Tip",
        "action": title.format(hero=hard["hero"]),
        "reason": body.format(
            hero=hard["hero"], my_hero=facts["hero"]["name"], lost=hard["lost"], games=hard["lanes"]
        ),
    }


def stun_card(language: str) -> dict[str, str]:
    """The card the real pipeline shows a stunned carry with Black King Bar ready."""
    from . import coach_demo

    name, key, role = STUN_HERO
    profiles = json.loads((ROOT / "data" / "heroes" / "hero_profiles.json").read_text("utf-8"))
    profile = next(p for p in profiles["profiles"] if p["hero"] == name)
    shown = coach_demo.cards(key, profile, role, language)
    card = next((c for c in shown if c.get("decision_point") == "DISABLED_STATUS"), None)
    if card is None or "Black King Bar" not in card["action"] or card.get("mode") != "urgent":
        raise SystemExit("stun-bkb: the app no longer shows the Black King Bar card on a stun")
    return {
        "label": "Терміново" if language == "uk" else "Urgent",
        "action": card["action"],
        "reason": card["reason"],
    }


# --- the scripts ---------------------------------------------------------------------

END = {
    "uk": {
        "say": "Wardly —|безкоштовний.",
        "what": "Тренер для Dota 2: підказки в грі й розбір після",
        "free": "Безкоштовно · Windows і Linux",
    },
    "en": {
        "say": "Wardly|is free.",
        "what": "A Dota 2 coach: tips in game, a review after",
        "free": "Free · Windows and Linux",
    },
}


def _line(text: str, hot: str = "", gold: str = "") -> list[dict[str, Any]]:
    """«WORD WORD» -> the parts of a kinetic line; `hot` words are the red ones."""
    marked, golden = set(hot.lower().split("|")), set(gold.lower().split("|"))
    parts = []
    for word in text.split():
        bare = word.strip(".,:;!?—").lower()
        parts.append({"w": word, "hot": bare in marked, "gold": bare in golden})
    return parts


def _statement(say: str, hot: str = "", **data: Any) -> Beat:
    """A beat whose big lines are exactly what is said."""
    lines = [_line(part, hot) for part in say.split("|")]
    return Beat(say, "statement", {"lines": lines, **data}, captions=False)


def _end(language: str, source: str = "") -> Beat:
    text = END[language]
    return Beat(
        text["say"],
        "end",
        {"what": text["what"], "free": text["free"], "fine": source, "bg": "base", "soft": True},
        captions=False,
        cues={"site": -1},
    )


def _source_note(facts: dict[str, Any], language: str) -> str:
    count = f"{facts['lanes']:,}".replace(",", " ")
    if language == "uk":
        return f"OpenDota · лігові ігри за {facts['days']} днів · {count} ліній · золото на 10:00"
    return f"OpenDota · league games, {facts['days']} days · {count} lanes · gold at 10:00"


def _rank_labels(entry: dict[str, Any], language: str) -> dict[str, str]:
    if language == "uk":
        return {
            "vs": "VS",
            "lost": "ліній програно",
            "sample": f"{entry['lost']} з {entry['lanes']} лігових ліній",
            "usual": f"зазвичай {entry['base']}%",
        }
    return {
        "vs": "VS",
        "lost": "of lanes lost",
        "sample": f"{entry['lost']} of {entry['lanes']} league lanes",
        "usual": f"usually {entry['base']}%",
    }


def lanes_top5(facts: dict[str, Any], language: str) -> list[Beat]:
    uk = language == "uk"
    top = facts["top"]
    places_uk = ["І перше.", "Друге.", "Третє.", "Четверте.", "П'яте місце."]
    places_en = ["And number one.", "Two.", "Three.", "Four.", "Number five."]
    beats = [
        _statement(
            "П'ять ліній,|які програні|ще на піку." if uk else "Five lanes|you lose|at the pick.",
            "п'ять|програні|five|lose",
            bg="fight",
            eyebrow="Dota 2 · лігові ігри" if uk else "Dota 2 · league games",
            top=300,
            shadows=[
                key for entry in reversed(top) for key in (entry["hero_key"], entry["enemy_key"])
            ],
        )
    ]
    for place in (5, 4, 3, 2, 1):
        entry = top[place - 1]
        final = place == 1
        versus = "проти" if uk else "into"
        say = f"{(places_uk if uk else places_en)[place - 1]}|{entry['hero']} {versus} {entry['enemy']}"
        lead = len((places_uk if uk else places_en)[place - 1].split())
        hero_words = len(entry["hero"].split())
        if final:
            tail = "програних ліній" if uk else "of lanes lost"
            say += f":|{percent_words(entry['pct'], language)}|{tail}."
        else:
            say += "."
        beats.append(
            Beat(
                say,
                "rank",
                {
                    "rank": place,
                    "final": final,
                    "bg": ("forest", "dark", "hook", "chrono", "fight")[place - 1],
                    "a": {"key": entry["hero_key"], "name": entry["hero"]},
                    "b": {"key": entry["enemy_key"], "name": entry["enemy"]},
                    "pct": entry["pct"],
                    "base": entry["base"],
                    "labels": _rank_labels(entry, language),
                },
                captions=False,
                cues={
                    # The opponent comes in on «into», a beat before its name.
                    "b": lead + hero_words,
                    # The share lands on the last word of its number; without one, on the enemy's name.
                    "pct": lead
                    + hero_words
                    + len(entry["enemy"].split())
                    + len(words(entry["pct"], language).split())
                    if final
                    else -1,
                },
                pause=0.25 if final else 0.0,
                hold=0.6 if final else 0.5,
            )
        )
    count = thousands_words(facts["lanes"], language)
    beats.append(
        Beat(
            f"Wardly порахував|{count}|лігових ліній."
            if uk
            else f"Wardly counted|{count}|league lanes.",
            "source",
            {
                "count": facts["lanes"],
                "bg": "base",
                "soft": True,
                "lines": [
                    _line("лігових ліній" if uk else "league lanes"),
                    _line("порахував Wardly" if uk else "counted by Wardly", "wardly"),
                ],
            },
            cues={"count": 1},
        )
    )
    beats.append(_end(language, _source_note(facts, language)))
    return beats


def lane_bully(facts: dict[str, Any], language: str) -> list[Beat]:
    uk = language == "uk"
    first, second, third = facts["podium"]
    if first["count"] * 3 < facts["cores"]:
        raise SystemExit("lane-bully: the leader no longer covers a third of the cores")
    guesses = facts["guesses"]
    cores = plural(first["count"], ("кор", "кори", "корів"))
    count = words(first["count"], language)
    hook = (
        "Один герой|ламає лінію|кожному третьому|кору."
        if uk
        else "One hero|ruins the lane|for every third|core."
    )
    name_words = first["hero"].split()
    reveal_say = (
        f"{first['hero']}.|{count.capitalize()} {cores}|частіше програють|лінію проти нього."
        if uk
        else f"{first['hero']}.|{count.capitalize()} cores|lose the lane|more often against him."
    )
    return [
        Beat(
            hook,
            "grid",
            {
                "bg": "dark",
                "lines": [_line(part, "один|третьому|one|third") for part in hook.split("|")],
                "tiles": facts["tiles"],
                "marked": facts["victims"],
            },
            captions=False,
            cues={"mark": 3 if uk else 4},
        ),
        Beat(
            f"Не {guesses[0]['hero']}.|Не {guesses[1]['hero']}."
            if uk
            else f"Not {guesses[0]['hero']}.|Not {guesses[1]['hero']}.",
            "guess",
            {
                "bg": "forest",
                "items": [
                    {"key": guesses[0]["key"], "label": guesses[0]["hero"], "word": 0},
                    {
                        "key": guesses[1]["key"],
                        "label": guesses[1]["hero"],
                        "word": 1 + len(guesses[0]["hero"].split()),
                    },
                ],
            },
            captions=False,
        ),
        Beat(
            reveal_say,
            "reveal",
            {
                "bg": "chrono",
                "tint": 0.25,
                "hero": first["key"],
                "name": [[{"w": word, "hot": True, "n": 1} for word in name_words]],
                "count": first["count"],
                "of": f"з {facts['cores']} корів" if uk else f"of {facts['cores']} cores",
                "note": "частіше програють лінію проти нього"
                if uk
                else "lose the lane more often against him",
                "strip": facts["victims"],
            },
            captions=False,
            cues={"count": len(name_words)},
            pause=0.3,
        ),
        Beat(
            f"Другий — {second['hero']}.|Третій — {third['hero']}."
            if uk
            else f"Second: {second['hero']}.|Third: {third['hero']}.",
            "podium",
            {
                "bg": "hook",
                "eyebrow": "Для скількох корів лінія важка"
                if uk
                else "Hard lane for this many cores",
                "items": [
                    {
                        "key": second["key"],
                        "name": second["hero"],
                        "value": second["count"],
                        "word": 2 if uk else 1,
                    },
                    {
                        "key": first["key"],
                        "name": first["hero"],
                        "value": first["count"],
                        "dim": True,
                    },
                    {
                        "key": third["key"],
                        "name": third["hero"],
                        "value": third["count"],
                        "word": (4 if uk else 2) + len(second["hero"].split()),
                    },
                ],
            },
            captions=False,
        ),
        Beat(
            f"Це {thousands_words(facts['lanes'], language)}|лігових ліній.|Порахував Wardly."
            if uk
            else f"That's {thousands_words(facts['lanes'], language)}|league lanes.|Counted by Wardly.",
            "source",
            {
                "count": facts["lanes"],
                "bg": "base",
                "soft": True,
                "lines": [
                    _line("лігових ліній" if uk else "league lanes"),
                    _line("порахував Wardly" if uk else "counted by Wardly", "wardly"),
                ],
            },
            cues={"count": 1},
        ),
        _end(language, _source_note(facts, language)),
    ]


def hero_lanes(facts: dict[str, Any], language: str) -> list[Beat]:
    uk = language == "uk"
    hero = facts["hero"]
    first, second = hero["hard"]
    easy = hero["easy"]
    me = {"key": hero["key"], "name": hero["name"]}
    name_len = len(hero["name"].split())

    def labels(entry: dict[str, Any], won: bool) -> dict[str, str]:
        part = entry["won"] if won else entry["lost"]
        usual = hero["base_won"] if won else hero["base"]
        if uk:
            return {
                "share": "ліній виграно" if won else "ліній програно",
                "sample": f"{part} з {entry['lanes']} лігових ліній",
                "usual": f"зазвичай {usual}%",
            }
        return {
            "share": "of lanes won" if won else "of lanes lost",
            "sample": f"{part} of {entry['lanes']} league lanes",
            "usual": f"usually {usual}%",
        }

    hook = (
        f"{hero['name']}.|Дві лінії,|де тебе|з'їдять."
        if uk
        else f"{hero['name']}.|Two lanes|that eat you|alive."
    )
    hook_lines = [_line(part, "дві|з'їдять|two|alive") for part in hook.split("|")]
    hook_lines[0] = [{"w": hero["name"], "hot": False, "gold": True, "n": name_len}]
    return [
        Beat(
            hook,
            "statement",
            {
                "bg": "forest",
                "lines": hook_lines,
                "hero": hero["key"],
                "heroY": 1210,
                "heroX": 600,
                "heroSize": 940,
                "top": 250,
                "max": 150,
            },
            captions=False,
        ),
        Beat(
            f"{first['hero']}:|{percent_words(first['pct'], language)}|ліній програно."
            if uk
            else f"{first['hero']}:|{percent_words(first['pct'], language)}|of lanes lost.",
            "matchup",
            {
                "bg": "hook",
                "me": me,
                "foe": {"key": first["key"], "name": first["hero"]},
                "pct": first["pct"],
                "base": hero["base"],
                "eyebrow": "Важка лінія" if uk else "Hard lane",
                "labels": labels(first, False),
            },
            captions=False,
            cues={"pct": len(first["hero"].split())},
        ),
        Beat(
            f"{second['hero']}:|{percent_words(second['pct'], language)}."
            if uk
            else f"{second['hero']}:|{percent_words(second['pct'], language)}.",
            "matchup",
            {
                "bg": "dark",
                "me": me,
                "foe": {"key": second["key"], "name": second["hero"]},
                "pct": second["pct"],
                "base": hero["base"],
                "eyebrow": "Важка лінія" if uk else "Hard lane",
                "labels": labels(second, False),
            },
            captions=False,
            cues={"pct": len(second["hero"].split())},
        ),
        Beat(
            f"А зручна|лінія —|{easy['hero']}." if uk else f"And the easy|lane:|{easy['hero']}.",
            "matchup",
            {
                "bg": "base",
                "easy": True,
                "me": me,
                "foe": {"key": easy["key"], "name": easy["hero"]},
                "pct": easy["pct"],
                "base": hero["base_won"],
                "eyebrow": "Зручна лінія" if uk else "Easy lane",
                "labels": labels(easy, True),
            },
            captions=False,
            cues={"pct": 4},
        ),
        Beat(
            "Wardly скаже це|просто в грі,|щойно побачить,|хто на твоїй лінії."
            if uk
            else "Wardly tells you|right in the game,|the moment it sees|who is in your lane.",
            "card",
            {
                "bg": "fight",
                "eyebrow": "Картка поверх гри" if uk else "The card over the game",
                "hero": hero["key"],
                "card": lane_card(facts, language),
                "cardY": 960,
            },
            cues={"card": 3},
        ),
        _end(language, _source_note(facts, language)),
    ]


def stun_bkb(language: str) -> list[Beat]:
    uk = language == "uk"
    card = stun_card(language)
    hero = STUN_HERO[1]
    labels = {
        "stunned": "СТАН" if uk else "STUNNED",
        "ready": "BKB ГОТОВИЙ" if uk else "BKB READY",
        "dead": "ПОМЕР" if uk else "DEAD",
        "rewind": "ВІДМОТАЙМО" if uk else "REWIND",
    }
    stun = {"bg": "chrono", "hero": hero, "item": STUN_ITEM, "labels": labels}
    hook = (
        "Тебе застанили.|BKB готовий.|І ти все одно|помер."
        if uk
        else "You got stunned.|BKB was ready.|And you still|died."
    )
    reason = (
        "Найчастіше добивають|у першу секунду|після контролю."
        if uk
        else "Most kills finish|in the first second|after a disable."
    )
    return [
        Beat(hook, "stun", {**stun, "tint": 0.15}, cues={}),
        Beat(
            "Відмотаймо." if uk else "Rewind.",
            "stun",
            {**stun, "back": True},
            captions=False,
            pause=0.15,
            hold=1.1,
        ),
        Beat(
            reason,
            "statement",
            {
                "bg": "chrono",
                "lines": [_line(part, "першу|секунду|first|second") for part in reason.split("|")],
                "top": 470,
            },
            captions=False,
        ),
        Beat(
            "Тому Wardly|показує це|просто поверх гри,|поки ти ще в стані."
            if uk
            else "So Wardly|shows this|right over the game|while you are still stunned.",
            "card",
            {
                "bg": "chrono",
                "eyebrow": "Картка поверх гри" if uk else "The card over the game",
                "card": card,
                "cardY": 820,
            },
            cues={"card": 2},
        ),
        Beat(
            "Контроль скінчився —|тиснеш BKB|і живеш."
            if uk
            else "The stun ends,|you press BKB,|and you live.",
            "stun",
            {**stun, "hold": 0.7, "saved": True},
            cues={"press": 3 if uk else 4},
        ),
        _end(language),
    ]


def facts_for(concept: str) -> dict[str, Any]:
    return {} if concept == "stun-bkb" else lane_facts()


def beats_for(concept: str, language: str, facts: dict[str, Any]) -> list[Beat]:
    if concept == "lanes-top5":
        return lanes_top5(facts, language)
    if concept == "lane-bully":
        return lane_bully(facts, language)
    if concept == "hero-lanes":
        return hero_lanes(facts, language)
    if concept == "stun-bkb":
        return stun_bkb(language)
    raise ValueError(concept)


# --- the voice and the timeline ---------------------------------------------------------


def said(beat: Beat) -> list[str]:
    return beat.say.replace("|", " ").split()


def narration(beats: list[Beat]) -> str:
    """What the voice gets: the beats as sentences, one per line."""
    return "\n".join(" ".join(said(beat)) for beat in beats)


def draft_words(beats: list[Beat]) -> list[dict[str, Any]]:
    """Word times without a voice: a steady reading pace (storyboards, tests)."""
    timed, at = [], 0.12
    for beat in beats:
        for word in said(beat):
            length = 0.16 + 0.045 * len(word)
            timed.append({"word": word, "start": round(at, 3), "end": round(at + length, 3)})
            at += length + 0.03
        at += 0.3
    return timed


def synthesize(text: str, voice_key: str, language: str, out: Path) -> list[dict[str, Any]]:
    """The voice as a 48 kHz mono WAV at `out`; its words with times."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set (use --draft for a silent storyboard)")
    voice_id, _ = VOICES[voice_key]
    body = {
        "text": text,
        "model_id": VOICE_MODEL,
        "language_code": language,
        "voice_settings": VOICE_SETTINGS,
    }
    answer = tts.api_request(VOICE_API.format(voice=voice_id), body, key)
    audio = base64.b64decode(answer.get("audio_base64") or "")
    if not audio:
        raise SystemExit("ElevenLabs: empty audio")
    source = out.with_suffix(".mp3")
    source.write_bytes(audio)
    subprocess.run(
        [
            frames.ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        check=True,
    )
    return tts.words_from_alignment(answer.get("alignment") or {})


def tighten(take: Path, timed: list[dict[str, Any]], out: Path) -> list[dict[str, Any]]:
    """The take without its long silences, a little faster, at `out`; the word times follow.

    The voice breathes between sentences for a third of a second and more, and
    the alignment hides it inside the word before. Every stretch quieter than
    SILENCE_DB below the take's peak and longer than SILENCE_KEEP is cut to
    SILENCE_KEEP (half of it kept on either side, so no word is clipped); then
    the whole take is played TEMPO times faster without changing its pitch."""
    import wave

    import numpy as np

    with wave.open(str(take), "rb") as source:
        rate = source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
            np.float64
        )
    hop = rate // 200
    count = len(audio) // hop
    level = np.sqrt(np.mean(audio[: count * hop].reshape(count, hop) ** 2, axis=1) + 1e-9)
    quiet = level < level.max() * 10 ** (SILENCE_DB / 20)
    # (start, end) in seconds of what is removed, oldest first.
    removed: list[tuple[float, float]] = []
    index = 0
    while index < count:
        if not quiet[index]:
            index += 1
            continue
        last = index
        while last < count and quiet[last]:
            last += 1
        start, end = index * hop / rate, last * hop / rate
        if end - start > SILENCE_KEEP and index > 0 and last < count:
            removed.append((start + SILENCE_KEEP / 2, end - SILENCE_KEEP / 2))
        index = last
    kept, at = [], 0.0
    fade = int(0.004 * rate)
    for start, end in [*removed, (len(audio) / rate, len(audio) / rate)]:
        piece = audio[int(at * rate) : int(start * rate)].copy()
        if len(piece) > 2 * fade:
            piece[:fade] *= np.linspace(0, 1, fade)
            piece[-fade:] *= np.linspace(1, 0, fade)
        kept.append(piece)
        at = end
    trimmed = out.with_name(out.stem + "-trimmed.wav")
    with wave.open(str(trimmed), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(np.concatenate(kept).astype("<i2").tobytes())
    subprocess.run(
        [frames.ffmpeg(), "-y", "-loglevel", "error", "-i", str(trimmed), "-af", f"atempo={TEMPO}",
         "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out)],
        check=True,
    )  # fmt: skip
    trimmed.unlink()

    def moved(t: float) -> float:
        gone = 0.0
        for start, end in removed:
            if t >= end:
                gone += end - start
            elif t > start:
                gone += t - start
        return round((t - gone) / TEMPO, 3)

    result = []
    for word in timed:
        start = moved(word["start"])
        result.append(
            {"word": word["word"], "start": start, "end": max(start + 0.02, moved(word["end"]))}
        )
    return result


def narrate(
    beats: list[Beat], voice_key: str, language: str, workdir: Path
) -> tuple[Path, list[dict[str, Any]]]:
    """The take, tightened, and its word times. The raw take is kept next to the
    text it was made from, so a rebuild does not ask for it again."""
    text = narration(beats)
    tag = hashlib.sha256(
        json.dumps([text, voice_key, VOICE_MODEL, VOICE_SETTINGS]).encode()
    ).hexdigest()[:12]
    wav, cache = workdir / f"voice-{tag}.wav", workdir / f"voice-{tag}.json"
    if wav.exists() and cache.exists():
        timed = json.loads(cache.read_text("utf-8"))
    else:
        timed = synthesize(text, voice_key, language, wav)
        expected = text.split()
        if [w["word"] for w in timed] != expected:
            raise SystemExit(
                f"the voice's words do not match the script: {len(timed)} for {len(expected)}"
            )
        cache.write_text(json.dumps(timed, ensure_ascii=False), "utf-8")
    tight = workdir / "voice.wav"
    return tight, tighten(wav, timed, tight)


def arrange(beats: list[Beat], timed: list[dict[str, Any]]) -> dict[str, Any]:
    """Scenes with their times, and how the take is cut to fit them.

    The take is cut only in silence: between beats (where the pause is cut to
    MAX_GAP and the beat's own `pause` and the previous one's `hold` are added)
    and inside a beat where the voice waits longer than MAX_INNER. Each kept
    piece carries half of the silence left on either side, so no word is
    clipped. The picture and the voice share one clock."""
    scenes: list[dict[str, Any]] = []
    cuts: list[dict[str, float]] = []
    at = 0
    piece: dict[str, float] = {}
    previous: dict[str, Any] | None = None

    def close(to: float) -> float:
        """End the open piece at `to` of the take; the video's time after it."""
        piece["to"] = round(to, 4)
        cuts.append(dict(piece))
        return piece["at"] + piece["to"] - piece["from"]

    for index, beat in enumerate(beats):
        count = len(said(beat))
        own = timed[at : at + count]
        at += count
        words_ = []
        scene_start = 0.0
        for position, word in enumerate(own):
            if previous is None:
                start = max(0.0, word["start"] - 0.06)
                piece = {"from": round(start, 4), "at": 0.12}
            else:
                gap = word["start"] - previous["end"]
                boundary = position == 0
                keep = min(gap, MAX_GAP if boundary else MAX_INNER)
                if boundary or gap > MAX_INNER:
                    clock = close(previous["end"] + keep / 2)
                    if boundary:
                        scene_start = round(clock + beats[index - 1].hold + beat.pause, 3)
                        clock = scene_start + LEAD
                    piece = {"from": round(word["start"] - keep / 2, 4), "at": round(clock, 4)}
            shift = piece["at"] - piece["from"]
            words_.append(
                {
                    "w": word["word"],
                    "start": round(word["start"] + shift, 3),
                    "end": round(word["end"] + shift, 3),
                }
            )
            previous = word
        scenes.append(
            {
                "type": beat.scene,
                "start": scene_start,
                "end": 0.0,
                "data": beat.data,
                "captions": beat.captions,
                "words": words_,
                "cues": {name: words_[i]["start"] for name, i in beat.cues.items()},
                "lines": _caption_lines(beat, words_),
            }
        )
    assert previous is not None
    close(previous["end"] + 0.25)
    for scene, following_scene in zip(scenes, scenes[1:], strict=False):
        scene["end"] = following_scene["start"]
    scenes[-1]["end"] = round(scenes[-1]["words"][-1]["end"] + beats[-1].hold + TAIL, 3)
    # The end card's address starts typing half a second in, under the voice.
    scenes[-1]["cues"]["site"] = round(
        min(scenes[-1]["words"][-1]["end"] - 0.15, scenes[-1]["start"] + 0.55), 3
    )
    return {"scenes": scenes, "cuts": cuts, "total": scenes[-1]["end"]}


def _caption_lines(beat: Beat, words_: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines, at = [], 0
    for part in beat.say.split("|"):
        count = len(part.split())
        chunk = words_[at : at + count]
        at += count
        if chunk:
            lines.append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "words": chunk})
    return lines


# --- pictures -------------------------------------------------------------------------


def _download(url: str, target: Path) -> bool:
    if target.exists() and target.stat().st_size > 0:
        return True
    request = urllib.request.Request(url, headers={"User-Agent": "Wardly promo"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            target.write_bytes(response.read())
    except OSError:
        return False
    return True


def _sequence(key: str, media: Path) -> dict[str, Any] | None:
    """A hero's idle loop as numbered WebP frames with alpha (decoded once)."""
    folder = media / f"seq-{key}"
    listed = sorted(folder.glob("*.webp")) if folder.exists() else []
    if not listed:
        video = media / f"{key}.webm"
        if not _download(RENDER_VIDEO.format(key=key), video):
            return None
        folder.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            [
                frames.ffmpeg(),
                "-y",
                "-loglevel",
                "error",
                "-c:v",
                "libvpx-vp9",
                "-i",
                str(video),
                "-vf",
                f"scale={SEQUENCE_SIZE}:{SEQUENCE_SIZE}",
                "-c:v",
                "libwebp",
                "-quality",
                "82",
                str(folder / "%03d.webp"),
            ],
            check=False,
        )
        listed = sorted(folder.glob("*.webp"))
        if done.returncode != 0 or not listed:
            return None
    return {"fps": SEQUENCE_FPS, "frames": [path.resolve().as_uri() for path in listed]}


def assets_for(scenes: list[dict[str, Any]], media: Path, download: bool = True) -> dict[str, Any]:
    """file:// addresses of everything the page shows. A missing picture is a gap, not an error."""
    media.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Any] = {"logo": (SITE / "assets" / "logo-mark.png").resolve().as_uri()}
    moving, still, tiles, icons, backs = set(), set(), set(), set(), set()
    for scene in scenes:
        data = scene["data"]
        if data.get("bg"):
            backs.add(data["bg"])
        kind = scene["type"]
        if kind in ("statement", "reveal", "card", "stun") and data.get("hero"):
            moving.add(data["hero"])
        still.update(data.get("shadows") or [])
        if kind == "rank":
            still.update((data["a"]["key"], data["b"]["key"]))
        if kind == "matchup":
            still.add(data["me"]["key"])
            moving.add(data["foe"]["key"])
        if kind == "guess":
            still.update(item["key"] for item in data["items"])
        if kind == "podium":
            still.update(item["key"] for item in data["items"])
        if kind == "grid":
            tiles.update(data["tiles"])
        if kind == "reveal":
            tiles.update(data.get("strip") or [])
        if data.get("item"):
            icons.add(data["item"])
    for key in backs:
        path = SITE / "assets" / "game" / f"{key}.jpg"
        if path.exists():
            assets[f"bg:{key}"] = path.resolve().as_uri()
    for key in tiles:
        path = SITE / "assets" / "heroes" / f"{key}.webp"
        if path.exists():
            assets[f"tile:{key}"] = path.resolve().as_uri()
    if not download:
        return assets
    for key in moving:
        sequence = _sequence(key, media)
        if sequence:
            assets[f"seq:{key}"] = sequence
        else:
            still.add(key)
    for key in still:
        target = media / f"{key}.png"
        if _download(RENDER_PNG.format(key=key), target):
            assets[f"hero:{key}"] = target.resolve().as_uri()
    for key in icons:
        target = media / f"item-{key}.png"
        if _download(ITEM_ICON.format(key=key), target):
            assets[f"icon:{key}"] = target.resolve().as_uri()
    return assets


# --- the page and the file --------------------------------------------------------------


def page(
    timeline: dict[str, Any], assets: dict[str, Any], site: str, language: str, concept: str
) -> str:
    scenes = json.loads(json.dumps(timeline["scenes"]))
    scenes[-1]["data"]["site"] = site
    cut = {
        "concept": concept,
        "lang": language,
        "fps": FPS,
        "total": timeline["total"],
        "scenes": scenes,
        "assets": assets,
    }
    fonts = (SITE / "assets" / "fonts").resolve().as_uri()
    css = (HERE / "cuts.css").read_text("utf-8").replace("__FONTS__", fonts)
    script = (HERE / "cuts.js").read_text("utf-8")
    data = json.dumps(cut, ensure_ascii=False).replace("</", "<\\/")
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8"><style>{css}</style></head>'
        '<body><div id="stage"></div><div id="caps"></div>'
        '<canvas id="grain" width="270" height="480"></canvas><div id="flash"></div>'
        f"<script>window.CUT = {data};</script>"
        # The lines are measured when they are built: the fonts come first.
        "<script>window.cutBoot = Promise.all(['900 100px Montserrat', '800 50px Montserrat', '700 50px Inter', '400 50px Inter']"
        ".flatMap((f) => [document.fonts.load(f, 'Wardly'), document.fonts.load(f, 'Тренер')]))"
        ".then(() => { const s = document.createElement('script'); s.textContent = "
        f"{json.dumps(script)}; document.body.append(s); return window.cutReady; }});</script>"
        "</body></html>"
    )


def _browser(playwright: Any) -> Any:
    return playwright.chromium.launch(
        executable_path=frames.chrome(),
        args=[
            "--allow-file-access-from-files",
            "--disable-web-security",
            "--font-render-hinting=none",
        ],
    )


def _open(browser: Any, html: str, target: Path) -> Any:
    target.write_text(html, encoding="utf-8")
    tab = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    problems: list[str] = []
    tab.on("pageerror", lambda error: problems.append(str(error)))
    tab.goto(target.resolve().as_uri(), wait_until="load")
    tab.evaluate("window.cutBoot")
    if problems:
        raise RuntimeError("the page failed: " + "; ".join(problems))
    tab.problems = problems
    return tab


def stills(html: str, times: list[float], out_dir: Path, name: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    paths = []
    with sync_playwright() as playwright:
        browser = _browser(playwright)
        tab = _open(browser, html, out_dir / f"{name}.html")
        for t in times:
            tab.evaluate(f"window.renderAt({t})")
            path = out_dir / f"{name}-{t:05.2f}.jpg"
            tab.screenshot(path=str(path), type="jpeg", quality=88)
            paths.append(path)
        if tab.problems:
            raise RuntimeError("the page failed: " + "; ".join(tab.problems))
        browser.close()
    return paths


def _encode_part(page_file: str, first: int, last: int, out: str, cover: str | None) -> str:
    """Frames [first, last) of the page at `page_file` as a video-only H.264 file (one process)."""
    from playwright.sync_api import sync_playwright

    command = [
        frames.ffmpeg(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
        "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-profile:v", "high", "-preset", "medium",
        "-crf", str(CRF), "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS), "-bf", "2", out,
    ]  # fmt: skip
    with sync_playwright() as playwright:
        browser = _browser(playwright)
        tab = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        failures: list[str] = []
        tab.on("pageerror", lambda error: failures.append(str(error)))
        tab.goto(Path(page_file).resolve().as_uri(), wait_until="load")
        tab.evaluate("window.cutBoot")
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        try:
            for index in range(first, last):
                tab.evaluate(f"window.renderAt({index / FPS})")
                encoder.stdin.write(tab.screenshot(type="jpeg", quality=93))
                if cover is not None and index == COVER_FRAME:
                    tab.screenshot(path=cover, type="jpeg", quality=90)
        finally:
            encoder.stdin.close()
            code = encoder.wait()
            browser.close()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with code {code}")
    if failures:
        raise RuntimeError("the page failed: " + "; ".join(failures))
    return out


def _encode(html: str, start: float, end: float, out: Path, cover: Path | None = None) -> Path:
    """The frames of [start, end) as a video-only H.264 file.

    Drawing a frame takes far longer than encoding it, so the range is split
    between processes (one browser each) and the pieces are joined without
    encoding again: every piece starts on a key frame."""
    from concurrent.futures import ProcessPoolExecutor

    first, last = round(start * FPS), round(end * FPS)
    page_file = out.with_suffix(".html")
    page_file.write_text(html, encoding="utf-8")
    workers = max(1, min(WORKERS, (last - first) // (2 * FPS) or 1))
    edges = [first + round((last - first) * i / workers) for i in range(workers + 1)]
    jobs = [
        (
            str(page_file),
            edges[i],
            edges[i + 1],
            str(out.with_name(f"{out.stem}-{i}.mp4")),
            str(cover) if cover and edges[i] <= COVER_FRAME < edges[i + 1] else None,
        )
        for i in range(workers)
    ]
    try:
        if workers == 1:
            parts = [_encode_part(*jobs[0])]
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                parts = list(pool.map(_encode_part, *zip(*jobs, strict=True)))
        _join([Path(part) for part in parts], None, out)
    finally:
        page_file.unlink(missing_ok=True)
        for job in jobs:
            Path(job[3]).unlink(missing_ok=True)
    return out


def _join(parts: list[Path], audio: Path | None, out: Path) -> Path:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{part.resolve()}'\n" for part in parts), "utf-8")
    command = [
        frames.ffmpeg(),
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
    ]
    if audio is not None:
        command += [
            "-i",
            str(audio),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
        ]
    command += ["-c:v", "copy", "-movflags", "+faststart", str(out)]
    subprocess.run(command, check=True)
    listing.unlink(missing_ok=True)
    return out


# --- what goes with the file ------------------------------------------------------------


def publishing(concept: str, language: str, facts: dict[str, Any]) -> dict[str, Any]:
    """The title, the description and the tags, per language (the same on every network)."""
    uk = language == "uk"
    site = "luhovyimvp.dev"
    if concept == "lanes-top5":
        first = facts["top"][0]
        title = (
            f"5 ліній, які програні ще на піку | {first['hero']} проти {first['enemy']}: {first['pct']}%"
            if uk
            else f"5 lanes you lose at the pick | {first['hero']} into {first['enemy']}: {first['pct']}%"
        )
        text = (
            f"{facts['lanes']:,} ліній із лігових ігор за рік: хто попереду за золотом на 10:00.".replace(
                ",", " "
            )
            if uk
            else f"{facts['lanes']:,} lanes of league games in a year: who is ahead in gold at 10:00."
        )
        tags = [first["hero"], first["enemy"], "laning"]
    elif concept == "lane-bully":
        first = facts["podium"][0]
        title = (
            f"Один герой ламає лінію кожному третьому кору | {first['hero']}"
            if uk
            else f"One hero ruins the lane for every third core | {first['hero']}"
        )
        text = (
            f"{first['hero']} робить лінію важкою для {first['count']} з {facts['cores']} корів (лігові ігри, золото на 10:00)."
            if uk
            else f"{first['hero']} makes the lane hard for {first['count']} of {facts['cores']} cores (league games, gold at 10:00)."
        )
        tags = [first["hero"], "mid lane", "laning"]
    elif concept == "hero-lanes":
        hero = facts["hero"]
        names = (
            " і ".join(o["hero"] for o in hero["hard"])
            if uk
            else " and ".join(o["hero"] for o in hero["hard"])
        )
        title = (
            f"{hero['name']}: дві лінії, де тебе з'їдять"
            if uk
            else f"{hero['name']}: two lanes that eat you alive"
        )
        text = (
            f"{hero['name']} найчастіше програє лінію проти {names}; зручна лінія — {hero['easy']['hero']}."
            if uk
            else f"{hero['name']} loses the lane most often to {names}; the easy lane is {hero['easy']['hero']}."
        )
        tags = [hero["name"], *[o["hero"] for o in hero["hard"]]]
    else:
        title = (
            "Застанили з готовим BKB — і ти все одно помер"
            if uk
            else "Stunned with BKB ready, and you still died"
        )
        text = (
            "Найчастіше добивають у першу секунду після контролю. Wardly показує це поверх гри, поки ти ще в стані."
            if uk
            else "Most kills finish in the first second after a disable. Wardly shows it over the game while you are still stunned."
        )
        tags = ["Black King Bar", "Juggernaut", "BKB"]
    about = (
        f"Wardly — безкоштовний тренер для Dota 2 (Windows і Linux): {site}"
        if uk
        else f"Wardly is a free Dota 2 coach (Windows and Linux): {site}"
    )
    hashtags = ["#dota2", "#dota", "#дота2" if uk else "#dota2tips", "#wardly"]
    return {
        "title": title[:100],
        "description": f"{text}\n\n{about}\n\n{' '.join(hashtags)}",
        "tags": ["Dota 2", "dota2", "Wardly", *tags][:12],
        "language": language,
    }


def problems(timeline: dict[str, Any], info: dict[str, Any] | None) -> list[str]:
    """Why the video should not go out, in plain words (empty: nothing found)."""
    found = []
    total = timeline["total"]
    if not 10 <= total <= MAX_SECONDS:
        found.append(f"the video is {total:.1f} s (10 to {MAX_SECONDS})")
    for index, scene in enumerate(timeline["scenes"]):
        if scene["end"] - scene["start"] < 0.6:
            found.append(f"scene {index + 1} ({scene['type']}) is shorter than 0.6 s")
    end = timeline["scenes"][-1]
    if (end["end"] - end["start"]) / total > 0.2:
        found.append("the end card takes more than a fifth of the video")
    if info is not None:
        if (info.get("width"), info.get("height")) != (WIDTH, HEIGHT):
            found.append(f"the file is {info.get('width')}x{info.get('height')}")
        if not info.get("audio"):
            found.append("the file has no sound")
        if abs(info.get("seconds", 0) - total) > 0.35:
            found.append(f"the file is {info.get('seconds')} s for a {total:.2f} s timeline")
    return found


def build(
    concept: str,
    language: str,
    out: Path,
    *,
    draft: bool = False,
    networks: tuple[str, ...] = ("tt", "yt"),
    voice_key: str | None = None,
    only_stills: bool = False,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from . import cuts_sound

    facts = facts_for(concept) if facts is None else facts
    beats = beats_for(concept, language, facts)
    voice_key = voice_key or CAST[(concept, language)]
    name = f"{concept}-{language}"
    work = out / "work" / name
    work.mkdir(parents=True, exist_ok=True)
    if draft:
        take, timed = None, draft_words(beats)
    else:
        take, timed = narrate(beats, voice_key, language, work)
    timeline = arrange(beats, timed)
    assets = assets_for(timeline["scenes"], out / "work" / "media")
    address = "luhovyimvp.dev/{}"
    result: dict[str, Any] = {
        "concept": concept,
        "language": language,
        "revision": REVISION,
        "voice": None
        if draft
        else {
            "key": voice_key,
            "name": VOICES[voice_key][1],
            "model": VOICE_MODEL,
            **VOICE_SETTINGS,
        },
        "seconds": timeline["total"],
        "narration": narration(beats),
        "publishing": publishing(concept, language, facts),
        "files": {},
    }
    if only_stills:
        html = page(timeline, assets, address.format(networks[0]), language, concept)
        times = sorted(
            {
                round(s["start"] + f * (s["end"] - s["start"]), 2)
                for s in timeline["scenes"]
                for f in (0.25, 0.6, 0.95)
            }
        )
        result["stills"] = [str(p) for p in stills(html, times, work, name)]
        result["problems"] = problems(timeline, None)
        return result
    sound = cuts_sound.mix(timeline, take, work / "sound.wav")
    tail_start = timeline["scenes"][-1]["start"]
    body_html = page(timeline, assets, address.format(networks[0]), language, concept)
    body = _encode(body_html, 0.0, tail_start, work / "body.mp4", cover=out / f"{name}.jpg")
    for network in networks:
        html = page(timeline, assets, address.format(network), language, concept)
        tail = _encode(html, tail_start, timeline["total"], work / f"tail-{network}.mp4")
        target = _join([body, tail], sound, out / f"{name}-{NETWORKS[network]}.mp4")
        info = frames.probe(target)
        result["files"][NETWORKS[network]] = {
            "file": target.name,
            "address": address.format(network),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            **info,
        }
        result["problems"] = problems(timeline, info)
    (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=CONCEPTS, action="append", help="these videos only")
    parser.add_argument("--lang", choices=LANGUAGES, action="append", help="these languages only")
    parser.add_argument(
        "--network", choices=tuple(NETWORKS), action="append", help="endings (default: tt and yt)"
    )
    parser.add_argument(
        "--voice", choices=tuple(VOICES), help="one voice for every video (default: CAST)"
    )
    parser.add_argument("--draft", action="store_true", help="no voice: a steady reading pace")
    parser.add_argument(
        "--stills", action="store_true", help="frames of each scene instead of the videos"
    )
    parser.add_argument(
        "--tidy",
        action="store_true",
        help="remove downloaded pictures and half-made files afterwards",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False
    lanes: dict[str, Any] | None = None
    for concept in args.only or CONCEPTS:
        if concept != "stun-bkb" and lanes is None:
            lanes = lane_facts()
        for language in args.lang or LANGUAGES:
            result = build(
                concept,
                language,
                args.out,
                draft=args.draft,
                networks=tuple(args.network or ("tt", "yt")),
                voice_key=args.voice,
                only_stills=args.stills,
                facts={} if concept == "stun-bkb" else lanes,
            )
            issues = result.get("problems") or []
            failed = failed or bool(issues)
            print(
                f"{concept} {language}: {result['seconds']:.1f} s"
                + ("; " + "; ".join(issues) if issues else "")
            )
    if args.tidy:
        # Valve's pictures and the pieces of the render are not part of the result;
        # the takes stay (work/<video>/voice-*.wav), so a rebuild can reuse them.
        shutil.rmtree(args.out / "work" / "media", ignore_errors=True)
        for leftover in (args.out / "work").glob("*/*.mp4"):
            leftover.unlink()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
