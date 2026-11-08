"""
post_match_analysis.py - deterministic post-match review of one player.

Input: MatchFacts (match_facts.py). Output: a language-neutral review:

- headline: hero, result, K/D/A, duration, overall score 0-100 and grade;
- sections (laning, farm, survival, fights, items, vision): a 0-100 score and
  the key numbers behind it;
- findings: strengths and things to improve, each with an id, severity and
  the numbers that prove it (texts come from analysis_texts.py, uk/en);
- series for charts (last hits vs target, gold earned, XP per minute) and a
  timeline of key moments (deaths, big items, buybacks, farm stalls).

Rules only use what the sources really report; a section without data is
left out instead of guessed. OpenDota benchmarks (percentile against other
players of the same hero) are preferred over the static targets below.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from app.advice_follow import analyze_advice_follow
from app.build_analysis import analyze_build
from app.death_review import review_deaths
from app.domain_contracts import Finding
from app.draft_analysis import analyze_draft
from app.finding_evidence import FINDING_FIELDS, attach_finding_evidence
from app.item_timing import classify_item_timing, normalize_item_name
from app.lane_duel import analyze_lane
from app.map_analysis import analyze_map
from app.peer_analysis import match_peers, peer_findings, player_roles
from app.role_analysis import analyze_role
from app.skill_build import review_skills
from app.usage_stats import advice_counts

# Bump when the rules change: stored reviews of an older version are rebuilt on read.
ANALYSIS_VERSION = 22
# Dota replays run at 30 ticks a second.
REPLAY_TICK_RATE = 30
# Last seconds before deaths (last_moments.py, via death_review.py).
SAVER_DEATHS = 2
BURST_DEATHS = 3
MAX_ADVICE_SHOWN = 40

# Static targets when OpenDota benchmarks are missing (GSI-only matches).
# xpm_good only draws the "good pace" line of the experience chart.
TARGETS: dict[str, dict[str, float]] = {
    "core": {
        "lh10_good": 55,
        "lh10_ok": 40,
        "gpm_good": 560,
        "gpm_ok": 430,
        "lh_rate": 5.5,
        "xpm_good": 620,
    },
    "offlane": {
        "lh10_good": 38,
        "lh10_ok": 25,
        "gpm_good": 460,
        "gpm_ok": 360,
        "lh_rate": 4.0,
        "xpm_good": 560,
    },
    "support": {
        "lh10_good": 12,
        "lh10_ok": 6,
        "gpm_good": 340,
        "gpm_ok": 260,
        "lh_rate": 1.0,
        "xpm_good": 420,
    },
}
SECTION_WEIGHTS: dict[str, dict[str, float]] = {
    "core": {"laning": 0.2, "farm": 0.3, "survival": 0.2, "fights": 0.15, "items": 0.15},
    "offlane": {"laning": 0.2, "farm": 0.2, "survival": 0.2, "fights": 0.25, "items": 0.15},
    "support": {"survival": 0.3, "fights": 0.25, "vision": 0.25, "farm": 0.1, "items": 0.1},
}
FARM_STALL_MINUTES = 4
BIG_DEATH_GOLD = 1200


def _clamp(value: float, low: float = 0, high: float = 100) -> int:
    return int(round(max(low, min(high, value))))


def _grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _rating(score: int) -> str:
    return "good" if score >= 70 else "ok" if score >= 50 else "bad"


def _at(series: list[int | None], minute: int) -> int | None:
    return series[minute] if len(series) > minute else None


# Match roles (peer_analysis) -> review roles (TARGETS).
REVIEW_ROLE = {"carry": "core", "mid": "core", "offlane": "offlane", "support": "support"}


def match_position(facts: Mapping[str, Any], opendota: dict[str, Any] | None) -> str | None:
    """carry | mid | offlane | support from OpenDota's lineup (lanes of a parsed
    replay, else the farm order inside the team, as for the rank comparison);
    None without the lineup."""
    players = (opendota or {}).get("players") or []
    index = next((i for i, p in enumerate(players) if p.get("me")), None)
    if index is None:
        return None
    return player_roles(players, (opendota or {}).get("duration") or facts.get("duration"))[index]


def detect_role(facts: Mapping[str, Any], opendota: dict[str, Any] | None = None) -> str:
    """The review role (TARGETS). Last hits per minute alone make a farming
    support a "core", so the match lineup decides when there is one."""
    position = match_position(facts, opendota)
    if position is not None:
        return REVIEW_ROLE.get(position, "core")
    lane_role = facts.get("lane_role")
    duration_min = max(1.0, (facts.get("duration") or 0) / 60)
    lh_rate = (facts.get("last_hits") or 0) / duration_min
    wards = (facts.get("obs_placed") or 0) + (facts.get("sen_placed") or 0)
    if wards >= 8 or (lh_rate < 2.0 and duration_min >= 20):
        return "support"
    if lane_role == 3:
        return "offlane"
    return "core"


def analyze_match(
    facts: Mapping[str, Any],
    *,
    meta: dict[str, Any] | None = None,
    opendota: dict[str, Any] | None = None,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`meta`: cached hero meta (build advice); `opendota`: trimmed match (rank peers,
    enemy lineup); `draft`: cached matchups + the player's hero pool (draft advice)."""
    role = detect_role(facts, opendota)
    position = match_position(facts, opendota)
    targets = TARGETS[role]
    findings: list[dict[str, Any]] = []
    sections: dict[str, dict[str, Any]] = {}

    for builder in (_laning, _farm, _survival, _fights, _items, _vision):
        section = builder(facts, role, targets, findings)
        if section is not None:
            sections[section.pop("name")] = section

    build, build_findings = analyze_build(facts, meta, role)
    findings.extend(build_findings)
    peers = match_peers(opendota)
    findings.extend(peer_findings(peers))
    # The better pick keeps the position (a mid hero is not offered to a carry).
    draft_block, draft_findings = analyze_draft(facts, opendota, draft, position or role)
    findings.extend(draft_findings)
    map_block, map_findings = analyze_map(facts)
    findings.extend(map_findings)
    follow_block, follow_findings = analyze_advice_follow(facts)
    findings.extend(follow_findings)
    death_block = review_deaths(facts)
    findings.extend(_last_moment_findings(death_block))
    role_block, role_findings = analyze_role(facts, opendota, position)
    findings.extend(role_findings)
    lane_block, lane_findings = analyze_lane(opendota, position)
    findings.extend(lane_findings)
    skills_block = review_skills(facts.get("skill_upgrades"), (meta or {}).get("skills"))
    if skills_block and not skills_block["same"]:
        _finding(
            findings,
            "skill_first_max",
            "improve",
            "laning",
            severity=1,
            weight=0.9,
            yours=skills_block["yours"],
            pro=skills_block["pro"],
            agree=skills_block["agree"],
            games=skills_block["games"],
        )
    if role_block and "runes" in role_block and "laning" in sections:
        # The mid's runes are shown with the lane numbers.
        sections["laning"]["runes"] = role_block["runes"]
        if role_block.get("enemy_runes") is not None:
            sections["laning"]["enemy_runes"] = role_block["enemy_runes"]
    if role_block and "stuns" in role_block and "fights" in sections:
        # The offlaner's control is shown with the fight numbers.
        sections["fights"]["stuns"] = role_block["stuns"]
        if role_block.get("enemy_stuns") is not None:
            sections["fights"]["enemy_stuns"] = role_block["enemy_stuns"]
    if role_block and role_block.get("enemy_tower_damage") is not None and "fights" in sections:
        sections["fights"]["enemy_tower_damage"] = role_block["enemy_tower_damage"]
    attach_finding_evidence(findings, facts)
    evidence_findings = [
        {"id": f["id"], "params": f["params"], "evidence": f["evidence"]}
        for f in findings
        if f["id"] in FINDING_FIELDS
    ]
    findings = _dedupe(findings)

    weights = SECTION_WEIGHTS[role]
    weighted = [
        (sections[name]["score"], weight) for name, weight in weights.items() if name in sections
    ]
    total_weight = sum(weight for _, weight in weighted)
    score = _clamp(sum(s * w for s, w in weighted) / total_weight) if total_weight else None

    strengths = sorted(
        (f for f in findings if f["kind"] == "strength"), key=lambda f: -f.get("weight", 1)
    )
    improvements = _per_section(
        sorted(
            (f for f in findings if f["kind"] == "improve"),
            key=lambda f: (-f["severity"], -f.get("weight", 1)),
        )
    )
    return {
        "version": ANALYSIS_VERSION,
        "match_id": facts.get("match_id"),
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": facts.get("sources", []),
        "parsed": bool(facts.get("parsed")),
        "evidence_findings": evidence_findings,
        "recording_coverage": facts.get("recording_coverage"),
        "role": role,
        "position": position,
        "headline": {
            "hero": facts.get("hero"),
            "hero_id": facts.get("hero_id"),
            "win": facts.get("win"),
            "duration": facts.get("duration"),
            "kills": facts.get("kills"),
            "deaths": facts.get("deaths"),
            "assists": facts.get("assists"),
            "gpm": facts.get("gpm"),
            "xpm": facts.get("xpm"),
            "last_hits": facts.get("last_hits"),
            "denies": facts.get("denies"),
            "net_worth": facts.get("net_worth"),
            "hero_damage": facts.get("hero_damage"),
            "score": score,
            "grade": _grade(score) if score is not None else None,
        },
        "sections": sections,
        "strengths": strengths[:5],
        "improvements": improvements[:6],
        "focus": [f["id"] for f in improvements[:3]],
        # Every problem found, before the per-section cap (focus_goal.py checks it).
        "problems": sorted({f["id"] for f in findings if f["kind"] == "improve"}),
        "series": {**_series(facts, targets), "items": _item_marks(facts, meta)},
        "moments": _moments(facts, findings),
        "build": build,
        "peers": peers,
        "draft": draft_block,
        "map": map_block,
        "death_review": death_block,
        # «Watch this moment»: a match clock → a replay tick (live-recorded matches).
        "replay": {"clock_offset": facts["clock_offset"], "tick_rate": REPLAY_TICK_RATE}
        if isinstance(facts.get("clock_offset"), int)
        else None,
        # Deaths with their last seconds recorded (live GSI): focus_goal REQUIRES it.
        "last_moments": (death_block or {}).get("with_last") or 0,
        "advice": (facts.get("advice_log") or [])[:MAX_ADVICE_SHOWN],
        # Counts over the whole log (the opt-in anonymous statistics, usage_stats.py).
        "advice_counts": advice_counts(facts.get("advice_log"), follow_block),
        "advice_follow": follow_block,
        "role_play": role_block,
        # The lane minute by minute against its enemy core (lane_duel.py).
        "lane": lane_block,
        # The first skill maxed against the pro order on the hero (skill_build.py).
        "skills": skills_block,
        # The enemy lineup (OpenDota), for the career's hardest opponents.
        "enemy_heroes": _enemy_heroes(opendota),
    }


