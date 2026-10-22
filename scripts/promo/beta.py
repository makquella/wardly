"""Build a Ukrainian/English recruitment pair and privately deliver reviewed files.

Use the Promo workflow with beta_campaign=build, send=false; inspect its artifact,
then beta_campaign=deliver with beta_run_id. Secrets stay inside GitHub Actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import (
    beta_scenes,
    beta_shorts,
    carry_beta,
    experiments,
    hook_review,
    media,
    release_carry,
    render,
    scenes,
    send,
    voice,
)

KIND = "wardly-beta-recruitment"
LANGUAGES = ("uk", "en")
VISUAL_REVISION = 4
NAMES = {"uk": "Українською", "en": "English"}
SOURCES = ["site/index.html", "site/en/index.html", "README.md", "AGENTS.md"]


def save(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def catalog() -> dict[str, Any]:
    """Check the authenticated model ID rather than assuming a marketing name."""
    models = experiments._api("/v1/models")
    model = experiments.modern_model(models)
    selected = next(row for row in models if row["model_id"] == model)
    supported = {row["language_id"] for row in selected.get("languages", [])}
    if supported and not set(LANGUAGES) <= supported:
        raise SystemExit(f"{model} does not list both Ukrainian and English")
    found = experiments._api(f"/v1/voices/{voice.DEFAULT_VOICE}")
    if found.get("voice_id") != voice.DEFAULT_VOICE:
        raise SystemExit("The selected Alex Nekrasov voice is unavailable")
    return {
        "model": model,
        "v4_available": model == "eleven_v4",
        "model_ids": [row["model_id"] for row in models if row.get("can_do_text_to_speech")],
        "voice_id": voice.DEFAULT_VOICE,
        "voice_name": found.get("name", voice.DEFAULT_VOICE_NAME),
        "languages": sorted(supported),
    }


def verify_claims(online: bool) -> dict[str, Any]:
    """The campaign promises only features documented by the real product/site."""
    root = scenes.ROOT
    checks = {
        "site/index.html": ("Безкоштовно", "Windows", "підказки", "розбір"),
        "site/en/index.html": ("Free", "Windows", "in-game", "review"),
    }
    result: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sources": SOURCES,
    }
    for name, required in checks.items():
        text = (root / name).read_text(encoding="utf-8").casefold()
        assert all(token.casefold() in text for token in required), f"Unsupported claim: {name}"
    if online:
        import urllib.request

        result["live_site"] = []
        for url in ("https://luhovyimvp.dev/", "https://luhovyimvp.dev/en/"):
            request = urllib.request.Request(url, headers={"User-Agent": send.USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                text = body.decode("utf-8").casefold()
                assert response.status == 200 and "wardly" in text and "windows" in text
                assert "free" in text if url.endswith("/en/") else "безкоштов" in text
                result["live_site"].append({"url": url, "sha256": hashlib.sha256(body).hexdigest()})
    return result


def timings(
    texts: list[str],
    words: list[dict[str, Any]],
    seconds: float,
    *,
    minimum: float = 30.0,
    maximum: float = 35.0,
    tail: float = 1.2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Keep the master take continuous; scene cuts follow its actual alignment."""
    expected = " ".join(texts).split()
    if [w["word"] for w in words] != expected:
        raise ValueError("Word alignment does not reproduce the exact narration")
    # ElevenLabs v4 can put its final character's tail ~80ms beyond the PCM
    # endpoint. Bound that endpoint-only rounding; never move word starts or
    # tolerate a missing final word. The independent ASR gate still checks it.
    if not words or words[-1]["start"] >= seconds or words[-1]["end"] > seconds + 0.12:
        raise ValueError(
            f"Word alignment ends at {words[-1]['end'] if words else 'missing'}s "
            f"but audio is {seconds:.3f}s"
        )
    words = [{**word, "end": min(word["end"], seconds)} for word in words]
    for index, word in enumerate(words):
        if word["start"] < 0 or word["end"] < word["start"]:
            raise ValueError("Invalid word timestamp")
        if index and word["start"] < words[index - 1]["start"]:
            raise ValueError("Word timestamps are not monotonic")
    total = max(minimum, math.ceil((seconds + tail) * scenes.FPS) / scenes.FPS)
    if total > maximum:
        raise ValueError(
            f"Narration is {seconds:.2f}s; shorten the script rather than speeding it up"
        )
    boundaries = [0.0]
    at = 0
    for text in texts[:-1]:
        at += len(text.split())
        boundaries.append(round((words[at - 1]["end"] + words[at]["start"]) / 2, 3))
    boundaries.append(total)
    timeline = [
        {"start": start, "end": end, "voice": text}
        for start, end, text in zip(boundaries[:-1], boundaries[1:], texts, strict=True)
    ]
    captions = scenes.subtitle_lines(words, min(total, words[-1]["end"] + 0.4))
    return timeline, captions, total


