"""
lane_duel.py - the lane minute by minute against the enemy who stood in it.

Parsed replays only: OpenDota gives every player's lane (`lane`: the physical
lane, the same number for both teams) and the per-minute series (last hits,
denies, gold, XP). trim_match keeps the first LANE_MINUTES + 1 values of each
for every player (`lane_t`) and the whole series for the reviewed one.

The opponent is the enemy core of the player's lane (the most last hits at
10:00 among the enemies who were not roaming); the lane total adds up the
gold of both teams' heroes in that lane, so a support's lane has a result too.
A core's lane is won or lost by the gold difference at 10:00 (GOLD_MARGIN);
the findings `lane_lost` / `lane_won` are for cores only, a support's lane is
shown, not judged.
"""

from __future__ import annotations

from typing import Any

LANE_MINUTES = 10
POINTS = (3, 5, 7, 10)
GOLD_MARGIN = 800
TURN_GAP = 300
LANES = {1, 2, 3}
CORE_POSITIONS = {"carry", "mid", "offlane"}
SERIES = ("lh", "dn", "gold", "xp")


def lane_series(player: dict[str, Any], key: str) -> list[int]:
    """The first LANE_MINUTES + 1 values of a per-minute series: the reviewed
    player's full `<key>_t`, anyone else's `lane_t`."""
    lane = player.get("lane_t") if isinstance(player.get("lane_t"), dict) else {}
    values = player.get(f"{key}_t") if player.get("me") else lane.get(key)
    if not isinstance(values, list):
        return []
    clean: list[int] = []
    for value in values[: LANE_MINUTES + 1]:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            break
        clean.append(int(value))
    return clean


def lane_snapshot(player: dict[str, Any]) -> dict[str, list[int]] | None:
    """{lh, dn, gold, xp} for trim_match (every player but the reviewed one)."""
    out = {}
    for key in SERIES:
        values = player.get(f"{key}_t")
        if isinstance(values, list) and len(values) > LANE_MINUTES:
            out[key] = [v for v in values[: LANE_MINUTES + 1] if isinstance(v, (int, float))]
    return out if len(out) == len(SERIES) else None


def _at(series: list[int], minute: int) -> int | None:
    return series[minute] if len(series) > minute else None


def _in_lane(player: dict[str, Any], lane: int) -> bool:
    return player.get("lane") == lane and not player.get("is_roaming")


