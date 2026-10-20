"""Recruitment alignment and private delivery fail closed before publishing."""

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.promo import beta, beta_scenes, beta_shorts, experiments, scenes, send  # noqa: E402


def test_master_take_scene_cuts_have_no_inserted_pauses_and_keep_every_word():
    texts = ["Play Dota?", "Give honest feedback."]
    words = scenes.estimated_words(" ".join(texts), 0.2, 29.0)
    timeline, captions, total = beta.timings(texts, words, 29.3)
    assert total == 30.5
    assert timeline[0]["end"] == timeline[1]["start"]
    assert timeline[-1]["end"] == total
    assert " ".join(c["text"] for c in captions) == " ".join(texts)
    assert captions[0]["start"] == 0.2
    assert "00:00:00,200" in beta.srt(captions)
    with pytest.raises(ValueError, match="shorten the script"):
        beta.timings(texts, words, 34.5)
    with pytest.raises(ValueError, match="exact narration"):
        beta.timings(["changed narration"], words, 29.3)


def test_both_scripts_match_source_claims_and_have_localized_final_calls_to_action():
    assert beta.verify_claims(online=False)["sources"]
    for language, keyword in (("uk", "БЕТА"), ("en", "BETA")):
        copy = beta_scenes.COPY[language]
        assert keyword in copy["voice"][-1]
        assert len(copy["voice"]) == len(copy["titles"]) == 7
        assert "Windows" in copy["free"]
        timeline, captions, _ = beta.storyboard(language)
        page = beta_scenes.page(language, timeline, captions)
        assert f'lang="{language}"' in page
        assert "data:image/" in page and "file://" not in page
        assert copy["site"] in page
        assert "0–4 000" in page
    english = " ".join(beta_scenes.COPY["en"]["voice"])
    assert not any("\u0400" <= char <= "\u04ff" for char in english)


def test_v4_final_character_rounding_keeps_starts_and_rejects_missing_speech():
    words = [
        {"word": "Comment", "start": 28.0, "end": 29.0},
        {"word": "BETA.", "start": 29.1, "end": 30.24},
    ]
    _, captions, _ = beta.timings(["Comment BETA."], words, 30.16)
    assert captions[-1]["words"][-1]["s"] == 29.1
    assert captions[-1]["words"][-1]["e"] == 30.16
    assert words[-1]["end"] == 30.24  # Keep the original provider evidence intact.
    with pytest.raises(ValueError, match="audio is"):
        beta.timings(["Comment BETA."], words, 29.9)
    with pytest.raises(ValueError, match="audio is"):
        beta.timings(["Comment BETA."], words, 29.0)


def test_actual_ukrainian_transcript_accepts_speech_spelling_without_discarding_letters():
    # Keep the original long take: it reproduces SequenceMatcher's autojunk
    # regression even after the campaign copy changes.
    expected = (
        "Граєш у Доту? Допоможи зробити Wardly кращим. "
        "Це безкоштовний Windows-тренер: підказки в матчі та розбір після гри. "
        "Шукаємо добровольців до чотирьох тисяч MMR. "
        "Особливо на Свені, Джагернауті й Терорблейді. "
        "Зіграй кілька матчів і розкажи, що справді допомогло. "
        "Що запізнилося чи відволікало? Де порада була неправильною? "
        "Разом зробимо поради точнішими, вчаснішими й кориснішими. "
        "Хочеш долучитися? Напиши «БЕТА» в коментарях."
    )
    actual = (
        "Граєш у доту? Допоможи зробити в ордлі кращим. Це безкоштовний віндовстренер. "
        "Підказків матчі та розбір після гри. Шукаємо добровольців до 4000 ммр. "
        "Особливо на свені Джагернаутій Террорблейді. Зіграй кілька матчів і розкажи, "
        "що справді допомогло. Що запізнилося чи відволікало, де порада була неправильною. "
        "Разом зробимо поради точнішими, вчаснішими і кориснішими. Хочеш долучитися? "
        "Напиши бета в коментарях."
    )
    assert beta.transcript_similarity(expected, actual) > 0.9
    assert beta.transcript_similarity(expected, "Different language and unrelated audio.") < 0.2


