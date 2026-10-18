"""Replay a Wardly match recording through the current backend and print every
distinct overlay card (advice, map hint, death screen, Aegis on the strip) with
its match clock — to see what the coach would say in that game now.

Recordings: Settings → «Keep match recordings for a week» (gzip JSON lines,
match_records.py). They hold the player's game: keep them on the computer,
never in the repository. Run from backend/ with its venv:

    cd backend
    .venv/bin/python ../scripts/replay_recording.py <recording.jsonl.gz> [--out cards.jsonl]
        [--items items.json] [--lang uk|en] [--from 20:00]

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
    args = parser.parse_args()

    for name in CLOCKED:
        module = importlib.import_module(name)
        if getattr(module, "datetime", None) is datetime:
            module.datetime = ReplayDateTime  # type: ignore[attr-defined]

    from fastapi.testclient import TestClient

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
    first: float | None = None
    polled: float | None = None
    with gzip.open(args.recording, "rt", encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("k") != "gsi":
                continue
            wall = float(record["w"])
            first = wall if first is None else first
            NOW["t"] = wall - first
            payload = dict(record["p"])
            payload["auth"] = {"token": token}
            client.post("/gsi", json=payload)
            if polled is not None and wall - polled < 1.0:
                continue
            polled = wall
            clock = (payload.get("map") or {}).get("clock_time")
            answer = client.get(f"/overlay/recommendation?lang={args.lang}").json()
            for kind, card_id, title, text in _cards(answer):
                if (kind, card_id) in seen:
                    continue
                seen.add((kind, card_id))
                rows.append(
                    {"clock": clock, "kind": kind, "id": card_id, "title": title, "text": text}
                )
    for row in rows:
        clock = row["clock"] if isinstance(row["clock"], int) else 0
        if clock < since:
            continue
        sign = "-" if clock < 0 else " "
        print(
            f"{sign}{abs(clock) // 60:>2}:{abs(clock) % 60:02d} {row['kind']:6} "
            f"{row['title']}" + (f" — {row['text']}" if row["text"] else "")
        )
    if args.out:
        args.out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
