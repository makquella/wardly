"""Synthetic but schema-faithful OpenDota matches and live GSI match streams.

The field names follow OpenDota's /api/matches/{id} and
/api/players/{id}/matches responses; values are generated so tests can shape
a "good" or "bad" game on purpose.
"""

from __future__ import annotations

import copy
from typing import Any

ME = 52079950
ME_STEAM64 = str(76561197960265728 + ME)
MATCH_ID = 8012345678

# (hero_id, npc name, radiant?)
LINEUP = [
    (8, "npc_dota_hero_juggernaut", True),
    (74, "npc_dota_hero_invoker", True),
    (129, "npc_dota_hero_mars", True),
    (26, "npc_dota_hero_lion", True),
    (5, "npc_dota_hero_crystal_maiden", True),
    (1, "npc_dota_hero_antimage", False),
    (11, "npc_dota_hero_nevermore", False),
    (2, "npc_dota_hero_axe", False),
    (86, "npc_dota_hero_rubick", False),
    (30, "npc_dota_hero_witch_doctor", False),
]


# OpenDota lane_role per LINEUP index (1 safe, 2 mid, 3 off); supports place wards.
LANE_ROLES = [1, 2, 3, 3, 1, 1, 2, 3, 3, 1]
SUPPORTS = {3, 4, 8, 9}
ENEMY_CARRY = 5


def _curve(per_minute: float, minutes: int, *, stall: tuple[int, int] | None = None) -> list[int]:
    values, total = [], 0.0
    for minute in range(minutes + 1):
        values.append(int(total))
        slow = stall and stall[0] <= minute < stall[1]
        total += 0.5 if slow else per_minute
    return values


def opendota_match(
    *,
    good: bool = True,
    parsed: bool = True,
    duration: int = 38 * 60,
    match_id: int = MATCH_ID,
    my_deaths: list[int] | None = None,
) -> dict[str, Any]:
    minutes = duration // 60
    my_deaths = (
        my_deaths
        if my_deaths is not None
        else ([900, 1700] if good else [240, 420, 1300, 1420, 1500, 2000, 2100, 2200, 2250])
    )
    players = []
    for index, (hero_id, _npc, radiant) in enumerate(LINEUP):
        slot = index if radiant else 128 + index - 5
        me = index == 0
        player: dict[str, Any] = {
            "account_id": ME if me else 100000 + index,
            "player_slot": slot,
            "hero_id": hero_id,
            "personaname": "Me" if me else f"Player {index}",
            "isRadiant": radiant,
            "win": 1 if radiant == good else 0,
            "kills": (11 if good else 3) if me else 4,
            "deaths": len(my_deaths) if me else 5,
            "assists": (14 if good else 6) if me else 8,
            "last_hits": (330 if good else 160)
            if me
            else (40 if index in SUPPORTS else 250 if index == ENEMY_CARRY else 150),
            "denies": (14 if good else 3) if me else 4,
            "gold_per_min": (690 if good else 390)
            if me
            else (600 if index == ENEMY_CARRY else 450),
            "xp_per_min": (720 if good else 430) if me else 500,
            "net_worth": (26000 if good else 11500) if me else 14000,
            "level": 25 if me else 20,
            "hero_damage": (32000 if good else 9000) if me else 15000,
            "tower_damage": (6000 if good else 300) if me else 1000,
            "hero_healing": 0,
            "lane_role": LANE_ROLES[index],
            "rank_tier": 54 if radiant else 55,
            "is_roaming": False,
            "item_0": "bfury" if good else "phase_boots",
            "benchmarks": {
                "gold_per_min": {"raw": 690 if good else 390, "pct": 0.86 if good else 0.12},
                "xp_per_min": {"raw": 720, "pct": 0.8 if good else 0.2},
                "last_hits_per_min": {"raw": 8.6, "pct": 0.83 if good else 0.1},
                "hero_damage_per_min": {"raw": 840, "pct": 0.8 if good else 0.15},
                "tower_damage": {"raw": 6000, "pct": 0.81 if good else 0.1},
            },
        }
        if parsed:
            rate = (
                (7.0 if good else 3.6)
                if me
                else (6.5 if index == ENEMY_CARRY else 1.0 if index in SUPPORTS else 4.0)
            )
            stall = None if good or not me else (15, 22)
            player.update(
                {
                    "times": [m * 60 for m in range(minutes + 1)],
                    "lh_t": _curve(rate, minutes, stall=stall),
                    "dn_t": _curve(1.5 if (me and good) else 0.3, minutes),
                    "gold_t": _curve(690 if (me and good) else 400, minutes),
                    "xp_t": _curve(720, minutes),
                    "lane_efficiency_pct": (82 if good else 38) if me else 60,
                    "teamfight_participation": 0.7 if good else 0.35,
                    "obs_placed": 12 if index in SUPPORTS else 0,
                    "sen_placed": 6 if index in SUPPORTS else 0,
                    "camps_stacked": 1,
                    "life_state_dead": len(my_deaths) * 40 if me else 150,
                    "purchase_log": (
                        [
                            {"time": -80, "key": "tango"},
                            {"time": 300, "key": "power_treads"},
                            {"time": 720, "key": "bfury"},
                            {"time": 1150, "key": "manta"},
                            {"time": 1500, "key": "black_king_bar"},
                        ]
                        if good
                        else [
                            {"time": -80, "key": "tango"},
                            {"time": 600, "key": "phase_boots"},
                            {"time": 1560, "key": "maelstrom"},
                        ]
                    )
                    if me
                    else [],
                    "kills_log": [],
                    "buyback_log": [],
                    "killed_by": {} if me else {},
                }
            )
        players.append(player)
    if parsed:
        # Our deaths: the enemy mid (Shadow Fiend) takes most of them.
        me_npc = LINEUP[0][1]
        for n, t in enumerate(my_deaths):
            killer = players[6] if n % 3 != 2 else players[7]
            killer["kills_log"].append({"time": t, "key": me_npc})
        players[0]["killed_by"] = {
            "npc_dota_hero_nevermore": sum(1 for n in range(len(my_deaths)) if n % 3 != 2),
            "npc_dota_hero_axe": sum(1 for n in range(len(my_deaths)) if n % 3 == 2),
        }
    return {
        "match_id": match_id,
        "start_time": 1790000000,
        "duration": duration,
        "radiant_win": good,
        "radiant_score": 38 if good else 20,
        "dire_score": 20 if good else 41,
        "game_mode": 22,
        "lobby_type": 7,
        "version": 21 if parsed else None,
        "patch": 58,
        "region": 3,
        "first_blood_time": 95,
        "players": players,
    }


