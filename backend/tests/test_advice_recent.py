from __future__ import annotations

import json


def _post_sample(client, repo_root, name: str) -> None:
    sample = repo_root / "data" / "gsi_samples" / name
    client.post("/gsi", json=json.loads(sample.read_text(encoding="utf-8")))


def test_recent_advice_is_empty_before_any_advice(client):
    response = client.get("/advice/recent")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_recent_advice_lists_shown_advice_newest_first(client, repo_root):
    _post_sample(client, repo_root, "low_mana.json")
    first = client.get("/overlay/recommendation").json()
    # Bypass anti-spam spacing between the two samples; keep the session history.
    from app.advice_scheduler import ADVICE_SCHEDULER

    ADVICE_SCHEDULER.reset()
    _post_sample(client, repo_root, "low_hp_juggernaut.json")
    second = client.get("/overlay/recommendation").json()

    items = client.get("/advice/recent").json()["items"]

    assert [item["action"] for item in items[:2]] == [
        second["recommendation"]["action"],
        first["recommendation"]["action"],
    ]
    assert items[0]["priority"] == second["recommendation"]["priority"]
    assert items[0]["hero"] == "Juggernaut"


def test_calm_farm_without_a_decision_is_not_listed(client, repo_root):
    # «Keep farming the safest route» decides nothing: no card, no history.
    _post_sample(client, repo_root, "calm_farming_antimage.json")
    body = client.get("/overlay/recommendation").json()

    assert body["recommendation"] is None
    assert body["suppressed_reason"] == "no_new_decision"
    assert client.get("/advice/recent").json() == {"items": []}


def test_recent_advice_limit_is_clamped(client, repo_root):
    _post_sample(client, repo_root, "low_mana.json")
    client.get("/overlay/recommendation")

    assert len(client.get("/advice/recent?limit=0").json()["items"]) == 1
    assert client.get("/advice/recent?limit=500").status_code == 200
