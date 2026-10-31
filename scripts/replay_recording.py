"""Replay a Wardly match recording through the current backend and print every
distinct overlay card (advice, map hint, death screen, Aegis on the strip) with
its match clock — to see what the coach would say in that game now.

Recordings: Settings → «Keep match recordings for a week» (gzip JSON lines,
match_records.py). They hold the player's game: keep them on the computer,
never in the repository. Run from backend/ with its venv:

    cd backend
    .venv/bin/python ../scripts/replay_recording.py <recording.jsonl[.gz]> [--out cards.jsonl]
        [--items items.json] [--lang uk|en] [--from 20:00] [--until 25:00]
        [--audit audit.jsonl] [--review review.md]

`--audit` writes one row per new card and per withdrawn card: the clock and wall
time of the poll, the snapshot the card stands on (advice_basis: its clock, the
tool it names, the numbers it cites), the status classification
(status_source.py) and how old the snapshot data was. `--review` writes a
Markdown table that sets each card the recording itself logged (`k=advice`,
what the version that played the match said) next to what the current code
shows at that very moment (an extra poll at the card's `w`) and the nearest new
card of the same family with its own evidence. The evidence is the nearest
preceding snapshot (never a later one: `w` orders the lines); recordings made
before 0.60 stamped GSI lines after publishing them, so a snapshot stamped up
to 0.05 s after the card is shown as the other candidate.

After the replay, `--audit` rows of cards naming a tool also carry
`historical`: the recorded use of that tool within the card's episode
(replay_outcomes.py): the decision snapshot, the poll that showed the card,
and the interval the use lies in, relative to both. This reads the future of
the recording and runs after the replay: it never feeds a decision, and it
says when the recorded player used the tool, not that a card made them.
The audit ends with the plan record (live_plan.py): `plan` rows (each plan and
how it ended) and `reassessment` rows (each major item received and what it
did to the current plan); and `farm` rows (farm_map.py: each farm target, its
estimate and how it ended).

The wall time of each payload is replayed through a fake clock (the advice
scheduler reads datetime.now), so cooldowns hold as in the real match. No
network: OpenDota is off; `--items` (OpenDota /api/constants/items, saved
once) gives the item prices for the build lines.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import json
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

os.environ["OPENDOTA_ENABLED"] = "false"
os.environ.setdefault("DOTA_AI_CONTROL_TOKEN", secrets.token_hex(32))
os.environ.setdefault("DOTA_AI_GSI_TOKEN", secrets.token_hex(32))
os.environ.setdefault("PLAYER_DATA_DIR", tempfile.mkdtemp(prefix="wardly-replay-"))
BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

BASE = datetime(2026, 1, 1, tzinfo=UTC)
NOW = {"t": 0.0}
CLOCKED = (
    "app.scheduler.state_utils",
    "app.advice_scheduler",
    "app.main",
    "app.match_memory",
    "app.gsi_snapshot",
    "app.advice_ux_policy",
    "app.coach_summary",
)


class ReplayDateTime(datetime):
    """datetime.now() at the recording's wall time."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        moment = BASE + timedelta(seconds=NOW["t"])
        return moment if tz else moment.replace(tzinfo=None)


def _open(path: Path) -> Any:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _clock_label(clock: Any) -> str:
    if not isinstance(clock, int):
        return "?"
    sign = "-" if clock < 0 else ""
    return f"{sign}{abs(clock) // 60:02d}:{abs(clock) % 60:02d}"


def _evidence(payload: dict[str, Any]) -> str:
    """The checkable facts of one raw snapshot for the review table."""
    hero = payload.get("hero") or {}
    player = payload.get("player") or {}
    flags = [f for f in ("stunned", "hexed", "silenced", "muted") if hero.get(f) is True]
    parts = [
        f"HP {hero.get('health')}/{hero.get('max_health')}",
        f"mana {hero.get('mana')}/{hero.get('max_mana')}",
    ]
    if flags:
        parts.append("+".join(flags) + f" debuff={hero.get('has_debuff')}")
    if hero.get("alive") is False:
        parts.append("dead")
    parts.append(f"gold {player.get('gold')} bb {hero.get('buyback_cost')}")
    parts.append(f"KDA {player.get('kills')}/{player.get('deaths')}/{player.get('assists')}")
    return ", ".join(parts)


