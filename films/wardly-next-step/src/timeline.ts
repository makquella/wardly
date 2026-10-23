// The single source of truth for time. Picture (src/acts), sound (src/sync.ts -> out/cues.json)
// and QA (scripts/grid-check.ts) all import this file, so a change here moves everything together.
// Think in bars and beats, never in seconds. Keep this file free of React and CSS imports:
// Node scripts load it directly.
import { holdFor, PACE, readingWindows, revealFor, wordCount, type PaceName } from './lib/pace';

export { PACE } from './lib/pace'; // grid-check checks COPY against the film's own pace numbers

export const FPS = 60;
export const BPM = 120;
export const W = 1080;
export const H = 1920;
/**
 * The film's pace (src/lib/pace.ts). calm: text arrives as short fragments that take turns with
 * the picture, held about 1-1.5 s (the default for text-led films, at 90-100 BPM). crisp: the
 * denser launch-film tempo, for briefs that ask for energy (at 120 BPM).
 */
export const PACE_NAME: PaceName = 'crisp';

/** Frames per beat. Must be a whole number (grid-check fails otherwise): 60 fps -> 90, 100, 120, 144, 150 BPM. */
export const BEAT = (60 / BPM) * FPS;
export const BAR = BEAT * 4;
/**
 * Absolute frame of a grid position: bar is 1-based, beat 0-3, sub = 16ths within the beat.
 * b(3) is the downbeat of bar 3; b(2, 1, 2) is the "and" of beat 2 in bar 2.
 */
export const b = (bar: number, beat = 0, sub = 0) => Math.round(((bar - 1) * 4 + beat) * BEAT + sub * (BEAT / 4));

/**
 * A choreography length written in 60 fps frames (the unit every number in the cinetic
 * references uses), converted to this film's fps. Cues come from b(); durations inside a move
 * use f60(), so the film keeps its timing if --fps changes.
 */
export const f60 = (frames: number) => Math.round((frames * FPS) / 60);

/** After the last bar the picture holds while the audio decays to digital silence. */
export const TAIL = FPS;

// Acts: contiguous, bar-aligned, [from, from + dur). The film is one continuous take (objects
// travel across act seams), so the acts are ranges of one picture, not separate shots.
export const ACT = {
  chaos: { from: b(1), dur: b(3) - b(1) }, // three questions collide over the app's own numbers
  live: { from: b(3), dur: b(6) - b(3) }, // the break; «купити» becomes «Купіть» of the real overlay card
  review: { from: b(6), dur: b(10) - b(6) }, // «Чому відстаю?» / «Що змінити?» answered by the real review card
  resolve: { from: b(10), dur: b(13) + TAIL - b(10) }, // one red dot: the slogan's full stop, then the logo
};

export const TOTAL = b(13) + TAIL;

/** Voice-over takes (audio/vo/voN.wav) and where they start. Spoken words drive the cues below. */
export const VO = {
  vo1: 8, // offgrid: voice «Що купити? Чому відстаю? Що змінити?» (3.6 s: starts early so «Що змінити?» lands before the storm)
  vo2: b(4, 0, 1) - 2, // offgrid: voice «Під час гри — одна коротка порада.»
  vo3: b(6, 0, 2), // «Після гри — чесний розбір матчу.» as «Чому відстаю?» comes forward
  vo4: b(7, 2, 2), // «Де саме ви відстали — і що змінити наступного разу.» (a breath after «матчу.»)
  vo5: b(10), // «Менше хаосу. Чіткіший наступний крок.» (on the clear, so «крок.» lands before the logo)
  vo6: b(11, 3) + 10, // offgrid: voice «Wardly. Безкоштовно для Windows.» «Wardly» as the wordmark appears; «Windows.» ends before the tail
};