def recent_matches(count: int = 15, *, start_match_id: int = MATCH_ID) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        good = index % 3 != 0
        rows.append(
            {
                "match_id": start_match_id - index,
                "player_slot": 0,
                "radiant_win": good,
                "duration": 2100 + index * 30,
                "game_mode": 22,
                "lobby_type": 7,
                "hero_id": 8 if index % 2 == 0 else 1,
                "start_time": 1790000000 - index * 4000,
                "version": 21 if index < 5 else None,
                "kills": 9 if good else 2,
                "deaths": 3 if good else 9,
                "assists": 10,
                "gold_per_min": 640 if good else 380,
                "xp_per_min": 690,
                "last_hits": 300 if good else 150,
                "denies": 10,
                "hero_damage": 25000,
                "lane_role": 1,
                "leaver_status": 0,
            }
        )
    return rows


# /constants/items shape (subset): key -> {id, dname, cost, components}.
RAW_ITEM_CONSTANTS = {
    "tango": {"id": 44, "dname": "Tango", "cost": 90, "components": None},
    "ward_observer": {"id": 42, "dname": "Observer Ward", "cost": 0, "components": None},
    "demon_edge": {"id": 51, "dname": "Demon Edge", "cost": 2200, "components": None},
    "power_treads": {"id": 63, "dname": "Power Treads", "cost": 1400, "components": ["boots"]},
    "phase_boots": {"id": 50, "dname": "Phase Boots", "cost": 1500, "components": ["boots"]},
    "bfury": {"id": 145, "dname": "Battle Fury", "cost": 4100, "components": ["quelling_blade"]},
    "manta": {"id": 147, "dname": "Manta Style", "cost": 4650, "components": ["yasha"]},
    "black_king_bar": {
        "id": 116,
        "dname": "Black King Bar",
        "cost": 4050,
        "components": ["ogre_axe"],
    },
    "maelstrom": {"id": 166, "dname": "Maelstrom", "cost": 2950, "components": ["javelin"]},
    "butterfly": {"id": 139, "dname": "Butterfly", "cost": 5450, "components": ["eagle"]},
    "abyssal_blade": {"id": 208, "dname": "Abyssal Blade", "cost": 6250, "components": ["basher"]},
}

