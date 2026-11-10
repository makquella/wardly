// Wardly Cuts (cuts.py): the page of one video, drawn frame by frame.
// window.CUT is the timeline; window.renderAt(t) puts every element where it
// is at second t (no clocks, no CSS animations: frame N is always the same),
// window.cutReady resolves when fonts and pictures are loaded.
(() => {
  "use strict";
  const CUT = window.CUT;
  const W = 1080;
  const H = 1920;
  const CX = 490; // the centre of what TikTok, Shorts and Reels leave uncovered
  const A = CUT.assets || {};

  // --- numbers ---------------------------------------------------------------
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const prog = (t, at, dur) => clamp((t - at) / dur);
  const out3 = (t) => 1 - (1 - t) ** 3;
  const out5 = (t) => 1 - (1 - t) ** 5;
  const in3 = (t) => t ** 3;
  const inOut = (t) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);
  const back = (t) => 1 + 2.4 * (t - 1) ** 3 + 1.4 * (t - 1) ** 2;
  const expo = (t) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }

  // --- elements --------------------------------------------------------------
  function el(parent, cls, html) {
    const node = document.createElement("div");
    if (cls) node.className = cls;
    if (html !== undefined) node.innerHTML = html;
    parent.append(node);
    return node;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  // Where an element is: x, y of its centre (c: false - of its top-left corner).
  function T(node, o) {
    const sx = (o.s ?? 1) * (o.sx ?? 1);
    const sy = (o.s ?? 1) * (o.sy ?? 1);
    node.style.transform =
      `translate(${(o.x ?? 0).toFixed(2)}px,${(o.y ?? 0).toFixed(2)}px)` +
      (o.c === false ? "" : " translate(-50%,-50%)") +
      (o.r ? ` rotate(${o.r.toFixed(3)}deg)` : "") +
      (o.k ? ` skewX(${o.k.toFixed(3)}deg)` : "") +
      ` scale(${sx.toFixed(4)},${sy.toFixed(4)})`;
    node.style.opacity = String(clamp(o.a ?? 1));
    node.style.filter = o.blur > 0.3 ? `blur(${o.blur.toFixed(1)}px)` : o.f || "";
  }
  // An entrance: from an offset, bigger and smeared, to rest.
  function enter(node, t, at, rest, from = {}, dur = 0.3) {
    const p = prog(t, at, dur);
    const e = (from.ease || back)(p);
    const q = out5(p);
    T(node, {
      ...rest,
      x: (rest.x ?? 0) + (from.dx ?? 0) * (1 - q),
      y: (rest.y ?? 0) + (from.dy ?? 0) * (1 - q),
      s: (rest.s ?? 1) * lerp(from.s ?? 1, 1, e),
      r: (rest.r ?? 0) + (from.r ?? 0) * (1 - q),
      sx: 1 + (from.smear ?? 0) * (1 - q) * (p > 0 ? 1 : 0),
      a: (rest.a ?? 1) * clamp(p * 5),
      blur: (from.blur ?? 0) * (1 - q)
    });
    return p;
  }
  function picture(parent, cls, src) {
    const box = el(parent, cls);
    if (src) {
      const img = new Image();
      img.src = src;
      box.append(img);
    }
    return box;
  }

  // --- pictures that move: a hero's idle animation, frame by frame -------------
  const sequences = new Map();
  const loading = [];
  function load(src) {
    const img = new Image();
    const done = new Promise((resolve) => {
      img.onload = () => (img.decode ? img.decode().then(resolve, resolve) : resolve());
      img.onerror = resolve;
    });
    img.src = src;
    loading.push(done);
    return img;
  }
  function sequence(key) {
    const seq = A[`seq:${key}`];
    if (!seq) return null;
    if (!sequences.has(key)) {
      sequences.set(key, { fps: seq.fps, frames: seq.frames.map(load) });
    }
    return sequences.get(key);
  }
  const drawn = [];
  // A hero: the moving render when the page has its frames, the still one otherwise.
  function hero(parent, key, size, flip) {
    const box = el(parent, "hero");
    box.style.width = box.style.height = `${size}px`;
    const seq = sequence(key);
    if (seq) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = Math.min(size, 900);
      box.append(canvas);
      drawn.push({ canvas, seq, flip });
    } else if (A[`hero:${key}`]) {
      const img = load(A[`hero:${key}`]);
      if (flip) img.style.transform = "scaleX(-1)";
      box.append(img);
    }
    return box;
  }
  function drawSequences(t) {
    for (const { canvas, seq, flip } of drawn) {
      if (!canvas.offsetParent) continue;
      const frame = seq.frames[Math.floor(t * seq.fps) % seq.frames.length];
      if (!frame || !frame.naturalWidth) continue;
      const ctx = canvas.getContext("2d");
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (flip) ctx.setTransform(-1, 0, 0, 1, canvas.width, 0);
      ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
    }
  }
  function tile(parent, key, w, h) {
    const box = el(parent, "tile");
    box.style.width = `${w}px`;
    box.style.height = `${h}px`;
    if (A[`tile:${key}`]) box.append(load(A[`tile:${key}`]));
    box.mark = el(box, "mark");
    box.ring = el(box, "ring");
    return box;
  }

  // --- effects every scene shares ------------------------------------------------
  const fx = { flash: 0, sx: 0, sy: 0, zoom: 1, red: 0 };
  // A hit at `at`: the picture jumps and settles; `power` in pixels.
  function hit(t, at, power = 26, frame = 0) {
    const p = t - at;
    if (p < 0 || p > 0.5) return;
    const k = Math.exp(-9 * p) * power;
    const r = rng(1000 + Math.round(at * 100) * 7 + frame);
    fx.sx += (r() - 0.5) * 2 * k;
    fx.sy += (r() - 0.5) * 2 * k;
    fx.zoom += 0.035 * Math.exp(-12 * p) * (power / 26);
    fx.flash = Math.max(fx.flash, p < 0.08 ? Math.min(0.42, 0.3 * (power / 26)) * (1 - p / 0.08) : 0);
  }
  function backdrop(root, scene) {
    const key = scene.data.bg;
    const img = key && A[`bg:${key}`] ? load(A[`bg:${key}`]) : null;
    if (img) {
      img.className = "bg" + (scene.data.soft ? " soft" : "");
      root.append(img);
    }
    const grid = el(root, "grid");
    el(root, "shade");
    const tint = el(root, "tint");
    const r = rng(scene.index * 97 + 5);
    const pan = { x: (r() - 0.5) * 240, y: (r() - 0.5) * 120, dx: (r() - 0.5) * 90, dy: (r() - 0.5) * 60 };
    return (t, d) => {
      const p = clamp(t / Math.max(d, 0.01));
      if (img) {
        img.style.transform = `translate(-50%,-50%) translate(${(pan.x + pan.dx * p).toFixed(1)}px,${(pan.y + pan.dy * p).toFixed(1)}px) scale(${(1.02 + 0.07 * p).toFixed(4)})`;
      }
      grid.style.transform = `translate(${(-40 * p).toFixed(1)}px,${(30 * p).toFixed(1)}px) rotate(-8deg)`;
      tint.style.opacity = String(scene.data.tint ?? 0);
    };
  }

  // --- kinetic lines: each word lands when it is said ------------------------------
  // lines: [[{ w, hot, gold }]], words: the said words in the same order (local times).
  function kinetic(root, lines, words, top, opts = {}) {
    const max = opts.max || 190;
    const width = opts.width || 860;
    const built = [];
    let at = 0;
    let y = top;
    for (const line of lines) {
      const row = el(root, "kline display");
      row.style.fontSize = "100px";
      const parts = line.map((part) => {
        const span = document.createElement("span");
        span.className = "kword" + (part.hot ? " hot" : "") + (part.gold ? " gold" : "");
        span.innerHTML = `<b>${esc(part.w)}</b>` + (part.hot && opts.underline !== false ? '<i class="ul"></i>' : "");
        row.append(span);
        const time = words[Math.min(at, words.length - 1)] || { start: 0, end: 0.3 };
        at += part.n ?? 1;
        return { span, part, time, ul: span.querySelector(".ul") };
      });
      const natural = Math.max(1, row.getBoundingClientRect().width);
      const size = Math.min(max, Math.floor((100 * width) / natural));
      row.style.fontSize = `${size}px`;
      row.style.top = `${y}px`;
      row.style.left = `${opts.left ?? 60}px`;
      y += size * (opts.leading || 0.98);
      built.push({ row, parts, size });
    }
    const height = y - top;
    const draw = (t, d, gone = 1e9) => {
      for (const { parts } of built) {
        for (const { span, time, ul, part } of parts) {
          const p = prog(t, time.start - 0.03, 0.2);
          const e = back(p);
          const q = out5(p);
          const leave = prog(t, gone, 0.16);
          span.style.opacity = String(clamp(p * 6) * (1 - leave));
          span.style.transform = `translate(${(-140 * in3(leave)).toFixed(1)}px,${(64 * (1 - q)).toFixed(1)}px) rotate(${(5 * (1 - q)).toFixed(2)}deg) scale(${lerp(1.5, 1, e).toFixed(4)}) scaleX(${(1 + 0.5 * leave).toFixed(3)})`;
          span.style.filter = p < 1 || leave > 0 ? `blur(${(16 * (1 - q) + 14 * leave).toFixed(1)}px)` : "";
          if (ul) ul.style.transform = `scaleX(${out5(prog(t, time.start + 0.1, 0.3)).toFixed(4)})`;
          if (part.hot && opts.hit !== false) hit(t, time.start, opts.power ?? 10, 3);
        }
      }
    };
    return { draw, height, bottom: y, built };
  }
  function countText(node, value, suffix = "") {
    node.textContent = `${Math.round(value).toLocaleString("en-US").replace(/,/g, " ")}${suffix}`;
  }
  // The app's overlay card: its label, action and reason, as the overlay shows them.
  function card(root, data) {
    const node = el(root, "ocard abs" + (data.calm ? " calm" : ""));
    node.innerHTML =
      `<div class="top"><i></i><span>${esc(data.label)}</span></div>` +
      `<div class="action">${esc(data.action)}</div>` +
      (data.reason ? `<div class="reason">${esc(data.reason)}</div>` : "") +
      '<div class="sweep"></div>';
    node.sweep = node.querySelector(".sweep");
    return node;
  }
  function drawCard(node, t, at, x, y) {
    const p = prog(t, at, 0.42);
    const q = out5(p);
    T(node, { x, y: y + 260 * (1 - q), s: lerp(0.86, 1, back(p)), a: clamp(p * 6), r: -3 * (1 - q), blur: 22 * (1 - q) });
    node.sweep.style.transform = `translateX(${lerp(-300, 1000, out3(prog(t, at + 0.25, 0.7))).toFixed(1)}px) skewX(-18deg)`;
    hit(t, at + 0.05, 16, 9);
  }

  // --- scenes ----------------------------------------------------------------
  const SCENES = {};

  // A statement: big lines, each word on its beat.
  SCENES.statement = (root, scene, local) => {
    const d = scene.data;
    let top = d.top ?? 520;
    let eyebrow = null;
    if (d.eyebrow) {
      eyebrow = el(root, "eyebrow abs", `<i></i>${esc(d.eyebrow)}`);
      top += 20;
    }
    const lines = kinetic(root, d.lines, local.words, top, { max: d.max, power: d.power });
    if (d.center) {
      const shift = Math.max(0, (d.center - lines.height) / 2);
      for (const { row } of lines.built) row.style.top = `${parseFloat(row.style.top) + shift}px`;
    }
    const shadows = (d.shadows || []).map((key) => {
      const box = el(root, "shadow");
      box.style.width = box.style.height = "760px";
      if (A[`hero:${key}`]) box.append(load(A[`hero:${key}`]));
      return box;
    });
    const mark = shadows.length ? el(root, "qmark", "?") : null;
    const face = d.hero ? hero(root, d.hero, d.heroSize || 900, d.flip) : null;
    if (face) root.insertBefore(face, root.querySelector(".kline"));
    const glow = face ? el(root, "glow") : null;
    if (glow) {
      glow.style.cssText += "width:700px;height:700px;background:rgba(240,85,96,.34)";
      root.insertBefore(glow, face);
    }
    return (t, dur) => {
      if (eyebrow) enter(eyebrow, t, 0.02, { x: 60, y: top - 78, c: false }, { dx: -80, blur: 10 }, 0.3);
      lines.draw(t, dur, dur - 0.14);
      shadows.forEach((box, i) => {
        // Two at a time, a new pair every 0.3 s: the lanes are not named yet.
        const step = 0.3;
        const pair = Math.floor(i / 2);
        const from = 0.25 + pair * step;
        const on = t >= from && (t < from + step || pair === Math.floor((shadows.length - 1) / 2));
        const p = out5(prog(t, from, 0.18));
        const side = i % 2 === 0 ? -1 : 1;
        T(box, { x: CX + side * (230 + 120 * (1 - p)), y: 1130, s: (i % 2 ? 1.05 : 0.92) * (1 + 0.04 * (t - from)), a: on ? 1 : 0 });
        if (box.firstChild) box.firstChild.style.transform = side > 0 ? "scaleX(-1)" : "";
      });
      if (mark) T(mark, { x: CX, y: 1120, s: 1 + 0.08 * Math.sin(t * 7), a: prog(t, 0.25, 0.1), r: -6 });
      if (face) {
        const hx = d.heroX ?? 560;
        const hy = d.heroY ?? 1180;
        const p = enter(face, t, d.heroAt ?? 0.05, { x: hx, y: hy, s: 1 + 0.04 * (t / dur) }, { dx: 380, s: 1.2, blur: 30, ease: out5 }, 0.45);
        T(glow, { x: hx, y: hy + 40, a: 0.9 * p, s: 1 + 0.08 * Math.sin(t * 2.2) });
      }
    };
  };

  // One place of a countdown: #N, the hero and who beats it in lane, the share of lost lanes.
  SCENES.rank = (root, scene, local) => {
    const d = scene.data;
    const glow = el(root, "glow");
    glow.style.cssText += "width:760px;height:760px;background:rgba(240,85,96,.42)";
    const slash = el(root, "slash");
    slash.style.cssText += "width:26px;height:1300px";
    const a = hero(root, d.a.key, 720, false);
    const b = hero(root, d.b.key, 860, true);
    const place = el(root, "num abs", `<span style="font-size:.5em;vertical-align:.52em;margin-right:.04em;color:var(--red)">#</span>${d.rank}`);
    place.style.cssText += `font-size:${d.final ? 330 : 290}px;color:#fff;text-shadow:0 18px 60px rgba(0,0,0,.6)`;
    const nameA = el(root, "plate white abs", esc(d.a.name));
    const nameB = el(root, "plate red abs", esc(d.b.name));
    const sizeA = Math.min(72, Math.floor(1400 / Math.max(8, d.a.name.length)));
    const sizeB = Math.min(88, Math.floor(1650 / Math.max(8, d.b.name.length)));
    nameA.style.fontSize = `${sizeA}px`;
    nameB.style.fontSize = `${sizeB}px`;
    const vs = el(root, "vs abs", esc(d.labels.vs));
    const pct = el(root, "num abs");
    pct.style.cssText += `font-size:${d.final ? 290 : 250}px;color:var(--red)`;
    const label = el(root, "eyebrow abs", d.labels.lost.split(" ").map(esc).join("<br>"));
    label.style.cssText += "color:#fff;font-size:30px;letter-spacing:.1em;line-height:1.25;white-space:normal";
    const sample = el(root, "small abs", esc(d.labels.sample));
    sample.style.fontSize = "30px";
    const meter = el(root, "meter abs", '<i class="usual"></i><i></i>');
    meter.style.width = "860px";
    const usual = meter.children[0];
    const bar = meter.children[1];
    const usualTick = el(root, "tick abs");
    usualTick.style.height = "58px";
    const usualLabel = el(root, "small abs", esc(d.labels.usual));
    usualLabel.style.fontSize = "28px";
    const second = local.cue("b", 0.5);
    // The share never comes before the hero it is about (cuts_sound.py keeps the same rule).
    const cue = Math.max(local.cue("pct", d.final ? 1.2 : 0.55), second + 0.5);
    const NAMES = 950;
    const BASE = 1150;
    return (t, dur) => {
      const drift = t / Math.max(dur, 0.01);
      enter(place, t, 0, { x: 60, y: 215, c: false }, { s: 2.4, blur: 30, dx: -60, ease: out5 }, 0.26);
      hit(t, 0.14, d.final ? 30 : 16, 1);
      const ax = 250 - 26 * drift;
      const bx = 716 + 26 * drift;
      enter(a, t, 0.08, { x: ax, y: 770, s: 1 + 0.03 * drift }, { dx: -620, s: 1.15, blur: 40, smear: 0.4, ease: out5 }, 0.36);
      const pb = enter(b, t, second - 0.12, { x: bx, y: 680, s: 1 + 0.06 * drift }, { dx: 700, s: 1.2, blur: 46, smear: 0.4, ease: out5 }, 0.36);
      hit(t, second + 0.1, d.final ? 22 : 12, 2);
      T(glow, { x: bx + 10, y: 690, a: 0.95 * pb, s: 1 + 0.07 * Math.sin(t * 3) });
      T(slash, { x: CX + 6, y: 700, r: 14, sy: out5(prog(t, 0.14, 0.34)), a: 0.95 });
      enter(vs, t, second - 0.04, { x: CX + 6, y: 700, r: -8 }, { s: 3.2, blur: 20, ease: out5 }, 0.22);
      enter(nameA, t, 0.24, { x: 60, y: NAMES, c: false, r: -3 }, { dx: -420, smear: 0.5, blur: 22, ease: out5 }, 0.3);
      const right = 60 + 860;
      enter(nameB, t, second + 0.06, { x: right - nameB.offsetWidth, y: NAMES + sizeA * 1.34, c: false, r: -3 }, { dx: 460, smear: 0.5, blur: 22, ease: out5 }, 0.3);
      // The share: counts up to its value and lands as it is said.
      const count = out3(prog(t, cue - 0.5, 0.5));
      countText(pct, d.pct * count, "%");
      enter(pct, t, cue - 0.5, { x: 52, y: BASE + 30, c: false }, { dy: 90, s: 0.7, blur: 18 }, 0.3);
      pct.style.transformOrigin = "0 60%";
      hit(t, cue, d.final ? 44 : 14, 4);
      const pulse = 1 + (d.final ? 0.14 : 0.06) * Math.exp(-9 * Math.max(0, t - cue)) * (t >= cue ? 1 : 0);
      pct.style.transform += ` scale(${pulse.toFixed(4)})`;
      const side = 52 + pct.offsetWidth + 26;
      enter(label, t, cue - 0.3, { x: side, y: BASE + 50, c: false }, { dx: 80, blur: 10, ease: out5 }, 0.3);
      T(sample, { x: 60, y: BASE + 300, c: false, a: prog(t, cue - 0.2, 0.2) });
      const my = BASE + 258;
      T(meter, { x: 60, y: my, c: false, a: prog(t, cue - 0.5, 0.2) });
      bar.style.width = `${(d.pct * count).toFixed(2)}%`;
      usual.style.width = `${d.base}%`;
      T(usualTick, { x: 60 + 8.6 * d.base, y: my - 14, c: false, a: prog(t, cue - 0.2, 0.2) });
      usualLabel.style.transform = "";
      T(usualLabel, { x: 60 + 860 - usualLabel.offsetWidth, y: BASE + 302, c: false, a: prog(t, cue - 0.2, 0.2) });
      a.style.filter += " saturate(.75) brightness(.8)";
    };
  };

  // Where the numbers come from: the count of lanes rolling up over a field of dots.
  SCENES.source = (root, scene, local) => {
    const d = scene.data;
    const field = el(root, "layer");
    const r = rng(77);
    const dots = [];
    for (let i = 0; i < 420; i += 1) {
      const dot = el(field, "dot");
      const lost = r() < 0.3;
      dot.style.background = lost ? "var(--red)" : "rgba(255,255,255,.75)";
      dots.push({ dot, x: 60 + (i % 21) * 43, y: 330 + Math.floor(i / 21) * 43, at: r() * 0.9, lost, wob: r() * 6.28 });
    }
    const big = el(root, "num abs");
    big.style.cssText += "font-size:250px;color:#fff;text-shadow:0 20px 80px rgba(0,0,0,.8)";
    const cue = local.cue("count", 0.3);
    // The two lines under the number come one word after another, after the count starts.
    const steps = d.lines.flat().map((_, i) => ({ start: cue + 0.25 + i * 0.13, end: cue + 0.4 + i * 0.13 }));
    const lines = kinetic(root, d.lines, steps, 1010, { max: 110, hit: false });
    return (t, dur) => {
      for (const { dot, x, y, at, lost, wob } of dots) {
        const p = prog(t, at * 0.9, 0.25);
        T(dot, { x, y: y + 3 * Math.sin(t * 2 + wob), s: back(p) * (lost ? 1.25 : 1), a: 0.9 * p });
      }
      const count = expo(prog(t, cue - 0.15, 1.0));
      countText(big, d.count * count);
      enter(big, t, 0.02, { x: 60, y: 760, c: false }, { dy: 120, s: 0.8, blur: 24 }, 0.35);
      hit(t, cue + 0.85, 18, 5);
      lines.draw(t, dur);
    };
  };

  // 39 cores as tiles; the ones a hero makes the lane hard for light up one by one.
  SCENES.grid = (root, scene, local) => {
    const d = scene.data;
    const lines = kinetic(root, d.lines, local.words, 300, { max: 170 });
    const cols = 6;
    const w = 134;
    const h = 76;
    const gap = 11;
    const top = Math.max(lines.bottom + 60, 800);
    const tiles = d.tiles.map((key, i) => {
      const box = tile(root, key, w, h);
      return { box, x: 60 + (i % cols) * (w + gap) + w / 2, y: top + Math.floor(i / cols) * (h + gap) + h / 2, marked: d.marked.indexOf(key) };
    });
    const counter = el(root, "num abs");
    counter.style.cssText += "font-size:150px;color:var(--red)";
    const cue = local.cue("mark", 1.0);
    const span = Math.max(0.5, Math.min(1.6, scene.end - scene.start - cue - 0.3));
    return (t, dur) => {
      lines.draw(t, dur, dur - 0.14);
      let lit = 0;
      tiles.forEach(({ box, x, y, marked }, i) => {
        const p = prog(t, 0.05 + i * 0.012, 0.22);
        const when = cue + (marked / Math.max(1, d.marked.length - 1)) * span;
        const on = marked >= 0 ? prog(t, when, 0.12) : 0;
        if (on > 0) lit += 1;
        const leave = prog(t, dur - 0.16, 0.16);
        T(box, { x: x - 160 * in3(leave), y, s: back(p) * (1 + 0.16 * on * Math.exp(-7 * Math.max(0, t - when))), a: p * (marked >= 0 || t < cue ? 1 : lerp(1, 0.32, prog(t, cue, 0.4))) * (1 - leave), blur: 14 * leave });
        box.ring.style.opacity = String(on);
        box.mark.style.opacity = String(0.55 * on);
        if (marked >= 0) hit(t, when, 5, 20 + i);
      });
      countText(counter, lit);
      T(counter, { x: 60 + cols * (w + gap) - gap, y: top + Math.ceil(tiles.length / cols) * (h + gap) + 86, a: lit ? 1 - prog(t, dur - 0.16, 0.14) : 0, s: 1 });
      counter.style.transform = counter.style.transform.replace("translate(-50%,-50%)", "translate(-100%,-50%)");
    };
  };

  // Guesses crossed out: «not Jakiro, not Viper».
  SCENES.guess = (root, scene, local) => {
    const d = scene.data;
    const items = d.items.map((item, i) => {
      const glow = el(root, "glow");
      glow.style.cssText += "width:640px;height:640px;background:rgba(255,255,255,.2)";
      const face = hero(root, item.key, 1500, i % 2 === 1);
      const word = local.words[item.word] || { start: 0.2 + i * 0.6 };
      return { item, glow, face, at: word.start, x: i === 0 ? 330 : 650, y: i === 0 ? 560 : 1040 };
    });
    // Names and crosses over both heroes, whichever came first.
    for (const item of items) {
      item.name = el(root, "plate white abs", esc(item.item.label));
      item.name.style.fontSize = "92px";
      item.cross = el(root, "cross");
      item.cross.style.width = "820px";
    }
    return (t, dur) => {
      for (const [i, item] of items.entries()) {
        const leave = prog(t, dur - 0.14, 0.14);
        const side = i === 0 ? -1 : 1;
        const struck = item.at + 0.34;
        const off = prog(t, struck, 0.12);
        const p = enter(item.face, t, item.at - 0.1, { x: item.x + side * 240 * in3(leave), y: item.y, a: 1 - leave }, { dx: side * 560, s: 1.2, blur: 36, ease: out5 }, 0.3);
        item.face.style.filter += ` grayscale(${(0.85 * off).toFixed(2)}) brightness(${lerp(1.1, 0.62, off).toFixed(2)})`;
        T(item.glow, { x: item.x, y: item.y, a: p * (1 - off) * (1 - leave) });
        enter(item.name, t, item.at, { x: item.x - side * 60, y: item.y + 270, r: -4, a: 1 - leave }, { s: 2, blur: 20, ease: out5 }, 0.2);
        T(item.cross, { x: item.x - 400, y: item.y + 150, c: false, r: side * -22, sx: out5(prog(t, struck - 0.02, 0.14)), a: 1 - leave });
        hit(t, struck + 0.02, 20, 30 + i);
      }
    };
  };

  // The answer: the hero fills the frame, the name lands, the count next to it.
  SCENES.reveal = (root, scene, local) => {
    const d = scene.data;
    const glow = el(root, "glow");
    glow.style.cssText += "width:980px;height:980px;background:rgba(240,85,96,.5)";
    const face = hero(root, d.hero, 1180, false);
    const name = kinetic(root, d.name, local.words, d.nameTop ?? 1010, { max: 210, power: 46, underline: false });
    const big = el(root, "num abs");
    big.style.cssText += "font-size:330px;color:#fff";
    const of = el(root, "eyebrow abs", esc(d.of || ""));
    of.style.cssText += "color:#fff;font-size:44px;letter-spacing:.08em";
    const note = el(root, "small abs", esc(d.note || ""));
    note.style.cssText += "font-size:40px;color:#fff;font-weight:600";
    const strip = el(root, "layer");
    const faces = (d.strip || []).map((key) => tile(strip, key, 150, 86));
    const cue = d.count ? local.cue("count", 0.9) : 1e9;
    return (t, dur) => {
      const p = enter(face, t, 0, { x: CX + 20, y: 640, s: 1 + 0.05 * (t / dur) }, { s: 1.7, blur: 60, ease: out5 }, 0.34);
      T(glow, { x: CX + 20, y: 660, a: p, s: 1 + 0.06 * Math.sin(t * 2.6) });
      hit(t, 0.06, 40, 40);
      const gone = d.count ? cue - 0.16 : 1e9;
      name.draw(t, dur, gone);
      if (d.count) {
        const count = out3(prog(t, cue - 0.1, 0.5));
        countText(big, d.count * count);
        enter(big, t, cue - 0.1, { x: 56, y: 1010, c: false }, { dx: -200, blur: 24, ease: out5 }, 0.3);
        enter(of, t, cue + 0.1, { x: 66 + big.offsetWidth + 20, y: 1150, c: false }, { dx: 120, blur: 14, ease: out5 }, 0.3);
        hit(t, cue + 0.4, 18, 41);
        enter(note, t, cue + 0.25, { x: 60, y: 1270, c: false }, { dx: -80, blur: 12, ease: out5 }, 0.3);
        faces.forEach((box, i) => {
          const x = 135 + i * 162 - ((t - cue) * 190) % (faces.length * 162);
          const wrapped = x < -90 ? x + faces.length * 162 : x;
          T(box, { x: wrapped, y: 1400, a: prog(t, cue + 0.15 + i * 0.03, 0.2) });
          box.ring.style.opacity = "1";
        });
      }
    };
  };

  // Three columns: who makes lanes hard most often.
  SCENES.podium = (root, scene, local) => {
    const d = scene.data;
    const title = el(root, "eyebrow abs", `<i></i>${esc(d.eyebrow)}`);
    title.style.cssText += "white-space:normal;width:860px;line-height:1.35";
    const base = 1250;
    const most = Math.max(...d.items.map((item) => item.value));
    const cols = d.items.map((item, i) => {
      const x = 60 + 143 + i * 287;
      const height = (item.value / most) * 520;
      const glow = el(root, "glow");
      glow.style.cssText += "width:380px;height:380px;background:rgba(255,255,255,.2)";
      const col = el(root, "col abs" + (item.dim ? " dim" : ""));
      col.style.width = "250px";
      col.style.height = `${height}px`;
      const face = hero(root, item.key, 430, false);
      const value = el(root, "num abs");
      value.style.cssText += "font-size:150px;color:#fff";
      const name = el(root, "small abs", esc(item.name));
      name.style.cssText += "color:#fff;font-weight:700;font-size:32px";
      return { item, x, height, glow, col, face, value, name, at: item.dim ? 0.05 : (local.words[item.word] || { start: 0.3 + i * 0.6 }).start };
    });
    return (t) => {
      enter(title, t, 0, { x: 60, y: 250, c: false }, { dx: -80, blur: 10 }, 0.3);
      for (const [i, c] of cols.entries()) {
        const p = out5(prog(t, c.at, 0.5));
        T(c.col, { x: c.x, y: base - c.height / 2, sy: Math.max(0.001, p) });
        c.col.style.transformOrigin = "50% 100%";
        const up = base - c.height * p - 170;
        T(c.glow, { x: c.x, y: up, a: prog(t, c.at + 0.1, 0.15) });
        T(c.face, { x: c.x, y: up, s: back(prog(t, c.at + 0.1, 0.3)), a: prog(t, c.at + 0.1, 0.15) });
        countText(c.value, c.item.value * out3(prog(t, c.at, 0.5)));
        T(c.value, { x: c.x, y: base - c.height * p + 105, a: prog(t, c.at + 0.1, 0.2) * (c.height * p > 150 ? 1 : 0) });
        T(c.name, { x: c.x, y: base + 44, a: prog(t, c.at, 0.2) });
        if (!c.item.dim) hit(t, c.at + 0.42, 14, 50 + i);
      }
    };
  };

  // One lane of a hero: the opponent, the share of lost (won) lanes against the usual one.
  SCENES.matchup = (root, scene, local) => {
    const d = scene.data;
    const colour = d.easy ? "var(--green)" : "var(--red)";
    const glow = el(root, "glow");
    glow.style.cssText += `width:820px;height:820px;background:${d.easy ? "rgba(76,195,138,.4)" : "rgba(240,85,96,.45)"}`;
    const me = hero(root, d.me.key, 600, false);
    const foe = hero(root, d.foe.key, 980, true);
    const tag = el(root, "eyebrow abs", `<i style="background:${colour}"></i>${esc(d.eyebrow)}`);
    const name = el(root, `plate abs ${d.easy ? "white" : "red"}`, esc(d.foe.name));
    name.style.fontSize = `${Math.min(132, Math.floor(1600 / Math.max(6, d.foe.name.length)))}px`;
    const pct = el(root, "num abs");
    pct.style.cssText += `font-size:270px;color:${colour}`;
    const label = el(root, "eyebrow abs", d.labels.share.split(" ").map(esc).join("<br>"));
    label.style.cssText += "color:#fff;font-size:30px;letter-spacing:.1em;line-height:1.25;white-space:normal";
    const sample = el(root, "small abs", esc(d.labels.sample));
    sample.style.fontSize = "30px";
    const meter = el(root, "meter abs", '<i class="usual"></i><i></i>');
    meter.style.width = "860px";
    meter.children[1].style.background = colour;
    const tickMark = el(root, "tick abs");
    tickMark.style.height = "58px";
    const usual = el(root, "small abs", esc(d.labels.usual));
    usual.style.fontSize = "28px";
    const cue = local.cue("pct", 0.6);
    const NAME = 930;
    return (t, dur) => {
      const drift = t / Math.max(dur, 0.01);
      enter(tag, t, 0, { x: 60, y: 250, c: false }, { dx: -80, blur: 10 }, 0.3);
      enter(me, t, 0.02, { x: 220, y: 600, s: 1, a: 0.9 }, { dx: -300, blur: 24, ease: out5 }, 0.3);
      me.style.filter += " saturate(.6) brightness(.7)";
      const p = enter(foe, t, 0.06, { x: 630 + 20 * drift, y: 660, s: 1 + 0.05 * drift }, { dx: 760, s: 1.25, blur: 50, smear: 0.4, ease: out5 }, 0.36);
      T(glow, { x: 640, y: 680, a: p, s: 1 + 0.06 * Math.sin(t * 2.8) });
      hit(t, 0.2, 22, 60);
      enter(name, t, 0.2, { x: 60, y: NAME, c: false, r: -3 }, { dx: -500, smear: 0.5, blur: 24, ease: out5 }, 0.3);
      const count = out3(prog(t, cue - 0.45, 0.45));
      countText(pct, d.pct * count, "%");
      const base = NAME + name.offsetHeight + 40;
      enter(pct, t, cue - 0.45, { x: 52, y: base, c: false }, { dy: 90, s: 0.7, blur: 18 }, 0.3);
      pct.style.transformOrigin = "0 60%";
      pct.style.transform += ` scale(${(1 + 0.1 * Math.exp(-9 * Math.max(0, t - cue)) * (t >= cue ? 1 : 0)).toFixed(4)})`;
      hit(t, cue, 22, 61);
      const side = 52 + pct.offsetWidth + 26;
      enter(label, t, cue - 0.25, { x: side, y: base + 24, c: false }, { dx: 80, blur: 10, ease: out5 }, 0.3);
      const my = base + 246;
      T(meter, { x: 60, y: my, c: false, a: prog(t, cue - 0.45, 0.2) });
      meter.children[1].style.width = `${(d.pct * count).toFixed(2)}%`;
      meter.children[0].style.width = `${d.base}%`;
      T(tickMark, { x: 60 + 8.6 * d.base, y: my - 14, c: false, a: prog(t, cue - 0.2, 0.2) });
      T(sample, { x: 60, y: my + 46, c: false, a: prog(t, cue - 0.18, 0.2) });
      T(usual, { x: 60 + 860 - usual.offsetWidth, y: my + 48, c: false, a: prog(t, cue - 0.2, 0.2) });
    };
  };

  // The app's own card over the game: what the player sees.
  SCENES.card = (root, scene, local) => {
    const d = scene.data;
    const tag = el(root, "eyebrow abs", `<i></i>${esc(d.eyebrow)}`);
    const face = d.hero ? hero(root, d.hero, 760, false) : null;
    const node = card(root, d.card);
    const cue = local.cue("card", 0.25);
    return (t, dur) => {
      enter(tag, t, 0, { x: 60, y: 250, c: false }, { dx: -80, blur: 10 }, 0.3);
      if (face) enter(face, t, 0.02, { x: 690, y: 560, s: 1 + 0.04 * (t / dur) }, { dx: 400, blur: 30, ease: out5 }, 0.4);
      drawCard(node, t, cue, CX, d.cardY ?? 900);
    };
  };

  // The stun: the hero cannot act, HP falls, the item sits ready and unused.
  // data.back plays the same moment backwards, as a tape (the «rewind»).
  SCENES.stun = (root, scene, local) => {
    const d = scene.data;
    const face = hero(root, d.hero, 900, false);
    const ringBox = el(root, "ringwrap");
    ringBox.innerHTML =
      '<svg width="560" height="560" viewBox="0 0 560 560" style="display:block;overflow:visible">' +
      '<circle cx="280" cy="280" r="250" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="18"/>' +
      '<circle class="arc" cx="280" cy="280" r="250" fill="none" stroke="#f05560" stroke-width="18" stroke-linecap="round" stroke-dasharray="1571" transform="rotate(-90 280 280)"/></svg>';
    const arc = ringBox.querySelector(".arc");
    const stamp = el(root, "stamp abs", esc(d.labels.stunned));
    stamp.style.cssText += "font-size:76px;color:#fff;background:var(--red);padding:.1em .34em .12em";
    const hp = el(root, "hud");
    hp.innerHTML = '<div class="hpbar"><u></u><i></i></div><div class="hpnum"></div>';
    const hpFill = hp.querySelector("i");
    const hpLag = hp.querySelector("u");
    const hpNum = hp.querySelector(".hpnum");
    const slot = el(root, "slot abs");
    if (A[`icon:${d.item}`]) slot.append(load(A[`icon:${d.item}`]));
    const ready = el(slot, "ready");
    const dark = el(slot, "dark");
    const readyTag = el(root, "plate abs", esc(d.labels.ready));
    readyTag.style.cssText += "font-size:40px;background:var(--gold);color:#111";
    const dead = el(root, "stamp abs", esc(d.labels.dead));
    dead.style.cssText += "font-size:150px;color:var(--red);letter-spacing:-.01em";
    const scan = el(root, "scan");
    const tear = el(root, "tear");
    const back2 = el(root, "stamp abs", `◀◀ ${esc(d.labels.rewind || "")}`);
    back2.style.cssText += "font-size:64px;color:#fff";
    const lines = d.lines ? kinetic(root, d.lines, local.words, d.linesTop ?? 250, { max: 150, hit: false }) : null;
    // The moment itself, by its own clock `m` in 0..1: stunned 0..0.62, free, dead at 0.86.
    const HITS = [0.08, 0.2, 0.33, 0.47, 0.6, 0.72, 0.84];
    const hpAt = (m) => {
      let value = 72;
      for (const [i, at] of HITS.entries()) {
        if (m >= at) value -= [9, 8, 11, 9, 12, 13, 10][i];
      }
      return Math.max(0, value);
    };
    return (t, dur) => {
      const p = clamp(t / Math.max(dur, 0.01));
      const m = d.back ? lerp(0.98, 0.04, inOut(prog(t, 0.15, dur - 0.5))) : d.hold !== undefined ? d.hold : lerp(0, 1, p);
      const stunned = m < 0.62;
      const isDead = m >= 0.86 && !d.saved;
      const saved = d.saved ? prog(t, local.cue("press", 0.4), 0.2) : 0;
      const shock = d.back ? 0 : HITS.reduce((sum, at) => sum + (m >= at ? Math.exp(-(m - at) * 40) : 0), 0);
      T(face, { x: CX + 10 + (stunned ? 7 * Math.sin(m * 180) : 0), y: 640, s: 1 + 0.03 * p, a: 1 });
      face.style.filter = isDead ? "grayscale(1) brightness(.4)" : `brightness(${(1 + 0.9 * shock).toFixed(2)}) saturate(${(1 - 0.5 * shock).toFixed(2)})` + (saved ? ` drop-shadow(0 0 ${(60 * saved).toFixed(0)}px rgba(242,193,78,.9))` : "");
      T(ringBox, { x: CX + 10, y: 640, a: stunned && !isDead ? 1 : 0, r: m * 60, s: 1 + 0.02 * Math.sin(m * 90) });
      arc.setAttribute("stroke-dashoffset", String(1571 * clamp(m / 0.62)));
      T(stamp, { x: CX + 10, y: 326, r: -4, a: stunned ? 1 : 0, s: 1 + 0.05 * Math.sin(m * 120) });
      const now = d.saved ? Math.max(hpAt(Math.min(m, 0.63)), 0) : hpAt(m);
      T(hp, { x: 110, y: 1000, c: false, a: 1 });
      hpFill.style.width = `${now}%`;
      hpLag.style.left = `${now}%`;
      hpLag.style.width = `${Math.min(14, 14 * shock)}%`;
      hpNum.textContent = `${Math.round(now * 21)} / 2100`;
      hpFill.style.background = now < 30 ? "linear-gradient(180deg,#ff7a6b,#c8332f)" : "";
      const pulse = 1 + 0.07 * Math.sin(t * 9);
      T(slot, { x: CX + 10, y: 1150, s: 0.86 * (isDead ? 1 : pulse) * (1 + 0.5 * saved * (1 - saved)) });
      ready.style.opacity = isDead ? "0" : String(0.6 + 0.4 * Math.sin(t * 9));
      dark.style.opacity = saved ? String(0.75 * saved) : "0";
      T(readyTag, { x: CX + 10, y: 1256, a: isDead || saved ? 0 : 1, r: -2 });
      T(dead, { x: CX, y: 660, a: isDead && !d.back ? 1 : 0, s: isDead ? 1 + 0.9 * Math.exp(-(m - 0.86) * 60) : 1, r: -5 });
      if (!d.back && !d.saved && d.hold === undefined) {
        for (const [i, at] of HITS.entries()) hit(t, at * dur, i > 4 ? 30 : 12, 70 + i);
        hit(t, 0.86 * dur, 46, 79);
        fx.red = Math.max(fx.red, isDead ? 0.25 + 0.9 * Math.exp(-(m - 0.86) * 45) : 0.45 * shock);
      }
      if (d.saved) {
        hit(t, local.cue("press", 0.4), 30, 80);
        fx.red = 0;
      }
      scan.style.opacity = d.back ? "1" : "0";
      tear.style.opacity = d.back ? "1" : "0";
      tear.style.top = `${((t * 2600) % 2200) - 100}px`;
      T(back2, { x: CX, y: 215, a: d.back ? 0.55 + 0.45 * Math.sin(t * 22) : 0 });
      if (d.back) {
        fx.sx += 9 * Math.sin(t * 90);
        root.style.filter = `saturate(.35) contrast(1.15) hue-rotate(${(8 * Math.sin(t * 40)).toFixed(1)}deg)`;
      }
      if (lines) lines.draw(t, dur, dur - 0.14);
    };
  };

  // The end: the name, what it costs, and an address to type.
  SCENES.end = (root, scene, local) => {
    const d = scene.data;
    const logo = picture(root, "logo", A.logo);
    logo.style.width = logo.style.height = "210px";
    const name = el(root, "display abs", "Wardly");
    name.style.cssText += "font-size:150px;text-transform:none;letter-spacing:-.04em;color:#fff";
    const what = el(root, "small abs", esc(d.what));
    what.style.cssText += "font-size:42px;line-height:1.25;color:#fff;font-weight:600;white-space:normal;width:760px;text-align:center";
    const pill = el(root, "pill", esc(d.free));
    const addr = el(root, "addr");
    const fine = el(root, "fine", esc(d.fine || ""));
    const [host, path] = d.site.split("/");
    const full = d.site;
    const cue = local.cue("site", 0.5);
    return (t) => {
      enter(logo, t, 0.02, { x: CX, y: 560 }, { s: 0.3, r: -40, blur: 20 }, 0.4);
      hit(t, 0.12, 20, 90);
      enter(name, t, 0.14, { x: CX, y: 760 }, { dy: 80, s: 1.3, blur: 20 }, 0.32);
      enter(what, t, 0.26, { x: CX, y: 905 }, { dy: 50, blur: 12, ease: out5 }, 0.3);
      enter(pill, t, 0.4, { x: CX, y: 1050 }, { s: 0.5, blur: 12 }, 0.3);
      const typed = Math.round(full.length * prog(t, cue, 0.55));
      const shown = full.slice(0, typed);
      const cut = shown.indexOf("/");
      addr.innerHTML = (cut < 0 ? esc(shown) : `${esc(shown.slice(0, cut))}<em>${esc(shown.slice(cut))}</em>`) + (Math.floor(t * 3) % 2 === 0 || typed < full.length ? '<i class="caret"></i>' : '<i class="caret" style="opacity:0"></i>');
      T(addr, { x: CX, y: 1230, a: prog(t, cue - 0.1, 0.1) });
      T(fine, { x: CX, y: 1400, a: prog(t, 0.7, 0.3) });
      void host;
      void path;
    };
  };

  // --- the timeline ----------------------------------------------------------------
  const stage = document.getElementById("stage");
  const caps = document.getElementById("caps");
  const flash = document.getElementById("flash");
  const grain = document.getElementById("grain");
  const OUT = 0.14;
  const built = CUT.scenes.map((scene, index) => {
    scene.index = index;
    const root = el(stage, `scene scene-${scene.type}`);
    const local = {
      words: (scene.words || []).map((w) => ({ ...w, start: w.start - scene.start, end: w.end - scene.start })),
      cue: (name, fallback) => (scene.cues && scene.cues[name] !== undefined ? scene.cues[name] - scene.start : fallback)
    };
    const back = backdrop(root, scene);
    const content = el(root, "layer");
    root.style.display = "block"; // measured while visible
    const draw = SCENES[scene.type](content, scene, local);
    root.style.display = "none";
    return { scene, root, back, draw, content };
  });
  stage.append(caps);

  // What the voice says now: the caption line with the word being said.
  const lines = CUT.scenes.flatMap((scene) => (scene.captions ? scene.lines : []));
  let shownLine = null;
  function captions(t) {
    const line = lines.find((l) => t >= l.start - 0.06 && t < l.end + 0.12);
    if (line !== shownLine) {
      shownLine = line;
      caps.innerHTML = line ? line.words.map((w) => `<span>${esc(w.w)}</span>`).join("") : "";
    }
    if (!line) return;
    [...caps.children].forEach((span, i) => {
      const w = line.words[i];
      const p = prog(t, w.start - 0.04, 0.12);
      span.className = t >= w.start - 0.04 && t < w.end + 0.03 ? "now" : t >= w.end ? "said" : "";
      span.style.transform = `translateY(${(14 * (1 - out5(p))).toFixed(1)}px) scale(${(t >= w.start - 0.04 && t < w.end + 0.03 ? 1.07 : 1).toFixed(2)})`;
      span.style.opacity = String(0.35 + 0.65 * p);
    });
  }

  function drawGrain(frame) {
    const ctx = grain.getContext("2d");
    const image = ctx.createImageData(grain.width, grain.height);
    const r = rng(frame * 7919 + 13);
    for (let i = 0; i < image.data.length; i += 4) {
      const v = (r() * 255) | 0;
      image.data[i] = image.data[i + 1] = image.data[i + 2] = v;
      image.data[i + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
  }

  window.renderAt = (t) => {
    fx.flash = 0;
    fx.sx = 0;
    fx.sy = 0;
    fx.zoom = 1;
    fx.red = 0;
    for (const item of built) {
      const { scene, root, back, draw } = item;
      const d = scene.end - scene.start;
      const local = t - scene.start;
      const last = scene.index === built.length - 1;
      const visible = local >= 0 && (local < d + (last ? 1 : OUT));
      root.style.display = visible ? "block" : "none";
      if (!visible) continue;
      root.style.filter = "";
      // The cut: the old picture is thrown left and smeared, the new one settles from a push-in.
      const leave = last ? 0 : prog(local, d, OUT);
      const arrive = scene.index === 0 ? 1 : out5(prog(local, 0, 0.2));
      root.style.zIndex = leave > 0 ? "2" : "1";
      root.style.opacity = String(1 - in3(leave));
      root.style.transform = leave > 0 ? `translateX(${(-260 * in3(leave)).toFixed(1)}px) scale(${(1 + 0.05 * leave).toFixed(4)})` : `scale(${lerp(1.07, 1, arrive).toFixed(4)})`;
      if (leave > 0) root.style.filter = `blur(${(26 * leave).toFixed(1)}px)`;
      back(Math.min(local, d), d);
      draw(Math.min(local, d + OUT), d);
      if (scene.index > 0 && scene.flash !== false) fx.flash = Math.max(fx.flash, local < 0.07 ? 0.22 * (1 - local / 0.07) : 0);
    }
    drawSequences(t);
    captions(t);
    stage.style.transform = `translate(${fx.sx.toFixed(2)}px,${fx.sy.toFixed(2)}px) scale(${fx.zoom.toFixed(4)})`;
    flash.style.opacity = String(clamp(fx.flash));
    flash.style.background = fx.red > 0 ? "#f05560" : "#fff";
    if (fx.red > 0) flash.style.opacity = String(clamp(Math.max(fx.flash, 0.5 * fx.red)));
    drawGrain(Math.round(t * CUT.fps));
  };

  window.cutReady = Promise.all([document.fonts.ready, ...loading]).then(() => {
    // Lines were measured with fallback fonts if the real ones came late: build again is
    // not needed, the page waits for fonts before this script runs (see cuts.py).
    window.renderAt(0);
    return true;
  });
})();
