# The six voice takes from the repository's ElevenLabs preset (scripts/promo/voice.py: Alex
# Nekrasov, eleven_v4, uk, stability 0.5, speed 1.0). One take per file:
#   audio/vo/voN.src.mp3  as delivered by the API
#   audio/vo/voN.wav      48 kHz mono, silence trimmed to 30 ms before the onset and 150 ms after the end
# Needs ELEVENLABS_API_KEY (sent only as a header, never printed).
#   python tools/elevenlabs_vo.py            all six
#   python tools/elevenlabs_vo.py 3 6        re-take vo3 and vo6
import json, os, subprocess, sys, urllib.error, urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

VOICE = "9Sj8ugvpK1DmcAXyvi3a"  # Alex Nekrasov - Confident and Clear
MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v4")
TEXTS = {
    1: "Що купити? Чому відстаю? Що змінити?",
    2: "Під час гри — одна коротка порада.",
    3: "Після гри — чесний розбір матчу.",
    4: "Де саме ви відстали — і що змінити наступного разу.",
    5: "Менше хаосу. Чіткіший наступний крок.",
    6: "Wardly. Безкоштовно для Windows.",
}
VO = Path(__file__).resolve().parent.parent / "audio" / "vo"
SR = 48000


def tts(text: str, key: str) -> bytes:
    body = {"text": text, "model_id": MODEL, "language_code": "uk", "voice_settings": {"stability": 0.5, "speed": 1.0}}
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg", "User-Agent": "Wardly promo"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ElevenLabs: HTTP {e.code} {e.read(400).decode('utf-8', 'replace').replace(key, '[redacted]')}") from None


def to_wav(src: Path, dst: Path) -> float:
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.float32).astype(np.float64)
    env = np.sqrt(np.convolve((x / (np.abs(x).max() + 1e-9)) ** 2, np.ones(240) / 240, mode="same"))
    loud = np.nonzero(env > 10 ** (-45 / 20))[0]
    a, b = max(0, loud[0] - int(0.03 * SR)), min(len(x), loud[-1] + int(0.15 * SR))
    y = x[a:b]
    y[: int(0.003 * SR)] *= np.linspace(0, 1, int(0.003 * SR))
    y[-int(0.04 * SR) :] *= np.linspace(1, 0, int(0.04 * SR))
    sf.write(dst, y, SR, subtype="PCM_24")
    return len(y) / SR


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is required")
    for n in [int(a) for a in sys.argv[1:]] or sorted(TEXTS):
        src = VO / f"vo{n}.src.mp3"
        src.write_bytes(tts(TEXTS[n], key))
        print(f"vo{n}: {MODEL}, {to_wav(src, VO / f'vo{n}.wav'):.2f} s")


if __name__ == "__main__":
    main()
