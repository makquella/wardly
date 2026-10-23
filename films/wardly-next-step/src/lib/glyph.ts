// Where the dot of a glyph really is («?», «.»), found in the font's own pixels: the glyph is
// drawn on a canvas and the lowest connected run of inked rows is the dot. Results are relative
// to the glyph's pen origin on the baseline, so a DOM span can place a circle exactly over it.
// Only call under <FontGate>.
const cache = new Map<string, Dot>();

export type Dot = { cx: number; cy: number; r: number; top: number }; // cy/top: px above (negative) the baseline

export const glyphDot = (ch: string, size: number, weight: number, family: string): Dot => {
  const key = `${ch}|${size}|${weight}|${family}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const pad = Math.ceil(size * 0.5);
  const w = Math.ceil(size * 1.2) + pad * 2;
  const h = Math.ceil(size * 1.6) + pad * 2;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('glyphDot: no 2D canvas');
  ctx.font = `${weight} ${size}px ${family}`;
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = 'black'; // an offscreen measuring canvas, never on screen
  const base = Math.round(h * 0.7);
  ctx.fillText(ch, pad, base);
  const data = ctx.getImageData(0, 0, w, h).data;
  const inked = (x: number, y: number) => data[(y * w + x) * 4 + 3] > 127;
  const rowInk = (y: number) => {
    let n = 0;
    for (let x = 0; x < w; x++) if (inked(x, y)) n++;
    return n;
  };
  // From the bottom: first inked row, then up until an empty row: that run is the dot.
  let y1 = h - 1;
  while (y1 > 0 && rowInk(y1) === 0) y1--;
  let y0 = y1;
  while (y0 > 0 && rowInk(y0 - 1) > 0) y0--;
  let x0 = w;
  let x1 = 0;
  for (let y = y0; y <= y1; y++)
    for (let x = 0; x < w; x++)
      if (inked(x, y)) {
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
      }
  const dot = { cx: (x0 + x1 + 1) / 2 - pad, cy: (y0 + y1 + 1) / 2 - base, r: Math.max(x1 - x0 + 1, y1 - y0 + 1) / 2, top: y0 - base };
  cache.set(key, dot);
  return dot;
};
