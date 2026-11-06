"""scripts/fetch_recordings.py: the pure parts (no network)."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_recordings as fetch  # noqa: E402

ROW = {
    "id": "S-ABCDEF",
    "split": "tune",
    "hero": "npc_dota_hero_axe",
    "minutes": 31,
    "size": 3_000_000,
    "version": "0.63.0",
}


def test_listing_keeps_only_well_formed_rows():
    body = {
        "ok": True,
        "sessions": [
            ROW,
            {**ROW, "id": "S-GHJKLM", "split": "holdout"},
            {**ROW, "id": "../../x"},
            {**ROW, "id": "S-OOOOOO"},  # 0 and O are not in the id alphabet
            {**ROW, "id": "S-NPQRST", "split": "other"},
            "junk",
        ],
    }
    assert [row["id"] for row in fetch.parse_listing(body)] == ["S-ABCDEF", "S-GHJKLM"]
    assert fetch.parse_listing(None) == [] and fetch.parse_listing({"sessions": "x"}) == []


def test_destination_is_inside_the_split_folder(tmp_path):
    assert (
        fetch.destination(tmp_path, "holdout", "S-ABCDEF")
        == tmp_path / "holdout" / "S-ABCDEF.jsonl.gz"
    )
    for split, record_id in (("tune", "../S-ABCDEF"), ("x", "S-ABCDEF")):
        with pytest.raises(ValueError):
            fetch.destination(tmp_path, split, record_id)


def test_downloaded_files_are_skipped(tmp_path):
    other = {**ROW, "id": "S-GHJKLM", "split": "holdout"}
    path = fetch.destination(tmp_path, "tune", "S-ABCDEF")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    assert fetch.pending([ROW, other], tmp_path) == [other]


def test_only_an_anonymized_meta_line_is_accepted():
    def packed(first):
        return gzip.compress((json.dumps(first) + "\n{}\n").encode())

    assert fetch.looks_anonymized(packed({"k": "meta", "anonymized": True}))
    assert not fetch.looks_anonymized(packed({"k": "meta"}))
    assert not fetch.looks_anonymized(b"not gzip")


def test_a_gzip_bomb_is_not_inflated():
    import time
    import tracemalloc

    meta = (json.dumps({"k": "meta", "anonymized": True}) + "\n").encode()
    bomb = gzip.compress(meta + b"\0" * (200 * 1024 * 1024), compresslevel=9)
    assert len(bomb) < 1024 * 1024  # a small download that would inflate to 200 MB
    tracemalloc.start()
    started = time.perf_counter()
    try:
        assert fetch.looks_anonymized(bomb)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 32 * 1024 * 1024, f"inflated {peak} bytes"
    assert time.perf_counter() - started < 2
    # No newline at all in the bomb: still bounded, and refused.
    assert not fetch.looks_anonymized(gzip.compress(b"\0" * (100 * 1024 * 1024), compresslevel=9))


def test_the_table_lists_hero_split_and_size():
    text = fetch.table([ROW])
    assert "S-ABCDEF" in text and "tune" in text and "axe" in text and "2.9" in text
