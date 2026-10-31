"""Real normalization, HTTP readers and controlled threads prove GSI publication."""

from __future__ import annotations

import copy
import sys
import threading
from pathlib import Path
from types import FrameType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import gsi_state, main


def _packet(hero: str = "juggernaut", last_hits: int = 40) -> dict[str, Any]:
    return {
        "map": {
            "matchid": "8012345678",
            "clock_time": 600,
            "game_time": 600,
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
        },
        "hero": {"name": f"npc_dota_hero_{hero}", "health": 800, "max_health": 1000},
        "player": {"gold": 500, "last_hits": last_hits, "kills": 2, "deaths": 1},
    }


def test_http_reader_keeps_old_coherent_packet_while_actual_async_normalizer_is_paused(
    client: TestClient,
) -> None:
    initial = client.post("/gsi", json=_packet()).json()
    entered, release = threading.Event(), threading.Event()
    responses, errors = [], []
    original_trace = threading.gettrace()

    def trace(frame: FrameType, event: str, _arg: Any) -> Any:
        if event == "call" and frame.f_code is gsi_state.normalize_gsi_payload.__code__:
            sys.settrace(None)
            entered.set()
            assert release.wait(5)
        return None

    def write() -> None:
        try:
            responses.append(client.post("/gsi", json=_packet("luna", 70)))
        except Exception as error:  # noqa: BLE001 - inspect actual request-thread failure
            errors.append(error)

    threading.settrace(trace)
    worker = threading.Thread(target=write)
    worker.start()
    try:
        assert entered.wait(5)
        current = client.get("/gsi/debug/latest").json()
        assert current["latest_raw_payload"]["hero"]["name"] == "npc_dota_hero_juggernaut"
        assert current["latest_normalized_state"]["hero"] == "Juggernaut"
        assert current["timestamp"] == initial["timestamp"]
        status = client.get("/gsi/status").json()
        assert status["hero"] == "Juggernaut" and status["in_match"]
    finally:
        threading.settrace(original_trace)
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    assert len(responses) == 1 and responses[0].status_code == 200
    current = client.get("/gsi/debug/latest").json()
    assert current["latest_raw_payload"]["hero"]["name"] == "npc_dota_hero_luna"
    assert current["latest_normalized_state"]["hero"] == "Luna"
    assert current["latest_normalized_state"]["extra_context"]["match_session_id"]


def test_caller_and_reader_mutations_do_not_change_the_published_snapshot(
    client: TestClient,
) -> None:
    payload = _packet()
    result = gsi_state.update_latest_gsi(payload)
    payload["hero"]["name"] = "npc_dota_hero_luna"
    result["state"]["hero"] = "Luna"
    result["state"]["extra_context"]["last_hits"] = 999
    debug = gsi_state.get_gsi_debug_latest()
    debug["latest_raw_payload"]["player"]["last_hits"] = 999
    debug["latest_normalized_state"]["extra_context"].clear()
    current = client.get("/gsi/debug/latest").json()
    assert current["latest_raw_payload"] == _packet()
    assert current["latest_normalized_state"]["hero"] == "Juggernaut"
    assert current["latest_normalized_state"]["extra_context"]["last_hits"] == 40


def test_failed_enrichment_preserves_the_previous_complete_snapshot(client: TestClient) -> None:
    client.post("/gsi", json=_packet())
    previous = client.get("/gsi/debug/latest").json()

    def fail(state: dict[str, Any]) -> None:
        state["hero"] = "half built"
        raise ValueError("construction failed")

    with pytest.raises(ValueError, match="construction failed"):
        gsi_state.update_latest_gsi(_packet("luna"), enrich=fail)
    assert client.get("/gsi/debug/latest").json() == previous
    gsi_state.update_latest_gsi(_packet("luna"))
    assert client.get("/state/current").json()["state"]["hero"] == "Luna"


def test_concurrent_real_normalizers_observe_serial_previous_context() -> None:
    gsi_state.update_latest_gsi(_packet())
    start = threading.Barrier(3)
    observed, errors = [], []

    def trace(frame: FrameType, event: str, _arg: Any) -> Any:
        if event == "call" and frame.f_code is gsi_state.normalize_gsi_payload.__code__:
            sys.settrace(None)
            previous = frame.f_locals["previous_extra_context"]
            observed.append(
                (previous["last_hits"], frame.f_locals["payload"]["player"]["last_hits"])
            )
        return None

    def write(last_hits: int) -> None:
        try:
            start.wait(timeout=5)
            sys.settrace(trace)
            gsi_state.update_latest_gsi(_packet(last_hits=last_hits))
        except Exception as error:  # noqa: BLE001 - inspect actual writer-thread failure
            errors.append(error)
        finally:
            sys.settrace(None)

    workers = [threading.Thread(target=write, args=(value,)) for value in (50, 60)]
    for worker in workers:
        worker.start()
    start.wait(timeout=5)
    for worker in workers:
        worker.join(5)
    assert not any(worker.is_alive() for worker in workers) and not errors
    assert len(observed) == 2
    assert observed[0][0] == 40 and observed[1][0] == observed[0][1]
    current = gsi_state.get_gsi_debug_latest()
    assert current["latest_raw_payload"]["player"]["last_hits"] == observed[1][1]
    assert current["latest_normalized_state"]["extra_context"]["last_hits"] == observed[1][1]