def public_matchup(
    block: dict[str, Any],
    position: str | None,
    files: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """How this lane usually goes in public league games (lane_matchup.py): the
    player's hero in `position` against the lane's enemy core. Context only: the
    result and findings never read it. None for a support, an unknown hero or a
    pair without a public row."""
    from app.lane_matchup import MIN_LANES, matchup

    if position not in CORE_POSITIONS:
        return None
    hero = block.get("hero_id") if block.get("hero_id") is not None else block.get("hero")
    enemy = block.get("enemy_id") if block.get("enemy_id") is not None else block.get("enemy")
    row = matchup(hero, position, enemy, files)
    if row is None or row["lanes"] < MIN_LANES:
        return None
    return {
        "enemy": row["hero"],
        "lanes": row["lanes"],
        "won": row["won"],
        "even": row["even"],
        "lost": row["lost"],
        "kind": row["kind"],
        "baseline_lost": row["baseline_lost"],
        "baseline_won": row["baseline_won"],
    }


def analyze_lane(
    opendota: dict[str, Any] | None,
    position: str | None,
    files: dict[int, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(block, findings): block = {lane, hero, enemy, points [{minute, lh, enemy_lh,
    dn, enemy_dn, gold_diff, xp_diff}], gold_diff, xp_diff, total_diff, result
    (won/even/lost), turn (the minute the gold gap opened and stayed), judged,
    matchup (only for a judged core lane with a public row: see public_matchup)};
    None without a parsed lane."""
    if not opendota or not opendota.get("parsed"):
        return None, []
    players = [p for p in opendota.get("players") or [] if isinstance(p, dict)]
    me = next((p for p in players if p.get("me")), None)
    if me is None or me.get("lane") not in LANES or me.get("is_roaming"):
        return None, []
    lane = me["lane"]
    side = bool(me.get("isRadiant", True))
    mine = {key: lane_series(me, key) for key in SERIES}
    if len(mine["gold"]) <= LANE_MINUTES:
        return None, []
    enemies = [
        p
        for p in players
        if bool(p.get("isRadiant", True)) != side
        and _in_lane(p, lane)
        and len(lane_series(p, "gold")) > LANE_MINUTES
    ]
    if not enemies:
        return None, []
    enemy = max(enemies, key=lambda p: _at(lane_series(p, "lh"), LANE_MINUTES) or 0)
    theirs = {key: lane_series(enemy, key) for key in SERIES}
    points = []
    for minute in POINTS:
        gold, enemy_gold = _at(mine["gold"], minute), _at(theirs["gold"], minute)
        xp, enemy_xp = _at(mine["xp"], minute), _at(theirs["xp"], minute)
        points.append(
            {
                "minute": minute,
                "lh": _at(mine["lh"], minute),
                "enemy_lh": _at(theirs["lh"], minute),
                "dn": _at(mine["dn"], minute),
                "enemy_dn": _at(theirs["dn"], minute),
                "gold_diff": gold - enemy_gold
                if gold is not None and enemy_gold is not None
                else None,
                "xp_diff": xp - enemy_xp if xp is not None and enemy_xp is not None else None,
            }
        )
    gold_diff = mine["gold"][LANE_MINUTES] - theirs["gold"][LANE_MINUTES]
    xp = _at(mine["xp"], LANE_MINUTES)
    enemy_xp = _at(theirs["xp"], LANE_MINUTES)
    allies = [
        p
        for p in players
        if bool(p.get("isRadiant", True)) == side
        and _in_lane(p, lane)
        and len(lane_series(p, "gold")) > LANE_MINUTES
    ]
    total_diff = sum(lane_series(p, "gold")[LANE_MINUTES] for p in allies) - sum(
        lane_series(p, "gold")[LANE_MINUTES] for p in enemies
    )
    result = "won" if gold_diff >= GOLD_MARGIN else "lost" if gold_diff <= -GOLD_MARGIN else "even"
    block = {
        "lane": lane,
        "hero": me.get("hero"),
        "hero_id": me.get("hero_id"),
        "enemy": enemy.get("hero"),
        "enemy_id": enemy.get("hero_id"),
        "allies": [p.get("hero") for p in allies if not p.get("me")],
        "enemies": [p.get("hero") for p in enemies],
        "points": points,
        "gold_diff": gold_diff,
        "xp_diff": xp - enemy_xp if xp is not None and enemy_xp is not None else None,
        "total_diff": total_diff,
        "result": result,
        "turn": _turn(mine["gold"], theirs["gold"], result),
        "judged": position in CORE_POSITIONS,
    }
    matchup = public_matchup(block, position, files)
    if matchup is not None:
        block["matchup"] = matchup
    findings: list[dict[str, Any]] = []
    last = points[-1]
    if block["judged"] and result != "even" and last["lh"] is not None:
        findings.append(
            {
                "id": "lane_lost" if result == "lost" else "lane_won",
                "kind": "improve" if result == "lost" else "strength",
                "section": "laning",
                "severity": 2,
                "weight": 1.3,
                "params": {
                    "hero": enemy.get("hero"),
                    "gold": abs(gold_diff),
                    "lh_mine": last["lh"],
                    "lh_theirs": last["enemy_lh"],
                    "turn": block["turn"],
                },
            }
        )
    return block, findings


def _turn(mine: list[int], theirs: list[int], result: str) -> int | None:
    """The first minute from which the gold gap stayed TURN_GAP+ on the side the
    lane ended on (None for an even lane)."""
    if result == "even":
        return None
    sign = 1 if result == "won" else -1
    turn = None
    for minute in range(1, LANE_MINUTES + 1):
        if (mine[minute] - theirs[minute]) * sign >= TURN_GAP:
            turn = minute if turn is None else turn
        else:
            turn = None
    return turn


CAREER_MATCHES = 20
CAREER_MIN = 3
HARD_ENEMY_LOSSES = 2


def career_lanes(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The lanes of the last CAREER_MATCHES analysed matches with a judged lane
    (`matches` newest first): {games, won, even, lost, gold_diff (the average at
    10:00), games_list (oldest first: hero, enemy, result, gold_diff,
    match_id), hard (enemy cores the lane was lost to HARD_ENEMY_LOSSES+
    times)}; None under CAREER_MIN lanes."""
    rows = []
    for match in matches:
        lane = (match.get("analysis") or {}).get("lane")
        if not isinstance(lane, dict) or not lane.get("judged"):
            continue
        if lane.get("result") not in ("won", "even", "lost"):
            continue
        rows.append((match, lane))
        if len(rows) >= CAREER_MATCHES:
            break
    if len(rows) < CAREER_MIN:
        return None
    counts = {
        result: sum(1 for _, lane in rows if lane["result"] == result)
        for result in ("won", "even", "lost")
    }
    diffs = [lane["gold_diff"] for _, lane in rows if isinstance(lane.get("gold_diff"), int)]
    lost_to: dict[str, int] = {}
    for _, lane in rows:
        if lane["result"] == "lost" and lane.get("enemy"):
            lost_to[lane["enemy"]] = lost_to.get(lane["enemy"], 0) + 1
    hard = sorted(
        ({"hero": hero, "lost": n} for hero, n in lost_to.items() if n >= HARD_ENEMY_LOSSES),
        key=lambda row: (-row["lost"], row["hero"]),
    )[:3]
    return {
        "games": len(rows),
        **counts,
        "gold_diff": round(sum(diffs) / len(diffs)) if diffs else None,
        "games_list": [
            {
                "match_id": match.get("match_id"),
                "hero": lane.get("hero"),
                "hero_id": lane.get("hero_id"),
                "enemy": lane.get("enemy"),
                "result": lane["result"],
                "gold_diff": lane.get("gold_diff"),
            }
            for match, lane in reversed(rows)
        ],
        "hard": hard,
    }


RECORD_MIN_GAMES = 2
# The live «behind their pace» tip compares last hits at these minutes with the
# opponent's average in the player's past lanes against them.
PACE_MINUTES = (5, 7)


def lane_records(matches: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """{enemy core: {won, even, lost, games}} over the judged lanes of the
    analysed `matches` (any hero of the player's), for the live «hard lane» tip;
    with the enemy's last hits at PACE_MINUTES summed over `pace_games` lanes
    (`enemy_lh_<minute>`) when the reviews have the minute points."""
    records: dict[str, dict[str, int]] = {}
    for match in matches:
        lane = (match.get("analysis") or {}).get("lane")
        if not isinstance(lane, dict) or not lane.get("judged"):
            continue
        enemy, result = lane.get("enemy"), lane.get("result")
        if not isinstance(enemy, str) or result not in ("won", "even", "lost"):
            continue
        row = records.setdefault(enemy, {"won": 0, "even": 0, "lost": 0, "games": 0})
        row[result] += 1
        row["games"] += 1
        pace = _enemy_pace(lane.get("points"))
        if pace is not None:
            row["pace_games"] = row.get("pace_games", 0) + 1
            for minute, value in pace.items():
                row[f"enemy_lh_{minute}"] = row.get(f"enemy_lh_{minute}", 0) + value
    return records


def _enemy_pace(points: Any) -> dict[int, int] | None:
    """The enemy's last hits at each of PACE_MINUTES, None when one is missing."""
    if not isinstance(points, list):
        return None
    by_minute = {
        point.get("minute"): point.get("enemy_lh") for point in points if isinstance(point, dict)
    }
    pace = {}
    for minute in PACE_MINUTES:
        value = by_minute.get(minute)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        pace[minute] = value
    return pace


def lane_record_for(
    opponents: list[str], records: dict[str, dict[str, int]]
) -> dict[str, Any] | None:
    """The first lane opponent with a clear past record against them
    (RECORD_MIN_GAMES+ lanes lost, or won, and more of those than the other):
    {hero, kind (hard | easy), won, even, lost, games}, plus `pace` (lane_pace_for)
    when known; kind None when only the pace is; None without either."""
    record: dict[str, Any] | None = None
    for hero in opponents:
        row = records.get(hero)
        if not row:
            continue
        counts = {key: row[key] for key in ("won", "even", "lost", "games")}
        if row["lost"] >= RECORD_MIN_GAMES and row["lost"] > row["won"]:
            record = {"hero": hero, "kind": "hard", **counts}
            break
        if row["won"] >= RECORD_MIN_GAMES and row["won"] > row["lost"]:
            record = {"hero": hero, "kind": "easy", **counts}
            break
    pace = lane_pace_for(opponents, records)
    if pace is None:
        return record
    return {**(record or {"hero": pace["hero"], "kind": None}), "pace": pace}


def lane_pace_for(
    opponents: list[str], records: dict[str, dict[str, int]]
) -> dict[str, Any] | None:
    """The first lane opponent met in RECORD_MIN_GAMES+ reviewed lanes with the
    minute points: {hero, games, lh: {minute: their average last hits}}."""
    for hero in opponents:
        row = records.get(hero) or {}
        games = row.get("pace_games", 0)
        if games >= RECORD_MIN_GAMES:
            lh = {minute: round(row[f"enemy_lh_{minute}"] / games) for minute in PACE_MINUTES}
            return {"hero": hero, "games": games, "lh": lh}
    return None