# /heroes/8/itemPopularity shape: {phase: {item_id: count}}.
JUGG_POPULARITY = {
    "start_game_items": {"44": 900},
    "early_game_items": {"63": 500, "50": 300, "44": 200},
    "mid_game_items": {"145": 700, "147": 520, "116": 480, "166": 150, "51": 90},
    "late_game_items": {"139": 400, "208": 300},
}

# /scenarios/itemTimings shape (hero 8): win rate falls with later purchases.
JUGG_TIMINGS = [
    {"hero_id": 8, "item": item, "time": time, "games": str(games), "wins": str(round(games * wr))}
    for item, rows in {
        "bfury": [
            (600, 300, 0.60),
            (900, 900, 0.57),
            (1200, 900, 0.52),
            (1500, 600, 0.47),
            (1800, 300, 0.42),
            (2100, 120, 0.38),
        ],
        "manta": [
            (900, 200, 0.58),
            (1200, 700, 0.55),
            (1500, 800, 0.50),
            (1800, 400, 0.45),
            (2400, 150, 0.40),
        ],
        "black_king_bar": [
            (1200, 300, 0.56),
            (1500, 600, 0.52),
            (1800, 500, 0.48),
            (2400, 200, 0.43),
        ],
        "maelstrom": [
            (900, 300, 0.55),
            (1200, 500, 0.50),
            (1500, 300, 0.45),
            (1800, 150, 0.40),
            (2100, 40, 0.35),
        ],
    }.items()
    for time, games, wr in rows
]


# /heroStats shape (subset): picks/wins per bracket.
def _hero_stats_row(hero_id: int, picks: int, base_wins: int, step: int) -> dict[str, Any]:
    row: dict[str, Any] = {"id": hero_id}
    for bracket in range(1, 9):
        row[f"{bracket}_pick"] = picks
        row[f"{bracket}_win"] = base_wins + step * bracket
    return row


RAW_HERO_STATS = [_hero_stats_row(8, 10000, 5000, 30), _hero_stats_row(1, 8000, 3800, 20)]


# /heroes/{id}/matchups shape: games and wins of the hero against each enemy.
def _matchups(winrates: dict[int, float], games: int = 400) -> list[dict[str, Any]]:
    return [
        {"hero_id": hero_id, "games_played": games, "wins": round(games * wr)}
        for hero_id, wr in winrates.items()
    ]


# Juggernaut is slightly behind the default enemy five (Anti-Mage, Shadow Fiend,
# Axe, Rubick, Witch Doctor); Anti-Mage (the player's other hero) is ahead.
RAW_MATCHUPS = {
    8: _matchups({1: 0.45, 11: 0.47, 2: 0.49, 86: 0.50, 30: 0.52, 44: 0.46}),
    1: _matchups({11: 0.55, 2: 0.53, 86: 0.52, 30: 0.56, 44: 0.50}),
}


