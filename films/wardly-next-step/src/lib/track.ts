// Keyframed poses: a value (or a bag of values) that holds between keys and eases from one key to
// the next on that key's curve. Scale-like fields interpolate in log space (lmix), so a zoom
// keeps a constant perceived speed. Pure functions of the frame.
import { clamp, E, type Ease, lmix, mix } from './anim';

export type Pose = Record<string, number>;
export type Key<P extends Pose> = { f: number; v: P; e?: Ease; dur?: number };

const LOG = new Set(['s', 'scale', 'k']);

/**
 * The pose at `frame`. Each key k (after the first) is reached by a move that starts at
 * k.f - (k.dur ?? gap to the previous key) and ends at k.f, on k.e (default E.out).
 */
export const track = <P extends Pose>(frame: number, keys: Key<P>[]): P => {
  if (frame <= keys[0].f) return { ...keys[0].v };
  let cur: P = { ...keys[0].v };
  for (let i = 1; i < keys.length; i++) {
    const k = keys[i];
    const prevF = keys[i - 1].f;
    const start = k.dur !== undefined ? k.f - k.dur : prevF;
    if (frame <= start) return cur;
    const t = clamp((frame - start) / Math.max(1, k.f - start));
    const e = (k.e ?? E.out)(t);
    const next = { ...cur } as P;
    for (const name of Object.keys(k.v)) {
      const a = cur[name] ?? k.v[name];
      const b = k.v[name];
      (next as Pose)[name] = LOG.has(name) && a > 0 && b > 0 ? lmix(a, b, e) : mix(a, b, e);
    }
    if (frame < k.f) return next;
    cur = { ...cur, ...k.v };
  }
  return cur;
};

/** A point on a quadratic arc from a to b, bowed sideways by `bow` of the distance. */
export const arc = (a: { x: number; y: number }, b: { x: number; y: number }, t: number, bow = 0.18) => {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const cx = mx - dy * bow;
  const cy = my + dx * bow;
  const u = 1 - t;
  return { x: u * u * a.x + 2 * u * t * cx + t * t * b.x, y: u * u * a.y + 2 * u * t * cy + t * t * b.y };
};

/** Mix two #RRGGBB colours. */
export const mixColor = (a: string, b: string, t: number) => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const A = p(a);
  const B = p(b);
  const c = A.map((v, i) => Math.round(mix(v, B[i], clamp(t))));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
};
