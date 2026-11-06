"""
rule_table.py - one table per rule over every recording players sent: an OFFLINE
tuning aid, run after the replay. Nothing here feeds the live decisions.

Every recording of `tune` and of `holdout` (fetch_recordings.py puts them in
backend/session_records/cloud/<split>/*.jsonl.gz) is replayed through the CURRENT
code (replay_recording.py, one subprocess per recording: the replay mutates
module globals), and the audit rows are counted per rule, the two splits apart:

- advice cards: the rule is the card's decision point; a repeat is a card of the
  same rule shown again within REPEAT_WINDOW seconds of the previous card of
  that rule (wall time `w`), i.e. a second card for the same episode;
  withdrawn = cards taken back while held (the withdrawn row names the card's
  decision point). Checkable cards name a tool (replay_outcomes.py): used after
  = the recorded use came after the card was shown (or in the sampling interval
  that holds the show), done before = the action was already done when the card
  appeared, not used = no recorded use in the card's episode;
- farm cards (`FARM:wave`, `FARM:camp`): used after = the recorded player went
  there (farm_outcomes.py); a repeat is the same target kind again within
  REPEAT_WINDOW game seconds;
- map hints, the strip and death screens (`HINT:<family>`, `STRIP:<family>`,
  `DEATH`): cards and repeats only (game seconds), nothing to check. The family
  is the id without its per-instance part («fight@1234» -> fight); each death
  is its own card (the replay numbers death screens by the death counter).

The recorded player never saw these cards, so the words are «the recorded use
after the card» and «went there», never «followed»: the table says what the
recorded match did near a card, not that a card changed anything.

    cd backend
    .venv/bin/python ../scripts/rule_table.py [--cloud DIR] [--tune PATH]... [--holdout PATH]...
        [--jobs N] [--work DIR [--reuse]] [--json OUT.json]
        [--compare BASE.json [--gate]]

Rules are tuned on `tune`. A change is accepted only if `holdout` did not get
worse: save `--json base.json` on the code before the change, then run
`--compare base.json --gate` after it (exit code 3 when holdout is worse; the
thresholds are the constants below; tune deltas are printed, never gate). An
`ALL` row (every card of every rule) is gated with the same thresholds, so noise
from a new rule counts; a rule that is `new` or `gone` is only information. The
gate refuses (exit 2) when the two runs did not use the same holdout recordings. Do not
move a recording between sides after looking at it (docs/LIVE_ADVICE_AUDIT.md).

Exit codes: 0 done, 1 a replay failed (the rest is still printed), 2 bad
arguments, no recordings at all, or a gate over different holdout recordings,
3 the gate found holdout worse.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_CLOUD = BACKEND / "session_records" / "cloud"
SPLITS = ("tune", "holdout")
SUFFIXES = (".jsonl.gz", ".jsonl")

# A card of the same rule within this many seconds of the previous one is a
# repeat: a second card for the same episode (wall seconds for advice, game
# seconds for farm cards and hints).
REPEAT_WINDOW = 60.0
# Decision outcomes (replay_outcomes.py) that cannot be checked.
UNCHECKABLE = {"no_tool", "decision_unknown"}
USED_AFTER = {"after_show", "around_show"}
# The gate: holdout is WORSE for a rule when, with at least MIN_CARDS cards
# (checkable cards for the used-after share) in both runs, the used-after share
# fell by USED_DROP, the repeat share rose by REPEAT_RISE (both in share points),
# or the cards per 10 minutes rose by NOISE_RISE (a fraction: more noise).
MIN_CARDS = 5
USED_DROP = 0.10
REPEAT_RISE = 0.10
NOISE_RISE = 0.50
REPLAY_TIMEOUT = 1800  # seconds per recording
JSON_VERSION = 1
UNMATCHED = "WITHDRAWN:unmatched"
UNCHECKED_PREFIXES = ("HINT:", "STRIP:", "DEATH")
ALL_RULE = "ALL"


class InputError(Exception):
    """Bad arguments or files: exit code 2."""


# --- inputs ---------------------------------------------------------------


def _files_of(path: Path) -> list[Path]:
    """A recording file, or the recordings directly inside a directory."""
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.is_file() and p.name.endswith(SUFFIXES))
    if path.is_file():
        return [path]
    raise InputError(f"not found: {path}")


def discover(
    cloud: Path | None, tune: Sequence[Path] = (), holdout: Sequence[Path] = ()
) -> dict[str, list[Path]]:
    """The recordings of each split: the cloud folder's tune/ and holdout/, plus
    explicit files or directories. A file named on both sides is an error."""
    found: dict[str, list[Path]] = {side: [] for side in SPLITS}
    for side, extra in (("tune", tune), ("holdout", holdout)):
        paths: list[Path] = []
        if cloud is not None and (cloud / side).is_dir():
            paths += _files_of(cloud / side)
        for path in extra:
            paths += _files_of(path)
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found[side].append(resolved)
    clash = set(found["tune"]) & set(found["holdout"])
    if clash:
        names = ", ".join(sorted(p.name for p in clash))
        raise InputError(f"a recording cannot be both tune and holdout: {names}")
    return found


def sha12(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:12]


def work_names(paths: Sequence[Path]) -> list[str]:
    """A unique file stem per recording of one split for the work folder."""
    names: list[str] = []
    for path in paths:
        stem = path.name
        for suffix in SUFFIXES:
            stem = stem.removesuffix(suffix)
        name, number = stem, 1
        while name in names:
            number += 1
            name = f"{stem}-{number}"
        names.append(name)
    return names


# --- counting (pure) --------------------------------------------------------


def new_counts() -> dict[str, Any]:
    return {
        "cards": 0,
        "repeats": 0,
        "withdrawn": 0,
        "checkable": 0,
        "used_after": 0,
        "already_done": 0,
        "not_used": 0,
        "died": 0,
        "delays": [],  # upper bound of delay_from_shown of each used_after card
    }


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def count_repeats(times: Iterable[float], window: float = REPEAT_WINDOW) -> int:
    """Cards within `window` of the previous card (each card against the one before)."""
    ordered = sorted(times)
    return sum(
        1 for before, after in zip(ordered, ordered[1:], strict=False) if after - before <= window
    )


def advice_counts(audit: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per decision point: new cards, repeats, withdrawn, recorded-use outcomes."""
    rules: dict[str, dict[str, Any]] = {}
    times: dict[str, list[float]] = {}
    for row in audit:
        kind = row.get("kind")
        if kind not in {"advice", "withdrawn"}:
            continue
        point = row.get("decision_point")
        rule = str(point) if point else (UNMATCHED if kind == "withdrawn" else "UNKNOWN")
        counts = rules.setdefault(rule, new_counts())
        if kind == "withdrawn":
            counts["withdrawn"] += 1
            continue
        counts["cards"] += 1
        wall = _number(row.get("w"))
        if wall is not None:
            times.setdefault(rule, []).append(wall)
        historical = row.get("historical")
        outcome = historical.get("outcome") if isinstance(historical, dict) else None
        if not outcome or outcome in UNCHECKABLE:
            continue
        counts["checkable"] += 1
        if outcome in USED_AFTER:
            counts["used_after"] += 1
            delay = historical.get("delay_from_shown")
            if isinstance(delay, list) and len(delay) == 2 and _number(delay[1]) is not None:
                counts["delays"].append(float(delay[1]))
        elif outcome == "already_done":
            counts["already_done"] += 1
        elif outcome == "not_used_in_episode":
            counts["not_used"] += 1
        elif outcome == "died_before_use":
            counts["died"] += 1
    for rule, stamps in times.items():
        rules[rule]["repeats"] = count_repeats(stamps)
    return rules


