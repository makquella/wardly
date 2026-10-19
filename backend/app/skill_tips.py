"""
skill_tips.py - прокачка: an unspent skill point, the ultimate at 6/12/18 and a
talent at 10/15/20/25, from the live GSI hero and abilities blocks.

Counting the points spent from scratch is not safe: innate abilities (7.36+)
level up by themselves, and a talent or the attribute bonus may be missing from
the payload. So the tracker works on changes: from the first tick it sees, a
level gained must be followed by one more level in the abilities, talents or
attributes. A level spent that it cannot see (an innate levelling with the
ultimate) only moves the base, so the error is always towards saying nothing.

One tip per new hero level, after the point has stayed unspent for
UNSPENT_WAIT seconds of game clock while alive; after 10 without talent fields
in the payload only the ultimate is named (a talent taken would read as a
point left unspent).
"""

from __future__ import annotations

import math
from typing import Any

from app.ability_normalization import NOT_HERO_ABILITY_PREFIXES as NOT_HERO_ABILITY_PREFIXES
from app.ability_normalization import not_hero_ability as not_hero_ability
from app.hero_profiles import find_ability, get_key_safety_abilities
from app.skill_build import label, next_skill

ULTIMATE_LEVELS = (6, 12, 18)
TALENT_LEVELS = (10, 15, 20, 25)
UNSPENT_WAIT = 15  # seconds of game clock with the point unspent
# A point "unspent" for this long is a miscount (a talent or the attribute bonus
# the payload does not show), not a forgotten point: start counting again.
UNSPENT_STALE = 180
TIP_SHOW = 20  # seconds the tip stays on the card
# Ultimates that are never levelled at 6/12/18: Invoke has one level from the
# start, so a point owed at 12 would read as «learn your ultimate».
FIXED_ULTIMATES = frozenset({"invoker_invoke"})
# A hard lane (live_hints.lane_pressure): up to this hero level, a point goes to
# the hero's escape or defensive ability while it is still unlearned, before the
# pro order (which often maxes a farming or damage skill first).
LANE_SAFETY_UNTIL_LEVEL = 7

TEXTS = {
    "ultimate": {
        "en": ("Learn your ultimate", "{name} is ready to learn: level {level} opens it."),
        "uk": ("Вивчіть ультимейт", "{name} можна вивчити: його відкриває {level}-й рівень."),
    },
    "talent": {
        "en": ("Pick a talent", "The level-{tier} talent is waiting: open the talent tree."),
        "uk": ("Оберіть талант", "Талант {tier}-го рівня чекає: відкрийте дерево талантів."),
    },
    "talent_pro": {
        "en": (
            "Pick a talent",
            "Level {tier}: pros on this hero take “{name}” ({picked} of {games}).",
        ),
        "uk": (
            "Оберіть талант",
            "Талант {tier}-го рівня: про-гравці на цьому герої беруть «{name}» ({picked} з {games}).",
        ),
    },
    # A hero plan's talent for the enemy lineup (hero_items.plan_skills).
    "talent_clearers": {
        "en": (
            "Pick a talent",
            "Level {tier}: take “{name}”. {count} enemy heroes clear illusions fast ({enemies}): "
            "longer images would not last.",
        ),
        "uk": (
            "Оберіть талант",
            "Талант {tier}-го рівня: беріть «{name}». Ворожих героїв, які швидко вбивають ілюзії, — "
            "{count} ({enemies}): довші ілюзії не проживуть.",
        ),
    },
    "skill": {
        "en": ("Put the point in {name}", "The pro order on this hero: {order}."),
        "uk": ("Вкладіть очко в {name}", "Порядок прокачки в про-гравців на цьому герої: {order}."),
    },
    "skill_lane": {
        "en": (
            "Put the point in {name}",
            "A hard lane: a first point in {name} keeps you alive. After it, the pro order: {order}.",
        ),
        "uk": (
            "Вкладіть очко в {name}",
            "Важка лінія: перше очко в {name} допоможе вижити. Далі — порядок про-гравців: {order}.",
        ),
    },
    "opening": {
        "en": (
            "First point: {name}",
            "Pros on this hero start with {name} ({agree} of {games} games).",
        ),
        "uk": (
            "Перше очко: {name}",
            "Про-гравці на цьому герої починають з {name} ({agree} з {games} ігор).",
        ),
    },
    "point": {
        "en": (
            "Unspent skill point",
            "A level without the point spent is a weaker hero in the next fight.",
        ),
        "uk": (
            "Не вкладено очко навичок",
            "Рівень без вкладеного очка — герой слабший у наступній бійці.",
        ),
    },
}


