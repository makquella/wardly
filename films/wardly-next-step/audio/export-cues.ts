// Writes out/cues.json for audio/build_soundtrack.py: every sound event from src/sync.ts (the
// picture's own constants) plus the film's length. Run: npx tsx audio/export-cues.ts
import { mkdirSync, writeFileSync } from 'node:fs';
import cues from '../src/sync';
import { FPS, TOTAL, BPM } from '../src/timeline';

mkdirSync('out', { recursive: true });
writeFileSync('out/cues.json', JSON.stringify({ fps: FPS, total: TOTAL, bpm: BPM, events: cues() }, null, 1));
console.log(`cues: ${cues().length} events, ${TOTAL} frames`);