def test_shorter_take_does_not_insert_a_thirty_second_floor_or_cut_speech():
    texts = ["Play Sven?", "Help test the advice.", "Comment BETA."]
    words = scenes.estimated_words(" ".join(texts), 0.1, 21.0)
    timeline, captions, total = beta.timings(texts, words, 21.2, minimum=20, maximum=27, tail=0.8)
    assert total == 22.0
    assert timeline[-1]["end"] == total
    assert captions[-1]["words"][-1]["e"] == words[-1]["end"]
    with pytest.raises(ValueError, match="shorten the script"):
        beta.timings(texts, words, 26.3, minimum=20, maximum=27, tail=0.8)


def test_new_sven_metadata_keeps_legacy_approval_ids_stable():
    old = {"sha256": "a" * 64, "visual_revision": 3}
    new = {**old, "visual_revision": 4}
    for language in beta.LANGUAGES:
        original = beta_shorts.package(language, old)
        revised = beta_shorts.package(language, new)
        assert original["youtube_title"] == beta_shorts.COPY[language]["title"]
        assert revised["id"] != original["id"]
        assert "shorts-sven-" + language in revised["caption"]
        assert revised["youtube_language"] == language


@contextmanager
def telegram(chat_type="private", *, old_metadata_api=False, keeps=send.YOUTUBE_KEYS):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.path, body))
            result = {"type": chat_type}
            if self.path == "/v1/admin/promo":
                submitted = json.loads(body)
                response = {
                    "ok": True,
                    "media_key": "a" * 32,
                    "status": "pending",
                    "youtube_ready": True,
                }
                if not old_metadata_api:
                    response.update({key: submitted[key] for key in keeps if key in submitted})
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(encoded)
                return
            if self.path.endswith("sendMessage"):
                result = {"message_id": len(calls)}
            if self.path.endswith("sendVideo"):
                result = {
                    "message_id": len(calls),
                    "chat": {"type": chat_type},
                    "video": {"width": 1080, "height": 1920, "duration": 32, "file_size": 24},
                }
            encoded = json.dumps({"ok": True, "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.path, body))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)


def pair(folder, **extra):
    for language in beta.LANGUAGES:
        target = folder / language
        target.mkdir()
        (target / "video.mp4").write_bytes(b"locally reviewed MP4")
        (target / "cover.jpg").write_bytes(b"cover")
        beta.save(
            target / "speech-check.json",
            {"ok": True, "language": language, "sha256": beta.digest(target / "video.mp4")},
        )
        beta.save(
            target / "package.json",
            {
                "kind": beta.KIND,
                "language": language,
                "draft": False,
                "seconds": 32,
                "visual_revision": 3,
                "layout": {"ok": True},
                "sha256": beta.digest(target / "video.mp4"),
                "voice_config": {"name": "Alex Nekrasov", "model": "eleven_v4"},
                **extra,
            },
        )


def test_actual_private_upload_returns_two_receipts_without_publishing(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path)
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        beta.deliver(tmp_path)
        assert len(calls) == 3
        assert all("sendVideo" in route for route, _ in calls[1:])
        assert all(b"reply_markup" not in body and b"promo:all" not in body for _, body in calls)
        beta.deliver(tmp_path)
        assert len(calls) == 4  # getChat only; existing receipts prevent duplicate uploads.
        receipt_path = tmp_path / "uk" / "telegram-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["sha256"] = "old render"
        beta.save(receipt_path, receipt)
        with pytest.raises(ValueError, match="different video"):
            beta.deliver(tmp_path)
        assert len(calls) == 5
        receipt["sha256"] = beta.digest(tmp_path / "uk" / "video.mp4")
        beta.save(receipt_path, receipt)
    for language in beta.LANGUAGES:
        receipt = json.loads((tmp_path / language / "telegram-receipt.json").read_text())
        assert receipt["ok"] and receipt["message_id"] and receipt["chat_type"] == "private"
        assert "token" not in json.dumps(receipt)


def test_channel_or_altered_pair_is_rejected_before_any_video_upload(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path)
    with telegram("channel") as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        with pytest.raises(SystemExit, match="private developer chat"):
            beta.deliver(tmp_path)
        assert len(calls) == 1
    (tmp_path / "en" / "video.mp4").write_bytes(b"unreviewed replacement")
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        with pytest.raises(ValueError, match="integrity"):
            beta.deliver(tmp_path)
        assert len(calls) == 1


def test_native_schedule_preview_shows_kyiv_time_without_manual_publish_buttons(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path)
    for language in beta.LANGUAGES:
        beta.save(
            tmp_path / language / "native-schedule.json",
            {
                "verified": True,
                "sha256": beta.digest(tmp_path / language / "video.mp4"),
                "publish_at": "2026-10-17T14:00:00Z",
                "url": f"https://www.youtube.com/shorts/{language}-fixture",
            },
        )
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        beta.deliver(tmp_path)
    videos = [body for route, body in calls if route.endswith("sendVideo")]
    assert len(videos) == 2
    assert all(b"17.10.2026 17:00" in body for body in videos)
    assert all(b"reply_markup" not in body and b"14:00" not in body for body in videos)
    assert all(b"No publication scheduled" not in body for body in videos)


def test_reviewed_pair_gets_only_shorts_buttons_and_exact_localized_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("API_ADMIN_TOKEN", "local-api-fixture")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path)
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        monkeypatch.setenv("API_URL", url)
        beta.deliver(tmp_path, shorts=True)
        registered = [json.loads(body) for route, body in calls if route == "/v1/admin/promo"]
        assert len(registered) == 2
        assert [meta["youtube_language"] for meta in registered] == ["uk", "en"]
        videos = [body for route, body in calls if route.endswith("sendVideo")]
        assert len(videos) == 2
        assert all(b"promo:yt:" in body and b"promo:no:" in body for body in videos)
        assert all(b"promo:all:" not in body and b"promo:tg:" not in body for body in videos)
        replies = [json.loads(body) for route, body in calls if route.endswith("sendMessage")]
        assert len(replies) == 2
        for language, meta, reply in zip(beta.LANGUAGES, registered, replies, strict=True):
            assert meta["youtube_title"] in reply["text"]
            assert meta["caption"] in reply["text"]
            assert ", ".join(meta["youtube_tags"]) in reply["text"]
            receipt = json.loads((tmp_path / language / "shorts-approval-receipt.json").read_text())
            assert receipt["youtube_package_id"] == meta["id"]
            assert receipt["details_message_id"] == reply["reply_to_message_id"] + 1
            assert receipt["youtube_ready"]
            assert (
                "Shorts"
                in beta_shorts.keyboard(language, meta["id"])["inline_keyboard"][0][0]["text"]
            )
        count = len(calls)
        beta.deliver(tmp_path, shorts=True)
        assert len(calls) == count + 1  # getChat only: no duplicate uploads/registrations.


def test_worker_must_preserve_metadata_before_a_publication_button_is_sent(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("API_ADMIN_TOKEN", "local-api-fixture")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path)
    with telegram(old_metadata_api=True) as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        monkeypatch.setenv("API_URL", url)
        with pytest.raises(SystemExit, match="preserve youtube_tags"):
            beta.deliver(tmp_path, shorts=True)
        assert not any(route.endswith("sendVideo") for route, _ in calls)


def test_the_release_pair_claims_match_the_shipped_plans():
    from scripts.promo import release_carry

    claims = release_carry.verify()
    assert claims["carries"] == 20 and claims["league_games"] > 10000
    story = release_carry.profile()
    for language in beta.LANGUAGES:
        voice = story.COPY[language]["voice"]
        assert len(voice) == 7
        joined = " ".join(voice)
        assert "Bloodthorn" in joined and "Windows" in joined
        package = beta_shorts.package(
            language,
            {"sha256": "0" * 64, "visual_revision": 7, "creative": release_carry.CREATIVE},
        )
        assert package["topic"] == f"release-0.57-carries-{language}"
        assert "20" in package["youtube_title"] and len(package["youtube_title"]) <= 100
        assert f"ref=shorts-carry-{language}" in package["caption"]
        assert "release-0-57-0" in package["caption"]


@pytest.mark.parametrize("creative", ["carry-match-review", "carry-decisive-moments"])
def test_the_carry_beta_pairs_say_what_the_app_says(creative):
    from scripts.promo import carry_beta

    carry_beta.verify(creative)
    story = carry_beta.profile(creative)
    for language in beta.LANGUAGES:
        voice = " ".join(story.COPY[language]["voice"])
        assert "Windows" in voice
        package = beta_shorts.package(
            language,
            {
                "sha256": "0" * 64,
                "visual_revision": carry_beta.REVISION[creative],
                "creative": creative,
            },
        )
        assert package["topic"] == f"{creative}-{language}"
        assert package["youtube_publish_at"] == carry_beta.PUBLISH_AT[creative]
        assert carry_beta.kyiv(package["youtube_publish_at"]).endswith(" 17:00")
        assert len(package["youtube_title"]) <= 100
        assert "beta.html?ref=shorts-" in package["caption"]
        assert "MMR" in package["caption"]
    screens = carry_beta.review("uk")
    assert screens["score"] == ("62", "C", "Оцінка")
    assert screens["finding"][1].startswith("31 добивань до 10:00 проти 44 у керрі")
    assert screens["focus"][0] == "Головне на наступну гру"
    cards = carry_beta.cards("uk")
    assert cards["aegis"][0] == "Аегіс у ворогів до 30:03"
    assert "не вистачає 530" in cards["death"][1]
    assert cards["fight"][1].startswith("ТП — готово.")


def test_a_scheduled_pair_registers_its_time_and_shows_it_in_kyiv(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("API_ADMIN_TOKEN", "local-api-fixture")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path, creative="carry-match-review", visual_revision=8)
    with telegram() as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        monkeypatch.setenv("API_URL", url)
        beta.deliver(tmp_path, shorts=True)
        registered = [json.loads(body) for route, body in calls if route == "/v1/admin/promo"]
        assert [m["youtube_publish_at"] for m in registered] == ["2026-10-21T14:00:00Z"] * 2
        videos = [body for route, body in calls if route.endswith("sendVideo")]
        assert all(b"21.10.2026 17:00" in body for body in videos)
        replies = [
            json.loads(body)["text"] for route, body in calls if route.endswith("sendMessage")
        ]
        assert "Публікація: 21.10.2026 17:00 за Києвом" in replies[0]
        assert "Publication: 21.10.2026 17:00 Kyiv time" in replies[1]


def test_a_worker_that_drops_the_publish_time_gets_no_button(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "local-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setenv("API_ADMIN_TOKEN", "local-api-fixture")
    monkeypatch.setattr(beta, "media_check", lambda _path: {"ok": True})
    pair(tmp_path, creative="carry-decisive-moments", visual_revision=9)
    with telegram(keeps=("youtube_tags", "youtube_language")) as (url, calls):
        monkeypatch.setattr(experiments, "TELEGRAM_API", url)
        monkeypatch.setenv("API_URL", url)
        with pytest.raises(SystemExit, match="preserve youtube_publish_at"):
            beta.deliver(tmp_path, shorts=True)
        assert not any(route.endswith("sendVideo") for route, _ in calls)
