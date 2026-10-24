from __future__ import annotations


def _state(
    timestamp: int,
    *,
    hp: int = 100,
    game_state: str = "pressure",
    farm_quality: str = "low",
    last_hits: int = 80,
) -> dict:
    return {
        "hero": "Phantom Lancer",
        "role": "carry",
        "minute": timestamp // 60,
        "level": 15,
        "gold": 0,
        "items": ["Power Treads", "Manta Style"],
        "hp_percent": hp,
        "game_state": game_state,
        "team_status": "unknown",
        "event_context": "test replay pressure",
        "extra_context": {
            "source_type": "replay_gsi_like",
            "context_confidence": "high",
            "game_time": timestamp,
            "timestamp_seconds": timestamp,
            "alive": True,
            "mana_percent": 80,
            "last_hits": last_hits,
            "farm_quality": farm_quality,
            "hp_pressure_state": "healthy" if hp > 65 else "critical",
            "position_zone": "lane_area",
            "position_risk": "medium",
            "missing_signals": ["enemy_positions", "nearby_allies_enemies"],
        },
    }


def _send_demo_state(client, timestamp: int, state: dict) -> dict:
    response = client.post(
        "/demo/replay-state",
        json={
            "timestamp_seconds": timestamp,
            "state": state,
            "simulation_file": "test_spacing.jsonl",
            "speed": 5,
        },
    )
    assert response.status_code == 200
    return response.json()["overlay"]


def test_duplicate_demo_advice_is_suppressed(client):
    first = _send_demo_state(client, 1200, _state(1200))
    second = _send_demo_state(client, 1205, _state(1205))

    assert first["new_advice"] is True
    assert second["new_advice"] is not True
    assert second["advice_count"] == first["advice_count"]


def test_game_time_spacing_blocks_normal_coaching_every_few_seconds(client):
    first = _send_demo_state(client, 1200, _state(1200))
    second = _send_demo_state(client, 1210, _state(1210, game_state="pressure tower"))

    assert first["new_advice"] is True
    assert second["new_advice"] is not True
    assert second["advice_count"] == first["advice_count"]
    assert second.get("suppressed_by_game_time_spacing") or second["status"] in {
        "active_advice",
        "cooldown",
    }


def test_urgent_low_hp_can_interrupt_game_time_spacing(client):
    first = _send_demo_state(client, 1200, _state(1200))
    urgent = _send_demo_state(client, 1211, _state(1211, hp=28, game_state="pressure"))

    assert first["new_advice"] is True
    assert urgent["decision_point"] == "LOW_HP"
    assert urgent["new_advice"] is True
    assert urgent["game_time_gap_since_previous_advice"] == 11.0


def _behind(state: dict) -> dict:
    """Calm farm with something to decide: the team 11 kills behind."""
    state["extra_context"].update({"team_name": "radiant", "radiant_score": 5, "dire_score": 16})
    return state


def test_calm_farm_with_nothing_to_decide_stays_silent(client):
    # «Keep farming the safest route» is no decision: neither a card nor a
    # heartbeat nudge after a long silence (advice_validity.FILLER_ACTIONS).
    first = _send_demo_state(
        client,
        1200,
        _state(1200, game_state="calm farming", farm_quality="okay", last_hits=180),
    )
    second = _send_demo_state(
        client,
        1381,
        _state(1381, game_state="calm farming", farm_quality="okay", last_hits=190),
    )
    assert first["new_advice"] is not True and first["recommendation"] is None
    assert second["new_advice"] is not True
    assert client.get("/overlay/stats").json()["heartbeat_nudge_count"] == 0


def test_long_silence_can_trigger_safe_heartbeat_nudge(client):
    first = _send_demo_state(
        client,
        1200,
        _behind(_state(1200, game_state="calm farming", farm_quality="okay", last_hits=180)),
    )
    second = _send_demo_state(
        client,
        1381,
        _behind(_state(1381, game_state="calm farming", farm_quality="okay", last_hits=190)),
    )
    stats = client.get("/overlay/stats").json()

    assert first["new_advice"] is True
    assert second["new_advice"] is True
    assert second["recommendation"]["priority"] == "low"
    assert second["game_time_gap_since_previous_advice"] == 181.0
    assert stats["heartbeat_nudge_count"] == 1


def test_heartbeat_does_not_replace_urgent_low_hp(client):
    _send_demo_state(
        client,
        1200,
        _state(1200, game_state="calm farming", farm_quality="okay", last_hits=180),
    )
    urgent = _send_demo_state(
        client,
        1381,
        _state(1381, hp=28, game_state="pressure", farm_quality="okay", last_hits=190),
    )
    stats = client.get("/overlay/stats").json()

    assert urgent["decision_point"] == "LOW_HP"
    assert urgent["new_advice"] is True
    assert stats["heartbeat_nudge_count"] == 0


def test_heartbeat_nudge_stays_non_aggressive(client):
    _send_demo_state(
        client,
        1200,
        _behind(_state(1200, game_state="calm farming", farm_quality="okay", last_hits=180)),
    )
    heartbeat = _send_demo_state(
        client,
        1381,
        _behind(_state(1381, game_state="calm farming", farm_quality="okay", last_hits=190)),
    )
    action = heartbeat["recommendation"]["action"].lower()

    assert heartbeat["new_advice"] is True
    assert "farm" in action or "reset" in action or "safer" in action
    assert not any(
        word in action for word in ("fight now", "take objective", "buy back", "push now")
    )