def storyboard(
    language: str,
    *,
    story: Any = beta_scenes,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    texts = story.COPY[language]["voice"]
    lengths: tuple[float, ...] = (3.2, 3.8, 3.5, 2.5, 4, 2.8, 3)
    if len(texts) != len(lengths):
        # Another scene count: about as long as the words take to say.
        per_word, per_scene = getattr(story, "DRAFT_PACE", (0.45, 1.0))
        lengths = tuple(max(2.5, per_word * len(text.split()) + per_scene) for text in texts)
    words, at = [], 0.0
    for text, span in zip(texts, lengths, strict=True):
        words.extend(scenes.estimated_words(text, at + 0.05, at + span - 0.2))
        at += span
    maximum = getattr(story, "MAX_SECONDS", 27)
    return timings(texts, words, at, minimum=20, maximum=maximum, tail=0.8)


def srt(captions: list[dict[str, Any]]) -> str:
    def stamp(seconds: float) -> str:
        millis = round(seconds * 1000)
        return f"{millis // 3600000:02}:{millis // 60000 % 60:02}:{millis // 1000 % 60:02},{millis % 1000:03}"

    return "\n".join(
        f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}\n"
        for i, c in enumerate(captions, 1)
    )


def prepare_motion(out: Path, heroes: tuple[str, ...] = beta_scenes.HEROES) -> dict[str, list[str]]:
    """Reuse the promo pipeline's official Valve idle renders, with alpha intact."""
    root = out / "motion"
    root.mkdir(exist_ok=True)
    result = {}
    sources = []
    for hero in heroes:
        url = media.RENDER_VIDEO.format(hero=hero)
        video = media.download(url, root / f"{hero}.webm")
        if video is None:
            raise RuntimeError(f"Official {hero} animation is unavailable")
        target = root / hero
        target.mkdir(exist_ok=True)
        subprocess.run(
            [
                render.ffmpeg(),
                "-y",
                "-v",
                "error",
                "-c:v",
                "libvpx-vp9",
                "-i",
                str(video),
                "-vf",
                "fps=20,scale=640:-1",
                "-an",
                "-c:v",
                "libwebp",
                "-quality",
                "78",
                str(target / "%04d.webp"),
            ],
            capture_output=True,
            check=True,
        )
        frames = sorted(target.glob("*.webp"))
        if len(frames) < 20:
            raise ValueError(f"Incomplete {hero} animation")
        result[hero] = [beta_scenes.uri(frame) for frame in frames]
        sources.append(
            {
                "hero": hero,
                "url": url,
                "sha256": digest(video),
                "frames": len(frames),
                "fps": 20,
            }
        )
        print(f"{hero}: {len(frames)} animated frames")
    save(root / "sources.json", sources)
    return result


