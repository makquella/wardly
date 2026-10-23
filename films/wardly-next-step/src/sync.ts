// The sound events of the film, from the same constants the picture animates with.
// scripts/export-cues.ts writes them to out/cues.json; audio/build_soundtrack.py voices each one
// with a designed sound on its exact frame. Every sound has a visible cause; continuous motion
// and most moves stay silent (the music carries them).
import { CUE, FPS, TOTAL, VO } from './timeline';

export type Kind =
  | 'tick' | 'tock' | 'hit' | 'land' | 'pop' | 'whoosh' | 'riser'
  | 'drop' | 'key' | 'click' | 'snap' | 'swell' | 'bell' | 'suck' | 'text' | 'slam' | 'roll' | 'voice';

export type SoundEvent = {
  f: number;
  kind: Kind;
  weight?: number;
  pan?: number;
  pitch?: number | string;
  apexFrac?: number;
  dur?: number;
  variant?: string;
  id?: string;
};

const SLAM = 6; // frames from the spoken word to the contact (scenes/layout.ts)
const STORM = [0, 15, 23, 30, 34, 38, 41, 43, 44, 45]; // scenes/layout.ts STORM

export default function cues(): SoundEvent[] {
  const ev: SoundEvent[] = [];
  // the questions slam in on their contact frames
  [CUE.q1, CUE.q2, CUE.q3].forEach((q, i) => ev.push({ f: q + SLAM, kind: 'slam', weight: 1 + 0.1 * i, pan: [-0.1, 0.12, -0.05][i], id: `q${i + 1}-slam` }));
  // the storm: a tick on every interruption, rising
  STORM.forEach((d, j) => ev.push({ f: CUE.storm + d, kind: 'tick', weight: 0.5 + 0.05 * j, pan: [-0.2, 0.2, 0][j % 3], id: `storm${j}` }));
  ev.push({ f: CUE.brk, kind: 'riser', dur: CUE.brk - CUE.storm, id: 'storm-riser' });
  // the break: a hard stop (the riser cuts), a low suck into the quiet
  ev.push({ f: CUE.brk, kind: 'suck', weight: 0.8, dur: 40, id: 'break' });
  // the morph: three letters roll (one soft tick each), the card lands with its dot
  [0, 1, 2].forEach((j) => ev.push({ f: CUE.roll + j * 4 + 8, kind: 'roll', weight: 0.55, pan: 0.05 * j, id: `roll${j}` }));
  ev.push({ f: CUE.shrink + 24, kind: 'whoosh', weight: 0.3, dur: 44, apexFrac: 0.55, id: 'word-into-card' });
  ev.push({ f: CUE.dotLand, kind: 'land', variant: 'light', weight: 0.55, pan: -0.3, id: 'card-dot' });
  // the live card leaves, the review arrives
  ev.push({ f: CUE.away + 18, kind: 'whoosh', weight: 0.6, dur: 40, apexFrac: 0.45, id: 'card-away' });
  ev.push({ f: CUE.index, kind: 'pop', weight: 0.7, pan: -0.3, id: 'index' });
  ev.push({ f: CUE.title + 8, kind: 'text', weight: 0.5, id: 'finding' });
  ev.push({ f: CUE.drill + 22, kind: 'land', variant: 'light', weight: 0.9, pan: -0.3, id: 'red-dot' });
  // everything clears; the slogan; the dot flies to the logo; the one clean hit on «Wardly»
  ev.push({ f: CUE.clear + 24, kind: 'whoosh', weight: 0.5, dur: 44, apexFrac: 0.5, id: 'clear' });
  ev.push({ f: CUE.period, kind: 'bell', weight: 0.6, id: 'period' });
  ev.push({ f: CUE.wordmark, kind: 'hit', weight: 1, id: 'lockup' });
  // the voice-over takes
  Object.entries(VO).forEach(([id, f]) => ev.push({ f, kind: 'voice', id }));
  for (const e of ev) if (e.f < 0 || e.f > TOTAL) throw new Error(`sync: ${e.id} at ${e.f} is outside the film`);
  void FPS;
  return ev.sort((a, b) => a.f - b.f);
}
