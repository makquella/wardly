"""
hero_items.py - counter items for the player's own hero (data/heroes/item_plans).

situational_items answers an enemy hero by kind and position alone: a carry
against evasion gets Monkey King Bar, whoever the carry is. A hero's plan says
what that hero buys instead, from the hero's build and the items' current
mechanics (each rule keeps its `basis`), e.g. Terrorblade:

- evasion (Phantom Assassin, Windranger) and an escape a silence stops (Queen
  of Pain's Blink, Storm Spirit's Ball Lightning...): Bloodthorn — the silence
  stops the escape and gives True Strike to his illusions too;
- evasion alone: Monkey King Bar;
- heavy healing: his own Eye of Skadi after Manta Style;
- illusion heroes: Butterfly, and the Dragon Lance into Hydra's Breath
  (Metamorphosis attacks from range) instead of Hurricane Pike;
- heroes who jump on him (Slark, Phantom Assassin, Spirit Breaker): Pike.

`build`: the hero's usual order when no counter or tempo holds (high-rank
won games, instead of the all-ranks OpenDota popularity); `unless` skips an
entry another item answered (Hurricane Pike after Hydra's Breath).

`skills`: the hero's skill build from the same high-rank games (the order the
basic abilities are maxed, the first point, the talents), instead of the few
recent pro games skill_build.py reads.

`tempo`: with the player's own net worth over the plan's curve (minute → net
worth, from high-rank games where the hero wins ~85% above it) the counters
wait and the next item is the tempo build's (Terrorblade, in the order of his
farmed won games: Manta Style, Aghanim's Shard, Dragon Lance, Eye of Skadi,
Butterfly, Daedalus), then the Aegis and the throne. A player's GSI
shows no enemy net worth, so the hero's own farm is the observed sign.
"""

from __future__ import annotations

import json
import string
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

ITEM_PLANS_DIR = DATA_DIR / "heroes" / "item_plans"
SCHEMA = 1
# Each rule (and the tempo build) carries its own reason, {en, uk}: one clause
# without a final period, shown on the draft card, after «Why <item>:» on the
# death screen and as the farm advice's reason (advice_i18n turns the English
# into the Ukrainian with reason_templates). Placeholders it may use:
PLACEHOLDERS = {"enemy", "escape", "spell", "item", "net_worth"}
TEMPO_WHY = "tempo"
POSITIONS = {"carry", "mid", "offlane"}
RULE_KEYS = {
    "id",
    "why",
    "family",
    "item",
    "name",
    "enemy",
    "also",
    "minute",
    "basis",
    "reason",
}


def groups() -> dict[str, dict[str, str | None]]:
    """Enemy hero groups a rule names: {group: {hero: spell or None}}."""
    from app.draft_analysis import COUNTERS, ESCAPES, ILLUSION_CLEARERS, JUMPERS
    from app.situational_items import BREAK_PASSIVES

    return {
        "evasion": dict.fromkeys(COUNTERS["evasion"][0]),
        "illusions": dict.fromkeys(COUNTERS["illusions"][0]),
        "invisibility": dict.fromkeys(COUNTERS["invisibility"][0]),
        "healing": dict.fromkeys(COUNTERS["healing"][0]),
        "escape": dict(ESCAPES),
        "break": dict(BREAK_PASSIVES),
        "jumpers": dict(JUMPERS),
        "illusion_clearers": dict.fromkeys(ILLUSION_CLEARERS),
    }


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def check_reason(reason: Any, fail: Any, where: str) -> None:
    """{en, uk}: one clause each, no final period, the same known placeholders."""
    if not isinstance(reason, dict) or set(reason) != {"en", "uk"}:
        raise fail(f"{where}: reason must be {{en, uk}}")
    try:
        names = {lang: placeholders(text) for lang, text in reason.items()}
    except (ValueError, TypeError):
        raise fail(f"{where}: reason has a broken placeholder") from None
    for lang, text in reason.items():
        if not isinstance(text, str) or not text.strip() or text.rstrip().endswith("."):
            raise fail(f"{where}: reason.{lang} is one clause without a final period")
        if not names[lang] <= PLACEHOLDERS:
            raise fail(f"{where}: reason.{lang} uses {sorted(names[lang] - PLACEHOLDERS)}")
    if names["uk"] != names["en"]:
        raise fail(f"{where}: reason.en and reason.uk name different placeholders")


