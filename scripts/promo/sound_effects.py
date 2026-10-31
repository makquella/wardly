"""Sound effects and a music bed for the hook-format Shorts, from ElevenLabs.

`beta_campaign=sfx` runs this in the Promo workflow with the existing
ELEVENLABS_API_KEY and keeps the MP3s in the run's artifact (promo-out/sfx);
the cut mixes them under the narration. A failed music request is reported and
skipped (the plan may not include music); the effects are required.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .voice import USER_AGENT

API = "https://api.elevenlabs.io/v1"
# name: (prompt, seconds). Short, dry hits that sit under a voice.
EFFECTS = {
    "slam": (
        "Heavy fist slam on a wooden gaming desk, keyboard and can rattle, close and punchy",
        1.2,
    ),
    "boom": ("Deep cinematic trailer boom impact with sub bass tail, dark and huge", 2.5),
    "hit": ("Short punchy cinematic hit, tight transient, modern trailer style", 0.8),
    "whoosh": ("Fast airy whoosh transition, left to right, clean, modern UI motion", 0.7),
    "swipe": ("Quick digital swipe transition with a subtle glitch tail", 0.6),
    "riser": ("Tense cinematic riser building up for two seconds into a sudden stop", 2.0),
    "logo": (
        "Magical shimmering reveal with a bright sparkle and a soft bass bloom, game logo sting",
        2.0,
    ),
    "typing": ("Fast typing on a mechanical keyboard, ten crisp clicky keystrokes", 1.2),
    "enter": ("Single heavy mechanical keyboard Enter key press, satisfying thock", 0.5),
    "click": ("Crisp futuristic UI button click", 0.5),
    "check": ("Bright positive UI confirmation ping, game interface, short", 0.5),
    "tick": ("Tiny digital counter tick, very short", 0.5),
    "score": ("Score counter rolling up fast and landing with a satisfying ding", 1.5),
    "stamp": ("Rubber stamp slammed hard on a wooden table, punchy thud", 0.8),
    "glitch": ("Short harsh digital glitch stutter, data corruption", 0.6),
    "chat": ("Game chat message notification pop, short and soft", 0.5),
    "sword": ("Metal sword clash with sparks, short and sharp", 1.0),
}
MUSIC = (
    "Dark energetic trap beat for a gaming promo, 140 BPM, punchy 808 bass, crisp hi-hats, "
    "tense synth stabs, cinematic hits, no vocals, builds fast, loops cleanly"
)


def request(path: str, body: dict, key: str, timeout: int = 180) -> bytes:
    data = json.dumps(body).encode("utf-8")
    for pause in (5, 15, None):
        call = urllib.request.Request(
            f"{API}{path}",
            data=data,
            method="POST",
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(call, timeout=timeout) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read(300).decode("utf-8", "replace").replace(key, "[redacted]")
            if error.code in (429, 500, 502, 503, 504) and pause is not None:
                time.sleep(pause)
                continue
            raise RuntimeError(f"HTTP {error.code} {detail.strip()}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            if pause is not None:
                time.sleep(pause)
                continue
            raise RuntimeError(str(error).replace(key, "[redacted]")) from None
    raise RuntimeError("no response")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("promo-out/sfx"))
    parser.add_argument("--music-seconds", type=int, default=32)
    args = parser.parse_args()
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is required")
    args.out.mkdir(parents=True, exist_ok=True)
    report: dict[str, str] = {}
    for name, (prompt, seconds) in EFFECTS.items():
        audio = request(
            "/sound-generation",
            {"text": prompt, "duration_seconds": seconds, "prompt_influence": 0.6},
            key,
        )
        (args.out / f"{name}.mp3").write_bytes(audio)
        report[name] = f"{len(audio)} bytes"
        print(f"{name}: {len(audio)} bytes")
    try:
        music = request(
            "/music",
            {"prompt": MUSIC, "music_length_ms": args.music_seconds * 1000},
            key,
            timeout=300,
        )
        (args.out / "music.mp3").write_bytes(music)
        report["music"] = f"{len(music)} bytes"
    except RuntimeError as error:
        report["music"] = f"skipped: {error}"
    print(f"music: {report['music']}")
    (args.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
