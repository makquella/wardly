"""The film's soundtrack: voice-over, effects and a music bed, mixed and mastered.

Voice, effects and music are ElevenLabs takes (tools/elevenlabs_vo.py, tools/elevenlabs_sfx.py),
placed here on the frames in out/cues.json (exported from the picture's own constants by
audio/export-cues.ts). Every effect take is trimmed to its attack (or centred on its apex) and
levelled to the designed sound it replaced, so the balance of the mix stays as tuned.

    python audio/build_soundtrack.py --cues out/cues.json --out public/audio/soundtrack.wav \
        --stems out/stems --json out/qa/score.json

Music at the film's 120 BPM, three ElevenLabs parts laid on the bars with their beats on the grid:
the tension pulse under the questions stops dead on the break, the calm pad swells in after the
pause, the light groove enters on bar 8, and the music stops on the wordmark: one clean hit and
its tail. `--music code` builds the earlier numpy score (D minor, resolving to D major) instead.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import signal

SR = 48000
ROOT = Path(__file__).resolve().parent


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def t_axis(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def env_exp(n: int, tau: float, attack: float = 0.002) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / tau)


def bp(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def hp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def lp(x: np.ndarray, f: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def sweep_sine(f0: float, f1: float, sec: float, curve: float = 6.0) -> np.ndarray:
    t = t_axis(sec)
    f = f1 + (f0 - f1) * np.exp(-t * curve / sec * 4)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def fade_edges(x: np.ndarray, a: float = 0.002, b: float = 0.01) -> np.ndarray:
    n = len(x)
    na, nb = min(n, int(a * SR)), min(n, int(b * SR))
    x = x.copy()
    if na:
        x[:na] *= np.linspace(0, 1, na)
    if nb:
        x[-nb:] *= np.linspace(1, 0, nb)
    return x


def midi(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- effects
SFX = ROOT / "sfx"
MUSIC = ROOT / "music"


def decode(path: Path) -> np.ndarray:
    """An MP3 take as 48 kHz mono float."""
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.float32).astype(np.float64)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12))


# kind: (takes, level dB, how it is levelled, trim). Levels: the RMS of the designed sound each take
# replaces, at weight 1 (first 100 ms after the attack; a whoosh around its apex; a riser over its
# last 100 ms), so the mix keeps its balance. Trim: "attack" starts the take 1 ms before its first
# sample within 30 dB of its peak; "apex" centres the take's 30 ms envelope maximum on the event's
# apex; "end" ends a riser on the last frame of its build (the cut is the break).
KIT = {
    "slam": (["slam", "slam-2", "slam-3"], -11.7, "attack"),
    "tick": (["tick-2", "tick"], -24.9, "attack"),
    "riser": (["riser"], -13.0, "end"),
    "suck": (["stop"], -13.8, "attack"),
    "roll": (["letter"], -27.5, "attack"),
    "land": (["land"], -16.7, "attack"),
    "pop": (["index"], -19.4, "attack"),
    "text": (["text"], -35.1, "attack"),
    "whoosh": (["whoosh", "whoosh-2"], -22.7, "apex"),
    "bell": (["bell"], -14.9, "attack"),
    "hit": (["hit"], -9.1, "attack"),
}
LENGTH = {"text": 0.2}  # seconds kept of a take whose tail has a second bump (a stray onset on no picture event)
_takes: dict[str, np.ndarray] = {}


def take(name: str) -> np.ndarray:
    if name not in _takes:
        _takes[name] = decode(SFX / f"{name}.mp3")
    return _takes[name]


def sfx(kind: str, k: int, w: float, dur: float | None = None) -> tuple[np.ndarray, float]:
    """(the take, trimmed and levelled; its anchor in seconds from its first sample)."""
    names, level, trim = KIT[kind]
    x = take(names[k % len(names)]).copy()
    if kind in LENGTH:
        x = x[: int(LENGTH[kind] * SR)]
    x = x - np.mean(x)
    env = np.sqrt(np.convolve(x**2, np.ones(48) / 48, mode="same"))
    pk = env.max()
    if trim == "attack":
        on = max(0, int(np.argmax(env > pk * 10 ** (-30 / 20))) - int(0.001 * SR))
        x = x[on:]
        ref = x[: int(0.1 * SR)]
        anchor = 0.0
    elif trim == "apex":
        e30 = np.sqrt(np.convolve(x**2, np.ones(1440) / 1440, mode="same"))
        ap = int(np.argmax(e30))
        ref = x[max(0, ap - 2400) : ap + 2400]
        anchor = ap / SR
    else:  # end: the riser ends where its build is last within 3 dB of its loudest, trimmed to dur
        e30 = np.sqrt(np.convolve(x**2, np.ones(1440) / 1440, mode="same"))
        end = int(np.nonzero(e30 > e30.max() * 10 ** (-3 / 20))[0][-1])
        start = max(0, end - int((dur or 1.0) * SR))
        x = x[start:end] * np.linspace(0, 1, end - start) ** 2.2  # it builds into the break: quiet until the last beat, so the storm's ticks stay heard
        ref = x[-int(0.1 * SR) :]
        anchor = len(x) / SR
    x = x * 10 ** ((level - rms_db(ref)) / 20) * w
    x = fade_edges(x, 0.001 if trim != "apex" else 0.02, 0.06 if kind in LENGTH else 0.02)
    if trim == "end":
        x[-int(0.003 * SR) :] *= np.linspace(1, 0, int(0.003 * SR))  # the hard stop, without a click
    return x, anchor


# ---------------------------------------------------------------- music
CHORDS = {  # bar (1-based) -> MIDI notes (D minor, resolving to D major on the logo)
    3: [50, 57, 62, 64, 69],  # Dm(add9): swells in out of the pause
    4: [50, 57, 62, 65, 69, 76],  # Dm9
    5: [46, 53, 57, 62, 65, 72],  # Bbmaj9
    6: [41, 53, 57, 60, 64, 67],  # Fmaj9
    7: [45, 52, 55, 60, 64, 71],  # Am7(add9)
    8: [50, 57, 62, 65, 69, 76],  # Dm9
    9: [46, 53, 57, 62, 65, 72],  # Bbmaj9
    10: [43, 50, 55, 58, 62, 69],  # Gm9
    11: [45, 52, 57, 62, 64, 67],  # A7sus4
}


def pad_voice(freq: float, sec: float, seed: int) -> np.ndarray:
    t = t_axis(sec)
    r = rng(seed)
    y = np.zeros(len(t))
    for det in (-0.07, 0.0, 0.07):
        ph = r.uniform(0, 2 * np.pi)
        f = freq * 2 ** (det / 12)
        y += np.sin(2 * np.pi * f * t + ph) + 0.25 * np.sin(2 * np.pi * 2 * f * t + ph) + 0.08 * np.sin(2 * np.pi * 3 * f * t)
    return y / 3


def music(total: float, bar: float, beat: float, cues: dict) -> dict[str, np.ndarray]:
    n = int(total * SR)
    tension = np.zeros(n)
    pad = np.zeros(n)
    drums = np.zeros(n)
    brk = cues["brk"]
    storm = cues["storm"]
    # --- tension (0 .. break): a dissonant low cluster opening up, a sub pulse, ticking 16ths
    sec = brk
    t = t_axis(sec)
    cluster = sum(np.sign(np.sin(2 * np.pi * f * t + i)) * 0.2 for i, f in enumerate((midi(38), midi(39), midi(50) * 1.003, midi(45))))
    blocks = 32
    edges = np.linspace(0, len(t), blocks + 1).astype(int)
    cl = np.zeros(len(t))
    for i in range(blocks):
        fc = 180 * (6 ** (i / (blocks - 1)))
        seg = cluster[max(0, edges[i] - 4096) : edges[i + 1]]
        y = lp(seg, fc)
        cl[edges[i] : edges[i + 1]] = y[-(edges[i + 1] - edges[i]) :]
    cl *= np.linspace(0.35, 1.0, len(t))
    tension[: len(t)] += cl * 0.45
    k = 0
    while k * beat < brk - 0.01:  # sub pulse on every beat
        s = int(k * beat * SR)
        hit = sweep_sine(90, 38, 0.35, 6) * env_exp(int(0.35 * SR), 0.12, 0.002) * 0.55
        e = min(n, s + len(hit))
        tension[s:e] += hit[: e - s]
        k += 1
    step = beat / 4
    j = 0
    r = rng(11)
    while j * step < brk - 0.01:  # 16th ticks, 32nds in the storm
        at = j * step
        lvl = 0.12 + 0.18 * (at / brk)
        for sub in ([0.0, step / 2] if at >= storm else [0.0]):
            s = int((at + sub) * SR)
            nn = int(0.03 * SR)
            x = hp(r.standard_normal(nn), 6000) * env_exp(nn, 0.006, 0.0004) * lvl * (1.0 if j % 4 == 0 else 0.6)
            e = min(n, s + nn)
            tension[s:e] += x[: e - s]
        j += 1
    cut = int(brk * SR)
    tension[cut - int(0.004 * SR) : cut] *= np.linspace(1, 0, int(0.004 * SR))
    tension[cut:] = 0
    # --- pad from the card on, a bar per chord; enters softly after the pause
    pad_in = cues["pad_in"]
    for b, notes in CHORDS.items():
        start = (b - 1) * bar
        if start + bar <= pad_in:
            continue
        dur = bar + 0.6
        y = sum(pad_voice(midi(m), dur, b * 10 + i) * (0.6 if m < 48 else 0.35) for i, m in enumerate(notes))
        y = lp(y, 1400 if b < 8 else 2200)
        envl = np.minimum(1, t_axis(dur) / 0.35) * np.minimum(1, (dur - t_axis(dur)) / 0.6)
        y = y * envl * 0.18
        s = int(max(start, pad_in) * SR)
        y = y[int((max(start, pad_in) - start) * SR) :]
        if start < pad_in:  # the first entry swells in slowly out of the pause
            sw = min(len(y), int(1.6 * SR))
            y[:sw] *= np.linspace(0, 1, sw) ** 2
        e = min(n, s + len(y))
        pad[s:e] += y[: e - s]
        # a soft pluck arpeggio on 8ths over the chord
        for q in range(8):
            at = start + q * beat / 2
            if at < pad_in + beat or b == 3:  # the swell out of the pause stays a held chord
                continue
            m = notes[[2, 3, 4, 5, 4, 3, 4, 5][q]] + 12
            nn = int(0.6 * SR)
            pl = np.sin(2 * np.pi * midi(m) * t_axis(0.6)) * env_exp(nn, 0.16, 0.003)
            pl += 0.3 * np.sin(2 * np.pi * midi(m) * 2 * t_axis(0.6)) * env_exp(nn, 0.06, 0.003)
            lvl = 0.05 if b < 8 else 0.07
            s2 = int(at * SR)
            e2 = min(n, s2 + nn)
            pad[s2:e2] += pl[: e2 - s2] * lvl
    # --- air: a faint room tone under everything after the break, so the pause is quiet, never a dropout
    r0 = rng(5)
    air = lp(r0.standard_normal(n), 900) * 10 ** (-58 / 20) * 3
    air[: int(brk * SR)] = 0
    pad += air
    # --- a light kick and hat from bar 8, a clap from bar 10 (the build to the slogan)
    r = rng(23)
    for b in range(8, 12):
        for q in range(4):
            at = (b - 1) * bar + q * beat
            s = int(at * SR)
            kick = sweep_sine(120, 45, 0.4, 7) * env_exp(int(0.4 * SR), 0.11, 0.0015) * (0.28 if q in (0, 2) or b >= 10 else 0)
            e = min(n, s + len(kick))
            drums[s:e] += kick[: e - s]
            hh_at = at + beat / 2
            s3 = int(hh_at * SR)
            nn = int(0.05 * SR)
            hh = hp(r.standard_normal(nn), 7000) * env_exp(nn, 0.012, 0.0004) * 0.1
            e3 = min(n, s3 + nn)
            drums[s3:e3] += hh[: e3 - s3]
            if b >= 10 and q in (1, 3):
                nn = int(0.2 * SR)
                cp = bp(r.standard_normal(nn), 900, 3500) * env_exp(nn, 0.05, 0.001) * 0.18
                e4 = min(n, s + nn)
                drums[s:e4] += cp[: e4 - s]
    # the music stops on the bar line of the logo
    stop = int(cues["stop"] * SR)
    for x in (pad, drums):
        x[stop - int(0.02 * SR) : stop] *= np.linspace(1, 0, int(0.02 * SR))
        x[stop:] = 0
    return {"tension": tension, "pad": pad * 0.9, "drums": drums}


def beat_phase(x: np.ndarray, beat: float) -> float:
    """Seconds from the take's start to its first beat: the offset of a beat-spaced grid that
    collects the most onset strength (10 ms log-energy rises). The parts are asked for at 120 BPM
    and hold it (beat phase spread under 10 ms), so a phase is all they need to sit on the grid."""
    hop = int(0.01 * SR)
    e = np.log10(np.array([np.mean(x[i : i + hop] ** 2) for i in range(0, len(x) - hop, hop)]) + 1e-10)
    flux = np.maximum(0, np.diff(e, prepend=e[0]))
    span = int(min(len(x) / SR, 8.0) / 0.01)
    best, at = -1.0, 0.0
    for ms in range(int(beat * 1000)):
        idx = (np.arange(ms / 10, span, beat * 100)).astype(int)
        score = float(flux[idx].sum())
        if score > best:
            best, at = score, ms / 1000
    return at


def music_eleven(total: float, beat: float, cues: dict) -> tuple[dict[str, np.ndarray], dict]:
    """The three ElevenLabs parts on the film's bars, each levelled to the section it replaces
    (integrated loudness of the numpy score: tension -18.1, pad -24.5, pad + drums -22.6 LUFS)."""
    n = int(total * SR)
    meter = pyln.Meter(SR)
    brk, pad_in, groove_in, stop = cues["brk"], cues["pad_in"], cues["groove"], cues["stop"]
    info: dict = {}
    parts: dict[str, np.ndarray] = {}
    for name, start, end, lufs in (("tension", 0.0, brk, -18.1), ("calm", brk, groove_in, -24.5), ("groove", groove_in, stop, -22.6)):
        x = decode(MUSIC / f"{name}.mp3")
        ph = beat_phase(x, beat)
        need = int((end - start) * SR)
        y = x[int(ph * SR) :]
        if name == "calm" and len(y) < need:  # the pad's two-bar figure runs 8 s; loop its second turn (bar-aligned) once more
            loop = y[int(4.0 * SR) : int(8.0 * SR)]
            xf = int(0.03 * SR)
            body = y[: int(8.0 * SR)]
            while len(body) < need:
                seg = loop.copy()
                body[-xf:] = body[-xf:] * np.linspace(1, 0, xf) + seg[:xf] * np.linspace(0, 1, xf)
                body = np.concatenate([body, seg[xf:]])
            y = body
        y = y[:need]
        y = y * 10 ** ((lufs - meter.integrated_loudness(y)) / 20)
        bus = np.zeros(n)
        s0 = int(start * SR)
        bus[s0 : s0 + len(y)] = y
        parts[name] = bus
        info[name] = {"beat_phase_s": round(ph, 3), "from_s": start, "to_s": end}
    t = np.arange(n) / SR
    # the questions build: the pulse rises from -6 dB to full into the break, which cuts it dead
    parts["tension"] *= np.interp(t, [0, brk], [0.5, 1.0])
    head = int(0.025 * SR)  # the film starts from silence, then the pulse (its first beat sits on frame 0)
    parts["tension"][:head] *= np.linspace(0, 1, head) ** 2
    cut = int(brk * SR)
    parts["tension"][cut - int(0.004 * SR) : cut] *= np.linspace(1, 0, int(0.004 * SR))
    parts["tension"][cut:] = 0
    # the pad swells in slowly out of the pause; the groove takes over on bar 8
    calm = parts["calm"]
    calm[: int(pad_in * SR)] = 0
    sw = int(1.6 * SR)
    calm[int(pad_in * SR) : int(pad_in * SR) + sw] *= np.linspace(0, 1, sw) ** 2
    g0 = int(groove_in * SR)
    xo = int(0.15 * SR)
    calm[g0 - xo : g0] *= np.linspace(1, 0, xo)
    groove = parts["groove"]
    groove[g0 : g0 + int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    # air: a faint room tone under everything after the break, so the pause is quiet, never a dropout
    air = lp(rng(5).standard_normal(n), 900) * 10 ** (-58 / 20) * 3
    air[:cut] = 0
    # the music stops on the bar line of the logo
    stop_i = int(stop * SR)
    for x in (calm, groove):
        x[stop_i - int(0.02 * SR) : stop_i] *= np.linspace(1, 0, int(0.02 * SR))
        x[stop_i:] = 0
    return {"tension": parts["tension"], "pad": calm + air, "drums": groove}, info


# ---------------------------------------------------------------- mix
def place(bus: np.ndarray, x: np.ndarray, at: float, pan: float = 0.0) -> None:
    s = int(round(at * SR))
    if s < 0:
        x = x[-s:]
        s = 0
    e = min(bus.shape[0], s + len(x))
    if e <= s:
        return
    gl = np.cos((pan + 1) * np.pi / 4)
    gr = np.sin((pan + 1) * np.pi / 4)
    bus[s:e, 0] += x[: e - s] * gl * np.sqrt(2)
    bus[s:e, 1] += x[: e - s] * gr * np.sqrt(2)


def load_vo(path: Path) -> tuple[np.ndarray, float]:
    x, sr = sf.read(path, always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:
        x = signal.resample_poly(x, SR, sr)
    x = hp(x, 80)
    x = compress(x / (np.max(np.abs(x)) + 1e-9), -22, 3.0, att=0.002, rel=0.08)  # tame the take's peaks so it sits up front
    x = compress(x, -9, 8.0, att=0.0004, rel=0.04)  # and catch the plosives
    # the onset: first point the short-term level passes -38 dBFS
    env = np.sqrt(np.convolve(x**2, np.ones(240) / 240, mode="same"))
    on = int(np.argmax(env > 10 ** (-38 / 20)))
    return x, on / SR


def compress(x: np.ndarray, thr_db: float, ratio: float, att: float = 0.003, rel: float = 0.12) -> np.ndarray:
    """Feed-forward compressor on a mono signal (peak-ish envelope, soft attack/release)."""
    lvl = np.abs(x)
    a, r = np.exp(-1 / (att * SR)), np.exp(-1 / (rel * SR))
    env = np.empty_like(lvl)
    cur = 0.0
    for i, v in enumerate(lvl):
        cur = a * cur + (1 - a) * v if v > cur else r * cur + (1 - r) * v
        env[i] = cur
    db = 20 * np.log10(env + 1e-9)
    over = np.maximum(0, db - thr_db)
    return x * 10 ** (-over * (1 - 1 / ratio) / 20)


def true_peak(x: np.ndarray) -> float:
    up = signal.resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.max(np.abs(up)) + 1e-12)


def limiter(x: np.ndarray, ceiling_db: float) -> tuple[np.ndarray, float]:
    """Look-ahead peak limiter on the 4x oversampled peak, 1.5 ms attack, 80 ms release."""
    ceil = 10 ** (ceiling_db / 20)
    up = np.max(np.abs(signal.resample_poly(x, 4, 1, axis=0)), axis=1)
    peak = up[: 4 * len(x)].reshape(len(x), 4).max(axis=1)
    need = np.minimum(1.0, ceil / np.maximum(peak, 1e-9))
    look = int(0.0015 * SR)
    # hold the minimum over the look-ahead window, then smooth the release
    from scipy.ndimage import minimum_filter1d

    g = minimum_filter1d(need, size=2 * look + 1, origin=0)
    g = np.concatenate([g[look:], np.ones(look)])
    rel = np.exp(-1 / (0.08 * SR))
    out = np.empty_like(g)
    cur = 1.0
    for i, v in enumerate(g):
        cur = v if v < cur else v + (cur - v) * rel
        out[i] = cur
    hot = np.nonzero(out < 10 ** (-1.5 / 20))[0]
    limiter.hot = sorted({round(i / SR, 1) for i in hot})[:40]  # type: ignore[attr-defined]
    return x * out[:, None], float(20 * np.log10(out.min()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cues", default="out/cues.json")
    ap.add_argument("--out", default="public/audio/soundtrack.wav")
    ap.add_argument("--stems", default="out/stems")
    ap.add_argument("--json", default="out/qa/score.json")
    ap.add_argument("--lufs", type=float, default=-14.0)
    ap.add_argument("--draft", action="store_true", help="no music, effects and voice only")
    ap.add_argument("--music", choices=("eleven", "code"), default="eleven", help="ElevenLabs parts (audio/music) or the numpy score")
    a = ap.parse_args()
    data = json.loads(Path(a.cues).read_text())
    fps, total = data["fps"], data["total"]
    beat = 60 / data["bpm"]
    bar = beat * 4
    sec = total / fps
    n = int(sec * SR)
    ev = data["events"]
    byid = {e["id"]: e for e in ev}
    fr = lambda f: f / fps  # noqa: E731

    vo_bus = np.zeros((n, 2))
    fx_bus = np.zeros((n, 2))
    mu_bus = np.zeros((n, 2))
    # events.placed: what the effects stem sounds; events.skipped: cues it leaves to another stem (the
    # voice takes), so scripts/av-audit.py does not look for them in the effects stem
    report: dict = {"events": {"placed": [], "skipped": []}, "warnings": []}

    # voice: each take placed so its onset lands on its frame, levelled per take
    meter = pyln.Meter(SR)
    for i in range(1, 7):
        e = byid[f"vo{i}"]
        x, on = load_vo(ROOT / "vo" / f"vo{i}.wav")
        lv = meter.integrated_loudness(x)
        x = x * 10 ** ((-17.0 - lv) / 20)
        place(vo_bus, x, fr(e["f"]) - on, 0.0)
        report["events"]["skipped"].append({"id": e["id"], "f": e["f"], "kind": "voice", "t": round(fr(e["f"]), 3), "onset_in_take": round(on, 3), "take_lufs": round(lv, 1), "stem": "voice"})

    vo_bus, vo_gr = limiter(vo_bus, -5.0)  # the voice's peaks held 12 dB over its loudness
    report["voice_limiter_db"] = round(vo_gr, 2)

    used: dict[str, int] = {}
    for e in ev:
        kind, w, pan = e["kind"], e.get("weight", 1.0), e.get("pan", 0.0) * 0.15 / 0.2
        if kind not in KIT:
            continue
        k = used.get(kind, 0)
        used[kind] = k + 1
        if kind == "suck":
            w = 1.0  # the break is levelled as one sound, its weight only times the picture
        x, anchor = sfx(kind, k, w, e["dur"] / fps if kind == "riser" else None)
        place(fx_bus, x, fr(e["f"]) - anchor, pan)
        report["events"]["placed"].append({"id": e.get("id"), "f": e["f"], "kind": kind, "take": KIT[kind][0][k % len(KIT[kind][0])], "t": round(fr(e["f"]), 3)})

    if not a.draft:
        cues = {"brk": fr(byid["break"]["f"]), "storm": fr(byid["storm0"]["f"]), "pad_in": fr(byid["break"]["f"]) + 1.0, "groove": 7 * bar, "stop": fr(byid["lockup"]["f"])}
        if a.music == "code":
            m = music(sec, bar, beat, cues)
        else:
            m, report["music_parts"] = music_eleven(sec, beat, cues)
        for part in m.values():
            place(mu_bus, part, 0, 0)

    # duck the music under the voice (6 dB, 40 ms attack, 250 ms release)
    vo_env = np.abs(vo_bus).max(axis=1)
    vo_env = signal.sosfilt(signal.butter(1, 8, fs=SR, output="sos"), vo_env)
    talk = np.clip(vo_env / 0.02, 0, 1)
    duck = 10 ** (-6 * talk / 20)
    mu_bus *= duck[:, None]

    fx_bus = np.tanh(fx_bus * 1.5) / 1.5  # round off the effects' transients
    mix = vo_bus * 1.0 + fx_bus * 0.9 + mu_bus * 0.8
    # master: loudness to target, then the limiter for true peak
    l0 = meter.integrated_loudness(mix)
    mix *= 10 ** ((a.lufs - l0) / 20)
    mix, gr = limiter(mix, -1.6)
    hot1 = list(limiter.hot)  # type: ignore[attr-defined]
    l1 = meter.integrated_loudness(mix)
    mix *= 10 ** ((a.lufs - l1) / 20)
    mix, gr2 = limiter(mix, -1.6)
    # the head enters from zero over 3 ms (no click on frame 0), the tail decays to digital zero
    head = int(0.003 * SR)
    mix[:head] *= np.linspace(0, 1, head)[:, None]
    tail = int(0.4 * SR)
    mix[-tail:] *= np.linspace(1, 0, tail)[:, None] ** 2
    mix[-480:] = 0
    lufs = meter.integrated_loudness(mix)
    tp = true_peak(mix)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sf.write(a.out, mix, SR, subtype="PCM_24")
    stems = Path(a.stems)
    stems.mkdir(parents=True, exist_ok=True)
    g = 10 ** ((a.lufs - l0) / 20)
    for name, bus in (("voice", vo_bus), ("sfx", fx_bus * 0.9), ("music", mu_bus * 0.8)):
        sf.write(stems / f"{name}.wav", np.clip(bus * g, -1, 1), SR, subtype="PCM_24")
    report.update({"lufs": round(lufs, 2), "true_peak_db": round(tp, 2), "limiter_max_gr_db": round(min(gr, gr2), 2), "limiter_hot_s": hot1, "seconds": sec, "sfx": "ElevenLabs sound-generation (audio/sfx)", "music": "ElevenLabs music (audio/music)" if a.music == "eleven" else "numpy score", "voice": "ElevenLabs eleven_v4, Alex Nekrasov (uk)"})
    if abs(lufs - a.lufs) > 0.5:
        report["warnings"].append(f"loudness {lufs:.2f} LUFS off target {a.lufs}")
    if tp > -1.5:
        report["warnings"].append(f"true peak {tp:.2f} dBTP above -1.5")
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("lufs", "true_peak_db", "limiter_max_gr_db", "limiter_hot_s", "warnings")}))


if __name__ == "__main__":
    main()