def test_session_reset_clears_packet_and_delta_context(client: TestClient) -> None:
    client.post("/gsi", json=_packet(last_hits=40))
    assert client.post("/session/reset").status_code == 200
    assert client.get("/state/current").json() == {
        "status": "waiting_for_gsi",
        "timestamp": None,
        "state": None,
    }
    assert client.get("/gsi/debug/latest").json()["latest_raw_payload"] is None
    assert client.get("/gsi/status").json()["in_match"] is False
    assert client.get("/session/memory").json()["hero"] is None
    result = client.post("/gsi", json=_packet(last_hits=70)).json()
    assert result["state"]["extra_context"]["last_hits"] == 70


def test_concurrent_http_reset_waits_for_writer_and_then_clears_complete_context(
    client: TestClient,
) -> None:
    client.post("/gsi", json=_packet())
    entered, reset_entered, release = threading.Event(), threading.Event(), threading.Event()
    errors, responses = [], []
    original_trace = threading.gettrace()

    def trace(frame: FrameType, event: str, _arg: Any) -> Any:
        if event == "call" and frame.f_code is gsi_state.normalize_gsi_payload.__code__:
            sys.settrace(None)
            entered.set()
            assert release.wait(5)
        elif event == "call" and frame.f_code is main.reset_session.__code__:
            # The reset then waits on the outer live operation (live_operation.py).
            sys.settrace(None)
            reset_entered.set()
        return None

    def request(path: str, payload: dict[str, Any] | None = None) -> None:
        try:
            responses.append(client.post(path, json=payload))
        except Exception as error:  # noqa: BLE001 - inspect actual request-thread failure
            errors.append(error)

    writer = threading.Thread(target=request, args=("/gsi", _packet("luna")))
    resetter = threading.Thread(target=request, args=("/session/reset",))
    threading.settrace(trace)
    writer.start()
    try:
        assert entered.wait(5)
        resetter.start()
        assert reset_entered.wait(5)
        assert client.get("/state/current").json()["state"]["hero"] == "Juggernaut"
    finally:
        threading.settrace(original_trace)
        release.set()
        writer.join(5)
        if resetter.ident is not None:
            resetter.join(5)
    assert not writer.is_alive() and not resetter.is_alive() and not errors
    assert len(responses) == 2 and all(response.status_code == 200 for response in responses)
    assert client.get("/state/current").json()["state"] is None
    assert client.get("/session/memory").json()["hero"] is None


def test_debug_file_io_cannot_hold_writer_or_publication_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gsi_state, "GSI_DEBUG_LOG", True)
    monkeypatch.setattr(gsi_state, "GSI_DEBUG_SAMPLES_DIR", tmp_path)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def trace(frame: FrameType, event: str, _arg: Any) -> Any:
        if event == "call" and frame.f_code is gsi_state._write_debug_payload_sample.__code__:
            sys.settrace(None)
            entered.set()
            assert release.wait(5)
        return None

    def write() -> None:
        try:
            sys.settrace(trace)
            gsi_state.update_latest_gsi(_packet())
        except Exception as error:  # noqa: BLE001 - inspect actual debug-I/O thread failure
            errors.append(error)
        finally:
            sys.settrace(None)

    worker = threading.Thread(target=write)
    worker.start()
    try:
        assert entered.wait(5)
        first = copy.deepcopy(gsi_state.get_current_state())
        assert first["state"]["hero"] == "Juggernaut"
        gsi_state.update_latest_gsi(_packet("luna"))
        assert gsi_state.get_current_state()["state"]["hero"] == "Luna"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    assert len(list(tmp_path.glob("*.json"))) == 2


def _creep_minimap() -> dict[str, Any]:
    return {
        "o1": {
            "image": "minimap_creep",
            "unitname": "npc_dota_creep_goodguys_melee",
            "team": 2,
            "xpos": -4000,
            "ypos": -6000,
            "visionrange": 750,
        },
        "o2": {
            "image": "minimap_siege",
            "unitname": "npc_dota_badguys_siege",
            "team": 3,
            "xpos": -3000,
            "ypos": -6000,
        },
        "o3": {
            "image": "minimap_creep",
            "unitname": "npc_dota_neutral_kobold",
            "team": 4,
            "xpos": -2000,
            "ypos": -3000,
        },
    }


def test_minimap_creep_lists_are_read_once_and_never_published(client: TestClient) -> None:
    # Up to ~176 creeps a payload: farm_map.py reads them; the published state,
    # the previous context and the memory's last_states keep only farm_target.
    from app.gsi_snapshot import TRANSIENT_KEYS
    from app.match_memory import MATCH_MEMORY

    for clock in (600, 601):
        packet = _packet()
        packet["map"]["clock_time"] = clock
        packet["player"]["team_name"] = "radiant"
        packet["minimap"] = _creep_minimap()
        assert client.post("/gsi", json=packet).status_code == 200
    extra = client.get("/state/current").json()["state"]["extra_context"]
    assert not TRANSIENT_KEYS & extra.keys()
    assert "farm_target" in extra
    debug = client.get("/gsi/debug/latest").json()["latest_normalized_state"]["extra_context"]
    assert not TRANSIENT_KEYS & debug.keys()
    snapshot = gsi_state._GSI.capture()
    assert snapshot is not None and not TRANSIENT_KEYS & snapshot.previous_context.keys()
    assert all(not TRANSIENT_KEYS & s["extra_context"].keys() for s in MATCH_MEMORY.last_states)
