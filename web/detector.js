// Finding pieces in the camera picture, as the sorting machine does (bricksort/sorter/detector.py and
// machine.py): compare each picture with the empty belt in small blocks; anything that looks different
// (and isn't just a shadow) is an object; follow objects from picture to picture, and photograph each
// once as it crosses the middle line.
//
// All sizes are in "machine pixels" (the desktop's 720-pixel camera); k = picture pixels per machine
// pixel, so a sharper picture finds the same objects.
"use strict";

class Detector {
  constructor(k = 1, threshold = 28, minArea = 120, mergeGap = 20) {
    this.k = k;
    this.step = Math.max(1, Math.round(4 * k));   // block size in picture pixels (4 machine pixels)
    this.threshold = threshold;
    this.minArea = minArea;
    this.mergeGap = mergeGap;
    this.seen = [];
  }

  blocks(img) {
    // average colour of every step x step block: Float32Array (bh * bw * 3)
    const S = this.step, bw = Math.floor(img.width / S), bh = Math.floor(img.height / S), d = img.data;
    const out = new Float32Array(bw * bh * 3), W = img.width, n = S * S;
    for (let by = 0; by < bh; by++)
      for (let y = by * S; y < by * S + S; y++)
        for (let bx = 0; bx < bw; bx++) {
          const o = (by * bw + bx) * 3;
          let i = (y * W + bx * S) * 4;
          for (let x = 0; x < S; x++, i += 4) { out[o] += d[i]; out[o + 1] += d[i + 1]; out[o + 2] += d[i + 2]; }
        }
    for (let i = 0; i < out.length; i++) out[i] /= n;
    this.bw = bw; this.bh = bh;
    return out;
  }

  learnBackground(frames) {
    // the empty belt at several belt positions: its average look, and how much it varies by itself
    const all = frames.map((f) => this.blocks(f)), N = all.length, L = all[0].length;
    this.bg = new Float32Array(L);
    this.noise = new Float32Array(L / 3);
    for (let i = 0; i < L; i++) { let s = 0; for (const a of all) s += a[i]; this.bg[i] = s / N; }
    if (N > 2)
      for (let j = 0; j < L / 3; j++) {
        let worst = 0;
        for (let c = 0; c < 3; c++) {
          const i = 3 * j + c, mean = this.bg[i];
          let v = 0;
          for (const a of all) v += (a[i] - mean) ** 2;
          worst = Math.max(worst, Math.sqrt(v / N));
        }
        this.noise[j] = worst;
      }
  }

  mask(img) {
    const f = this.blocks(img), b = this.bg, bw = this.bw, bh = this.bh, m = new Uint8Array(bw * bh);
    for (let j = 0; j < bw * bh; j++) {
      const i = 3 * j;
      const diff = Math.max(Math.abs(f[i] - b[i]), Math.abs(f[i + 1] - b[i + 1]), Math.abs(f[i + 2] - b[i + 2]));
      const lf = (f[i] + f[i + 1] + f[i + 2]) / 3 + 1, lb = (b[i] + b[i + 1] + b[i + 2]) / 3 + 1, ratio = lf / lb;
      const chroma = Math.max(Math.abs(f[i] / lf - b[i] / lb), Math.abs(f[i + 1] / lf - b[i + 1] / lb),
        Math.abs(f[i + 2] / lf - b[i + 2] / lb));
      const shadow = ratio > 0.35 && ratio < 0.97 && chroma < 0.12;   // the belt, only darker: not an object
      const limit = this.noise ? Math.max(this.threshold, 3 * this.noise[j] + 10) : this.threshold;
      m[j] = diff > limit && !shadow ? 1 : 0;
    }
    const around = (src, x, y) => {
      let n = 0;
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx, yy = y + dy;
          if ((dx || dy) && xx >= 0 && yy >= 0 && xx < bw && yy < bh) n += src[yy * bw + xx];
        }
      return n;
    };
    const tidy = new Uint8Array(bw * bh);   // drop lonely blocks (2+ neighbours), then close small gaps
    for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) tidy[y * bw + x] = m[y * bw + x] && around(m, x, y) >= 2 ? 1 : 0;
    const grown = new Uint8Array(bw * bh);
    for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) grown[y * bw + x] = tidy[y * bw + x] || around(tidy, x, y) > 0 ? 1 : 0;
    return grown;
  }

  find(img) {
    // the objects in the picture: [{x0, y0, x1, y1, area, cx, cy, bits}], in machine pixels
    const m = this.mask(img), bw = this.bw, bh = this.bh, seen = new Uint8Array(bw * bh), blobs = [];
    const px = this.step / this.k;   // one block in machine pixels
    for (let start = 0; start < bw * bh; start++) {
      if (!m[start] || seen[start]) continue;
      let x0 = bw, y0 = bh, x1 = 0, y1 = 0, n = 0, sx = 0, sy = 0;
      const stack = [start];
      seen[start] = 1;
      while (stack.length) {
        const p = stack.pop(), x = p % bw, y = (p - x) / bw;
        n++; sx += x; sy += y;
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
        for (let dy = -1; dy <= 1; dy++)
          for (let dx = -1; dx <= 1; dx++) {
            const xx = x + dx, yy = y + dy, q = yy * bw + xx;
            if (xx >= 0 && yy >= 0 && xx < bw && yy < bh && m[q] && !seen[q]) { seen[q] = 1; stack.push(q); }
          }
      }
      const area = n * px * px;
      if (area < this.minArea) continue;
      blobs.push({ x0: x0 * px, y0: y0 * px, x1: (x1 + 1) * px, y1: (y1 + 1) * px, area, cx: (sx / n) * px, cy: (sy / n) * px, bits: [] });
    }
    return this.mergeGap ? mergeClose(blobs, this.mergeGap) : blobs;
  }
}

