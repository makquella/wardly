"""The film's Shorts package: its metadata, its publish time and the one private delivery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.promo import beta, beta_shorts, carry_beta, experiments, film  # noqa: E402
from test_promo_beta import telegram  # noqa: E402


def test_the_film_narration_is_the_six_voiced_lines():
    lines = film.voice_lines()
    assert len(lines) == 6
    assert lines[0] == "Що купити?"
    assert lines[-1] == "Wardly. Безкоштовно для Windows."


def test_the_film_metadata_is_honest_and_fits_youtube():
    meta = film.metadata("uk")
    assert len(meta["title"]) <= 100 and "Dota 2" in meta["title"]
    assert len(meta["description"]) <= 5000
    assert sum(len(tag) for tag in meta["tags"]) <= 500
    assert "ref=shorts-next-step-uk" in meta["description"]
    assert "Без обіцянок приросту MMR" in meta["description"]
    with pytest.raises(ValueError):
        film.metadata("en")


def test_the_film_is_scheduled_for_17_00_in_kyiv_on_24_october():
    package = beta_shorts.package(
        "uk", {"sha256": "0" * 64, "visual_revision": 2, "creative": film.CREATIVE}
    )
    assert package["youtube_publish_at"] == film.PUBLISH_AT
    assert carry_beta.kyiv(package["youtube_publish_at"]) == "24.10.2026 17:00"
    assert package["topic"] == "film-next-step-uk"
    assert package["youtube_title"] == film.metadata("uk")["title"]
    assert package["youtube_language"] == "uk"


def reviewed(folder: Path) -> None:
    target = folder / "uk"
    target.mkdir()
    (target / "video.mp4").write_bytes(b"locally reviewed film")
    (target / "cover.jpg").write_bytes(b"cover")
    beta.save(
        target / "speech-check.json",
        {"ok": True, "language": "uk", "sha256": beta.digest(target / "video.mp4")},
    )
    beta.save(
        target / "package.json",
        {
            "kind": film.KIND,
            "creative": film.CREATIVE,
            "language": "uk",
            "draft": False,
            "seconds": 25.0,
            "visual_revision": film.VISUAL_REVISION,
            "layout": {"ok": True},
            "sha256": beta.digest(target / "video.mp4"),
            "voice_config": {"name": "Alex Nekrasov", "model": "eleven_v4"},
        },
    )


def test_the_film_goes_once_to_the_private_chat_with_only_the_shorts_button(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("API_ADMIN_TOKEN", "local-api-fixture")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    reviewed(tmp_path)
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        monkeypatch.setenv("API_URL", url)
        beta.deliver(tmp_path, shorts=True, languages=film.LANGUAGES, kind=film.KIND)
        registered = [json.loads(body) for route, body in calls if route == "/v1/admin/promo"]
        assert [m["youtube_publish_at"] for m in registered] == ["2026-10-24T14:00:00Z"]
        videos = [body for route, body in calls if route.endswith("sendVideo")]
        assert len(videos) == 1
        assert b"promo:yt:" in videos[0] and b"promo:no:" in videos[0]
        assert b"promo:all:" not in videos[0] and b"promo:tg:" not in videos[0]
        assert b"24.10.2026 17:00" in videos[0]
        replies = [
            json.loads(body)["text"] for route, body in calls if route.endswith("sendMessage")
        ]
        assert "Публікація: 24.10.2026 17:00 за Києвом" in replies[0]
        count = len(calls)
        beta.deliver(tmp_path, shorts=True, languages=film.LANGUAGES, kind=film.KIND)
        assert len(calls) == count + 1  # getChat only: no second upload or registration


def test_a_beta_pair_artifact_is_not_sent_as_the_film(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    reviewed(tmp_path)
    package = json.loads((tmp_path / "uk" / "package.json").read_text())
    beta.save(tmp_path / "uk" / "package.json", {**package, "kind": beta.KIND})
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        with pytest.raises(ValueError, match="not the requested"):
            beta.deliver(tmp_path, shorts=True, languages=film.LANGUAGES, kind=film.KIND)
        assert not any(route.endswith("sendVideo") for route, _ in calls)
