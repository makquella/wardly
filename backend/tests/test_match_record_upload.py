"""The anonymized copy of a recording sent to the developer (app/match_record_upload.py)."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest
from match_fixtures import gsi_match_stream

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from app import match_record_upload
from app.match_record_upload import MAX_UPLOAD_BYTES, UploadError, upload_copy

# Values planted in an old-style recording; none may reach the upload.
NICK = "PlantedNickname"
STEAM = "76561198012345678"
ACCOUNT = "52079950"
MATCH = "8012345678"
TOKEN = "planted-gsi-token-xyz"
CHAT = "planted chat line"
PERSONA = "PlantedPersona"
START = 1_790_000_000  # a real-looking Unix time: the match must not be dated by it


def _write(path: Path, lines: list[dict]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


def _payload(clock: int, **extra) -> dict:
    return {
        "auth": {"token": TOKEN},
        "provider": {"name": "Dota 2", "appid": 570, "timestamp": START + clock},
        "map": {
            "matchid": MATCH,
            "clock_time": clock,
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
        },
        "player": {"steamid": STEAM, "accountid": ACCOUNT, "name": NICK, "kills": 1},
        "previously": {"map": {"matchid": MATCH}, "player": {"persona_name": PERSONA}},
        "hero": {"name": "npc_dota_hero_juggernaut", "alive": True},
        "events": [
            {"event_type": "chat_message", "message": CHAT},
            {"event_type": "roshan_killed", "game_time": clock},
        ],
        **extra,
    }


def _recording(tmp_path: Path) -> Path:
    # A file as an older version wrote it: ids left in nested blocks, an
    # absolute timestamp in every line and the match id in the meta line.
    lines: list[dict] = [
        {
            "k": "meta",
            "match_id": MATCH,
            "hero": "npc_dota_hero_juggernaut",
            "started_at": "2026-11-01T18:30:00+00:00",
            "payloads": 3,
            "advice": 1,
            "last_clock": 125,
            "format": 1,
        }
    ]
    for index, clock in enumerate((5, 65, 125)):
        wall = 90_000.0 + clock
        stamp = f"2026-11-01T18:3{index}:00+00:00"
        lines.append({"k": "gsi", "w": wall, "ts": stamp, "p": _payload(clock)})
        if clock == 65:
            lines.append(
                {
                    "k": "advice",
                    "w": wall + 0.2,
                    "snap": stamp,
                    "clock": clock,
                    "dp": "laning",
                    "action": "Hold the lane",
                    "reason": "Enemy is near.",
                    "priority": "high",
                    "basis": {"clock": clock, "observed_at": 1_792_000_000.5},
                }
            )
    return _write(tmp_path / f"2026-11-01_1830_{MATCH}.jsonl.gz", lines)


def _decoded(copy) -> str:
    return gzip.decompress(copy.data).decode("utf-8")


def test_every_private_value_is_gone_from_the_upload_bytes(tmp_path):
    path = _recording(tmp_path)
    copy = upload_copy(path, app_version="0.63.0")
    text = _decoded(copy)
    for planted in (NICK, STEAM, ACCOUNT, MATCH, TOKEN, CHAT, PERSONA, path.name, "2026-11-01"):
        assert planted not in text, planted
    # Neither does the compressed stream mention them (the gzip header has no file name).
    assert MATCH.encode() not in copy.data and path.name.encode() not in copy.data
    for key in ('"steamid"', '"accountid"', '"matchid"', '"match_id"', '"auth"', "started_at"):
        assert key not in text


def test_the_absolute_match_time_is_gone_but_joins_and_order_stay(tmp_path):
    copy = upload_copy(_recording(tmp_path))
    lines = [json.loads(line) for line in _decoded(copy).splitlines()]
    assert str(START) not in _decoded(copy) and "1792000000" not in _decoded(copy)
    gsi = [line for line in lines if line["k"] == "gsi"]
    advice = next(line for line in lines if line["k"] == "advice")
    assert [line["p"]["provider"]["timestamp"] for line in gsi] == [0, 60, 120]
    assert gsi[0]["w"] == 0.0 and gsi[1]["w"] == 60.0
    # The card still joins its snapshot: the same stamp text on both lines.
    assert advice["snap"] == gsi[1]["ts"] and advice["w"] == 60.2
    assert advice["basis"]["observed_at"] > 0
    assert [g["p"]["map"]["clock_time"] for g in gsi] == [5, 65, 125]  # the game clock is kept


def test_the_meta_line_keeps_only_the_non_identifying_fields(tmp_path):
    copy = upload_copy(_recording(tmp_path), app_version="0.63.0")
    meta = json.loads(_decoded(copy).splitlines()[0])
    assert meta == {
        "k": "meta",
        "hero": "npc_dota_hero_juggernaut",
        "payloads": 3,
        "advice": 1,
        "last_clock": 125,
        "format": 1,
        "upload": 1,
        "anonymized": True,
        "app_version": "0.63.0",
    }
    assert (copy.hero, copy.minutes, copy.payloads, copy.advice) == (
        "npc_dota_hero_juggernaut",
        2,
        3,
        1,
    )


def test_game_facts_survive_redaction(tmp_path):
    lines = [json.loads(x) for x in _decoded(upload_copy(_recording(tmp_path))).splitlines()]
    first = next(line for line in lines if line["k"] == "gsi")["p"]
    assert first["player"] == {"kills": 1}
    assert first["hero"]["name"] == "npc_dota_hero_juggernaut"
    assert first["events"] == [{"event_type": "roshan_killed", "game_time": 5}]


def test_the_copy_is_the_same_for_the_same_file(tmp_path):
    path = _recording(tmp_path)
    assert upload_copy(path).data == upload_copy(path).data  # no time in the gzip header


def test_the_replay_scripts_read_the_copy(tmp_path):
    from farm_outcomes import _rows

    out = tmp_path / "copy.jsonl.gz"
    out.write_bytes(upload_copy(_recording(tmp_path)).data)
    assert [row["clock"] for row in _rows(out)] == [5, 65, 125]


def test_a_recording_made_by_this_version_gives_a_clean_copy(client, tmp_path):
    client.post("/settings/advice", json={"match_records": True})
    for payload in gsi_match_stream(minutes=8, death_minutes=(4,)):
        client.post("/gsi", json=payload)
        client.get("/overlay/recommendation")
    record = client.get("/match-records").json()["records"][0]
    response = client.get(f"/match-records/{record['id']}/upload")
    assert response.status_code == 200
    assert response.headers["x-upload-hero"] == "npc_dota_hero_juggernaut"
    assert int(response.headers["x-upload-minutes"]) >= 7
    text = gzip.decompress(response.content).decode("utf-8")
    assert record["match_id"] not in text and record["id"] not in text
    assert '"matchid"' not in text and '"steamid"' not in text and '"auth"' not in text
    kinds = {json.loads(line)["k"] for line in text.splitlines()}
    assert kinds == {"meta", "gsi", "advice"}


def test_the_endpoint_refuses_bad_ids(client):
    assert client.get("/match-records/../../etc/upload").status_code == 404
    assert client.get("/match-records/2026-01-01_0000_1/upload").status_code == 404


def test_a_private_key_that_survives_blocks_the_upload(tmp_path, monkeypatch):
    path = _recording(tmp_path)
    monkeypatch.setattr(match_record_upload, "redact", lambda payload: payload)
    with pytest.raises(UploadError) as error:
        upload_copy(path)
    assert error.value.code == "unredacted"


def test_an_oversized_copy_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(match_record_upload, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(UploadError) as error:
        upload_copy(_recording(tmp_path))
    assert error.value.code == "too_large"
    assert MAX_UPLOAD_BYTES == 20 * 1024 * 1024


def test_the_endpoint_answers_413_for_too_large(client, monkeypatch):
    client.post("/settings/advice", json={"match_records": True})
    for payload in gsi_match_stream(minutes=6, death_minutes=()):
        client.post("/gsi", json=payload)
    record = client.get("/match-records").json()["records"][0]
    monkeypatch.setattr(match_record_upload, "MAX_UPLOAD_BYTES", 100)
    response = client.get(f"/match-records/{record['id']}/upload")
    assert response.status_code == 413 and response.json()["code"] == "too_large"


def test_a_recording_without_payloads_or_unreadable_is_refused(tmp_path):
    only_meta = _write(tmp_path / "a.jsonl.gz", [{"k": "meta"}])
    with pytest.raises(UploadError) as empty:
        upload_copy(only_meta)
    assert empty.value.code == "empty"
    broken = tmp_path / "b.jsonl.gz"
    broken.write_bytes(b"not gzip")
    with pytest.raises(UploadError) as unreadable:
        upload_copy(broken)
    assert unreadable.value.code == "unreadable"