def format_reason(reason: dict[str, str], **values: Any) -> dict[str, str]:
    """The reason in both languages with its placeholders filled."""
    filled = {k: "" if v is None else str(v) for k, v in values.items()}
    return {lang: text.format_map(_Missing(filled)) for lang, text in reason.items()}


class _Missing(dict):  # type: ignore[type-arg]
    def __missing__(self, key: str) -> str:
        return ""


def reason_templates() -> list[tuple[str, str]]:
    """(English, Ukrainian) of every plan's reasons (advice_i18n)."""
    pairs: list[tuple[str, str]] = []
    for plan in load_plans().values():
        for rule in plan["rules"]:
            pairs.append((rule["reason"]["en"], rule["reason"]["uk"]))
        if plan.get("tempo"):
            pairs.append((plan["tempo"]["reason"]["en"], plan["tempo"]["reason"]["uk"]))
    return pairs


def validate(plan: Any, source: str = "plan") -> dict[str, Any]:
    """The plan when it follows the schema; ValueError naming what is wrong."""
    from app.dota_constants import hero_id_from_name

    def fail(message: str) -> ValueError:
        return ValueError(f"{source}: {message}")

    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise fail(f"schema must be {SCHEMA}")
    if hero_id_from_name(plan.get("hero")) is None:
        raise fail(f"unknown hero {plan.get('hero')!r}")
    positions = plan.get("positions")
    if not isinstance(positions, list) or not positions or not set(positions) <= POSITIONS:
        raise fail(f"positions must be some of {sorted(POSITIONS)}")
    known = groups()
    rules = plan.get("rules")
    if not isinstance(rules, list) or not rules:
        raise fail("no rules")
    ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or not set(rule) <= RULE_KEYS:
            raise fail(f"a rule has unknown keys: {sorted(set(rule) - RULE_KEYS)}")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or rule_id in ids:
            raise fail(f"rule id {rule_id!r} is missing or repeated")
        ids.add(rule_id)
        if not isinstance(rule.get("why"), str) or not rule["why"].strip():
            raise fail(f"{rule_id}: why is required")
        check_reason(rule.get("reason"), fail, rule_id)
        for key in ("family", "item", "name", "basis"):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                raise fail(f"{rule_id}: {key} is required")
        for key in ("enemy", "also"):
            if key in rule and rule[key] not in known:
                raise fail(f"{rule_id}: {key} must be one of {sorted(known)}")
        if "enemy" not in rule:
            raise fail(f"{rule_id}: enemy is required")
        minute = rule.get("minute")
        if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute <= 60:
            raise fail(f"{rule_id}: minute must be 0..60")
    suppress = plan.get("suppress", {})
    if not isinstance(suppress, dict) or not all(
        isinstance(v, str) and v.strip() for v in suppress.values()
    ):
        raise fail("suppress maps a generic why to the reason it does not fit")
    skills = plan.get("skills")
    if skills is not None:
        validate_skills(skills, fail)
    build = plan.get("build")
    if build is not None and (
        not isinstance(build, list)
        or not build
        or not all(
            isinstance(e, dict)
            and isinstance(e.get("item"), str)
            and e.get("name")
            and all(isinstance(u, str) for u in e.get("unless", []))
            for e in build
        )
        or not isinstance(plan.get("build_basis"), str)
        or not plan["build_basis"].strip()
    ):
        raise fail("build needs items [{item, name, unless?}] and a build_basis")
    tempo = plan.get("tempo")
    if tempo is not None:
        items = tempo.get("items") if isinstance(tempo, dict) else None
        raw = tempo.get("net_worth") if isinstance(tempo, dict) else None
        curve: list[Any] = raw if isinstance(raw, list) else []
        points = [p for p in curve if isinstance(p, list) and len(p) == 2]
        if (
            not isinstance(items, list)
            or not items
            or not all(
                isinstance(i, dict) and isinstance(i.get("item"), str) and i.get("name")
                for i in items
            )
            or not points
            or len(points) != len(curve)
            or not all(
                all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in p)
                for p in points
            )
            or [p[0] for p in points] != sorted({p[0] for p in points})
            or not isinstance(tempo.get("basis"), str)
            or not tempo["basis"].strip()
        ):
            raise fail(
                "tempo needs items [{item, name}], a net_worth curve [[minute, gold], ...] "
                "with rising minutes, and a basis"
            )
        check_reason(tempo.get("reason"), fail, "tempo")
    return plan


