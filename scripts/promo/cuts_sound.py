"""The sound of a Wardly Cut: the voice, a pulse under it, and a hit for every
move on screen. Everything but the voice is synthesised here from sines and
noise (numpy): no samples, no generated effects, the same file for the same
timeline.

`events()` reads the moments from the timeline the page draws (cuts.js): the
times there and here come from the same scene data, so a number lands with
its sound. `mix()` writes a 48 kHz stereo WAV as long as the video.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np

SR = 48000
BPM = 96
# Loudness of the layers before the master (linear gains).
VOICE = 1.0
BED = 0.17
EFFECTS = 0.44
# The moments of the stun scene, as cuts.js plays them (shares of the scene).
STUN_HITS = (0.08, 0.2, 0.33, 0.47, 0.6, 0.72, 0.84)
STUN_DEATH = 0.86


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    """A fast linear attack and an exponential decay (seconds)."""
    t = np.arange(n) / SR
    rise = np.clip(t / max(attack, 1e-4), 0, 1)
    return rise * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, n)


def _band(x: np.ndarray, low: float, high: float) -> np.ndarray:
    """A band of `x` with soft edges (FFT)."""
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    edge_low = np.clip((freqs - low * 0.7) / max(low * 0.3, 1), 0, 1)
    edge_high = np.clip((high * 1.3 - freqs) / max(high * 0.3, 1), 0, 1)
    return np.fft.irfft(spectrum * edge_low * edge_high, len(x))


def _sweep(x: np.ndarray, start: float, end: float, q: float = 2.2) -> np.ndarray:
    """`x` through a band-pass whose centre moves from `start` to `end` Hz."""
    n = len(x)
    centre = start * (end / start) ** (np.arange(n) / max(n - 1, 1))
    f = 2 * np.sin(np.pi * np.minimum(centre, SR / 6.5) / SR)
    out = np.empty(n)
    low = band = 0.0
    damp = 1 / q
    for i in range(n):
        low += f[i] * band
        high = x[i] - low - damp * band
        band += f[i] * high
        out[i] = band
    return out


def whoosh(seconds: float = 0.28, seed: int = 1, up: bool = True) -> np.ndarray:
    """Air passing: the cut between two scenes."""
    n = int(seconds * SR)
    body = _sweep(_noise(n, seed), 350 if up else 4200, 4200 if up else 350)
    t = np.arange(n) / n
    shape = np.sin(np.pi * t**1.6) ** 2
    return body * shape * 0.9


def impact(power: float = 1.0, seed: int = 2) -> np.ndarray:
    """A low hit with a short crack on top: a number or a name landing."""
    n = int(0.7 * SR)
    t = np.arange(n) / SR
    pitch = 42 + 70 * np.exp(-t * 26)
    sub = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-t * (5.5 - 1.5 * min(power, 1.5)))
    body = _band(_noise(n, seed), 90, 900) * _env(n, 0.002, 0.07)
    crack = _band(_noise(n, seed + 1), 1800, 9000) * _env(n, 0.0005, 0.018)
    return np.tanh((sub * 0.95 + body * 0.6 + crack * 0.5) * (0.7 + 0.5 * power)) * 0.9


def thud(seed: int = 3) -> np.ndarray:
    """A smaller, drier hit."""
    n = int(0.28 * SR)
    t = np.arange(n) / SR
    pitch = 60 + 90 * np.exp(-t * 40)
    sub = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-t * 14)
    body = _band(_noise(n, seed), 200, 2400) * _env(n, 0.001, 0.03)
    return (sub * 0.8 + body * 0.5) * 0.8


def tick(pitch: float = 2100.0) -> np.ndarray:
    """One step of a counter."""
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * pitch * t) * np.exp(-t * 190) * 0.5


def ding() -> np.ndarray:
    """The app's card appearing: two clear partials."""
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 880 * t) * np.exp(-t * 5) + 0.6 * np.sin(
        2 * np.pi * 1318.5 * t
    ) * np.exp(-t * 7)
    tone += 0.25 * np.sin(2 * np.pi * 2637 * t) * np.exp(-t * 12)
    return tone * np.clip(t / 0.004, 0, 1) * 0.45


def slash(seed: int = 5) -> np.ndarray:
    """A guess crossed out."""
    n = int(0.16 * SR)
    return _sweep(_noise(n, seed), 5200, 900, 1.6) * _env(n, 0.004, 0.05) * 1.2