// Named sync points (absolute frames). Voice-led cues sit where the word is spoken.
export const CUE = {
  q1: VO.vo1, // offgrid: voice «Що купити?» slams in on «Що»
  q2: VO.vo1 + 76, // offgrid: voice «Чому відстаю?»
  q3: VO.vo1 + 160, // offgrid: voice «Що змінити?»
  storm: b(2, 2, 2), // the questions start interrupting each other on 8ths (scenes/layout.ts STORM_T ends on the break)
  brk: b(3), // the break: everything stops
  settle: b(3, 1, 2), // the noise has fallen away; one question is left
  hook: b(3, 2), // «Що» leaves and the «?» loses its hook
  roll: b(3, 2, 2), // «купити» rolls to «Купіть»
  shrink: b(3, 3, 2), // the word shrinks into the card, the card grows around it
  dotLand: b(4, 1), // the dot lands as the card's status dot
  away: b(6), // the live card recedes
  q2Come: b(6, 0, 1), // offgrid: overlap «Чому відстаю?» comes forward from the top edge as the card leaves
  review: b(6, 1), // the review card builds
  index: b(6, 3), // the «?» dot becomes the finding's index
  title: b(7), // the finding's title and text
  push: VO.vo4 + 57, // offgrid: voice the camera pushes onto 36 / 65 on «відстали»
  q3Come: VO.vo4 + 134, // offgrid: voice «Що змінити?» rises from the bottom edge on «змінити»
  drill: VO.vo4 + 178, // offgrid: voice the drill opens; the dot turns red
  clear: b(10), // everything clears to the red dot
  slogan1: VO.vo5, // «Менше хаосу.»
  slogan2: VO.vo5 + 105, // offgrid: voice «Чіткіший наступний крок.» lands just after the word is spoken, once «Менше хаосу.» is read
  period: VO.vo5 + 175, // offgrid: voice «крок.» — the red dot is the full stop
  logo: b(11, 3), // the dot flies to the logo's orbit; the orbit draws itself
  wordmark: b(12), // «Wardly» locks: the one clean hit
  cta: b(12, 2), // the address
  end: b(13),
};
export type Copy = {
  id: string;
  text: string; // exactly what is on screen (\n separates lines)
  in: number; // first frame any of it is visible
  resolved: number; // first frame it is fully readable
  out: number; // first frame it starts to leave (TOTAL if it stays)
  kind?: 'copy' | 'ui'; // 'ui': a string the product shows (a typed command, code, a URL, an app label); not budgeted
  chain?: string; // the thought this fragment belongs to (fx/Chain renders a chain; grid-check checks its gaps)
  mode?: 'build' | 'replace'; // build: fragments append to one held line; replace: each takes the last one's place
};

const pace = PACE[PACE_NAME];

/**
 * One line of copy revealed word by word with this film's pace (the numbers <Words> uses), so
 * `resolved` is the frame its last word is fully in. `out` defaults to the pace's hold.
 */
export const line = (id: string, text: string, inF: number, out?: number): Copy => {
  const n = wordCount(text);
  const resolved = inF + f60(revealFor(n, pace));
  return { id, text, in: inF, resolved, out: out ?? resolved + f60(holdFor(n, pace)) };
};

/**
 * One thought as a chain of fragments, one COPY entry each (`<id>.1`, `<id>.2`, ...), rendered by
 * fx/Chain. A thought longer than 4 words arrives this way: 1-4 words per fragment, never a whole
 * sentence at once, with a picture beat between fragments (the product does what the fragment set
 * up). Give each fragment its first frame; `resolved` follows from the pace.
 *   build    fragments append to one held line, which re-centres; the line clears as a whole, at
 *            `out` (default: the last fragment's resolve plus the hold of the full line)
 *   replace  each fragment leaves (as a whole, over pace.exitDur: 24 f when calm) and has gone
 *            6 f before the next one rises in its place, so two fragments never share the spot;
 *            the last one leaves at `out` (default: its resolve plus its hold)
 * grid-check checks the result: every fragment is read before the next arrives, the picture beat
 * between them, the words on screen at once and the copy rate.
 */
export const chain = (id: string, mode: 'build' | 'replace', fragments: [text: string, inF: number][], o: { out?: number } = {}): Copy[] => {
  const base = fragments.map(([text, inF], i) => ({ id: `${id}.${i + 1}`, text, in: inF, resolved: inF + f60(revealFor(wordCount(text), pace)), chain: id, mode }));
  const last = base[base.length - 1];
  if (!last) throw new Error(`timeline: chain "${id}" has no fragments`);
  const words = (list: { text: string }[]) => list.reduce((n, c) => n + wordCount(c.text), 0);
  if (mode === 'build') {
    const out = o.out ?? last.resolved + f60(holdFor(words(base), pace));
    return base.map((c) => ({ ...c, out }));
  }
  // replace: the outgoing fragment's exit (exitDur) is over 6 f before the next one starts to rise
  const leave = f60(pace.exitDur) + f60(6);
  return base.map((c, i) => ({ ...c, out: base[i + 1] ? base[i + 1].in - leave : (o.out ?? c.resolved + f60(holdFor(wordCount(c.text), pace))) }));
};