def _last_moment_findings(death_block: dict[str, Any] | None) -> list[dict[str, Any]]:
    """From the last seconds before deaths (GSI): a saving item left unpressed
    (SAVER_DEATHS+ deaths) and burst deaths (BURST_DEATHS+)."""
    if not death_block or not death_block.get("with_last"):
        return []
    rows = [row for row in death_block["deaths"] if "last" in row]
    found: list[dict[str, Any]] = []
    unused = [row for row in rows if "saver_ready" in row["notes"]]
    if len(unused) >= SAVER_DEATHS:
        items = Counter(name for row in unused for name in row["last"]["usable"])
        _finding(
            found,
            "died_with_saver_ready",
            "improve",
            "survival",
            severity=2,
            weight=1.4,
            count=len(unused),
            item=items.most_common(1)[0][0],
            times=[row["t"] for row in unused],
        )
    bursts = [row for row in rows if "burst" in row["notes"]]
    if len(bursts) >= BURST_DEATHS:
        _finding(
            found,
            "burst_deaths",
            "improve",
            "survival",
            severity=1,
            count=len(bursts),
            of=len(rows),
        )
    return found


def _enemy_heroes(opendota: dict[str, Any] | None) -> list[int]:
    players = (opendota or {}).get("players") or []
    me = next((p for p in players if p.get("me")), None)
    if me is None:
        return []
    side = bool(me.get("isRadiant", True))
    return [
        int(p["hero_id"])
        for p in players
        if bool(p.get("isRadiant", True)) != side
        and isinstance(p.get("hero_id"), int)
        and p["hero_id"] > 0
    ]


