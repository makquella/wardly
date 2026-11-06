"""fetch_recordings.py - download the match recordings players sent to the
developer (services/api, docs/DATA_PLAN.md stage 5) for offline tuning.

    WARDLY_ADMIN_TOKEN=... python scripts/fetch_recordings.py [--split tune|holdout] [--dry-run]

Files land in backend/session_records/cloud/<split>/<id>.jsonl.gz (git-ignored)
and are read by `replay_recording.py`, `farm_outcomes.py` and
`replay_outcomes.py` like a local recording. A file already downloaded is
skipped, so the script can run again and again.

The split is fixed by the server from the recording's number (about a quarter
is `holdout`): tune rules on `tune` only, then check them once on `holdout`.
The admin token comes only from the environment, never from an argument, and
is never printed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "backend" / "session_records" / "cloud"
DEFAULT_API = "https://api.luhovyimvp.dev"
SPLITS = ("tune", "holdout")
_ID = re.compile(r"S-[2-9A-HJ-NP-Z]{6}")


def parse_listing(body: Any) -> list[dict[str, Any]]:
    """The recordings of an /v1/admin/sessions answer; rows with a bad id or split are dropped."""
    rows = body.get("sessions") if isinstance(body, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if (
            isinstance(row, dict)
            and _ID.fullmatch(str(row.get("id")))
            and row.get("split") in SPLITS
        ):
            out.append(row)
    return out


def destination(out: Path, split: str, record_id: str) -> Path:
    if split not in SPLITS or not _ID.fullmatch(record_id):
        raise ValueError("bad recording id or split")
    return out / split / f"{record_id}.jsonl.gz"


def pending(rows: list[dict[str, Any]], out: Path) -> list[dict[str, Any]]:
    """Recordings not downloaded yet (in either split folder)."""
    return [
        row
        for row in rows
        if not any(destination(out, side, row["id"]).exists() for side in SPLITS)
    ]


def looks_anonymized(data: bytes) -> bool:
    """The first line is the anonymized meta line (the server checked the same)."""
    try:
        first = gzip.decompress(data).split(b"\n", 1)[0]
        meta = json.loads(first)
    except (OSError, EOFError, ValueError):
        return False
    return meta.get("k") == "meta" and meta.get("anonymized") is True


def table(rows: list[dict[str, Any]]) -> str:
    lines = [f"{'id':<9} {'split':<8} {'hero':<24} {'min':>4} {'MB':>6}  version"]
    for row in rows:
        hero = str(row.get("hero") or "").removeprefix("npc_dota_hero_")
        size = (row.get("size") or 0) / 1024 / 1024
        lines.append(
            f"{row['id']:<9} {row['split']:<8} {hero:<24} {row.get('minutes') or 0:>4} "
            f"{size:>6.1f}  {row.get('version') or ''}"
        )
    return "\n".join(lines)


def _get(url: str, token: str) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - https API
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--split", choices=SPLITS, help="only this side")
    parser.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--api", default=os.environ.get("WARDLY_API_URL", DEFAULT_API))
    args = parser.parse_args()
    token = os.environ.get("WARDLY_ADMIN_TOKEN", "").strip()
    if not token:
        print("Set WARDLY_ADMIN_TOKEN in the environment.", file=sys.stderr)
        return 2
    api = args.api.rstrip("/")
    query = f"?split={args.split}" if args.split else ""
    try:
        rows = parse_listing(json.loads(_get(f"{api}/v1/admin/sessions{query}", token)))
    except urllib.error.HTTPError as error:
        # 404 is also what a wrong token gets: the server hides the admin routes.
        print(f"The server answered HTTP {error.code}; check the token.", file=sys.stderr)
        return 1
    except (urllib.error.URLError, ValueError) as error:
        print(f"Could not read the list: {error}", file=sys.stderr)
        return 1
    todo = pending(rows, args.out)
    print(f"{len(rows)} on the server, {len(todo)} new")
    if todo:
        print(table(todo))
    if args.dry_run:
        return 0
    failed = 0
    for row in todo:
        target = destination(args.out, row["split"], row["id"])
        try:
            data = _get(f"{api}/v1/admin/session/{row['id']}", token)
        except (urllib.error.URLError, OSError) as error:
            print(f"{row['id']}: not downloaded ({error})", file=sys.stderr)
            failed += 1
            continue
        if not looks_anonymized(data):
            print(f"{row['id']}: skipped, the file is not an anonymized recording", file=sys.stderr)
            failed += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