function mergeAll(blobs) {
  const area = blobs.reduce((s, b) => s + b.area, 0);
  return { x0: Math.min(...blobs.map((b) => b.x0)), y0: Math.min(...blobs.map((b) => b.y0)),
    x1: Math.max(...blobs.map((b) => b.x1)), y1: Math.max(...blobs.map((b) => b.y1)), area,
    cx: blobs.reduce((s, b) => s + b.cx * b.area, 0) / area, cy: blobs.reduce((s, b) => s + b.cy * b.area, 0) / area,
    bits: blobs.flatMap((b) => (b.bits.length ? b.bits : [b.area])) };
}

function mergeClose(blobs, gap) {
  // bits whose boxes (almost) overlap are one object
  blobs = [...blobs];
  for (let merged = true; merged;) {
    merged = false;
    outer: for (let i = 0; i < blobs.length; i++)
      for (let j = i + 1; j < blobs.length; j++) {
        const a = blobs[i], b = blobs[j];
        if (a.x0 - gap <= b.x1 && b.x0 - gap <= a.x1 && a.y0 - gap <= b.y1 && b.y0 - gap <= a.y1) {
          blobs[i] = mergeAll([a, b]);
          blobs.splice(j, 1);
          merged = true;
          break outer;
        }
      }
  }
  return blobs;
}

const longSide = (b) => Math.max(b.x1 - b.x0, b.y1 - b.y0);

// Following objects from picture to picture and deciding when to photograph them (machine.py)
class Tracker {
  constructor(width) {
    this.width = width;   // machine pixels
    this.tracks = new Map();   // id -> {x, y, done, seen, before}
    this.next = 0;
    this.frame = 0;
    this.tracked = [];
  }

  // returns what to photograph now: [[blob, [blobs too close along the belt to separate], [their track ids]]];
  // this.tracked: [[track id, blob]] of everything in this picture
  step(blobs, pxPerMm, togetherMm = 10) {
    this.frame++;
    const past = (x) => x - this.width / 2 >= 0, used = new Set(), tracked = [];
    for (const b of [...blobs].sort((p, q) => p.cx - q.cx)) {
      let best = null, dist = 80;
      for (const [id, t] of this.tracks) {
        const d = Math.hypot(b.cx - t.x, b.cy - t.y);
        if (!used.has(id) && d < dist && b.cx - t.x > -15) { best = id; dist = d; }
      }
      if (best === null) {
        best = this.next++;
        this.tracks.set(best, { x: b.cx, y: b.cy, done: false, seen: this.frame, before: !past(b.cx) });
      }
      used.add(best);
      Object.assign(this.tracks.get(best), { x: b.cx, y: b.cy, seen: this.frame });
      tracked.push([best, b]);
    }
    for (const [id, t] of this.tracks) if (this.frame - t.seen >= 10) this.tracks.delete(id);
    const gapMm = (a, b) => Math.max(0, Math.max(a.x0, b.x0) - Math.min(a.x1, b.x1)) / pxPerMm;
    const now = [];
    for (const [id, b] of tracked) {
      const t = this.tracks.get(id);
      // once, as it crosses the middle; something first seen already past the middle is a bit of a
      // piece photographed already
      if (t.done || !t.before || !past(b.cx)) continue;
      const group = tracked.filter(([, o]) => gapMm(o, b) < togetherMm);
      group.forEach(([gid]) => (this.tracks.get(gid).done = true));
      now.push([b, group.map(([, o]) => o), group.map(([gid]) => gid)]);
    }
    this.tracked = tracked;
    return now;
  }
}