// Every on-screen word: the word budget (kind: 'ui' entries are counted apart), the hold check,
// and the text-flow checks (fragments, words on screen at once, copy rate, text share) read this.
export const COPY: Copy[] = [
  // The opening questions: each slams in on its spoken word and is read under the voice.
  { id: 'q1', text: 'Що купити?', in: CUE.q1, resolved: CUE.q1 + 6, out: CUE.hook },
  { id: 'q2', text: 'Чому відстаю?', in: CUE.q2, resolved: CUE.q2 + 6, out: CUE.settle },
  { id: 'q3', text: 'Що змінити?', in: CUE.q3, resolved: CUE.q3 + 6, out: CUE.settle },
  // While they wait at the edges they are dim objects, not copy; they are read again when they come forward.
  { id: 'q2b', text: 'Чому відстаю?', in: CUE.q2Come, resolved: CUE.q2Come + 40, out: CUE.title + 2 },
  { id: 'q3b', text: 'Що змінити?', in: CUE.q3Come - 30, resolved: CUE.q3Come - 4, out: CUE.drill + 6 },
  // The product's own text (kind 'ui'): read while it is on screen.
  { id: 'live-card', text: 'Купіть частини наступного предмета на 1800 золота зараз', in: CUE.dotLand - 8, resolved: CUE.dotLand + 34, out: CUE.away, kind: 'ui' },
  { id: 'live-reason', text: 'Невитрачене золото частково втрачається при наступній смерті.', in: CUE.dotLand + 14, resolved: CUE.dotLand + 56, out: CUE.away, kind: 'ui' },
  { id: 'finding', text: 'Програли лінію за добиваннями · 36 добивань до 10:00 проти 65', in: CUE.title, resolved: CUE.title + 30, out: CUE.clear, kind: 'ui' },
  { id: 'drill', text: 'Вправа: на лінії стежте за HP кріпів', in: CUE.drill + 10, resolved: CUE.drill + 40, out: CUE.clear, kind: 'ui' },
  // The slogan, built as two fragments; it stays on the end card.
  ...chain('slogan', 'build', [['Менше хаосу.', CUE.slogan1], ['Чіткіший наступний крок.', CUE.slogan2]], { out: TOTAL }),
  { id: 'wordmark', text: 'Wardly', in: CUE.wordmark - 24, resolved: CUE.wordmark, out: TOTAL },
  { id: 'free', text: 'Безкоштовно для Windows', in: CUE.cta, resolved: CUE.cta + 30, out: TOTAL },
  { id: 'url', text: 'luhovyimvp.dev', in: CUE.cta + 8, resolved: CUE.cta + 38, out: TOTAL, kind: 'ui' },
];

/**
 * When each COPY entry is being read: [from, to) frame ranges by id (src/lib/pace.ts
 * readingWindows(): from `resolved` for at most readMax, an earlier fragment of a build chain only
 * for its own hold, then the whole line again). The one rule every check uses: export-cues.ts
 * writes it into out/cues.json, and grid-check, layout-audit, measure-speed and forensics read it.
 * Nothing new should start inside a window: the read happens in the quiet.
 */
export const READ = readingWindows(COPY, pace, FPS, TOTAL);

/** One COPY entry by id; acts read their text and timing from here so the budget stays true. */
export const copy = (id: string): Copy => {
  const c = COPY.find((x) => x.id === id);
  if (!c) throw new Error(`timeline: no COPY entry "${id}"`);
  return c;
};

/** The fragments of one chain, in order of arrival. */
export const chainOf = (id: string): Copy[] => {
  const list = COPY.filter((x) => x.chain === id).sort((p, q) => p.in - q.in);
  if (!list.length) throw new Error(`timeline: no COPY chain "${id}"`);
  return list;
};
