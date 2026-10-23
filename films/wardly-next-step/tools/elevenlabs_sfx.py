# Sound effects and the music bed from ElevenLabs (after scripts/promo/sound_effects.py):
#   audio/sfx/<name>.mp3     sound-generation, one file per effect (variants: <name>-2.mp3, ...)
#   audio/music/<part>.mp3   music in three parts, laid on the film's bars by the build (120 BPM, D minor)
#   audio/sfx/report.json    what was asked and what came back
# audio/build_soundtrack.py trims each take to its attack (or its apex) and places it on its cue.
# Needs ELEVENLABS_API_KEY (sent only as a header, never printed).
#   python tools/elevenlabs_sfx.py               every effect and the music
#   python tools/elevenlabs_sfx.py slam bell     only these (re-take)
#   python tools/elevenlabs_sfx.py music         only the music (or one part: calm)
import json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
ROOT = Path(__file__).resolve().parent.parent / "audio"
# name: (prompt, seconds, variants[, prompt influence, default 0.6]). Dry, close, short: they sit under a voice and on a cue.
EFFECTS = {
    "slam": ("Heavy punchy impact, a fist slamming a wooden desk layered with a deep cinematic hit, dry, tight, instant attack, no reverb", 1.0, 3),
    "tick": ("Tiny crisp digital clock tick, a single very short dry high click", 0.5, 2),
    "riser": ("Tense cinematic noise riser with a rising synth tone, building fast for one second and cutting off abruptly, no impact", 1.2, 1),
    "stop": ("A single muffled low thud that drops away into silence, soft sub bass impact with a short downward pitch fall, quiet room, clean", 1.6, 2),
    "letter": ("One tiny soft wooden click, a single short tap, very short and dry, no hiss", 0.5, 2),
    "land": ("Soft user interface pop, a small dot dropping into place, gentle rounded click with a tiny low thump, minimal", 0.5, 1),
    "index": ("A single soft bubble pop, short rounded user interface notification blip, clear and audible, dry", 0.5, 2),
    "text": ("Very soft short paper swipe, text appearing on a screen, subtle user interface sound", 0.5, 1),
    "whoosh": ("Clean airy whoosh, soft and smooth, a card sliding past, modern user interface motion, no impact", 0.8, 2),
    "bell": ("Single small bright bell chime, one clear pure tone with a gentle short decay, no reverb wash", 1.5, 1),
    "hit": ("A single clean bell-like logo hit: one low sub thump and a bright ringing chime struck once, decaying smoothly, one strike only, dry and clean", 3.0, 3, 0.7),
}
# The music bed in three parts, each asked for alone so it keeps its character (one request with a
# section plan came back as a single sub-bass drone with no change at the break). The build lays
# them on the film's bars (src/timeline.ts: 120 BPM, bar = 2 s): «tension» until the break (4.0 s),
# silence, «calm» swelling in after the pause, «groove» from bar 8 (14 s), and it stops on the
# wordmark (22.0 s). Each part runs longer than its slot so none of them ends on its own.
MUSIC = {
    "tension": "Tense dark electronic pulse at exactly 120 BPM in D minor: a punchy sub bass hit on every beat, fast ticking closed hi-hat sixteenths, a dissonant detuned synth cluster slowly opening its filter, building pressure, instrumental, no melody, no vocals",
    "calm": "Calm warm ambient synth pad in D minor at exactly 120 BPM with a soft gentle plucked arpeggio on eighth notes, spacious, airy, quiet, no drums, no sub bass, instrumental, clean modern tech product, no vocals",
    "groove": "Light minimal electronic groove at exactly 120 BPM in D minor: soft kick on every beat, crisp closed hi-hats on the off-beats, soft claps on two and four, warm synth pad and plucked arpeggio, hopeful and rising, instrumental, clean modern tech product, no vocals",
}


def post(path: str, body: dict, key: str, timeout: int = 300) -> bytes:
    for pause in (5, 15, None):
        req = urllib.request.Request(
            f"{API}{path}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg", "User-Agent": "Wardly promo"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read(400).decode("utf-8", "replace").replace(key, "[redacted]").strip()
            if e.code in (429, 500, 502, 503, 504) and pause is not None:
                time.sleep(pause)
                continue
            raise RuntimeError(f"HTTP {e.code} {detail}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if pause is not None:
                time.sleep(pause)
                continue
            raise RuntimeError(str(e).replace(key, "[redacted]")) from None
    raise RuntimeError("no response")


def main() -> None:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is required")
    only = set(sys.argv[1:])
    (ROOT / "sfx").mkdir(parents=True, exist_ok=True)
    (ROOT / "music").mkdir(parents=True, exist_ok=True)
    rep_path = ROOT / "sfx" / "report.json"
    report = json.loads(rep_path.read_text()) if rep_path.exists() else {}
    for name, (prompt, sec, variants, *rest) in EFFECTS.items():
        influence = rest[0] if rest else 0.6
        if only and name not in only:
            continue
        for v in range(1, variants + 1):
            out = ROOT / "sfx" / (f"{name}.mp3" if v == 1 else f"{name}-{v}.mp3")
            data = post("/sound-generation", {"text": prompt, "duration_seconds": sec, "prompt_influence": influence}, key)
            out.write_bytes(data)
            report[out.name] = {"prompt": prompt, "seconds": sec, "bytes": len(data)}
            print(f"{out.name}: {len(data)} bytes")
    for name, prompt in MUSIC.items():
        if only and name not in only and "music" not in only:
            continue
        data = post("/music", {"prompt": prompt, "music_length_ms": 12000, "model_id": "music_v1", "force_instrumental": True}, key, timeout=600)
        (ROOT / "music" / f"{name}.mp3").write_bytes(data)
        report[f"music/{name}.mp3"] = {"prompt": prompt, "seconds": 12, "bytes": len(data)}
        print(f"music/{name}.mp3: {len(data)} bytes")
    rep_path.write_text(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