def _per_section(findings: list[dict[str, Any]], limit: int = 2) -> list[dict[str, Any]]:
    """Keep the order but at most `limit` findings per section, so one area can't fill the list."""
    counts: dict[str, int] = {}
    result = []
    for finding in findings:
        section = finding.get("section", "")
        counts[section] = counts.get(section, 0) + 1
        if counts[section] <= limit:
            result.append(finding)
    return result


# A comparison with the same-role player of this match says the same as a
# generic finding, with a concrete reference: it replaces it and keeps its priority.
REPLACED_BY_PEER = {
    "gpm_low": "peer_gpm_behind",
    "gpm_low_static": "peer_gpm_behind",
    "lh10_low": "peer_lh10_behind",
    "deaths_high": "peer_deaths_more",
}


def _dedupe(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop generic findings when a more specific one says the same thing."""
    late_items = {f["params"].get("item") for f in findings if f["id"] == "build_timing_late"}
    fast_items = {f["params"].get("item") for f in findings if f["id"] == "build_timing_good"}
    by_id = {f["id"]: f for f in findings}
    result = []
    for finding in findings:
        item = finding["params"].get("item")
        if finding["id"] == "core_item_slow" and item in late_items:
            continue
        if finding["id"] == "core_item_fast" and item in fast_items:
            continue
        peer = by_id.get(REPLACED_BY_PEER.get(finding["id"], ""))
        if peer is not None:
            peer["severity"] = max(peer["severity"], finding["severity"])
            peer["weight"] = max(peer.get("weight", 1), finding.get("weight", 1))
            continue
        result.append(finding)
    return result


def _finding(
    findings: list[dict[str, Any]],
    finding_id: str,
    kind: Literal["strength", "improve"],
    section: str,
    *,
    severity: int = 1,
    weight: float = 1.0,
    **params: Any,
) -> None:
    finding: Finding = {
        "id": finding_id,
        "kind": kind,
        "section": section,
        "severity": severity,
        "weight": weight,
        "params": params,
        "evidence": [],
    }
    findings.append(dict(finding))


def _laning(facts, role, targets, findings) -> dict[str, Any] | None:
    lh10 = _at(facts.get("lh_t") or [], 10)
    lh_source = (facts.get("provenance") or {}).get("lh10")
    if isinstance(lh_source, dict) and lh_source.get("precision") == "carried_sample":
        lh10 = None
    dn10 = _at(facts.get("dn_t") or [], 10)
    efficiency = facts.get("lane_efficiency_pct")
    lane_deaths = [
        d for d in facts.get("deaths_log") or [] if type(d.get("t")) is int and 0 <= d["t"] <= 600
    ]
    if lh10 is None and efficiency is None and len(lane_deaths) < 2:
        return None
    scores = []
    if lh10 is not None and role != "support":
        scores.append(100 * min(1.0, lh10 / targets["lh10_good"]))
        if lh10 >= targets["lh10_good"]:
            _finding(
                findings,
                "lh10_great",
                "strength",
                "laning",
                weight=2,
                lh10=lh10,
                target=int(targets["lh10_good"]),
            )
        elif lh10 < targets["lh10_ok"]:
            gap = int(targets["lh10_good"]) - lh10
            _finding(
                findings,
                "lh10_low",
                "improve",
                "laning",
                severity=3 if lh10 < targets["lh10_ok"] * 0.7 else 2,
                weight=gap / 10,
                lh10=lh10,
                target=int(targets["lh10_good"]),
                gold_lost=gap * 40,
            )
    if efficiency is not None:
        scores.append(efficiency)
        if efficiency >= 70:
            _finding(findings, "lane_eff_high", "strength", "laning", efficiency=round(efficiency))
        elif efficiency < 45:
            _finding(
                findings,
                "lane_eff_low",
                "improve",
                "laning",
                severity=2,
                efficiency=round(efficiency),
            )
    if dn10 is not None and dn10 >= 10 and role != "support":
        _finding(findings, "denies_good", "strength", "laning", weight=0.5, denies=dn10)
    if len(lane_deaths) >= 2:
        _finding(
            findings,
            "lane_deaths",
            "improve",
            "laning",
            severity=3 if len(lane_deaths) >= 3 else 2,
            weight=len(lane_deaths),
            count=len(lane_deaths),
            times=[d["t"] for d in lane_deaths],
        )
    if not scores:
        return None
    score = _clamp(sum(scores) / len(scores) - 12 * max(0, len(lane_deaths) - 1))
    return {
        "name": "laning",
        "score": score,
        "rating": _rating(score),
        "lh10": lh10,
        "dn10": dn10,
        "lane_efficiency": efficiency,
        "lane_deaths": len(lane_deaths),
    }


def _farm(facts, role, targets, findings) -> dict[str, Any] | None:
    gpm = facts.get("gpm")
    if gpm is None:
        return None
    pct = (facts.get("benchmarks") or {}).get("gold_per_min")
    hero = facts.get("hero")
    if pct is not None:
        score = _clamp(pct * 100)
    else:
        span = targets["gpm_good"] - targets["gpm_ok"]
        score = _clamp(50 + 40 * (gpm - targets["gpm_ok"]) / span, 10, 100)
    if pct is not None and pct >= 0.7:
        _finding(
            findings,
            "gpm_high",
            "strength",
            "farm",
            weight=2,
            gpm=gpm,
            pct=round(pct * 100),
            hero=hero,
        )
    elif pct is None and gpm >= targets["gpm_good"]:
        _finding(
            findings,
            "gpm_high_static",
            "strength",
            "farm",
            weight=2,
            gpm=gpm,
            target=int(targets["gpm_good"]),
        )
    elif role != "support" and (
        (pct is not None and pct < 0.35) or (pct is None and gpm < targets["gpm_ok"])
    ):
        _finding(
            findings,
            "gpm_low" if pct is not None else "gpm_low_static",
            "improve",
            "farm",
            severity=3 if score < 30 else 2,
            weight=2,
            gpm=gpm,
            pct=round(pct * 100) if pct is not None else None,
            target=int(targets["gpm_good"]),
            hero=hero,
        )
    stalls = _farm_stalls(facts.get("lh_t") or [], role)
    for stall in stalls[:2]:
        _finding(
            findings,
            "farm_stall",
            "improve",
            "farm",
            severity=2,
            weight=stall["to"] - stall["from"],
            **stall,
        )
    lh_pct = (facts.get("benchmarks") or {}).get("last_hits_per_min")
    return {
        "name": "farm",
        "score": score,
        "rating": _rating(score),
        "gpm": gpm,
        "gpm_pct": pct,
        "last_hits_pct": lh_pct,
        "xpm": facts.get("xpm"),
        "stalls": len(stalls),
    }


def _farm_stalls(lh_t: list[int | None], role: str) -> list[dict[str, Any]]:
    """Stretches after minute 10 where a core took < 2 last hits a minute."""
    if role == "support" or len(lh_t) < 14:
        return []
    stalls, start = [], None
    for minute in range(11, len(lh_t)):
        current, previous = lh_t[minute], lh_t[minute - 1]
        if current is None or previous is None:
            start = None
            continue
        slow = current - previous < 2
        if slow and start is None:
            start = minute - 1
        if (not slow or minute == len(lh_t) - 1) and start is not None:
            end = minute if slow else minute - 1
            if end - start >= FARM_STALL_MINUTES:
                begin, finish = lh_t[start], lh_t[end]
                if begin is not None and finish is not None:
                    stalls.append({"from": start, "to": end, "last_hits": finish - begin})
            start = None
    return sorted(stalls, key=lambda s: s["from"] - s["to"])


def _survival(facts, role, targets, findings) -> dict[str, Any] | None:
    deaths = facts.get("deaths")
    duration = facts.get("duration")
    if deaths is None or not duration:
        return None
    per10 = deaths / max(1.0, duration / 600)
    score = _clamp(100 - per10 * 22, 5, 100)
    minutes = round(duration / 60)
    time_dead = facts.get("time_dead")
    if deaths <= 3 and minutes >= 25:
        _finding(
            findings,
            "deaths_low",
            "strength",
            "survival",
            weight=1.5,
            deaths=deaths,
            minutes=minutes,
        )
    elif per10 >= 2.2 or deaths >= 9:
        _finding(
            findings,
            "deaths_high",
            "improve",
            "survival",
            severity=3 if per10 >= 3 else 2,
            weight=per10,
            deaths=deaths,
            minutes=minutes,
            time_dead=time_dead,
            dead_pct=round(100 * time_dead / duration) if time_dead else None,
        )
    deaths_log = facts.get("deaths_log") or []
    rich = [d for d in deaths_log if (d.get("gold") or 0) >= BIG_DEATH_GOLD]
    if rich:
        worst = max(rich, key=lambda d: d["gold"])
        _finding(
            findings,
            "death_with_gold",
            "improve",
            "survival",
            severity=2,
            weight=len(rich),
            count=len(rich),
            gold=worst["gold"],
            t=worst["t"],
        )
    streak = _death_streak(deaths_log)
    if streak:
        _finding(
            findings,
            "death_streak",
            "improve",
            "survival",
            severity=2,
            weight=streak["count"],
            **streak,
        )
    killed_by = facts.get("killed_by") or {}
    if killed_by:
        hero, count = max(killed_by.items(), key=lambda item: item[1])
        if count >= 3 and deaths and count / deaths >= 0.4:
            _finding(
                findings,
                "killed_by_one",
                "improve",
                "survival",
                severity=1,
                weight=count,
                hero=hero,
                count=count,
                deaths=deaths,
            )
    return {
        "name": "survival",
        "score": score,
        "rating": _rating(score),
        "deaths": deaths,
        "deaths_per_10": round(per10, 1),
        "time_dead": time_dead,
        "buybacks": len(facts.get("buybacks") or []),
    }


def _death_streak(deaths_log: list[dict[str, Any]]) -> dict[str, Any] | None:
    times = sorted(d["t"] for d in deaths_log if d.get("t") is not None)
    best = None
    for i in range(len(times)):
        j = i
        while j + 1 < len(times) and times[j + 1] - times[i] <= 300:
            j += 1
        count = j - i + 1
        if count >= 3 and (best is None or count > best["count"]):
            best = {"count": count, "from": times[i], "to": times[j]}
    return best


def _fights(facts, role, targets, findings) -> dict[str, Any] | None:
    kp = facts.get("kill_participation")
    damage_pct = (facts.get("benchmarks") or {}).get("hero_damage_per_min")
    tower_pct = (facts.get("benchmarks") or {}).get("tower_damage")
    if kp is None and damage_pct is None:
        return None
    parts = []
    minutes = round((facts.get("duration") or 0) / 60)
    if kp is not None:
        parts.append(min(100, kp * 125))
        if kp >= 0.7:
            _finding(findings, "kp_high", "strength", "fights", weight=1.5, kp=round(kp * 100))
        elif kp < 0.4 and minutes >= 25:
            _finding(
                findings,
                "kp_low",
                "improve",
                "fights",
                severity=2,
                weight=1.5,
                kp=round(kp * 100),
                team_kills=facts.get("team_kills"),
            )
    if damage_pct is not None:
        parts.append(damage_pct * 100)
        if damage_pct >= 0.75:
            _finding(
                findings,
                "damage_high",
                "strength",
                "fights",
                weight=1,
                pct=round(damage_pct * 100),
                damage=facts.get("hero_damage"),
            )
        elif damage_pct < 0.25 and role != "support":
            _finding(
                findings,
                "damage_low",
                "improve",
                "fights",
                severity=1,
                weight=1,
                pct=round(damage_pct * 100),
                damage=facts.get("hero_damage"),
            )
    if tower_pct is not None and tower_pct >= 0.75 and role != "support":
        _finding(
            findings,
            "towers_high",
            "strength",
            "fights",
            weight=0.8,
            pct=round(tower_pct * 100),
            damage=facts.get("tower_damage"),
        )
    score = _clamp(sum(parts) / len(parts))
    return {
        "name": "fights",
        "score": score,
        "rating": _rating(score),
        "kill_participation": round(kp * 100) if kp is not None else None,
        "hero_damage": facts.get("hero_damage"),
        "hero_damage_pct": damage_pct,
        "tower_damage": facts.get("tower_damage"),
    }


def big_items(items_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Meaningful completed items (no components/consumables), first purchase each."""
    seen, result = set(), []
    for entry in sorted(items_log, key=lambda e: e.get("t") or 0):
        info = classify_item_timing(entry.get("item"))
        name = info["item"]
        if not info["is_meaningful"] or name in seen or entry.get("t") is None:
            continue
        seen.add(name)
        result.append(
            {"t": entry["t"], "item": name, "category": info["category"], "cost": info["cost"]}
        )
    return result


# A support's first item that saves a core in a fight: on time by this minute,
# late after that one, missing in a game at least this long.
SAVE_ITEM_NAMES = {
    "Glimmer Cape",
    "Force Staff",
    "Hurricane Pike",
    "Ghost",
    "Ethereal Blade",
    "Lotus Orb",
    "Solar Crest",
    "Pavise",
    "Guardian Greaves",
}
SAVE_ITEM_ON_TIME = 15
SAVE_ITEM_LATE = 22
SAVE_ITEM_GAME = 25


def _support_items(facts, findings) -> dict[str, Any] | None:
    """A support's items: the first save item (Glimmer Cape, Force Staff…) and when."""
    log = facts.get("items_log") or []
    if not log:
        return None
    duration = facts.get("duration") or 0
    saves = sorted(
        (entry["t"], normalize_item_name(entry.get("item")))
        for entry in log
        if entry.get("t") is not None and normalize_item_name(entry.get("item")) in SAVE_ITEM_NAMES
    )
    first = {"t": saves[0][0], "item": saves[0][1]} if saves else None
    if first is None:
        if duration < SAVE_ITEM_GAME * 60:
            return None
        score = 20
        _finding(
            findings,
            "save_item_missing",
            "improve",
            "items",
            severity=2,
            weight=1.5,
            minutes=round(duration / 60),
        )
    else:
        minute = first["t"] / 60
        score = _clamp(100 - max(0.0, minute - SAVE_ITEM_ON_TIME) * 5, 30, 100)
        if minute <= SAVE_ITEM_ON_TIME:
            _finding(
                findings,
                "save_item_fast",
                "strength",
                "items",
                weight=1,
                item=first["item"],
                t=first["t"],
            )
        elif minute > SAVE_ITEM_LATE:
            _finding(
                findings,
                "save_item_slow",
                "improve",
                "items",
                severity=1,
                weight=1,
                item=first["item"],
                t=first["t"],
            )
    return {
        "name": "items",
        "score": score,
        "rating": _rating(score),
        "save_item": first,
        "save_items": [{"t": t, "item": item} for t, item in saves[:4]],
    }


def _items(facts, role, targets, findings) -> dict[str, Any] | None:
    if role == "support":
        return _support_items(facts, findings)
    duration = facts.get("duration") or 0
    items = big_items(facts.get("items_log") or [])
    if not facts.get("items_log"):
        return None
    first = items[0] if items else None
    if first is None:
        if duration < 20 * 60:
            return None
        score = 25
        _finding(
            findings,
            "no_core_item",
            "improve",
            "items",
            severity=3,
            weight=2,
            minutes=round(duration / 60),
        )
    else:
        minute = first["t"] / 60
        score = _clamp(100 - max(0.0, minute - 14) * 6, 15, 100)
        if minute <= 14:
            _finding(
                findings,
                "core_item_fast",
                "strength",
                "items",
                weight=1.5,
                item=first["item"],
                t=first["t"],
            )
        elif minute >= 20:
            _finding(
                findings,
                "core_item_slow",
                "improve",
                "items",
                severity=2 if minute < 25 else 3,
                weight=(minute - 20) / 3 + 1,
                item=first["item"],
                t=first["t"],
            )
    return {
        "name": "items",
        "score": score,
        "rating": _rating(score),
        "first_item": first,
        "big_items": items[:8],
    }


def _vision(facts, role, targets, findings) -> dict[str, Any] | None:
    obs = facts.get("obs_placed")
    provenance = (facts.get("provenance") or {}).get("obs_placed")
    if isinstance(provenance, dict) and provenance.get("precision") == "inventory_estimate":
        if not (provenance.get("coverage") or {}).get("complete"):
            return None
    if role != "support" or obs is None:
        return None
    minutes = max(1.0, (facts.get("duration") or 0) / 60)
    per10 = obs / (minutes / 10)
    score = _clamp(per10 * 30, 10, 100)
    if per10 >= 3:
        _finding(
            findings,
            "wards_high",
            "strength",
            "vision",
            weight=1.5,
            obs=obs,
            sen=facts.get("sen_placed"),
        )
    elif per10 < 1.5:
        _finding(
            findings,
            "wards_low",
            "improve",
            "vision",
            severity=2,
            weight=1.5,
            obs=obs,
            minutes=round(minutes),
        )
    if (facts.get("camps_stacked") or 0) >= 5:
        _finding(
            findings, "stacks_good", "strength", "vision", weight=0.7, stacks=facts["camps_stacked"]
        )
    return {
        "name": "vision",
        "score": score,
        "rating": _rating(score),
        "obs_placed": obs,
        "sen_placed": facts.get("sen_placed"),
        "camps_stacked": facts.get("camps_stacked"),
    }


# --- charts / timeline ------------------------------------------------------------


def _series(facts: Mapping[str, Any], targets: dict[str, float]) -> dict[str, Any]:
    lh_t = facts.get("lh_t") or []
    gold = facts.get("gold_t") or []
    xp = facts.get("xp_t") or []
    minutes = list(range(len(lh_t) or len(gold)))
    return {
        "minutes": minutes,
        "last_hits": lh_t,
        "last_hits_target": [round(m * targets["lh_rate"]) for m in minutes],
        "denies": facts.get("dn_t") or [],
        "gold": gold,
        # Gold and experience earned at the role's good GPM / XPM, minute by minute.
        "gold_target": [round(m * targets["gpm_good"]) for m in range(len(gold))],
        "xp": xp,
        "xp_target": [round(m * targets["xpm_good"]) for m in range(len(xp))],
        "deaths": [d["t"] for d in facts.get("deaths_log") or [] if d.get("t") is not None],
    }


# A finished item that is not built from a recipe, still worth a mark.
ITEM_MARK_SINGLES = {"blink"}
ITEM_MARK_MIN_COST = 1200
ITEM_MARKS_MAX = 12


def _item_marks(facts: Mapping[str, Any], meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """[{t, key}]: the minute each finished item (a recipe of 1200+ gold, or a
    Blink Dagger) came, for the icons on the review's chart. The cached item
    constants tell a finished item from a part; without them, nothing."""
    items = ((meta or {}).get("constants") or {}).get("items") or {}
    if not items:
        return []
    marks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in sorted(
        (e for e in facts.get("items_log") or [] if e.get("t") is not None), key=lambda e: e["t"]
    ):
        raw = str(entry.get("item") or "").strip().lower()
        key = raw[5:] if raw.startswith("item_") else raw
        info = items.get(key) or {}
        finished = bool(info.get("assembled")) and (info.get("cost") or 0) >= ITEM_MARK_MIN_COST
        if key in seen or not (finished or key in ITEM_MARK_SINGLES):
            continue
        seen.add(key)
        marks.append({"t": int(entry["t"]), "key": key})
    return marks[:ITEM_MARKS_MAX]


def _moments(facts: Mapping[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    moments: list[dict[str, Any]] = []
    for death in facts.get("deaths_log") or []:
        if death.get("t") is not None:
            moments.append(
                {
                    "t": death["t"],
                    "type": "death",
                    "killer": death.get("killer"),
                    "gold": death.get("gold"),
                }
            )
    for item in big_items(facts.get("items_log") or [])[:8]:
        moments.append({"t": item["t"], "type": "item", "item": item["item"]})
    for t in facts.get("buybacks") or []:
        moments.append({"t": t, "type": "buyback"})
    for finding in findings:
        if finding["id"] == "farm_stall":
            moments.append(
                {
                    "t": finding["params"]["from"] * 60,
                    "type": "farm_stall",
                    "to": finding["params"]["to"] * 60,
                }
            )
    return sorted(moments, key=lambda m: m["t"])


def display_item(raw: Any) -> str:
    return normalize_item_name(raw)