FAMILIES = {
    "DISABLED_STATUS": "disable",
    "LOW_HP": "danger",
    "LOW_HP_WARNING": "danger",
    "RECENT_DAMAGE_WARNING": "danger",
    "OVERSTAY_WARNING": "danger",
    "ABILITY_SAFETY_COOLDOWN": "danger",
    "HERO_SURVIVABILITY_RISK": "danger",
    "DEATH_REVIEW": "death",
    "DEATH_LOW_RESOURCE": "death",
    "DEATH_WITH_ESCAPE_ON_COOLDOWN": "death",
    "REPEATED_DEATH_PATTERN": "death",
}


def _family(decision_point: Any) -> str:
    return FAMILIES.get(str(decision_point), "other")


def _shown(answer: dict[str, Any] | None) -> str:
    """What the overlay shows for one poll answer."""
    if not answer:
        return "?"
    advice = answer.get("recommendation")
    if isinstance(advice, dict) and advice.get("action"):
        kind = "new" if answer.get("new_advice") else "held"
        action = advice.get("action_en") or advice.get("action")
        return f"{kind} [{answer.get('decision_point')}] {action}"
    return f"nothing ({answer.get('status')}: {answer.get('suppressed_reason') or '-'})"


def _review(logged: list[dict[str, Any]], audit: list[dict[str, Any]], window: int = 10) -> str:
    """Markdown: each logged card next to what the current code shows at that
    very moment (a poll at the card's `w`), and the nearest new card of the
    same family with its own evidence: a card a few seconds away can be a
    different episode (another stun, another fall), never silently «kept»."""
    new_cards = [row for row in audit if row["kind"] == "advice"]
    lines = [
        "| Clock | Logged card (old) | Deciding snapshot | Current code at that moment "
        "| Nearest new card of this family |",
        "| --- | --- | --- | --- | --- |",
    ]
    paired: set[int] = set()
    for card in logged:
        clock = card.get("clock")
        family = _family(card.get("dp"))
        nearest = min(
            (
                (abs(row["clock"] - clock), index, row)
                for index, row in enumerate(new_cards)
                if isinstance(clock, int)
                and isinstance(row.get("clock"), int)
                and abs(row["clock"] - clock) <= window
                and _family(row.get("decision_point")) == family
            ),
            default=None,
            key=lambda item: (item[0], item[1]),
        )
        if nearest is None:
            near = "—"
        else:
            _, index, row = nearest
            paired.add(index)
            near = f"{_clock_label(row['clock'])} [{row['decision_point']}] {row['action']}"
            source = row.get("status_source") or {}
            if source.get("kind") not in (None, "none"):
                near += f" (status {source.get('kind')}: {', '.join(source.get('evidence') or [])})"
            near += f"; {row.get('evidence', '')}"
        evidence = card.get("evidence", "")
        if card.get("race_evidence"):
            evidence += (
                f" — or, published {card['race_gap']} s after the card's stamp (old "
                f"recordings stamp GSI after publication): {card['race_evidence']}"
            )
        old = f"[{card.get('dp')}] {card.get('action')} — {card.get('reason')}"
        lines.append(
            f"| {_clock_label(clock)} | {old} | {evidence} | {_shown(card.get('moment'))} | {near} |"
        )
    added = [row for index, row in enumerate(new_cards) if index not in paired]
    if added:
        lines += ["", "Cards the current code adds (no logged card of the family within 10 s):", ""]
        lines += [
            f"- {_clock_label(row['clock'])} [{row['decision_point']}] {row['action']} — "
            f"{row['reason']} ({row.get('evidence', '')})"
            for row in added
        ]
    withdrawn = [row for row in audit if row["kind"] == "withdrawn"]
    if withdrawn:
        lines += ["", "Cards withdrawn while held (no longer true):", ""]
        lines += [
            f"- {_clock_label(row['clock'])} {row['action']} ({row['reason']})" for row in withdrawn
        ]
    return "\n".join(lines) + "\n"


def _clock(text: str) -> int:
    minutes, _, seconds = text.partition(":")
    return int(minutes) * 60 + int(seconds or 0)