def layout_check(page_html: str, timeline: list[dict[str, Any]], folder: Path) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    path = folder / "storyboard.html"
    path.write_text(page_html, encoding="utf-8")
    errors: list[Any] = []
    checked = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=render.chrome(), args=["--allow-file-access-from-files"]
        )
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content(page_html, wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        assert page.evaluate("[...document.images].every(x=>x.complete&&x.naturalWidth>0)"), (
            "A real app image failed to load"
        )
        for index, scene in enumerate(timeline):
            for offset in (
                0,
                0.1,
                0.8,
                (scene["end"] - scene["start"]) / 2,
                scene["end"] - scene["start"] - 0.04,
            ):
                t = min(scene["end"] - 0.05, scene["start"] + offset)
                page.evaluate("t=>window.renderAt(t)", t)
                errors.extend(page.evaluate("window.layoutErrors()"))
                checked += 1
            page.evaluate("t=>window.renderAt(t)", (scene["start"] + scene["end"]) / 2)
            page.screenshot(path=str(folder / f"frame-{index}.jpg"), type="jpeg", quality=90)
        # Check every subtitle, including the longest Ukrainian lines.
        for caption in page.evaluate("captions"):
            for t in (caption["start"] + 0.01, (caption["start"] + caption["end"]) / 2):
                page.evaluate("t=>window.renderAt(t)", t)
                errors.extend(page.evaluate("window.layoutErrors()"))
                checked += 1
        browser.close()
    report = {
        "ok": not errors,
        "checked_frames": checked,
        "safe_bounds": [78, 196, 910, 1450],
        "errors": errors,
    }
    save(folder / "layout.json", report)
    if errors:
        raise ValueError(f"Layout failed: {errors[:3]}")
    return report


def media_check(video: Path) -> dict[str, Any]:
    info = render.probe(video)
    if not (
        info.get("video")
        and info.get("audio")
        and (info.get("width"), info.get("height")) == (1080, 1920)
        and 19.95 <= info.get("seconds", 0) <= 35.05
        and 0 < info["bytes"] < 49 * 1024 * 1024
    ):
        raise ValueError(f"Video fails delivery requirements: {info}")
    subprocess.run(
        [
            render.ffmpeg(),
            "-v",
            "error",
            "-xerror",
            "-i",
            str(video),
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    audio = subprocess.run(
        [
            render.ffmpeg(),
            "-hide_banner",
            "-i",
            str(video),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    # Some ffmpeg builds print final progress after the filter's JSON.
    measured, _ = json.JSONDecoder().raw_decode(audio[audio.rfind("{") :])
    loudness, peak = float(measured["input_i"]), float(measured["input_tp"])
    if not -18 <= loudness <= -11 or peak > -0.5:
        raise ValueError(f"Audio loudness/peak failed: {loudness} LUFS, {peak} dBTP")
    return {
        **info,
        "ok": True,
        "fully_decoded": True,
        "loudness_lufs": loudness,
        "true_peak_dbtp": peak,
    }


def build(out: Path, *, draft: bool = False, creative: str = "sven-under-4k") -> None:
    story: Any = beta_scenes
    revision = VISUAL_REVISION
    claims = verify_claims(online=not draft)
    if creative == release_carry.CREATIVE:
        # The 0.57 release pair: its own claims from the shipped carry plans.
        story = release_carry.profile()
        revision = release_carry.REVISION
        claims["release"] = release_carry.verify()
    elif creative == hook_review.CREATIVE:
        # The test Short in the dynamic hook format (docs/marketing/shorts-rules.md).
        story = hook_review.profile()
        revision = hook_review.REVISION
        claims["hook_review"] = hook_review.verify()
    elif creative in carry_beta.CREATIVES:
        # The scheduled carry-beta pairs: claims from the app's own texts.
        story = carry_beta.profile(creative)
        revision = carry_beta.REVISION[creative]
        claims["carry_beta"] = carry_beta.verify(creative)
    elif creative != "sven-under-4k":
        from . import beta_followups

        story = beta_followups.profile(creative)
        revision = {"juggernaut-review": 5, "terrorblade-feedback": 6}[creative]
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    save(out / "claims.json", claims)
    selected = None if draft else catalog()
    if selected:
        save(out / "voice-catalog.json", selected)
    motion = {} if draft else prepare_motion(out, getattr(story, "HEROES", beta_scenes.HEROES))
    for language in LANGUAGES:
        folder = out / language
        folder.mkdir(exist_ok=True)
        texts = story.COPY[language]["voice"]
        text = " ".join(texts)
        (folder / "script.txt").write_text(text + "\n", encoding="utf-8")
        if draft:
            timeline, captions, total = storyboard(language, story=story)
        else:
            assert selected
            os.environ.update(
                {
                    "ELEVENLABS_MODEL": selected["model"],
                    "ELEVENLABS_VOICE_ID": voice.DEFAULT_VOICE,
                    "ELEVENLABS_VOICE_NAME": voice.DEFAULT_VOICE_NAME,
                    "ELEVENLABS_LANGUAGE": language,
                    "ELEVENLABS_STABILITY": "0.5",
                    "ELEVENLABS_SPEED": "1.0",
                    "ELEVENLABS_CONTINUOUS": "true",
                }
            )
            cache_path = folder / "narration-config.json"
            identity = {"text": text, "voice_config": voice.configuration()}
            cached = json.loads(cache_path.read_text()) if cache_path.exists() else None
            if (
                cached == identity
                and (folder / "narration.wav").exists()
                and (folder / "alignment.json").exists()
            ):
                master = folder / "narration.wav"
                words = json.loads((folder / "alignment.json").read_text())
            else:
                result = voice.synthesize(text, folder / "narration.wav")
                if result is None:
                    raise SystemExit("ELEVENLABS_API_KEY is required; never deliver a silent draft")
                master, words = result
                save(folder / "alignment.json", words)
                save(cache_path, identity)
            timeline, captions, total = timings(
                texts,
                words,
                voice.duration(master),
                minimum=20,
                maximum=getattr(story, "MAX_SECONDS", 27),
                tail=0.8,
            )
            voice.join([(master, total)], folder / "padded.wav")
        aligned = [
            {"word": word["w"], "start": word["s"], "end": word["e"]}
            for caption in captions
            for word in caption["words"]
        ]
        captions = story.phrase_captions(language, aligned, captions[-1]["end"])
        save(folder / "timeline.json", timeline)
        save(folder / "captions.json", captions)
        (folder / "captions.srt").write_text(srt(captions), encoding="utf-8")
        page_html = story.page(language, timeline, captions, motion)
        layout = layout_check(page_html, timeline, folder)
        package = {
            "kind": KIND,
            "language": language,
            "draft": draft,
            "commit": os.environ.get("GITHUB_SHA"),
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "seconds": total,
            "voice_config": voice.configuration() if not draft else None,
            "continuous": True,
            "visual_revision": revision,
            "creative": creative,
            "animated_heroes": sorted(motion),
            "layout": layout,
        }
        if not draft:
            render.render(
                page_html,
                total,
                folder / "video.mp4",
                folder / "padded.wav",
                cover=folder / "cover.jpg",
                inline=True,
            )
            package["quality"] = media_check(folder / "video.mp4")
            package["sha256"] = digest(folder / "video.mp4")
            save(folder / "youtube-metadata.json", beta_shorts.package(language, package))
            (folder / "padded.wav").unlink()
        save(folder / "package.json", package)
        print(f"{language}: {'storyboard' if draft else 'video'} {total:.2f}s; layout passed")


def deliver(out: Path, *, shorts: bool = False) -> None:
    """Send privately; the explicit Shorts mode adds the existing YouTube-only callback."""
    bot, chat = send._env("TELEGRAM_BOT_TOKEN"), send._env("TELEGRAM_CHAT_ID")
    endpoint = f"{experiments.TELEGRAM_API}/bot{bot}"
    private = send._request(
        endpoint + "/getChat",
        method="POST",
        data=json.dumps({"chat_id": chat}).encode(),
        headers={"Content-Type": "application/json"},
    )
    if not private.get("ok") or private.get("result", {}).get("type") != "private":
        raise SystemExit(
            "Beta previews require a private developer chat; refusing channel/group delivery"
        )
    # Validate the entire pair before the first network upload.
    packages = {}
    receipt_name = "shorts-approval-receipt.json" if shorts else "telegram-receipt.json"
    for language in LANGUAGES:
        folder = out / language
        package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        if (
            package.get("kind") != KIND
            or package.get("draft")
            or package.get("language") != language
        ):
            raise ValueError("Artifact is not the requested finished beta campaign")
        if (
            not package.get("layout", {}).get("ok")
            or digest(folder / "video.mp4") != package["sha256"]
        ):
            raise ValueError("Reviewed artifact failed layout or integrity verification")
        speech = json.loads((folder / "speech-check.json").read_text(encoding="utf-8"))
        if (
            not speech.get("ok")
            or speech.get("language") != language
            or speech.get("sha256") != package["sha256"]
        ):
            raise ValueError("The narration has not passed speech/language verification")
        media_check(folder / "video.mp4")
        receipt_path = folder / receipt_name
        if receipt_path.exists():
            previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not previous.get("ok") or previous.get("sha256") != package["sha256"]:
                raise ValueError("Existing Telegram receipt belongs to a different video")
            if (
                shorts
                and previous.get("youtube_package_id")
                != beta_shorts.package(language, package)["id"]
            ):
                raise ValueError("Existing Shorts receipt belongs to different metadata")
        packages[language] = package
    metadata = {}
    if shorts:
        api, token = send._env("API_URL").rstrip("/"), send._env("API_ADMIN_TOKEN")
        for language, package in packages.items():
            folder = out / language
            metadata[language] = beta_shorts.package(language, package)
            if not (folder / receipt_name).exists():
                send.register(metadata[language], folder, api, token)
                save(folder / "youtube-metadata.json", metadata[language])
            else:
                stored = json.loads((folder / "youtube-metadata.json").read_text())
                if stored["id"] != metadata[language]["id"]:
                    raise ValueError("Stored YouTube metadata changed")
                metadata[language] = stored
    for language, package in packages.items():
        folder = out / language
        receipt_path = folder / receipt_name
        if receipt_path.exists():
            print(f"{language}: already delivered; preserving its Telegram receipt")
            if shorts:
                shorts_details(endpoint, chat, folder, metadata[language], language)
            continue
        fields = {
            "chat_id": chat,
            "supports_streaming": "true",
            "width": "1080",
            "height": "1920",
            "duration": str(round(package["seconds"])),
            "caption": f"Wardly · v{package.get('visual_revision', 1)} · {NAMES[language]} · {package['seconds']:.2f} s\n"
            + (
                "Бета-тестування · приватний перегляд. Публікацію не заплановано."
                if language == "uk"
                else "Beta recruitment · private review. No publication scheduled."
            )
            + f"\n{package['voice_config']['name']} · {package['voice_config']['model']}",
        }
        if shorts:
            meta = metadata[language]
            copy = beta_shorts.COPY[language]
            fields["caption"] = (
                f"Wardly · v{package['visual_revision']} · {NAMES[language]} · {package['seconds']:.2f} s\n"
                f"{meta['youtube_title']}\n\n"
                + copy["ready" if meta.get("youtube_ready") else "not_connected"]
            )
            if meta.get("youtube_publish_at"):
                when = carry_beta.kyiv(meta["youtube_publish_at"])
                fields["caption"] += (
                    f"\n🕔 YouTube: {when} (Київ)"
                    if language == "uk"
                    else f"\n🕔 YouTube: {when} (Kyiv)"
                )
            fields["reply_markup"] = json.dumps(
                beta_shorts.keyboard(language, meta["id"]), ensure_ascii=False
            )
        native_path = folder / "native-schedule.json"
        if not shorts and native_path.exists():
            native = json.loads(native_path.read_text())
            if not native.get("verified") or native["sha256"] != package["sha256"]:
                raise ValueError("Native schedule receipt does not match this video")
            at = datetime.fromisoformat(native["publish_at"].replace("Z", "+00:00")).astimezone(
                ZoneInfo("Europe/Kyiv")
            )
            fields["caption"] = (
                f"Wardly · {NAMES[language]} · {package['seconds']:.2f} s\n"
                + ("Автопублікація YouTube: " if language == "uk" else "Scheduled on YouTube: ")
                + at.strftime("%d.%m.%Y %H:%M")
                + (" (Київ)" if language == "uk" else " (Kyiv)")
                + f"\n{native['url']}"
            )
        body, kind = send.multipart(
            fields,
            {
                "video": (
                    f"wardly-beta-{language}-v{package.get('visual_revision', 1)}.mp4",
                    "video/mp4",
                    (folder / "video.mp4").read_bytes(),
                ),
                "thumbnail": (
                    "cover.jpg",
                    "image/jpeg",
                    (folder / "cover.jpg").read_bytes(),
                ),
            },
        )
        answer = send._request(
            endpoint + "/sendVideo",
            method="POST",
            data=body,
            headers={"Content-Type": kind},
        )
        result = answer.get("result", {})
        if not answer.get("ok") or not result.get("message_id") or not result.get("video"):
            raise ValueError("Telegram did not confirm video delivery; do not retry blindly")
        receipt = {
            "method": "sendVideo",
            "ok": answer["ok"],
            "message_id": result["message_id"],
            "chat_type": result["chat"]["type"],
            "video": {
                key: result["video"].get(key)
                for key in ("width", "height", "duration", "file_size")
            },
            "sha256": package["sha256"],
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        if shorts:
            receipt.update(
                {
                    "youtube_package_id": metadata[language]["id"],
                    "youtube_ready": metadata[language]["youtube_ready"],
                    "callback_data": f"promo:yt:{metadata[language]['id']}",
                }
            )
        save(receipt_path, receipt)
        print(f"{language}: Telegram API confirmed " + json.dumps(receipt))
        if shorts:
            shorts_details(endpoint, chat, folder, metadata[language], language)


def shorts_details(
    endpoint: str, chat: str, folder: Path, metadata: dict[str, Any], language: str
) -> None:
    """A failed details reply can resume without uploading the video twice."""
    path = folder / "shorts-approval-receipt.json"
    receipt = json.loads(path.read_text())
    if receipt.get("details_message_id"):
        return
    answer = send._request(
        endpoint + "/sendMessage",
        method="POST",
        data=json.dumps(
            {
                "chat_id": chat,
                "text": beta_shorts.details(language, metadata),
                "reply_to_message_id": receipt["message_id"],
                "disable_web_page_preview": True,
            },
            ensure_ascii=False,
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    if not answer.get("ok") or not answer.get("result", {}).get("message_id"):
        raise ValueError("Telegram did not confirm the Shorts metadata reply")
    receipt["details_message_id"] = answer["result"]["message_id"]
    save(path, receipt)


def transcript_similarity(expected: str, actual: str) -> float:
    """Compare speech without treating frequent letters in long prose as junk."""
    import re
    from difflib import SequenceMatcher

    def normalize(text: str) -> str:
        text = text.casefold().replace("wardley", "wardly").replace("вордлі", "wardly")
        return " ".join(re.findall(r"[\w]+", text))

    return SequenceMatcher(None, normalize(expected), normalize(actual), autojunk=False).ratio()


def speech_check(out: Path) -> None:
    """Independently recognize the rendered speech, including the English delivery."""
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
    for language in LANGUAGES:
        folder = out / language
        segments, info = model.transcribe(str(folder / "video.mp4"), beam_size=5, vad_filter=True)
        transcript = " ".join(segment.text.strip() for segment in segments)
        expected = (folder / "script.txt").read_text(encoding="utf-8")

        similarity = transcript_similarity(expected, transcript)
        report = {
            "ok": info.language == language
            and info.language_probability >= 0.65
            and similarity >= 0.7,
            "language": info.language,
            "language_probability": info.language_probability,
            "transcript": transcript,
            "similarity": round(similarity, 4),
            "model": "faster-whisper/small",
            "sha256": digest(folder / "video.mp4"),
        }
        save(folder / "speech-check.json", report)
        print(f"{language}: speech check " + json.dumps(report, ensure_ascii=False))
        if not report["ok"]:
            raise ValueError(f"{language}: inspect the narration before delivering")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("promo-out"))
    parser.add_argument("--draft", action="store_true", help="local storyboard only; never send")
    parser.add_argument(
        "--deliver-only",
        action="store_true",
        help="send the exact previously reviewed artifact",
    )
    parser.add_argument(
        "--speech-check",
        action="store_true",
        help="independent ASR/language verification",
    )
    parser.add_argument(
        "--shorts-approval",
        action="store_true",
        help="register reviewed videos and send YouTube-only buttons",
    )
    parser.add_argument(
        "--creative",
        default="sven-under-4k",
        choices=(
            "sven-under-4k",
            release_carry.CREATIVE,
            *carry_beta.CREATIVES,
            hook_review.CREATIVE,
        ),
        help=(
            "which pair to build (0.57 release: release_carry.py; carry beta: "
            "carry_beta.py; hook format test: hook_review.py)"
        ),
    )
    args = parser.parse_args()
    if sum((args.draft, args.deliver_only, args.speech_check, args.shorts_approval)) > 1:
        parser.error("choose one of draft, speech-check, deliver-only and shorts-approval")
    if args.speech_check:
        speech_check(args.out)
    elif args.deliver_only:
        deliver(args.out)
    elif args.shorts_approval:
        deliver(args.out, shorts=True)
    else:
        build(args.out, draft=args.draft, creative=args.creative)


if __name__ == "__main__":
    main()
