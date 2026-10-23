"""The film's soundtrack: voice-over, designed effects and a music bed, mixed and mastered.

Everything except the voice is synthesised here (numpy/scipy), deterministic, on the frames in
out/cues.json (exported from the picture's own constants by audio/export-cues.ts). The voice takes
are audio/vo/vo1..vo6.wav (ElevenLabs engine through Higgsfield, voice "Alexey").

    python audio/build_soundtrack.py --cues out/cues.json --out public/audio/soundtrack.wav \
        --stems out/stems --json out/qa/score.json

Music in D minor at the film's 120 BPM: a tense pulse under the questions that stops dead on the
break, a quiet pad once the card appears, a light kick from the review to the slogan, and on the
logo the music stops on the bar line and resolves to D major: one clean hit and its tail.
"""

from __future__ import annotations

import argparse
import json
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
def sfx_slam(w: float, seed: int) -> np.ndarray:
    n = int(0.9 * SR)
    body = sweep_sine(110, 42, 0.9, 5) * env_exp(n, 0.22, 0.001)
    r = rng(seed)
    crack = bp(r.standard_normal(n), 900, 5000) * env_exp(n, 0.018, 0.0005) * 0.9
    thud = bp(r.standard_normal(n), 120, 500) * env_exp(n, 0.07, 0.001) * 0.8
    return fade_edges(np.tanh((body * 1.0 + crack + thud) * 1.4) * 0.42 * w)


def sfx_tick(w: float, seed: int) -> np.ndarray:
    n = int(0.08 * SR)
    r = rng(seed)
    click = hp(r.standard_normal(n), 3500) * env_exp(n, 0.006, 0.0003)
    blip = np.sin(2 * np.pi * 2400 * t_axis(0.08)) * env_exp(n, 0.012, 0.0005) * 0.4
    return fade_edges((click + blip) * 0.35 * w)


def sfx_riser(sec: float, seed: int) -> np.ndarray:
    n = int(sec * SR)
    r = rng(seed)
    noise = r.standard_normal(n)
    out = np.zeros(n)
    # a band of noise whose centre climbs exponentially, filtered in short blocks
    blocks = 48
    edges = np.linspace(0, n, blocks + 1).astype(int)
    for i in range(blocks):
        fc = 500 * (14 ** (i / (blocks - 1)))
        seg = noise[max(0, edges[i] - 2048) : edges[i + 1]]
        y = bp(seg, fc / 1.6, min(fc * 1.6, SR / 2 - 100))
        out[edges[i] : edges[i + 1]] = y[-(edges[i + 1] - edges[i]) :]
    ramp = np.linspace(0, 1, n) ** 2.2
    tone = np.sin(2 * np.pi * np.cumsum(np.geomspace(220, 880, n)) / SR) * 0.15
    y = (out + tone) * ramp * 0.5
    y[-int(0.003 * SR) :] *= np.linspace(1, 0, int(0.003 * SR))  # the hard stop, without a click
    return y


def sfx_break(seed: int) -> np.ndarray:
    n = int(1.6 * SR)
    sub = np.sin(2 * np.pi * 44 * t_axis(1.6)) * env_exp(n, 0.45, 0.004)
    r = rng(seed)
    air = lp(r.standard_normal(n), 400) * env_exp(n, 0.25, 0.002) * 0.25
    return fade_edges((sub + air) * 0.32)


def sfx_roll(w: float, seed: int) -> np.ndarray:
    n = int(0.06 * SR)
    r = rng(seed)
    x = bp(r.standard_normal(n), 1800, 5000) * env_exp(n, 0.008, 0.0004)
    tone = np.sin(2 * np.pi * 1320 * t_axis(0.06)) * env_exp(n, 0.015, 0.0005) * 0.5
    return fade_edges((x + tone) * 0.3 * w)


def sfx_land(w: float, seed: int) -> np.ndarray:
    n = int(0.5 * SR)
    pop = sweep_sine(980, 620, 0.5, 8) * env_exp(n, 0.05, 0.0008)
    low = np.sin(2 * np.pi * 150 * t_axis(0.5)) * env_exp(n, 0.06, 0.001) * 0.6
    r = rng(seed)
    tx = bp(r.standard_normal(n), 2000, 7000) * env_exp(n, 0.006, 0.0003) * 0.4
    return fade_edges((pop * 0.55 + low + tx) * 0.5 * w)


def sfx_pop(w: float) -> np.ndarray:
    n = int(0.25 * SR)
    x = sweep_sine(760, 560, 0.25, 8) * env_exp(n, 0.04, 0.0008)
    return fade_edges(x * 0.35 * w)


def sfx_text(w: float, seed: int) -> np.ndarray:
    n = int(0.12 * SR)
    r = rng(seed)
    x = bp(r.standard_normal(n), 1500, 6000) * env_exp(n, 0.01, 0.0005)
    return fade_edges(x * 0.2 * w)


