"""
draft_analysis.py - the draft of one match, seen from the player's side.

Needs the enemy lineup, so only matches known to OpenDota (GSI in player mode
shows only your own hero). Works on cached OpenDota matchups
(/heroes/{id}/matchups: games and wins of a hero against every other hero):

- your hero against each enemy hero (win rate);
- which hero of your own pool fits this enemy lineup best (average edge over
  50 % against the enemies with enough games), among the heroes you play in
  the role of this match (a carry is not told to pick a support);
- counter items: a short curated list of well-known answers to enemy heroes
  (evasion, illusions, invisibility, healing), checked against the purchases.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from statistics import mean
from typing import Any

from app.dota_constants import hero_name
from app.hero_meta import item_key, item_name

# A matchup needs this many games before its win rate is used.
MIN_MATCHUP_GAMES = 20
# Pool hero with this many more points of edge than the pick -> advice.
BETTER_PICK_GAP = 3.0
MIN_ENEMIES_WITH_DATA = 3
# Counter-item advice only for games long enough to build it.
COUNTER_MIN_DURATION = 25 * 60

# OpenDota hero role tags that fit a role.
# Reviewed games in a role that count as the player's habit on a hero whose
# tags say otherwise (e.g. a mid Pudge).
HABIT_GAMES = 5
# Roles are review roles (core/offlane/support) or, with OpenDota's lineup,
# positions (carry/mid/offlane/support).
ROLE_TAGS: dict[str, set[str]] = {
    "core": {"Carry"},
    "carry": {"Carry"},
    "mid": {"Carry", "Nuker"},
    "offlane": {"Initiator", "Durable"},
    "support": {"Support"},
}

# Positions -> the review roles that COUNTERS name.
COUNTER_ROLE = {"carry": "core", "mid": "core"}

# reason -> (enemy heroes, counter items (OpenDota keys), roles that should buy them)
COUNTERS: dict[str, tuple[set[str], list[str], set[str]]] = {
    "evasion": (
        {"Phantom Assassin", "Windranger"},
        ["monkey_king_bar", "bloodthorn"],
        {"core", "offlane"},
    ),
    "illusions": (
        {"Phantom Lancer", "Naga Siren", "Terrorblade", "Chaos Knight", "Meepo"},
        ["maelstrom", "mjollnir", "bfury", "radiance"],
        {"core", "offlane"},
    ),
    "invisibility": (
        {
            "Riki",
            "Bounty Hunter",
            "Clinkz",
            "Weaver",
            "Nyx Assassin",
            "Mirana",
            "Templar Assassin",
            "Invoker",
        },
        ["dust", "ward_sentry", "gem"],
        {"support"},
    ),
    "healing": (
        # Heroes whose own healing wins fights; a healing support is in almost
        # every lineup and would ask for Spirit Vessel every game.
        {"Alchemist", "Necrophos", "Huskar", "Oracle", "Lifestealer"},
        ["spirit_vessel", "skadi"],
        {"core", "offlane", "support"},
    ),
}


# Enemy heroes whose single-target disable kills: Linken's Sphere blocks the
# spell (Primal Roar goes through BKB). Counted only when that hero killed the
# player TARGETED_KILLS times or more — a Lion in the lineup alone asks for no
# Linken's.
TARGETED_DISABLES = {
    "Beastmaster": "Primal Roar",
    "Doom": "Doom",
    "Legion Commander": "Duel",
    "Bane": "Fiend's Grip",
    "Batrider": "Flaming Lasso",
    "Pudge": "Dismember",
    "Lion": "Hex",
    "Shadow Shaman": "Hex",
    "Necrophos": "Reaper's Scythe",
    "Spirit Breaker": "Charge of Darkness",
    "Winter Wyvern": "Winter's Curse",
}
# Heroes who get away with a spell, which a silence (Bloodthorn, Orchid) stops
# (hero_items.py). Names from Valve's /herodata, patch 7.41f. Not here:
# Anti-Mage (Counterspell turns a targeted silence back) and Slark (Shadow
# Dance is no escape a silence answers).
ESCAPES = {
    "Queen of Pain": "Blink",
    "Storm Spirit": "Ball Lightning",
    "Puck": "Phase Shift",
    "Ember Spirit": "Fire Remnant",
    "Void Spirit": "Astral Step",
    "Weaver": "Shukuchi",
    "Mirana": "Leap",
    "Morphling": "Waveform",
    "Faceless Void": "Time Walk",
}
# Heroes who jump onto a carry: Hurricane Pike pushes them away and keeps the
# attacks going (hero_items.py). Not Legion Commander: Pike does not work in a
# Duel. Names from Valve's /herodata, patch 7.41f.
JUMPERS = {
    "Slark": "Pounce",
    "Phantom Assassin": "Phantom Strike",
    "Spirit Breaker": "Charge of Darkness",
}
# Heroes whose area damage or Hex clears illusions fast (hero_items.py: a
# Terrorblade's level-20 talent). From his 7.41 league games: with 2+ of them
# in the enemy lineup he takes +10 All Attributes in 44% of games, with none in
# 11%; heroes without area damage that read high there are left out.
ILLUSION_CLEARERS = {
    "Invoker",
    "Mars",
    "Disruptor",
    "Dawnbreaker",
    "Dark Seer",
    "Venomancer",
    "Lion",
    "Alchemist",
    "Lina",
    "Lich",
    "Luna",
    "Phoenix",
}
# Lineups (live advice only): heroes whose damage is mostly magic, and
# right-click carries. LINEUP_MIN of one kind among the enemies seen asks for
# the item against it (situational_items.py, the support's save item tip).
MAGIC_DAMAGE = {
    "Lina",
    "Lion",
    "Zeus",
    "Leshrac",
    "Skywrath Mage",
    "Queen of Pain",
    "Tinker",
    "Storm Spirit",
    "Puck",
    "Death Prophet",
    "Pugna",
    "Jakiro",
    "Crystal Maiden",
    "Witch Doctor",
    "Necrophos",
    "Invoker",
    "Nyx Assassin",
    "Earthshaker",
    "Sand King",
    "Outworld Destroyer",
    "Venomancer",
    "Viper",
    "Warlock",
    "Keeper of the Light",
    "Grimstroke",
    "Dark Willow",
    "Lich",
    "Disruptor",
    "Mirana",
    "Huskar",
    "Ember Spirit",
}
PHYSICAL_CARRIES = {
    "Phantom Assassin",
    "Juggernaut",
    "Sven",
    "Troll Warlord",
    "Ursa",
    "Faceless Void",
    "Slark",
    "Lifestealer",
    "Monkey King",
    "Anti-Mage",
    "Chaos Knight",
    "Drow Ranger",
    "Phantom Lancer",
    "Wraith King",
    "Templar Assassin",
    "Luna",
    "Medusa",
    "Terrorblade",
    "Clinkz",
    "Riki",
}
MAGIC_LINEUP_MIN = 3
PHYSICAL_LINEUP_MIN = 2

TARGETED_ITEM = "sphere"
TARGETED_NAME = "Linken's Sphere"
TARGETED_ROLES = {"core", "offlane"}
TARGETED_KILLS = 2


def _hero_id(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def pool_heroes(matches: list[dict[str, Any]], *, limit: int = 5, min_games: int = 3) -> list[int]:
    """Most played heroes of the player (hero ids)."""
    counts: dict[int, int] = {}
    for row in matches:
        if row.get("hero_id"):
            counts[int(row["hero_id"])] = counts.get(int(row["hero_id"]), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [hero for hero, games in ranked if games >= min_games][:limit]


def bought_items(facts: Mapping[str, Any], constants: dict[str, Any] | None) -> set[str] | None:
    """Item keys the player had: the purchase log of a parsed replay, else the
    final inventory (OpenDota gives item ids there). None when neither is known."""
    log = {item_key(entry.get("item")) for entry in facts.get("items_log") or []}
    if log:
        return log
    by_id = (constants or {}).get("by_id") or {}
    final = set()
    for raw in facts.get("final_items") or []:
        if isinstance(raw, bool):
            continue
        key = by_id.get(str(raw)) if isinstance(raw, int) or str(raw).isdigit() else item_key(raw)
        if key:
            final.add(key)
    return final or None


def fits_role(
    hero_id: int,
    role: str,
    played: dict[str, dict[str, int]] | None,
    tags: dict[str, list[str]] | None,
) -> bool:
    """Does the player play `hero_id` in `role`? The most common role of their
    reviewed games on the hero must match, and so must OpenDota's role tags
    (a Treant is not offered to a carry because a few games looked like farm),
    unless the player has a real habit: HABIT_GAMES games in that role. Without
    cached tags the games alone decide."""
    counts = (played or {}).get(str(hero_id)) or {}
    if counts and not _same_role(max(counts.items(), key=lambda kv: kv[1])[0], role):
        return False
    hero_tags = set((tags or {}).get(str(hero_id)) or [])
    if not hero_tags:  # no OpenDota tags cached: the player's games decide
        return bool(counts)
    if hero_tags & ROLE_TAGS.get(role, set()):
        return True
    return sum(n for key, n in counts.items() if _same_role(key, role)) >= HABIT_GAMES


def _same_role(a: str, b: str) -> bool:
    """Positions vs review roles: "core" (a review without the match lineup, or
    stored before positions) stands for carry or mid."""
    if a == b:
        return True
    return {a, b} in ({"core", "carry"}, {"core", "mid"})


def _winrate(matchups: dict[str, list[int]] | None, enemy_id: int) -> dict[str, Any] | None:
    games, wins = (matchups or {}).get(str(enemy_id), [0, 0])
    if games < MIN_MATCHUP_GAMES:
        return None
    return {"winrate": round(100 * wins / games, 1), "games": games}


def _edge(matchups: dict[str, list[int]] | None, enemy_ids: list[int]) -> float | None:
    rows = [_winrate(matchups, enemy) for enemy in enemy_ids]
    values = [row["winrate"] - 50 for row in rows if row]
    return round(mean(values), 1) if len(values) >= MIN_ENEMIES_WITH_DATA else None


def analyze_draft(
    facts: Mapping[str, Any],
    trimmed: dict[str, Any] | None,
    draft_meta: dict[str, Any] | None,
    role: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """-> (block for the review, findings). None without an enemy lineup."""
    findings: list[dict[str, Any]] = []
    if not trimmed:
        return None, findings
    players = trimmed.get("players") or []
    me = next((p for p in players if p.get("me")), None)
    if not me or not _hero_id(me.get("hero_id")):
        return None, findings
    my_side = bool(me.get("isRadiant", True))
    enemies = [
        p
        for p in players
        if bool(p.get("isRadiant", True)) != my_side and _hero_id(p.get("hero_id"))
    ]
    if not enemies:
        return None, findings
    enemy_ids = [_hero_id(p["hero_id"]) for p in enemies]
    my_id = _hero_id(me["hero_id"])
    meta = draft_meta or {}
    matchups = meta.get("matchups") or {}
    constants = meta.get("constants")

    enemy_rows = []
    for player in enemies:
        row = {"hero": player.get("hero"), "hero_id": int(player["hero_id"])}
        wr = _winrate(matchups.get(str(my_id)), int(player["hero_id"]))
        if wr:
            row.update(wr)
        enemy_rows.append(row)

    candidates = [
        hero
        for hero in meta.get("pool") or []
        if fits_role(hero, role, meta.get("pool_roles"), meta.get("hero_roles"))
    ]
    pool = []
    for hero_id in dict.fromkeys([my_id, *candidates]):
        edge = _edge(matchups.get(str(hero_id)), enemy_ids)
        if edge is not None:
            pool.append(
                {
                    "hero_id": hero_id,
                    "hero": hero_name(hero_id),
                    "edge": edge,
                    "picked": hero_id == my_id,
                }
            )
    pool.sort(key=lambda row: -row["edge"])
    mine = next((row for row in pool if row["picked"]), None)
    best = pool[0] if pool else None
    if mine and best and not best["picked"] and best["edge"] - mine["edge"] >= BETTER_PICK_GAP:
        findings.append(
            _finding(
                "draft_better_pick",
                "improve",
                severity=1,
                weight=(best["edge"] - mine["edge"]) / 2,
                hero=me.get("hero"),
                best=best["hero"],
                best_edge=best["edge"],
                edge=mine["edge"],
            )
        )

    # Without a purchase log or an inventory nothing is known about the items:
    # the counters are still shown, but no "missing" advice.
    known = bought_items(facts, constants)
    bought = known or set()
    counters = []
    long_game = (facts.get("duration") or 0) >= COUNTER_MIN_DURATION
    counter_role = COUNTER_ROLE.get(role, role)
    for reason, (heroes, items, roles) in COUNTERS.items():
        threats = [p.get("hero") for p in enemies if p.get("hero") in heroes]
        if not threats:
            continue
        has = [key for key in items if key in bought]
        names = [item_name(key, constants) for key in items]
        counters.append(
            {
                "reason": reason,
                "heroes": threats,
                "items": names,
                "bought": [item_name(key, constants) for key in has],
                "for_role": counter_role in roles,
            }
        )
        if counter_role not in roles or not long_game or known is None:
            continue
        params = {"reason": reason, "enemy": ", ".join(threats), "items": ", ".join(names)}
        if has:
            findings.append(
                _finding(
                    "counter_item_bought",
                    "strength",
                    weight=0.7,
                    item=item_name(has[0], constants),
                    **params,
                )
            )
        else:
            findings.append(
                _finding("counter_item_missing", "improve", severity=2, weight=2.2, **params)
            )

    # A single-target disable that killed the player: Linken's Sphere.
    killers = Counter(d.get("killer") for d in facts.get("deaths_log") or [] if isinstance(d, dict))
    targeted = sorted(
        (
            (killers.get(p.get("hero"), 0), p.get("hero"))
            for p in enemies
            if p.get("hero") in TARGETED_DISABLES
        ),
        reverse=True,
    )
    if targeted and targeted[0][0] >= TARGETED_KILLS:
        kills, enemy = targeted[0]
        spell = TARGETED_DISABLES[enemy]
        known_items = (constants or {}).get("items") or {}
        # The key alone reads «Sphere» when the item constants are not cached.
        name = (
            item_name(TARGETED_ITEM, constants) if TARGETED_ITEM in known_items else TARGETED_NAME
        )
        has = TARGETED_ITEM in bought
        counters.append(
            {
                "reason": "targeted",
                "heroes": [enemy],
                "items": [name],
                "bought": [name] if has else [],
                "for_role": counter_role in TARGETED_ROLES,
                "spell": spell,
                "kills": kills,
            }
        )
        if counter_role in TARGETED_ROLES and long_game and known is not None:
            params = {"reason": "targeted", "enemy": enemy, "items": name, "spell": spell}
            if has:
                findings.append(
                    _finding("counter_item_bought", "strength", weight=0.7, item=name, **params)
                )
            else:
                findings.append(
                    _finding("counter_item_missing", "improve", severity=2, weight=2.4, **params)
                )

    block = {
        "hero": me.get("hero"),
        "enemies": enemy_rows,
        "pool": pool,
        "counters": counters,
        "has_matchups": any("winrate" in row for row in enemy_rows),
        "better_pick": best["hero"]
        if mine and best and not best["picked"] and best["edge"] - mine["edge"] >= BETTER_PICK_GAP
        else None,
    }
    return block, findings


def _finding(
    finding_id: str, kind: str, *, severity: int = 1, weight: float = 1.0, **params: Any
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "kind": kind,
        "section": "draft",
        "severity": severity,
        "weight": weight,
        "params": params,
    }