def riser(seconds: float, seed: int = 6) -> np.ndarray:
    """Tension before an answer."""
    n = int(seconds * SR)
    t = np.arange(n) / n
    return _sweep(_noise(n, seed), 180, 5200, 3.0) * t**2.4 * 0.8


def rewind(seconds: float, seed: int = 7) -> np.ndarray:
    """A tape running backwards."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    share = np.arange(n) / n
    pitch = 240 + 1100 * share**1.4 + 60 * np.sin(2 * np.pi * 23 * t)
    tone = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    chop = 0.55 + 0.45 * np.sign(np.sin(2 * np.pi * 31 * t))
    hiss = _band(_noise(n, seed), 1500, 9000) * 0.35
    shape = np.clip(share / 0.05, 0, 1) * np.clip((1 - share) / 0.08, 0, 1)
    return (tone * 0.4 * chop + hiss) * shape * 0.7


def activation() -> np.ndarray:
    """An item pressed in time: a bright chord opening over a low hit."""
    n = int(1.1 * SR)
    t = np.arange(n) / SR
    chord = sum(
        np.sin(2 * np.pi * f * t) * a
        for f, a in ((440, 1), (659.3, 0.8), (880, 0.7), (1318.5, 0.35))
    )
    chord *= np.clip(t / 0.02, 0, 1) * np.exp(-t * 3.2) * (1 + 0.15 * np.sin(2 * np.pi * 9 * t))
    shimmer = _band(_noise(n, 9), 5000, 12000) * _env(n, 0.03, 0.25) * 0.5
    out = chord * 0.24 + shimmer * 0.4
    hit = impact(0.9, 10)
    out[: len(hit)] += hit[: len(out)] * 0.8
    return out


def punch(seed: int = 11) -> np.ndarray:
    """A hit taken: dull and short."""
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    sub = np.sin(2 * np.pi * np.cumsum(70 + 80 * np.exp(-t * 50)) / SR) * np.exp(-t * 18)
    body = _band(_noise(n, seed), 300, 3200) * _env(n, 0.001, 0.035)
    return (sub * 0.7 + body * 0.8) * 0.85


def events(timeline: dict[str, Any]) -> list[tuple[float, str, float]]:
    """(second, sound, gain) for every move the page makes."""
    found: list[tuple[float, str, float]] = []
    for index, scene in enumerate(timeline["scenes"]):
        start, end = scene["start"], scene["end"]
        length = end - start
        data, cues, kind = scene["data"], scene.get("cues") or {}, scene["type"]
        words = scene.get("words") or []
        if index:
            found.append((start - 0.2, "whoosh", 0.7))

        def cue(name: str, fallback: float, cues: dict = cues, start: float = start) -> float:
            return cues.get(name, start + fallback)

        if kind == "statement":
            for line in data["lines"]:
                for part in line:
                    if part.get("hot"):
                        at = next(
                            (
                                w["start"]
                                for w in words
                                if w["w"].strip(".,:;!?—").lower()
                                == part["w"].strip(".,:;!?—").lower()
                            ),
                            None,
                        )
                        if at is not None:
                            found.append((at, "thud", 0.7))
        elif kind == "rank":
            final = bool(data.get("final"))
            found.append((start + 0.14, "impact", 1.0 if final else 0.6))
            found.append((cue("b", 0.5) - 0.2, "whoosh", 0.6))
            found.append((cue("b", 0.5) + 0.1, "thud", 0.9))
            at = cue("pct", 1.2 if final else 0.55)
            if final:
                found.append((at - 1.1, "riser:1.0", 0.8))
            found += [(at - 0.5 + step * 0.05, "tick", 0.5) for step in range(10)]
            found.append((at, "impact", 1.5 if final else 0.75))
        elif kind == "source":
            at = cue("count", 0.3)
            found += [(at - 0.15 + step * 0.045, "tick", 0.45) for step in range(20)]
            found.append((at + 0.85, "impact", 0.8))
        elif kind == "grid":
            at = cue("mark", 1.0)
            span = max(0.5, min(1.6, length - (at - start) - 0.3))
            count = len(data["marked"])
            found += [(at + i / max(1, count - 1) * span, "tick:1500", 0.75) for i in range(count)]
        elif kind == "guess":
            for item in data["items"]:
                at = words[item["word"]]["start"] if item["word"] < len(words) else start + 0.3
                found.append((at - 0.1, "whoosh", 0.5))
                found.append((at + 0.2, "slash", 0.9))
                found.append((at + 0.24, "thud", 0.8))
        elif kind == "reveal":
            found.append((start - 0.9, "riser:0.9", 0.9))
            found.append((start + 0.06, "impact", 1.6))
            if data.get("count"):
                at = cue("count", 0.9)
                found += [(at - 0.1 + step * 0.045, "tick", 0.45) for step in range(11)]
                found.append((at + 0.4, "impact", 0.8))
        elif kind == "podium":
            for item in data["items"]:
                if item.get("dim"):
                    continue
                at = (
                    words[item["word"]]["start"]
                    if item.get("word", 99) < len(words)
                    else start + 0.4
                )
                found.append((at + 0.42, "impact", 0.7))
        elif kind == "matchup":
            found.append((start + 0.2, "impact", 0.9))
            at = cue("pct", 0.6)
            found += [(at - 0.45 + step * 0.05, "tick", 0.5) for step in range(9)]
            found.append((at, "impact", 1.0))
        elif kind == "card":
            at = cue("card", 0.25)
            found.append((at - 0.12, "whoosh", 0.6))
            found.append((at + 0.05, "thud", 0.8))
            found.append((at + 0.08, "ding", 1.0))
        elif kind == "stun":
            if data.get("back"):
                found.append((start + 0.1, f"rewind:{max(0.4, length - 0.2):.2f}", 1.0))
            elif data.get("saved"):
                found.append((cue("press", 0.4), "activation", 1.0))
            else:
                found += [
                    (start + share * length, "punch", 0.75 + 0.05 * i)
                    for i, share in enumerate(STUN_HITS)
                ]
                found.append((start + STUN_DEATH * length, "impact", 1.6))
        elif kind == "end":
            found.append((start + 0.12, "impact", 0.9))
            at = cue("site", 0.5)
            found += [(at + step * 0.035, "tick:1700", 0.4) for step in range(16)]
    return found


def _sound(name: str, seed: int) -> np.ndarray:
    kind, _, value = name.partition(":")
    if kind == "whoosh":
        return whoosh(seed=seed)
    if kind == "impact":
        return impact(seed=seed)
    if kind == "thud":
        return thud(seed)
    if kind == "tick":
        return tick(float(value) if value else 2100.0)
    if kind == "ding":
        return ding()
    if kind == "slash":
        return slash(seed)
    if kind == "riser":
        return riser(float(value), seed)
    if kind == "rewind":
        return rewind(float(value), seed)
    if kind == "activation":
        return activation()
    if kind == "punch":
        return punch(seed)
    raise ValueError(name)


def _place(track: np.ndarray, sound: np.ndarray, at: float, gain: float, pan: float = 0.0) -> None:
    """Add a mono sound to the stereo track at `at` seconds (pan -1..1)."""
    first = int(round(at * SR))
    if first < 0:
        sound = sound[-first:]
        first = 0
    last = min(first + len(sound), track.shape[0])
    if last <= first:
        return
    piece = sound[: last - first] * gain
    track[first:last, 0] += piece * (1 - max(pan, 0) * 0.6)
    track[first:last, 1] += piece * (1 + min(pan, 0) * 0.6)


def bed(total: float, drops: list[float], lift: float) -> np.ndarray:
    """The pulse under the video: a low note on every eighth, a soft kick on
    every beat from `lift` on, a dark chord far behind. It falls silent for a
    moment before each of `drops` (the answers), so the hit lands in a gap."""
    n = int(total * SR)
    t = np.arange(n) / SR
    beat = 60 / BPM
    out = np.zeros(n)
    # The low pulse: A1, eighths, each with its own short decay.
    phase = (t % (beat / 2)) / (beat / 2)
    pulse = np.sin(2 * np.pi * 55 * t) * np.exp(-phase * 3.2)
    pulse += 0.35 * np.sin(2 * np.pi * 110 * t) * np.exp(-phase * 5)
    out += pulse * 0.55
    # The chord: A, C, E an octave up, breathing slowly.
    chord = sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate((110.0, 130.8, 164.8, 220.0)))
    out += chord * 0.05 * (0.7 + 0.3 * np.sin(2 * np.pi * t / (beat * 8)))
    # The kick, once the video is moving.
    kick_n = int(0.3 * SR)
    kt = np.arange(kick_n) / SR
    kick = np.sin(2 * np.pi * np.cumsum(46 + 95 * np.exp(-kt * 38)) / SR) * np.exp(-kt * 13)
    hat_n = int(0.05 * SR)
    hat = _band(_noise(hat_n, 21), 6500, 14000) * _env(hat_n, 0.0005, 0.012)
    step = 0
    while step * beat / 2 < total:
        at = step * beat / 2
        first = int(at * SR)
        if at >= lift:
            if step % 2 == 0:
                last = min(first + kick_n, n)
                out[first:last] += kick[: last - first] * 0.75
            else:
                last = min(first + hat_n, n)
                out[first:last] += hat[: last - first] * 0.28
        step += 1
    gain = np.ones(n)
    for drop in drops:
        first, last = int((drop - 0.42) * SR), int(drop * SR)
        if 0 <= first < last <= n:
            gain[first:last] *= np.linspace(1, 0.0, last - first) ** 2
            tail = min(n, last + int(0.25 * SR))
            gain[last:tail] *= np.linspace(0.2, 1, tail - last)
    fade = int(0.6 * SR)
    gain[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    gain[: int(0.08 * SR)] *= np.linspace(0, 1, int(0.08 * SR))
    return out * gain


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getframerate() != SR or source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise ValueError(f"the voice must be 48 kHz mono 16-bit: {path}")
        return (
            np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64)
            / 32768
        )


def voice_track(take: Path, cuts: list[dict[str, float]], total: float) -> np.ndarray:
    """The take cut between beats and put where the timeline says."""
    source = _read(take)
    peak = float(np.max(np.abs(source))) or 1.0
    source = source / peak * 0.85
    out = np.zeros(int(total * SR))
    fade = int(0.006 * SR)
    for cut in cuts:
        piece = source[int(cut["from"] * SR) : int(cut["to"] * SR)].copy()
        if len(piece) < 2 * fade:
            continue
        piece[:fade] *= np.linspace(0, 1, fade)
        piece[-fade:] *= np.linspace(1, 0, fade)
        first = int(cut["at"] * SR)
        last = min(first + len(piece), len(out))
        if last > first >= 0:
            out[first:last] += piece[: last - first]
    return out


def _follow(signal: np.ndarray, release: float = 0.25) -> np.ndarray:
    """How loud `signal` is, smoothed: what the bed ducks under."""
    hop = SR // 100
    frames = len(signal) // hop
    level = np.sqrt(np.mean(signal[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    smooth = np.empty(frames)
    value, fall = 0.0, np.exp(-1 / (release * 100))
    for i in range(frames):
        value = max(level[i], value * fall)
        smooth[i] = value
    return np.clip(np.repeat(smooth, hop) / 0.12, 0, 1)


def mix(timeline: dict[str, Any], take: Path | None, out: Path) -> Path:
    total = timeline["total"]
    n = int(total * SR)
    track = np.zeros((n, 2))
    voice = voice_track(take, timeline["cuts"], total) if take is not None else np.zeros(n)
    moves = events(timeline)
    drops = [at for at, name, gain in moves if name == "impact" and gain >= 1.5]
    lift = timeline["scenes"][1]["start"] if len(timeline["scenes"]) > 1 else 0.0
    under = bed(total, drops, lift)
    duck = 1 - 0.55 * _follow(voice)
    under = under[:n] * np.pad(duck, (0, max(0, n - len(duck))), constant_values=1.0)[:n]
    track[:, 0] += under * BED
    track[:, 1] += under * BED
    for index, (at, name, gain) in enumerate(sorted(moves)):
        pan = ((index * 37) % 7 - 3) / 6 if name.startswith(("whoosh", "tick", "slash")) else 0.0
        _place(track, _sound(name, 100 + index), at, gain * EFFECTS, pan)
    track[:, 0] += voice[:n] * VOICE
    track[:, 1] += voice[:n] * VOICE
    track = np.tanh(track * 1.1) / np.tanh(1.1)
    peak = float(np.max(np.abs(track))) or 1.0
    track = track / peak * 0.84
    with wave.open(str(out), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(SR)
        target.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
    return out