def _int(value: Any) -> int | None:
    """A whole number from GSI; NaN, infinity or a huge value count as missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or abs(value) > 1000:
        return None
    return int(value)


def read_skills(payload: Any) -> dict[str, Any] | None:
    """Hero level, the levels spent (abilities + talents + attributes), the
    ultimate and whether the talent fields are there; None without the blocks."""
    if not isinstance(payload, dict):
        return None
    hero = payload.get("hero")
    abilities = payload.get("abilities")
    if not isinstance(hero, dict) or not isinstance(abilities, dict) or not abilities:
        return None
    level = _int(hero.get("level"))
    if level is None or not 1 <= level <= 30:
        return None
    spent = 0
    ultimate = None
    levels: dict[str, int] = {}
    bar: list[str] = []
    for key in sorted(abilities, key=_slot_order):
        ability = abilities[key]
        if not isinstance(ability, dict) or not_hero_ability(ability.get("name")):
            continue
        if isinstance(ability.get("name"), str) and not _hidden(ability["name"]):
            bar.append(ability["name"])
        ability_level = _int(ability.get("level")) or 0
        if 0 <= ability_level <= 10:
            spent += ability_level
            raw_name = ability.get("name")
            if isinstance(raw_name, str) and raw_name:
                levels.setdefault(raw_name, ability_level)
        if ability.get("ultimate") is True and ultimate is None:
            ultimate = {"raw_name": str(ability.get("name") or ""), "level": ability_level}
            if ability.get("passive") is True:
                ultimate["passive"] = True  # Coup de Grace, Juxtapose: nothing to press
    talent_keys = [key for key in hero if str(key).startswith("talent_")]
    talents = sum(1 for key in talent_keys if hero.get(key) is True)
    attributes = _int(hero.get("attributes_level")) or 0
    return {
        "level": level,
        "spent": spent + talents + attributes,
        "ultimate": ultimate,
        "has_talents": bool(talent_keys),
        "talents": {key: hero.get(key) is True for key in talent_keys},
        "levels": levels,
        "hero_key": _hero_key(hero.get("name")),
        # The abilities in the order of the HUD's ability bar (the skill arrows).
        "bar": bar,
    }


def _slot_order(key: Any) -> tuple[int, str]:
    """ability0 … ability10 in number order (a plain sort puts ability10 first)."""
    text = str(key)
    digits = text[len(text.rstrip("0123456789")) :]
    return (int(digits) if digits else 1_000, text)


def _hidden(name: str) -> bool:
    """A placeholder slot the HUD does not draw."""
    return name.startswith("generic_hidden") or "_empty" in name


def ability_slot(skills: dict[str, Any] | None, raw_name: str | None) -> dict[str, int] | None:
    """{slot, slots} of an ability on the bar, for the arrow over it; Shadowraze
    2/3 point at the first of the three."""
    bar = (skills or {}).get("bar") or []
    if not raw_name or raw_name not in bar:
        return None
    return {"slot": bar.index(raw_name), "slots": len(bar)}


def _hero_key(value: Any) -> str | None:
    """npc_dota_hero_juggernaut → juggernaut (the prefix of its ability names)."""
    prefix = "npc_dota_hero_"
    if isinstance(value, str) and value.startswith(prefix) and len(value) > len(prefix):
        return value[len(prefix) :]
    return None


def _ultimate_allowed(level: int) -> int:
    return sum(1 for need in ULTIMATE_LEVELS if level >= need)


def _talent_due(skills: dict[str, Any]) -> int | None:
    """The lowest talent tier reached with neither of its two talents taken."""
    talents = skills["talents"]
    for index, tier in enumerate(TALENT_LEVELS):
        if skills["level"] < tier:
            return None
        pair = (f"talent_{index * 2 + 1}", f"talent_{index * 2 + 2}")
        if not any(talents.get(key) for key in pair):
            return tier
    return None


class SkillTips:
    """Per-match state (reset with MatchMemory)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._base: tuple[int, int] | None = None  # (level, spent) seen last with nothing owed
        self._unspent_since: int | None = None
        self._shown: dict[int, int] = {}  # hero level -> clock the tip started
        self._skills: dict[str, Any] | None = None

    def observe(self, clock: int | None, skills: dict[str, Any] | None) -> None:
        if clock is None or skills is None:
            return
        level, spent = skills["level"], skills["spent"]
        if self._base is None or level < self._base[0]:
            # First tick or a new match: all spent — except a level-1 hero with
            # nothing learned, whose first point is plainly still to spend.
            self._base = (0, 0) if (level, spent) == (1, 0) else (level, spent)
        owed = (level - self._base[0]) - (spent - self._base[1])
        if owed <= 0:
            # Caught up (or more levels than points: an innate) → a new base.
            self._base = (level, spent)
            self._unspent_since = None
        elif self._unspent_since is None:
            self._unspent_since = clock
        elif clock - self._unspent_since > UNSPENT_STALE:
            self._base = (level, spent)
            self._unspent_since = None
            owed = 0
        self._skills = {**skills, "owed": max(0, owed)}

    def bar_size(self) -> int | None:
        """How many abilities the HUD bar shows (the arrow frame's calibration)."""
        bar = (self._skills or {}).get("bar")
        return len(bar) if bar else None

    def tip(
        self,
        clock: int | None,
        lang: str,
        *,
        alive: bool,
        build: dict[str, Any] | None = None,
        hero: str | None = None,
        lane_pressure: bool = False,
    ) -> dict[str, Any] | None:
        """`build`: the hero's pro skill order (app/skill_build.skill_order), which
        names the ability for an unspent point and the ultimate. `lane_pressure`
        (a hard lane, live_hints.lane_pressure) puts an early point in the
        `hero`'s escape or defensive ability first."""
        skills = self._skills
        if clock is None or not alive or skills is None or not skills["owed"]:
            return None
        if self._unspent_since is None or clock - self._unspent_since < UNSPENT_WAIT:
            return None
        level = skills["level"]
        start = self._shown.setdefault(level, clock)
        if not 0 <= clock - start <= TIP_SHOW:
            return None
        ultimate = skills["ultimate"]
        if (
            ultimate
            and ultimate["raw_name"] not in FIXED_ULTIMATES
            and ultimate["level"] < _ultimate_allowed(level)
        ):
            names = (build or {}).get("names") or {}
            name = names.get(ultimate["raw_name"]) or label(
                ultimate["raw_name"], skills.get("hero_key")
            )
            need = ULTIMATE_LEVELS[ultimate["level"]] if ultimate["level"] < 3 else level
            hint = _hint("ultimate", f"skill-ult@{level}", lang, name=name, level=need)
            return self._arrow(hint, ultimate["raw_name"], name)
        if not skills["has_talents"]:
            if level >= TALENT_LEVELS[0]:
                return None  # a talent taken would look like a point left unspent
            return self._point(level, lang, build, hero if lane_pressure else None)
        tier = _talent_due(skills)
        if tier is not None:
            pro = ((build or {}).get("talents") or {}).get(tier)
            because = (pro or {}).get("because")
            if pro and because and because.get("group") == "illusion_clearers":
                return _hint(
                    "talent_clearers",
                    f"skill-talent@{level}",
                    lang,
                    tier=tier,
                    name=pro["label"],
                    count=because["count"],
                    enemies=", ".join(because["enemies"]),
                )
            if pro and "picked" in pro:
                return _hint(
                    "talent_pro",
                    f"skill-talent@{level}",
                    lang,
                    tier=tier,
                    name=pro["label"],
                    picked=pro["picked"],
                    games=pro["games"],
                )
            return _hint("talent", f"skill-talent@{level}", lang, tier=tier)
        return self._point(level, lang, build, hero if lane_pressure else None)

    def _point(
        self,
        level: int,
        lang: str,
        build: dict[str, Any] | None,
        pressed_hero: str | None = None,
    ) -> dict[str, Any]:
        """The unspent point: the ability the pro order puts it in, when known;
        in a hard lane (`pressed_hero`) the hero's unlearned escape first."""
        skills = self._skills or {}
        opening = (build or {}).get("opening")
        levels = skills.get("levels") or {}
        if level == 1 and opening and not any(levels.values()):
            names = (build or {}).get("names") or {}
            name = names.get(opening["name"]) or label(opening["name"], skills.get("hero_key"))
            hint = _hint(
                "opening",
                "skill-point@1",
                lang,
                name=name,
                agree=opening["agree"],
                games=opening["games"],
            )
            return self._arrow(hint, opening["name"], name)
        name = next_skill(build, skills.get("levels"), level)
        safety = self._safety_skill(pressed_hero, level)
        if build and safety and safety != name:
            names = build.get("names") or {}
            key = skills.get("hero_key")
            steps = [{"key": n, "name": str(names.get(n) or label(n, key))} for n in build["order"]]
            shown = names.get(safety) or label(safety, key)
            order = " → ".join(step["name"] for step in steps)
            hint = _hint("skill_lane", f"skill-point@{level}", lang, name=shown, order=order)
            hint["order"] = steps
            return self._arrow(hint, safety, shown)
        if build and name:
            names = build.get("names") or {}
            key = skills.get("hero_key")
            steps = [{"key": n, "name": str(names.get(n) or label(n, key))} for n in build["order"]]
            order = " → ".join(step["name"] for step in steps)
            shown = names.get(name) or label(name, key)
            hint = _hint("skill", f"skill-point@{level}", lang, name=shown, order=order)
            # The order as icons on the card (the text says it in words too).
            hint["order"] = steps
            return self._arrow(hint, name, shown)
        return _hint("point", f"skill-point@{level}", lang)

    def _safety_skill(self, hero: str | None, level: int) -> str | None:
        """The raw name of the hero's escape or defensive ability (hero_profiles)
        still at level 0, from level 2 to LANE_SAFETY_UNTIL_LEVEL; None otherwise."""
        skills = self._skills or {}
        levels = skills.get("levels") or {}
        ultimate = (skills.get("ultimate") or {}).get("raw_name")
        if not hero or not 2 <= level <= LANE_SAFETY_UNTIL_LEVEL or not levels:
            return None
        key = skills.get("hero_key")
        abilities = [
            {"name": label(raw, key), "raw_name": raw} for raw in levels if raw != ultimate
        ]
        wanted = get_key_safety_abilities(hero)
        for display in [*wanted["escape"], *wanted["defensive"]]:
            found = find_ability(abilities, display)
            if found is not None and levels.get(str(found["raw_name"])) == 0:
                return str(found["raw_name"])
        return None

    def _arrow(self, hint: dict[str, Any], raw_name: str, name: str) -> dict[str, Any]:
        """The ability's place on the HUD bar: the launcher draws an arrow over it.
        `icon` (the ability's game name, Valve's icon file) is there even when
        the bar slot is not known: the card shows the icon next to the name."""
        hint["icon"] = raw_name
        slot = ability_slot(self._skills, raw_name)
        if slot is not None:
            hint["ability"] = {"key": raw_name, "name": name, **slot}
        return hint


def _hint(key: str, hint_id: str, lang: str, **params: Any) -> dict[str, Any]:
    title, text = TEXTS[key]["uk" if lang == "uk" else "en"]
    return {
        "kind": "tip",
        # The overlay card's label (instead of «Map»).
        "label": "Прокачка" if lang == "uk" else "Skills",
        "id": hint_id,
        "at": None,
        "at_label": None,
        "in_seconds": None,
        "title": title.format(**params),
        "hint": text.format(**params),
        "speak": True,
        # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
        "title_en": TEXTS[key]["en"][0].format(**params),
        # Kept on the overlay over the game plan (overlay/app.js).
        "over_plan": True,
    }
