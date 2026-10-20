"""Hand a package to the developer for approval:

  1. register it in the Worker (POST /v1/admin/promo) and upload the video
     and the cover to R2 (PUT /v1/admin/promo/<id>/<file>);
  2. send the video to TELEGRAM_CHAT_ID with three buttons
     (✅ Всюди · 📣 Лише Telegram · ▶️ Лише YouTube · ❌ Відхилити) and, as a
     reply, the details:
     captions per network, sources, the quality report.

The buttons go to the Worker's webhook (src/promo.js); nothing is published
from here. Environment: API_URL, API_ADMIN_TOKEN, TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID. Tokens are never printed.

    python -m scripts.promo.send promo-out
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

TIMEOUT = 120
# Cloudflare in front of the Worker refuses urllib's default "Python-urllib"
# agent (error 1010), so every request names itself.
USER_AGENT = "Wardly promo"
FORMAT_NAMES = {
    "coach": "Що підкаже Wardly",
    "meta": "Мета тижня",
    "hero": "Герой",
    "fact": "Факт тижня",
    "release": "Оновлення",
}


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _request(
    url: str,
    *,
    data: bytes | None = None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> Any:
    request = urllib.request.Request(
        url, data=data, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        # What the server said, so a failed run names its reason; the bot
        # token in Telegram's URL never reaches the log.
        detail = error.read(300).decode("utf-8", "replace").strip()
        raise SystemExit(f"{method} {redact(url)}: HTTP {error.code} {detail}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise SystemExit(f"{method} {redact(url)}: {redact(str(error))}") from None
    return json.loads(body) if body else {}


def redact(url: str) -> str:
    return re.sub(r"/bot[^/]+/", "/bot***/", url)


# Per-video YouTube metadata the Worker must keep (services/api/src/promo.js);
# youtube_publish_at schedules the video on YouTube itself.
YOUTUBE_KEYS = ("youtube_tags", "youtube_language", "youtube_publish_at")


def register(package: dict[str, Any], folder: Path, api: str, token: str) -> str:
    auth = {"Authorization": f"Bearer {token}"}
    meta = {
        key: package[key]
        for key in (
            "id",
            "format",
            "topic",
            "hook",
            "title",
            "youtube_title",
            "caption",
            "telegram_caption",
        )
    }
    meta.update({key: package[key] for key in YOUTUBE_KEYS if key in package})
    answer = _request(
        f"{api}/v1/admin/promo",
        data=json.dumps(meta, ensure_ascii=False).encode(),
        method="POST",
        headers={**auth, "Content-Type": "application/json"},
    )
    for key in YOUTUBE_KEYS:
        if key in meta and answer.get(key) != meta[key]:
            raise SystemExit(f"Worker did not preserve {key}; deploy the updated API first")
    if "youtube_language" in meta:
        package["youtube_ready"] = answer.get("youtube_ready") is True
        if answer.get("status") != "pending":
            raise SystemExit("This Shorts package was already decided; do not send another button")
    for name, kind in (("video.mp4", "video/mp4"), ("cover.jpg", "image/jpeg")):
        path = folder / name
        if path.exists():
            _request(
                f"{api}/v1/admin/promo/{package['id']}/{name}",
                data=path.read_bytes(),
                method="PUT",
                headers={**auth, "Content-Type": kind},
            )
    return str(answer["media_key"])


def keyboard(package_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Всюди", "callback_data": f"promo:all:{package_id}"},
                {"text": "📣 Лише Telegram", "callback_data": f"promo:tg:{package_id}"},
            ],
            [
                {"text": "▶️ Лише YouTube", "callback_data": f"promo:yt:{package_id}"},
                {"text": "❌ Відхилити", "callback_data": f"promo:no:{package_id}"},
            ],
        ]
    }


def approval_caption(package: dict[str, Any]) -> str:
    report = package["quality"]
    lines = [
        (
            f"<b>{html.escape(FORMAT_NAMES.get(package['format'], package['format']))}</b> · "
            f"{html.escape(package['title'])}"
        ),
        f"{package['seconds']:.0f} с · голос: {html.escape(package.get('voice', '?'))}",
    ]
    profile = package.get("voice_config")
    if profile and package.get("voice") == "elevenlabs":
        lines[1] = (
            f"{package['seconds']:.0f} с · {html.escape(profile['name'])} · "
            f"{html.escape(profile['model'])}"
        )
    if report["warnings"]:
        lines.append("⚠️ " + html.escape("; ".join(report["warnings"]))[:400])
    lines.append("Опублікувати? Деталі — у відповіді нижче.")
    return "\n".join(lines)[:1024]


def details(package: dict[str, Any]) -> str:
    sources = "\n".join(f"• {html.escape(s)}" for s in package["script"]["sources"])
    return (
        "<b>TikTok / Instagram</b>\n"
        f"<pre>{html.escape(package['caption'])}</pre>\n"
        f"<b>YouTube</b>: {html.escape(package['youtube_title'])}\n"
        f"<b>Telegram-канал</b>\n<pre>{html.escape(package['telegram_caption'])}</pre>\n"
        f"<b>Звідки дані</b>\n{sources}"
    )[:4000]


def multipart(
    fields: dict[str, str], files: dict[str, tuple[str, str, bytes]]
) -> tuple[bytes, str]:
    boundary = f"wardly-{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, kind, data) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {kind}\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_for_approval(package: dict[str, Any], folder: Path, bot: str, chat: str) -> int:
    files = {"video": ("wardly.mp4", "video/mp4", (folder / "video.mp4").read_bytes())}
    cover = folder / "cover.jpg"
    if cover.exists():
        files["thumbnail"] = ("cover.jpg", "image/jpeg", cover.read_bytes())
    media = package.get("media") or {}
    body, kind = multipart(
        {
            "chat_id": chat,
            "caption": approval_caption(package),
            "parse_mode": "HTML",
            "supports_streaming": "true",
            "width": str(media.get("width", 1080)),
            "height": str(media.get("height", 1920)),
            "duration": str(round(media.get("seconds", package["seconds"]))),
            "reply_markup": json.dumps(keyboard(package["id"])),
        },
        files,
    )
    sent = _request(
        f"https://api.telegram.org/bot{bot}/sendVideo",
        data=body,
        method="POST",
        headers={"Content-Type": kind},
    )
    message_id = int(sent["result"]["message_id"])
    _request(
        f"https://api.telegram.org/bot{bot}/sendMessage",
        data=json.dumps(
            {
                "chat_id": chat,
                "text": details(package),
                "parse_mode": "HTML",
                "reply_to_message_id": message_id,
            }
        ).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return message_id


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "promo-out")
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    if not package["quality"]["ok"]:
        raise SystemExit(
            "the package did not pass the quality check: " + "; ".join(package["quality"]["errors"])
        )
    if not (folder / "video.mp4").exists():
        raise SystemExit("no video.mp4 in the package")
    api = _env("API_URL").rstrip("/")
    register(package, folder, api, _env("API_ADMIN_TOKEN"))
    message = send_for_approval(
        package, folder, _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    )
    print(f"sent for approval: {package['format']} · {package['topic']} (message {message})")


if __name__ == "__main__":
    main()
