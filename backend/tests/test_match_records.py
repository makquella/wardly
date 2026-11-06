"""A week of match recordings kept on the player's computer (app/match_records.py)."""

from __future__ import annotations

import gzip
import json
import os
import time

from match_fixtures import MATCH_ID, ME, gsi_match_stream

from app.match_records import KEEP_DAYS, RECORD_EVERY, redact


def _lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_nothing_is_recorded_while_switched_off(client):
    for payload in gsi_match_stream(minutes=6, death_minutes=()):
        client.post("/gsi", json=payload)
    assert client.get("/match-records").json() == {
        "enabled": False,
        "keep_days": KEEP_DAYS,
        "records": [],
    }


def test_a_match_is_recorded_with_its_advice_and_saved_as_a_file(client):
    assert client.post("/settings/advice", json={"match_records": True}).json()["match_records"]
    for payload in gsi_match_stream(minutes=12, death_minutes=(7,)):
        client.post("/gsi", json=payload)
        client.get("/overlay/recommendation")
    body = client.get("/match-records").json()
    assert body["enabled"] is True and len(body["records"]) == 1
    record = body["records"][0]
    assert record["match_id"] == str(MATCH_ID)
    assert record["hero"] == "npc_dota_hero_juggernaut"
    assert record["minutes"] >= 11 and record["payloads"] > 50 and record["advice"] >= 1

    response = client.get(f"/match-records/{record['id']}")
    assert response.status_code == 200
    lines = [json.loads(line) for line in gzip.decompress(response.content).splitlines()]
    kinds = {line["k"] for line in lines}
    assert kinds == {"meta", "gsi", "advice"}
    assert lines[0]["k"] == "meta"
    advice = next(line for line in lines if line["k"] == "advice")
    assert advice["action"] and advice["dp"]
    # No Steam id, account id, nickname or GSI token anywhere in the file.
    text = gzip.decompress(response.content).decode("utf-8")
    assert str(ME) not in text and '"steamid"' not in text and '"auth"' not in text
    assert client.get("/match-records/../../etc").status_code == 404
    assert client.get("/match-records/2026-01-01_0000_1").status_code == 404


def test_redact_drops_ids_names_token_and_chat():
    payload = {
        "auth": {"token": "secret"},
        "player": {"steamid": "7656", "accountid": "1", "name": "nick", "kills": 3},
        "previously": {"player": {"name": "old nick"}},
        "events": [
            {"event_type": "chat_message", "message": "hi"},
            {"event_type": "roshan_killed", "game_time": 900},
        ],
    }
    clean = redact(payload)
    assert "auth" not in clean
    assert clean["player"] == {"kills": 3}
    assert clean["previously"] == {"player": {}}
    assert clean["events"] == [{"event_type": "roshan_killed", "game_time": 900}]
    assert payload["player"]["name"] == "nick"  # the live payload is untouched


def test_payloads_are_thinned_but_state_changes_are_kept(tmp_path):
    from app.match_records import MatchRecords

    records = MatchRecords()
    records.configure(tmp_path, enabled=True)
    # Ten payloads a second of the same game second, as real GSI sends them.
    stream = [p for p in gsi_match_stream(minutes=6, death_minutes=(3,), step_seconds=1)]
    now = 0.0
    for payload in stream:
        for _ in range(10):
            records.record_gsi(payload, now=now)
            now += 0.1
    records.flush()
    (path,) = tmp_path.glob("match_records/*.jsonl.gz")
    stored = [line for line in _lines(path) if line["k"] == "gsi"]
    sent = len(stream) * 10
    assert len(stream) <= len(stored) <= sent / 4  # every game second, not every payload
    alive = [line["p"]["hero"].get("alive") for line in stored]
    assert False in alive  # the death is there
    assert RECORD_EVERY == 0.5


def test_recordings_older_than_a_week_are_deleted(tmp_path):
    from app.match_records import MatchRecords

    records = MatchRecords()
    records.configure(tmp_path, enabled=True)
    for payload in gsi_match_stream(minutes=6, death_minutes=()):
        records.record_gsi(payload)
    records.flush()
    old = time.time() - (KEEP_DAYS + 1) * 86400
    for path in (tmp_path / "match_records").iterdir():
        os.utime(path, (old, old))
    assert records.prune() == 1
    assert records.list() == []


def test_a_spectated_match_is_not_recorded(tmp_path):
    from app.match_records import MatchRecords

    records = MatchRecords()
    records.configure(tmp_path, enabled=True)
    for payload in gsi_match_stream(minutes=6, death_minutes=()):
        payload["player"] = {"team2": {"player0": {}}, "team3": {}}
        records.record_gsi(payload)
    assert records.list() == []


def test_redact_removes_chat_events_at_every_depth():
    chat = {"event_type": "chat_message", "message": "secret words"}
    keep = {"event_type": "roshan_killed"}
    payload = {
        "events": [chat, keep],
        "previously": {"events": [chat, keep]},
        "added": {"events": [chat], "nested": [{"events": [chat, keep]}]},
    }
    clean = redact(payload)
    assert "secret words" not in json.dumps(clean)
    assert clean["events"] == [keep] and clean["previously"]["events"] == [keep]
    assert clean["added"]["events"] == [] and clean["added"]["nested"][0]["events"] == [keep]
    assert chat in payload["events"], "the input is not changed"