def farm_counts(
    audit: Iterable[dict[str, Any]], recording_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """FARM:wave / FARM:camp; «used after» is farm_outcomes' `went`."""
    from farm_outcomes import outcome

    rules: dict[str, dict[str, Any]] = {}
    times: dict[str, list[float]] = {}
    for card in audit:
        if card.get("kind") != "farm":
            continue
        since = _number(card.get("since"))
        if since is None or _number(card.get("x")) is None or _number(card.get("y")) is None:
            continue
        rule = f"FARM:{card.get('target') or 'unknown'}"
        counts = rules.setdefault(rule, new_counts())
        counts["cards"] += 1
        times.setdefault(rule, []).append(since)
        counts["checkable"] += 1
        if outcome(recording_rows, card)["went"]:
            counts["used_after"] += 1
        else:
            counts["not_used"] += 1
    for rule, stamps in times.items():
        rules[rule]["repeats"] = count_repeats(stamps)
    return rules


def hint_family(kind: str, card_id: Any) -> str:
    """The stable part of a card id: «fight@1234» -> fight, «missing:Axe@600» ->
    missing (the hero is per instance), «note_x» stays (one note per plan)."""
    if kind == "death":
        return "DEATH"
    family = str(card_id or "").split("@", 1)[0].split(":", 1)[0]
    prefix = "STRIP" if kind == "strip" else "HINT"
    return f"{prefix}:{family or 'unknown'}"


def hint_counts(cards: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map hints, strip and death screens of a `--out` cards file (game seconds)."""
    rules: dict[str, dict[str, Any]] = {}
    times: dict[str, list[float]] = {}
    for row in cards:
        kind = row.get("kind")
        if kind not in {"hint", "strip", "death"}:
            continue
        rule = hint_family(str(kind), row.get("id"))
        rules.setdefault(rule, new_counts())["cards"] += 1
        clock = _number(row.get("clock"))
        if clock is not None:
            times.setdefault(rule, []).append(clock)
    for rule, stamps in times.items():
        rules[rule]["repeats"] = count_repeats(stamps)
    return rules


def merge_counts(into: dict[str, dict[str, Any]], other: dict[str, dict[str, Any]]) -> None:
    for rule, counts in other.items():
        target = into.setdefault(rule, new_counts())
        for key, value in counts.items():
            if key == "delays":
                target[key].extend(value)
            else:
                target[key] += value


def analyse(
    recording_rows: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rules = advice_counts(audit)
    merge_counts(rules, farm_counts(audit, recording_rows))
    merge_counts(rules, hint_counts(cards))
    return rules


def game_minutes(recording_rows: list[dict[str, Any]]) -> float:
    """Minutes of play (the clock from 0:00 to the last second recorded)."""
    clocks = [r["clock"] for r in recording_rows if isinstance(r.get("clock"), int)]
    return round(max(0, max(clocks)) / 60, 2) if clocks else 0.0


def finalize(rules: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """JSON-safe: the delay list becomes its median."""
    out: dict[str, dict[str, Any]] = {}
    for rule, counts in rules.items():
        row = {k: v for k, v in counts.items() if k != "delays"}
        delays = counts.get("delays") or []
        row["median_delay_s"] = round(statistics.median(delays), 2) if delays else None
        out[rule] = row
    return out


# --- the run ------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def replay_one(recording: Path, audit: Path, cards: Path) -> None:
    """Replay one recording in its own process; raises RuntimeError with the tail of stderr."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "replay_recording.py"),
        str(recording),
        "--lang",
        "en",
        "--audit",
        str(audit),
        "--out",
        str(cards),
    ]
    try:
        done = subprocess.run(  # noqa: S603 - our own script, fixed argv
            command,
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=REPLAY_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"timed out after {REPLAY_TIMEOUT} s") from error
    if done.returncode != 0 or not audit.exists() or not cards.exists():
        tail = "\n".join((done.stderr or "").strip().splitlines()[-5:])
        raise RuntimeError(f"replay exited with {done.returncode}\n{tail}".strip())


def process(recording: Path, work: Path, name: str, *, reuse: bool) -> dict[str, Any]:
    """Replay (unless reused) and count one recording."""
    from farm_outcomes import _rows

    audit, cards = work / f"{name}.audit.jsonl", work / f"{name}.cards.jsonl"
    info: dict[str, Any] = {"name": name, "sha256_12": sha12(recording)}
    try:
        if not (reuse and audit.exists() and cards.exists()):
            replay_one(recording, audit, cards)
        rows = _rows(recording)
        rules = analyse(rows, _read_jsonl(audit), _read_jsonl(cards))
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        return {**info, "failed": str(error), "minutes": 0.0, "rules": {}}
    return {**info, "failed": None, "minutes": game_minutes(rows), "rules": rules}


def run_split(paths: Sequence[Path], work: Path, *, jobs: int, reuse: bool) -> list[dict[str, Any]]:
    names = work_names(paths)
    work.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = [
            pool.submit(process, path, work, name, reuse=reuse)
            for path, name in zip(paths, names, strict=True)
        ]
        return [future.result() for future in futures]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """One split: recordings, minutes and the counts per rule (delays kept)."""
    rules: dict[str, dict[str, Any]] = {}
    for result in results:
        merge_counts(rules, result["rules"])
    done = [r for r in results if not r["failed"]]
    return {
        "recordings": [
            {"name": r["name"], "sha256_12": r["sha256_12"], "minutes": r["minutes"]}
            | ({"failed": r["failed"]} if r["failed"] else {})
            for r in results
        ],
        "count": len(done),
        "minutes": round(sum(r["minutes"] for r in done), 2),
        "rules": rules,
    }


def git_state() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(  # noqa: S603,S607 - read-only git
                ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    return {
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
    }


def to_json(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": JSON_VERSION,
        **git_state(),
        "repeat_window_s": REPEAT_WINDOW,
        "splits": {
            side: {**data, "rules": finalize(data["rules"])} for side, data in summary.items()
        },
    }


# --- the table ------------------------------------------------------------------


def per_10(counts: dict[str, Any], minutes: float) -> float | None:
    return counts["cards"] / minutes * 10 if minutes > 0 else None


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _cell(part: int, whole: int) -> str:
    return f"{part} ({round(part / whole * 100)}%)" if whole else str(part)


HEADS = (
    "cards",
    "/10 min",
    "repeats",
    "checkable",
    "used after",
    "done before",
    "not used",
    "withdrawn",
)


def render_table(summary: dict[str, dict[str, Any]]) -> str:
    """Markdown: one row per rule, the two splits side by side."""
    empty = new_counts()
    names: set[str] = set()
    for side in SPLITS:
        names |= set(summary[side]["rules"])
    rules = sorted(
        names,
        key=lambda r: (
            -summary["tune"]["rules"].get(r, empty)["cards"],
            -summary["holdout"]["rules"].get(r, empty)["cards"],
            r,
        ),
    )
    lines = [
        "The recorded player never saw these cards: «used after» = the recorded use came after "
        "the card was shown (farm cards: the recorded player went there); «done before» = "
        "already done when the card appeared; «not used» = no recorded use in the card's "
        f"episode. Repeats: the same rule again within {REPEAT_WINDOW:.0f} s.",
        "",
    ]
    for side in SPLITS:
        data = summary[side]
        lines.append(f"- {side}: {data['count']} recordings, {data['minutes']:.0f} min")
    header = ["rule"] + [f"{side} {head}" for side in SPLITS for head in HEADS]
    lines += ["", "| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for rule in rules:
        row = [rule]
        for side in SPLITS:
            c = summary[side]["rules"].get(rule, empty)
            rate = per_10(c, summary[side]["minutes"])
            if rule.startswith(UNCHECKED_PREFIXES):
                checks = ["—", "—", "—", "—"]
            else:
                whole = c["checkable"]
                checks = [
                    str(whole),
                    _cell(c["used_after"], whole),
                    _cell(c["already_done"], whole),
                    _cell(c["not_used"], whole),
                ]
            row += [
                str(c["cards"]),
                f"{rate:.1f}" if rate is not None else "—",
                _cell(c["repeats"], c["cards"]),
                *checks,
                str(c["withdrawn"]),
            ]
        lines.append("| " + " | ".join(row) + " |")
    if not rules:
        lines.append("| (no cards) |" + " |" * (len(header) - 1))
    return "\n".join(lines)


# --- compare / gate ----------------------------------------------------------------


def _metrics(counts: dict[str, Any], minutes: float) -> dict[str, float | None]:
    return {
        "per_10": per_10(counts, minutes),
        "repeat_share": _share(counts["repeats"], counts["cards"]),
        "used_share": _share(counts["used_after"], counts["checkable"]),
    }


def worse_reasons(
    base: dict[str, Any], new: dict[str, Any], base_minutes: float, new_minutes: float
) -> list[str]:
    """Why holdout got worse for one rule (empty: not worse, or too few cards)."""
    reasons: list[str] = []
    b, n = _metrics(base, base_minutes), _metrics(new, new_minutes)
    if (
        min(base["checkable"], new["checkable"]) >= MIN_CARDS
        and b["used_share"] is not None
        and n["used_share"] is not None
        and b["used_share"] - n["used_share"] >= USED_DROP - 1e-9
    ):
        reasons.append(f"used after {b['used_share']:.0%} -> {n['used_share']:.0%}")
    if min(base["cards"], new["cards"]) >= MIN_CARDS:
        if (
            b["repeat_share"] is not None
            and n["repeat_share"] is not None
            and n["repeat_share"] - b["repeat_share"] >= REPEAT_RISE - 1e-9
        ):
            reasons.append(f"repeats {b['repeat_share']:.0%} -> {n['repeat_share']:.0%}")
        if (
            b["per_10"]
            and n["per_10"] is not None
            and n["per_10"] >= b["per_10"] * (1 + NOISE_RISE) - 1e-9
        ):
            reasons.append(f"cards per 10 min {b['per_10']:.1f} -> {n['per_10']:.1f}")
    return reasons


def total_counts(rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The ALL row: every card of every rule, summed."""
    total = {k: v for k, v in new_counts().items() if k != "delays"}
    for counts in rules.values():
        for key in total:
            total[key] += counts.get(key, 0)
    return total


def compare_runs(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Per rule and split the base and new numbers; holdout verdicts. Both
    arguments are `to_json` documents."""
    warnings: list[str] = []
    same_holdout = True
    for side in SPLITS:
        old = {r["sha256_12"] for r in base["splits"][side]["recordings"] if not r.get("failed")}
        cur = {r["sha256_12"] for r in new["splits"][side]["recordings"] if not r.get("failed")}
        if old != cur:
            same_holdout = same_holdout and side != "holdout"
            warnings.append(
                f"{side}: the two runs did not use the same recordings "
                f"({len(old - cur)} only in base, {len(cur - old)} only in new)"
            )
    empty = {k: v for k, v in new_counts().items() if k != "delays"}
    names: set[str] = set()
    for side in SPLITS:
        names |= set(base["splits"][side]["rules"]) | set(new["splits"][side]["rules"])
    rows = []
    for rule in [ALL_RULE, *sorted(names)]:
        row: dict[str, Any] = {"rule": rule, "worse": [], "note": ""}
        for side in SPLITS:
            if rule == ALL_RULE:
                b = total_counts(base["splits"][side]["rules"])
                n = total_counts(new["splits"][side]["rules"])
            else:
                b = {**empty, **base["splits"][side]["rules"].get(rule, {})}
                n = {**empty, **new["splits"][side]["rules"].get(rule, {})}
            base_minutes, new_minutes = (
                base["splits"][side]["minutes"],
                new["splits"][side]["minutes"],
            )
            row[side] = {
                "base": b,
                "new": n,
                "base_metrics": _metrics(b, base_minutes),
                "new_metrics": _metrics(n, new_minutes),
            }
            if side == "holdout":
                row["worse"] = worse_reasons(b, n, base_minutes, new_minutes)
                if rule != ALL_RULE and b["cards"] == 0 < n["cards"]:
                    row["note"] = "new"
                elif rule != ALL_RULE and n["cards"] == 0 < b["cards"]:
                    row["note"] = "gone"
        rows.append(row)
    return {
        "rows": rows,
        "warnings": warnings,
        "same_holdout": same_holdout,
        "worse": [{"rule": r["rule"], "reasons": r["worse"]} for r in rows if r["worse"]],
    }


def _arrow(old: float | None, new: float | None, fmt: str) -> str:
    left = format(old, fmt) if old is not None else "—"
    right = format(new, fmt) if new is not None else "—"
    return f"{left} -> {right}"


def render_compare(result: dict[str, Any]) -> str:
    lines = [f"WARNING: {w}" for w in result["warnings"]]
    header = [
        "rule",
        "tune cards",
        "tune used after",
        "tune repeats",
        "holdout cards",
        "holdout /10 min",
        "holdout used after",
        "holdout repeats",
        "holdout verdict",
    ]
    lines += ["", "| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    for row in result["rows"]:
        cells = [row["rule"]]
        for side in SPLITS:
            b, n = row[side]["base"], row[side]["new"]
            bm, nm = row[side]["base_metrics"], row[side]["new_metrics"]
            cells.append(f"{b['cards']} -> {n['cards']}")
            if side == "holdout":
                cells.append(_arrow(bm["per_10"], nm["per_10"], ".1f"))
            cells.append(_arrow(bm["used_share"], nm["used_share"], ".0%"))
            cells.append(_arrow(bm["repeat_share"], nm["repeat_share"], ".0%"))
        verdict = "WORSE: " + "; ".join(row["worse"]) if row["worse"] else row["note"] or "ok"
        cells.append(verdict)
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        f"Holdout is WORSE for {len(result['worse'])} rule(s)."
        if result["worse"]
        else "Holdout did not get worse."
    )
    lines.append(
        f"(ALL = every card of every rule; `new` / `gone` rules are information only. Checked with at least {MIN_CARDS} cards in both runs: used-after share down "
        f"{USED_DROP * 100:.0f} points, repeat share up {REPEAT_RISE * 100:.0f} points, "
        f"or cards per 10 min up {NOISE_RISE * 100:.0f} %. Tune deltas never gate.)"
    )
    return "\n".join(lines)


def load_base(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != JSON_VERSION:
            raise ValueError(f"version {data['version']}")
        for side in SPLITS:
            if not isinstance(data["splits"][side]["rules"], dict):
                raise ValueError("rules")
            if not isinstance(data["splits"][side]["recordings"], list):
                raise ValueError("recordings")
            if not isinstance(data["splits"][side]["minutes"], (int, float)):
                raise ValueError("minutes")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise InputError(f"{path} is not a rule_table --json file ({error})") from error
    return data


# --- main ----------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--cloud", type=Path, default=DEFAULT_CLOUD, help="folder with tune/ holdout/"
    )
    parser.add_argument(
        "--tune", type=Path, action="append", default=[], help="extra file or folder"
    )
    parser.add_argument(
        "--holdout", type=Path, action="append", default=[], help="extra file or folder"
    )
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument(
        "--work", type=Path, help="keep the replay outputs here (default: temporary)"
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="with --work: skip the replay of a recording whose outputs exist there "
        "(only for iterating on the table code; the code under test is NOT replayed again)",
    )
    parser.add_argument("--json", type=Path, dest="json_out", help="save the full numbers")
    parser.add_argument(
        "--compare", type=Path, help="a --json file from the code before the change"
    )
    parser.add_argument(
        "--gate", action="store_true", help="with --compare: exit 3 if holdout is worse"
    )
    args = parser.parse_args(argv)
    try:
        if args.reuse and not args.work:
            raise InputError("--reuse needs --work (nothing to reuse in a temporary folder)")
        if args.gate and not args.compare:
            raise InputError("--gate needs --compare BASE.json")
        base = load_base(args.compare) if args.compare else None
        found = discover(args.cloud, args.tune, args.holdout)
    except InputError as error:
        print(f"rule_table: {error}", file=sys.stderr)
        return 2
    if not any(found.values()):
        print(
            f"rule_table: no recordings in {args.cloud}/tune or /holdout and none given with "
            "--tune/--holdout; run scripts/fetch_recordings.py first.",
            file=sys.stderr,
        )
        return 2
    temp = None if args.work else Path(tempfile.mkdtemp(prefix="wardly-rule-table-"))
    work = args.work or temp
    assert work is not None
    try:
        results = {
            side: run_split(found[side], work / side, jobs=args.jobs, reuse=args.reuse)
            for side in SPLITS
        }
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
    failed = [(side, r) for side in SPLITS for r in results[side] if r["failed"]]
    summary = {side: summarize(results[side]) for side in SPLITS}
    print(render_table(summary))
    for side, result in failed:
        print(f"\nFAILED {side} {result['name']}: {result['failed']}", file=sys.stderr)
    document = to_json(summary)
    if args.json_out:
        args.json_out.write_text(
            json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    code = 1 if failed else 0
    if base is not None:
        compared = compare_runs(base, document)
        print("\n" + render_compare(compared))
        if args.gate and not compared["same_holdout"]:
            print(
                "rule_table: --gate refused: the two runs did not use the same holdout "
                "recordings; re-run the base on the same recordings.",
                file=sys.stderr,
            )
            return 2
        if args.gate and compared["worse"]:
            code = 3
    return code


if __name__ == "__main__":
    raise SystemExit(main())