class FakeOpenDota:
    """Stands in for OpenDotaClient in tests (same methods, no network)."""

    def __init__(
        self,
        matches: dict[int, dict[str, Any]] | None = None,
        recent: list[dict[str, Any]] | None = None,
    ):
        from app.opendota import summary_from_recent

        self.matches = matches or {}
        self.recent = recent or []
        self._summary = summary_from_recent
        self.parse_requests: list[int] = []
        self.calls: list[str] = []
        self.skill_orders: dict[int, dict[str, Any]] = {}

    def player(self, account_id: int) -> dict[str, Any]:
        self.calls.append(f"player:{account_id}")
        return {
            "account_id": account_id,
            "persona_name": "Me",
            "avatar_url": None,
            "steam_id64": ME_STEAM64,
            "rank_tier": 54,
        }

    def recent_matches(self, account_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        self.calls.append(f"recent:{account_id}")
        return [self._summary(row) for row in self.recent[:limit]]

    def match(self, match_id: int) -> dict[str, Any]:
        from app.opendota import OpenDotaError

        self.calls.append(f"match:{match_id}")
        if match_id not in self.matches:
            raise OpenDotaError("not_found", "no such match")
        return copy.deepcopy(self.matches[match_id])

    def request_parse(self, match_id: int) -> None:
        self.parse_requests.append(match_id)

    # Meta endpoints: parsed by the real client from the raw shapes above.
    def _real(self, raw: Any) -> Any:
        from app.opendota import OpenDotaClient

        return OpenDotaClient(session=_StaticSession(raw), min_interval=0)

    def item_constants(self) -> dict[str, Any]:
        self.calls.append("items")
        return self._real(RAW_ITEM_CONSTANTS).item_constants()

    def pro_skill_orders(self, hero_id: int) -> dict[str, Any]:
        # Not in `calls`: tests count the other requests. No pro games by default.
        return copy.deepcopy(
            self.skill_orders.get(hero_id) or {"orders": [], "names": {}, "ids": {}}
        )

    def item_popularity(self, hero_id: int) -> dict[str, dict[str, int]]:
        self.calls.append(f"popularity:{hero_id}")
        return self._real(JUGG_POPULARITY if hero_id == 8 else {}).item_popularity(hero_id)

    def item_timings(self, hero_id: int) -> list[dict[str, Any]]:
        self.calls.append(f"timings:{hero_id}")
        return self._real(JUGG_TIMINGS if hero_id == 8 else []).item_timings(hero_id)

    def hero_matchups(self, hero_id: int) -> dict[str, list[int]]:
        self.calls.append(f"matchups:{hero_id}")
        return self._real(RAW_MATCHUPS.get(hero_id, [])).hero_matchups(hero_id)

    def hero_stats(self) -> list[dict[str, Any]]:
        self.calls.append("herostats")
        return self._real(RAW_HERO_STATS).hero_stats()


class _StaticSession:
    """requests.Session stand-in: every request returns the same JSON body."""

    def __init__(self, body: Any):
        self.body = body

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        body = self.body

        class _Response:
            status_code = 200

            def json(self) -> Any:
                return copy.deepcopy(body)

        return _Response()


def _world_position(t: int) -> tuple[int, int]:
    if t < 10 * 60:
        return 2000 + (t % 120) * 10, -6300
    if 17 * 60 <= t < 21 * 60:
        return 3600, 3200
    return -2500, -4000


def gsi_match_stream(
    *,
    match_id: int = MATCH_ID,
    minutes: int = 32,
    lh_per_minute: float = 6.0,
    death_minutes: tuple[int, ...] = (7, 18, 19, 20),
    win: bool = True,
    step_seconds: int = 5,
    positions: bool = False,
) -> list[dict[str, Any]]:
    """Raw GSI payloads for a whole match of Juggernaut on Radiant.

    positions=True adds hero world coordinates: the bottom lane until 10:00,
    the Dire jungle from 17:00 to 21:00 (the late deaths), Radiant jungle
    otherwise; and the minimap block Wardly's GSI config always requests,
    showing no other hero (the player is alone: no ally next to them)."""
    payloads = []
    deaths = 0
    items = {"slot0": {"name": "item_tango"}}
    item_plan = {5 * 60: "item_power_treads", 13 * 60: "item_bfury", 21 * 60: "item_manta"}
    for t in range(-60, minutes * 60 + 1, step_seconds):
        minute = max(0, t) / 60
        if t > 0 and int(t / 60) in death_minutes and t % 60 == 0:
            deaths += 1
        for at, item in item_plan.items():
            if t >= at and item not in [v["name"] for v in items.values()]:
                items[f"slot{len(items)}"] = {"name": item}
        dead = any(t > 0 and m * 60 <= t < m * 60 + 20 for m in death_minutes)
        payloads.append(
            {
                "provider": {"name": "Dota 2", "appid": 570},
                "map": {
                    "matchid": str(match_id),
                    "clock_time": t,
                    "game_time": t + 90,
                    "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
                    "radiant_score": int(minute * 1.1),
                    "dire_score": int(minute * 0.8),
                },
                "player": {
                    "steamid": ME_STEAM64,
                    "accountid": str(ME),
                    "name": "Me",
                    "team_name": "radiant",
                    "kills": int(minute / 4),
                    "deaths": deaths,
                    "assists": int(minute / 3),
                    "last_hits": int(minute * lh_per_minute),
                    "denies": int(minute),
                    "gold": 1800 if dead else 400,
                    "gpm": int(300 + minute * 12),
                    "xpm": int(350 + minute * 12),
                },
                "hero": {
                    "name": "npc_dota_hero_juggernaut",
                    "level": min(30, 1 + int(minute / 1.5)),
                    "health_percent": 0 if dead else 80,
                    "alive": not dead,
                    "respawn_seconds": 20 if dead else 0,
                    "buyback_cooldown": 0,
                },
                "items": copy.deepcopy(items),
            }
        )
        if positions:
            x, y = _world_position(t)
            payloads[-1]["hero"].update({"xpos": x, "ypos": y})
            payloads[-1]["minimap"] = {}
    final = copy.deepcopy(payloads[-1])
    final["map"]["game_state"] = "DOTA_GAMERULES_STATE_POST_GAME"
    final["map"]["win_team"] = "radiant" if win else "dire"
    payloads.append(final)
    return payloads