def _item_constants(path: Path) -> dict[str, Any]:
    """OpenDota /constants/items → the cache shape of opendota.item_constants."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    by_id: dict[str, str] = {}
    items: dict[str, dict[str, Any]] = {}
    for key, item in raw.items():
        if not isinstance(item, dict):
            continue
        if item.get("id") is not None:
            by_id[str(item["id"])] = key
        items[key] = {
            "name": item.get("dname") or key,
            "cost": item.get("cost") or 0,
            "assembled": bool(item.get("components")),
            "components": [c for c in item.get("components") or [] if isinstance(c, str)],
        }
    return {"by_id": by_id, "items": items}


def _cards(answer: dict[str, Any]) -> list[tuple[str, Any, Any, Any]]:
    cards: list[tuple[str, Any, Any, Any]] = []
    advice = answer.get("recommendation")
    if isinstance(advice, dict) and advice.get("action"):
        cards.append(("advice", advice.get("action"), advice.get("action"), advice.get("reason")))
    for item in answer.get("timer_strip") or []:
        if "aegis" in str(item.get("kind")):
            cards.append(("strip", item.get("id"), item.get("label"), item.get("at_label")))
    hint = answer.get("map_hint")
    if isinstance(hint, dict):
        cards.append(("hint", hint.get("id"), hint.get("title"), hint.get("hint")))
    death = answer.get("death_screen")
    if isinstance(death, dict):
        cards.append(("death", death.get("id"), " | ".join(death.get("lines") or []), None))
    return cards


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("recording", type=Path)
    parser.add_argument("--out", type=Path, help="also write the cards as JSON lines")
    parser.add_argument("--items", type=Path, help="OpenDota /api/constants/items JSON")
    parser.add_argument("--lang", default="uk", choices=("uk", "en"))
    parser.add_argument("--from", dest="since", default="-2:00", help="print from this clock")
    parser.add_argument("--until", help="stop after this clock (a prefix of the match)")
    parser.add_argument("--audit", type=Path, help="write the card audit as JSON lines")
    parser.add_argument("--review", type=Path, help="write logged vs current cards (Markdown)")
    args = parser.parse_args()
    until = None
    if args.until:
        until = -_clock(args.until[1:]) if args.until.startswith("-") else _clock(args.until)

    for name in CLOCKED:
        module = importlib.import_module(name)
        if getattr(module, "datetime", None) is datetime:
            module.datetime = ReplayDateTime  # type: ignore[attr-defined]

    from fastapi.testclient import TestClient
    from replay_outcomes import historical_use, snapshot_row

    from app.gsi_state import normalize_gsi_payload
    from app.local_api_auth import LOCAL_API_AUTH, LOCAL_API_URL
    from app.main import app
    from app.match_records import MATCH_RECORDS
    from app.player_api import PLAYER_SERVICE
    from app.player_service import ITEM_CONSTANTS_KEY

    PLAYER_SERVICE.configure(
        Path(tempfile.mkdtemp(prefix="wardly-replay-data-")), client=None, auto_start=False
    )
    MATCH_RECORDS.set_enabled(False)
    if args.items:
        PLAYER_SERVICE.store.cache_set(ITEM_CONSTANTS_KEY, _item_constants(args.items))
    client = TestClient(
        app, base_url=LOCAL_API_URL, headers=LOCAL_API_AUTH.headers, client=("127.0.0.1", 50000)
    )
    token = os.environ["DOTA_AI_GSI_TOKEN"]
    since = -_clock(args.since[1:]) if args.since.startswith("-") else _clock(args.since)
    seen: set[tuple[str, Any]] = set()
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    logged: list[dict[str, Any]] = []
    last_raw: dict[str, Any] | None = None
    withdrawn_seen: dict[str, Any] | None = None
    first: float | None = None
    polled: float | None = None

    def poll(wall: float, clock: Any) -> dict[str, Any]:
        nonlocal withdrawn_seen
        answer = client.get(f"/overlay/recommendation?lang={args.lang}").json()
        withdrawn = answer.get("withdrawn_advice")
        if withdrawn and withdrawn != withdrawn_seen:
            audit.append({"kind": "withdrawn", "clock": clock, "w": wall, **withdrawn})
        withdrawn_seen = withdrawn
        advice = answer.get("recommendation")
        if answer.get("new_advice") and isinstance(advice, dict):
            basis = answer.get("advice_basis") or {}
            state = client.get("/state/current").json().get("state") or {}
            extra = state.get("extra_context") or {}
            observed = basis.get("observed_at")
            audit.append(
                {
                    "kind": "advice",
                    "clock": clock,
                    "w": wall,
                    "decision_point": answer.get("decision_point"),
                    "action": advice.get("action_en") or advice.get("action"),
                    "reason": advice.get("reason"),
                    "basis": basis,
                    "status_source": extra.get("status_source"),
                    # Seconds between the snapshot the card stands on and
                    # this poll (replay clock).
                    "data_age_s": round(
                        (BASE + timedelta(seconds=NOW["t"])).timestamp() - observed, 2
                    )
                    if isinstance(observed, (int, float))
                    else None,
                    "evidence": _evidence(last_raw or {}),
                    # The recording's `w` of the snapshot the card stands on.
                    "decision_w": round(first + observed - BASE.timestamp(), 3)
                    if isinstance(observed, (int, float)) and first is not None
                    else None,
                }
            )
        for kind, card_id, title, text in _cards(answer):
            if (kind, card_id) in seen:
                continue
            seen.add((kind, card_id))
            rows.append({"clock": clock, "kind": kind, "id": card_id, "title": title, "text": text})
        return answer

    racing: list[dict[str, Any]] = []
    last_clock: Any = None
    snapshots: list[dict[str, Any]] = []
    plan_rows: dict[str, dict[str, Any]] = {}
    memory_module = importlib.import_module("app.match_memory")
    with _open(args.recording) as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("k") == "advice":
                # What the version that played the match showed, with the
                # nearest preceding snapshot (by `w`) as its evidence, and what
                # the current code shows at that moment (the overlay polled then).
                entry = {**record, "evidence": _evidence(last_raw or {})}
                if first is not None and isinstance(record.get("w"), (int, float)):
                    NOW["t"] = float(record["w"]) - first
                    entry["moment"] = poll(float(record["w"]), last_clock)
                logged.append(entry)
                racing.append(entry)
                continue
            if record.get("k") != "gsi":
                continue
            wall = float(record["w"])
            for entry in racing:
                # Recordings before 0.60 stamped a GSI line after publishing it:
                # a card stamped a few ms before this line may stand on it.
                gap = round(wall - float(entry.get("w") or 0), 2)
                if not entry.get("snap") and 0 <= gap <= 0.05:
                    entry["race_evidence"] = _evidence(record["p"])
                    entry["race_gap"] = gap
            racing = []
            first = wall if first is None else first
            NOW["t"] = wall - first
            payload = dict(record["p"])
            last_raw = record["p"]
            clock = (payload.get("map") or {}).get("clock_time")
            last_clock = clock
            if until is not None and isinstance(clock, int) and clock > until:
                break
            payload["auth"] = {"token": token}
            client.post("/gsi", json=payload)
            # The plan's own record (live_plan.py), kept as it grows (the
            # match memory resets after the game): how each plan ended and
            # each reassessment after a major item was received; and each farm
            # target (farm_map.py) with how it ended.
            memory = memory_module.MATCH_MEMORY
            plan = memory.plan
            for kind, entries in (
                ("plan", plan.history),
                ("reassessment", plan.reassessments),
                ("farm", memory.farm_map.history),
            ):
                for entry in list(entries)[-3:]:  # at most a few new per snapshot
                    key = json.dumps([kind, entry], sort_keys=True, default=str)
                    row = {"kind": kind, **entry}
                    if kind == "farm":  # the target's own kind is wave or camp
                        row = {**entry, "target": entry.get("kind"), "kind": kind}
                    plan_rows.setdefault(key, row)
            normalized = normalize_gsi_payload(record["p"])
            snapshots.append(
                snapshot_row(wall, normalized.get("extra_context") or {}, normalized.get("hero"))
            )
            if polled is not None and wall - polled < 1.0:
                continue
            polled = wall
            poll(wall, clock)
    for row in rows:
        clock = row["clock"] if isinstance(row["clock"], int) else 0
        if clock < since:
            continue
        sign = "-" if clock < 0 else " "
        print(
            f"{sign}{abs(clock) // 60:>2}:{abs(clock) % 60:02d} {row['kind']:6} "
            f"{row['title']}" + (f" — {row['text']}" if row["text"] else "")
        )
    for row in audit:
        if row["kind"] != "advice":
            continue
        basis = row.get("basis") or {}
        source = row.get("status_source") or {}
        flags = source.get("flags") if source.get("kind") not in {None, "none"} else ()
        row["historical"] = historical_use(
            snapshots,
            tool=basis.get("tool"),
            decision_w=row.get("decision_w"),
            shown_w=float(row["w"]),
            status_flags=flags or (),
        )
    audit += plan_rows.values()
    if args.audit:
        args.audit.write_text(
            "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in audit),
            encoding="utf-8",
        )
    if args.review:
        if until is not None:
            logged = [
                c for c in logged if not isinstance(c.get("clock"), int) or c["clock"] <= until
            ]
        args.review.write_text(_review(logged, audit), encoding="utf-8")
    if args.out:
        args.out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
