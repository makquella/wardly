"""Real child-tracker capture cannot interleave with observation or reset."""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import FrameType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_gsi_snapshot import _packet
from test_match_memory_ownership import _paused_operation

from app import main, map_hints
from app.enemy_lanes import EnemyLanes
from app.match_memory import MATCH_MEMORY, LiveTrackerSnapshot, MatchMemory


def _seen_packet(hero: str = "juggernaut", enemy: str = "axe", clock: int = 200) -> dict[str, Any]:
    packet = _packet(hero)
    packet["map"].update({"clock_time": clock, "game_time": clock})
    packet["hero"].update({"alive": True, "xpos": 5000, "ypos": -6200})
    packet["player"]["team_name"] = "radiant"
    packet["minimap"] = {
        "enemy": {
            "image": "minimap_enemyicon",
            "unitname": f"npc_dota_hero_{enemy}",
            "team": 3,
            "xpos": 5000,
            "ypos": -6200,
        }
    }
    return packet


def _snapshot(clock: int = 230) -> LiveTrackerSnapshot:
    return MATCH_MEMORY.tracker_snapshot(clock=clock, lane="bot", alive=True, lang="en")


def _observe_lane(client: TestClient) -> None:
    for clock in (190, 195, 200):
        assert client.post("/gsi", json=_seen_packet(clock=clock)).status_code == 200


def test_snapshot_waits_for_all_child_observations_in_real_live_request(client: TestClient) -> None:
    _observe_lane(client)
    result: dict[str, Any] = {}
    errors: list[Exception] = []
    done = threading.Event()

    def write() -> None:
        try:
            result["write"] = client.post("/gsi", json=_seen_packet("luna", "lina"))
        except Exception as error:  # noqa: BLE001 - inspect real request failure
            errors.append(error)

    def read() -> None:
        try:
            result["read"] = _snapshot()
        except Exception as error:  # noqa: BLE001 - inspect real thread failure
            errors.append(error)
        finally:
            done.set()

    workers = [threading.Thread(target=write), threading.Thread(target=read)]
    with _paused_operation(EnemyLanes.observe.__code__, MatchMemory.tracker_snapshot.__code__) as (
        entered,
        watched,
        release,
    ):
        workers[0].start()
        try:
            assert entered.wait(5)  # enemies updated, lane/skill tracking has not run yet
            workers[1].start()
            assert watched.wait(5) and not done.wait(0.1)
        finally:
            release.set()
            for worker in workers:
                if worker.ident is not None:
                    worker.join(5)
    assert not any(worker.is_alive() for worker in workers) and not errors
    assert result["write"].status_code == 200
    assert result["read"].hero == "Luna" and result["read"].enemies == ["Lina"]
    assert result["read"].opponents == [] and result["read"].missing is None


@pytest.mark.parametrize("operation", ["reset", "live"])
def test_capture_holds_one_owner_until_all_child_reads_finish(
    client: TestClient, operation: str
) -> None:
    _observe_lane(client)
    result: dict[str, Any] = {}
    errors: list[Exception] = []
    done = threading.Event()

    def read() -> None:
        try:
            result["read"] = _snapshot()
        except Exception as error:  # noqa: BLE001 - inspect real thread failure
            errors.append(error)

    def write() -> None:
        try:
            result["write"] = (
                client.post("/session/reset")
                if operation == "reset"
                else client.post("/gsi", json=_seen_packet("luna", "lina"))
            )
        except Exception as error:  # noqa: BLE001 - inspect real request failure
            errors.append(error)
        finally:
            done.set()

    watch = (
        main.reset_session.__code__ if operation == "reset" else MatchMemory.observe_state.__code__
    )
    workers = [threading.Thread(target=read), threading.Thread(target=write)]
    with _paused_operation(EnemyLanes.opponents.__code__, watch) as (entered, watched, release):
        workers[0].start()
        try:
            assert entered.wait(5)  # the enemy list was already captured
            workers[1].start()
            assert watched.wait(5) and not done.wait(0.1)
        finally:
            release.set()
            for worker in workers:
                if worker.ident is not None:
                    worker.join(5)
    assert not any(worker.is_alive() for worker in workers) and not errors
    assert result["write"].status_code == 200
    view = result["read"]
    assert view.hero == "Juggernaut" and view.enemies == view.opponents == ["Axe"]
    assert view.missing["hero"] == "Axe" and view.missing["seconds"] == 30
    after = _snapshot()
    assert after.hero == (None if operation == "reset" else "Luna")
    assert after.enemies == ([] if operation == "reset" else ["Lina"])


def test_snapshot_is_detached_and_preserves_missing_and_observed_objectives(
    client: TestClient,
) -> None:
    _observe_lane(client)
    packet = _seen_packet(clock=230)
    packet["minimap"] = {}
    packet["hero"]["aegis"] = True
    packet["events"] = [{"event_type": "aegis_picked_up", "game_time": 230}]
    assert client.post("/gsi", json=packet).status_code == 200
    view = _snapshot(500)
    assert view.objective["id"] == "aegis@530" and view.roshan_strip[0]["at"] == 530
    view.enemies.clear()
    view.opponents.clear()
    view.objective["id"] = "changed"
    view.roshan_strip[0]["at"] = 0
    missing = _snapshot().missing
    assert missing is not None
    missing["hero"] = "changed"
    assert _snapshot().missing["hero"] == "Axe"
    again = _snapshot(500)
    assert again.enemies == again.opponents == ["Axe"]
    assert again.objective["id"] == "aegis@530" and again.roshan_strip[0]["at"] == 530
    assert MATCH_MEMORY.enemy_heroes() == ["Axe"]
    assert (
        MATCH_MEMORY.tracker_snapshot(clock=230, lane="bot", alive=False, lang="uk").missing is None
    )
    assert client.post("/session/reset").status_code == 200
    empty = MATCH_MEMORY.tracker_snapshot(clock=None, lane=None, alive=True, lang="en")
    assert empty.enemies == empty.opponents == empty.roshan_strip == []
    assert empty.missing is empty.skill_bar is empty.objective is None
    assert not empty.tp_missing and not empty.roshan_open


def test_cold_snapshot_timer_settings_are_prepared_before_ownership() -> None:
    reads: list[bool] = []
    original = sys.gettrace()

    def trace(frame: FrameType, event: str, _arg: Any) -> Any:
        if event == "call" and frame.f_code is Path.read_text.__code__:
            if frame.f_locals["self"] == map_hints.TIMERS_PATH:
                caller = frame.f_back
                owned = False
                while caller is not None:
                    owned |= (
                        caller.f_code.co_name == "guarded"
                        and caller.f_locals.get("self") is MATCH_MEMORY
                    )
                    caller = caller.f_back
                reads.append(owned)
        return None

    map_hints.timers.cache_clear()
    sys.settrace(trace)
    try:
        _snapshot()
        assert reads == [False]
    finally:
        sys.settrace(original)
        map_hints.timers.cache_clear()