def sfx_whoosh(sec: float, apex: float, w: float, seed: int) -> np.ndarray:
    n = int(sec * SR)
    r = rng(seed)
    noise = r.standard_normal(n)
    t = np.linspace(0, 1, n)
    shape = np.exp(-((t - apex) ** 2) / (2 * 0.16**2))
    lo = bp(noise, 300, 1500)
    hi = bp(noise, 1500, 6000)
    mixw = np.clip((t - apex + 0.3) / 0.6, 0, 1)
    y = (lo * (1 - mixw) + hi * mixw) * shape
    return fade_edges(y * 0.35 * w, 0.01, 0.02)


def bell(freq: float, sec: float, w: float) -> np.ndarray:
    n = int(sec * SR)
    t = t_axis(sec)
    y = np.zeros(n)
    for ratio, amp, tau in ((1.0, 1.0, 1.1), (2.0, 0.35, 0.6), (2.76, 0.25, 0.35), (5.4, 0.1, 0.15)):
        y += amp * np.sin(2 * np.pi * freq * ratio * t) * env_exp(n, tau, 0.002)
    return fade_edges(y * 0.25 * w, 0.002, 0.05)


def sfx_hit(w: float, seed: int) -> np.ndarray:
    sec = 3.0
    n = int(sec * SR)
    sub = np.sin(2 * np.pi * midi(38) * t_axis(sec)) * env_exp(n, 0.55, 0.003)
    r = rng(seed)
    tx = bp(r.standard_normal(n), 800, 6000) * env_exp(n, 0.02, 0.0006) * 0.5
    b = bell(midi(74), sec, 1.2) + bell(midi(81), sec, 0.6) + bell(midi(78), sec, 0.5)  # D5 A5 F#5: D major
    return fade_edges((sub * 0.9 + tx + b) * 0.55 * w, 0.002, 0.3)


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
    return {"tension": tension, "pad": pad, "drums": drums}


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
    report: dict = {"events": [], "warnings": []}

    # voice: each take placed so its onset lands on its frame, levelled per take
    meter = pyln.Meter(SR)
    for i in range(1, 7):
        e = byid[f"vo{i}"]
        x, on = load_vo(ROOT / "vo" / f"vo{i}.wav")
        lv = meter.integrated_loudness(x)
        x = x * 10 ** ((-17.0 - lv) / 20)
        place(vo_bus, x, fr(e["f"]) - on, 0.0)
        report["events"].append({"id": e["id"], "t": round(fr(e["f"]), 3), "onset_in_take": round(on, 3), "take_lufs": round(lv, 1)})

    vo_bus, vo_gr = limiter(vo_bus, -5.0)  # the voice's peaks held 12 dB over its loudness
    report["voice_limiter_db"] = round(vo_gr, 2)

    for k, e in enumerate(ev):
        kind, w, pan = e["kind"], e.get("weight", 1.0), e.get("pan", 0.0) * 0.15 / 0.2
        at = fr(e["f"])
        x = None
        if kind == "slam":
            x = sfx_slam(w, k)
        elif kind == "tick":
            x = sfx_tick(w, k)
        elif kind == "riser":
            d = e["dur"] / fps
            x = sfx_riser(d, k)
            at -= d
        elif kind == "suck":
            x = sfx_break(k)
        elif kind == "roll":
            x = sfx_roll(w, k)
        elif kind == "land":
            x = sfx_land(w, k)
        elif kind == "pop":
            x = sfx_pop(w)
        elif kind == "text":
            x = sfx_text(w, k)
        elif kind == "whoosh":
            d = e["dur"] / fps
            x = sfx_whoosh(d, e.get("apexFrac", 0.5), w, k)
            at -= d * e.get("apexFrac", 0.5)
        elif kind == "bell":
            x = bell(midi(86), 1.6, w)  # D6
        elif kind == "hit":
            x = sfx_hit(w, k)
        if x is not None:
            place(fx_bus, x, at, pan)
            report["events"].append({"id": e.get("id"), "kind": kind, "t": round(fr(e["f"]), 3)})

    if not a.draft:
        cues = {"brk": fr(byid["break"]["f"]), "storm": fr(byid["storm0"]["f"]), "pad_in": fr(byid["break"]["f"]) + 1.0, "stop": fr(byid["lockup"]["f"])}
        m = music(sec, bar, beat, cues)
        place(mu_bus, m["tension"], 0, 0)
        place(mu_bus, m["pad"] * 0.9, 0, 0)
        place(mu_bus, m["drums"], 0, 0)

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
    # the tail decays to digital zero
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
    report.update({"lufs": round(lufs, 2), "true_peak_db": round(tp, 2), "limiter_max_gr_db": round(min(gr, gr2), 2), "limiter_hot_s": hot1, "seconds": sec, "sfx": "designed in code (numpy), no external samples", "voice": "ElevenLabs engine via Higgsfield, preset voice Alexey"})
    if abs(lufs - a.lufs) > 0.5:
        report["warnings"].append(f"loudness {lufs:.2f} LUFS off target {a.lufs}")
    if tp > -1.5:
        report["warnings"].append(f"true peak {tp:.2f} dBTP above -1.5")
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("lufs", "true_peak_db", "limiter_max_gr_db", "limiter_hot_s", "warnings")}))


if __name__ == "__main__":
    main()