@lru_cache(maxsize=1)
def load_plans(directory: Path = ITEM_PLANS_DIR) -> dict[int, dict[str, Any]]:
    """{hero id: plan} for every plan file; a broken file raises (tests and CI
    load them all)."""
    from app.dota_constants import hero_id_from_name

    plans: dict[int, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        plan = validate(json.loads(path.read_text(encoding="utf-8")), path.name)
        hero_id = hero_id_from_name(plan["hero"])
        if hero_id is None or hero_id in plans:
            raise ValueError(f"{path.name}: a second plan for {plan['hero']}")
        plans[hero_id] = plan
    return plans


def plan_for(hero: Any, position: str | None) -> dict[str, Any] | None:
    """The hero's plan when the hero plays one of its positions; else None."""
    from app.dota_constants import hero_id_from_name

    hero_id = hero_id_from_name(hero) if isinstance(hero, str) else None
    plan = load_plans().get(hero_id) if hero_id is not None else None
    if plan is None or position not in plan["positions"]:
        return None
    return plan


def replaced(plan: dict[str, Any]) -> set[str]:
    """The generic whys the plan answers itself or drops."""
    return {rule["family"] for rule in plan["rules"]} | set(plan.get("suppress", {}))


def hero_rows(plan: dict[str, Any], enemies: list[str], minute: int | None) -> list[dict[str, Any]]:
    """The plan's rules that hold, first per family: {why, key, name, enemy,
    escape, spell, family_items}."""
    known = groups()
    family_items: dict[str, list[str]] = {}
    for rule in plan["rules"]:
        family_items.setdefault(rule["family"], []).append(rule["item"])
    rows: list[dict[str, Any]] = []
    done: set[str] = set()
    for rule in plan["rules"]:
        if rule["family"] in done or (minute or 0) < rule["minute"]:
            continue
        enemy = next((e for e in enemies if e in known[rule["enemy"]]), None)
        if enemy is None:
            continue
        escape = None
        if "also" in rule:
            escape = next((e for e in enemies if e in known[rule["also"]] and e != enemy), None)
            if escape is None:
                continue
        spell = known[rule["also"]].get(escape) if escape else known[rule["enemy"]].get(enemy)
        done.add(rule["family"])
        rows.append(
            {
                "why": rule["why"],
                "key": rule["item"],
                "name": rule["name"],
                "enemy": enemy,
                "escape": escape,
                "spell": spell,
                "family_items": family_items[rule["family"]],
                "reason": rule["reason"],
            }
        )
    return rows


def tempo_threshold(plan: dict[str, Any], minute: int | None) -> int | None:
    """The plan's tempo net worth for `minute`: linear between the curve's
    points, the last segment's slope after them; None before the first point."""
    tempo = plan.get("tempo")
    if not tempo or not isinstance(minute, int):
        return None
    points = tempo["net_worth"]
    if minute < points[0][0]:
        return None
    for (m0, g0), (m1, g1) in zip(points, points[1:], strict=False):
        if m0 <= minute <= m1:
            return round(g0 + (g1 - g0) * (minute - m0) / (m1 - m0))
    if len(points) == 1:
        return points[0][1]
    (m0, g0), (m1, g1) = points[-2], points[-1]
    return round(g1 + (g1 - g0) * (minute - m1) / (m1 - m0))


def tempo_rows(
    plan: dict[str, Any], net_worth: int | None, minute: int | None
) -> list[dict[str, Any]] | None:
    """The tempo build's items in order when the player's net worth is over the
    plan's curve ({key, name}); None otherwise (the counters stay)."""
    threshold = tempo_threshold(plan, minute)
    if threshold is None or not isinstance(net_worth, int) or net_worth < threshold:
        return None
    reason = plan["tempo"]["reason"]
    return [{"key": i["item"], "name": i["name"], "reason": reason} for i in plan["tempo"]["items"]]


def validate_skills(skills: Any, fail: Any) -> None:
    """A plan's `skills`: {order, games, first_agree, opening {name, agree},
    talents {tier: {name, label, picked, games}}, basis}."""

    def count(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    if not isinstance(skills, dict):
        raise fail("skills must be an object")
    order = skills.get("order")
    if not isinstance(order, list) or not order or not all(isinstance(n, str) for n in order):
        raise fail("skills.order lists ability names")
    games = skills.get("games")
    if not count(games) or not count(skills.get("first_agree")) or skills["first_agree"] > games:
        raise fail("skills needs games and first_agree (at most games)")
    opening = skills.get("opening")
    if opening is not None and (
        not isinstance(opening, dict)
        or not isinstance(opening.get("name"), str)
        or not count(opening.get("agree"))
        or opening["agree"] > games
    ):
        raise fail("skills.opening is {name, agree}")
    talents = skills.get("talents") or {}
    for tier, talent in talents.items() if isinstance(talents, dict) else []:
        if (
            str(tier) not in ("10", "15", "20", "25")
            or not isinstance(talent, dict)
            or not isinstance(talent.get("name"), str)
            or not talent.get("label")
            or not count(talent.get("picked"))
            or not count(talent.get("games"))
            or talent["picked"] > talent["games"]
        ):
            raise fail(f"skills.talents[{tier}] is {{name, label, picked, games}}")
        instead = talent.get("instead")
        if instead is not None and (
            not isinstance(instead, dict)
            or not isinstance(instead.get("name"), str)
            or not instead.get("label")
            or instead.get("enemy") not in groups()
            or not count(instead.get("min"))
            or not isinstance(instead.get("basis"), str)
            or not instead["basis"].strip()
        ):
            raise fail(f"skills.talents[{tier}].instead is {{name, label, enemy, min, basis}}")
    if not isinstance(skills.get("basis"), str) or not skills["basis"].strip():
        raise fail("skills needs a basis")


def plan_skills(
    plan: dict[str, Any] | None, enemies: list[str] | None = None
) -> dict[str, Any] | None:
    """The plan's skill build in skill_build.skill_order's shape (order,
    talents by hero level, opening, first_agree, games); None without one. A
    talent row's `instead` replaces the usual pick when `min` heroes of its
    enemy group are among `enemies` ({name, label, because: {count, enemies}})."""
    skills = (plan or {}).get("skills")
    if not skills:
        return None
    opening = skills.get("opening")
    known = groups()
    talents: dict[int, dict[str, Any]] = {}
    for tier, talent in (skills.get("talents") or {}).items():
        instead = talent.get("instead")
        seen = [e for e in enemies or [] if e in known[instead["enemy"]]] if instead else []
        if instead and len(seen) >= instead["min"]:
            talents[int(tier)] = {
                "name": instead["name"],
                "label": instead["label"],
                "because": {"group": instead["enemy"], "count": len(seen), "enemies": seen[:2]},
            }
        else:
            talents[int(tier)] = {
                k: v for k, v in talent.items() if k in ("name", "label", "picked", "games")
            }
    return {
        "order": list(skills["order"]),
        "games": skills["games"],
        "first_agree": skills["first_agree"],
        "opening": {**opening, "games": skills["games"]} if opening else None,
        "talents": talents,
    }
