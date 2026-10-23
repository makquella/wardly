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
  panTo?: number; // the pan travels from `pan` to here over the sound (a directional sweep)
  variant?: string;
  id?: string;
};

const ITEMS = 6; // scenes/Dota.tsx: five items and the TP scroll, a 16th apart
const ITEM_STEP = 7.5; // scenes/Dota.tsx ITEM_STEP
const SLOT_PAN = [-0.35, 0, 0.35, -0.35, 0, 0.5]; // the slot's column, left to right

export default function cues(): SoundEvent[] {
  const ev: SoundEvent[] = [];
  // Juggernaut stops dead: one short hit (the music's first beat lands with it)
  // the swoosh of his move from the right, into the stop
  ev.push({ f: CUE.hit - 5, kind: 'whoosh', weight: 0.55, dur: 18, apexFrac: 0.55, pan: 0.5, panTo: 0, id: 'hero-move' });
  ev.push({ f: CUE.hit, kind: 'slam', weight: 1.2, pan: 0.1, id: 'hero-hit' });
  // the camera runs up the blade and its shape opens: one sweep, travelling left to right with it
  ev.push({ f: CUE.wipe, kind: 'whoosh', weight: 0.9, dur: 40, apexFrac: 0.6, pan: -0.6, panTo: 0.6, id: 'blade-sweep' });
  // each item clicks into its slot
  for (let i = 0; i < ITEMS; i++) ev.push({ f: CUE.item0 + i * ITEM_STEP, kind: 'click', weight: i === ITEMS - 1 ? 0.6 : 0.8, pan: SLOT_PAN[i], id: `item${i}` });
  // the focus moves between the two candidates
  ev.push({ f: CUE.optA, kind: 'tick', weight: 0.55, pan: 0.25, id: 'focus-damage' });
  ev.push({ f: CUE.optB, kind: 'tick', weight: 0.65, pan: -0.3, id: 'focus-bkb' });
  // the pick is silent; then the pause (the music stops dead), and the card opens
  ev.push({ f: CUE.brk, kind: 'suck', weight: 0.5, dur: 40, id: 'break' }); // a soft stop: the pause is quiet
  ev.push({ f: CUE.reveal + 2, kind: 'pop', weight: 0.8, pan: -0.35, id: 'card-open' });
  ev.push({ f: CUE.reveal + 26, kind: 'text', weight: 0.5, id: 'card-text' });
  ev.push({ f: CUE.why + 4, kind: 'text', weight: 0.4, id: 'card-why' });
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
