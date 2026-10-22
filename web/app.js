// BrickSort in the browser: find the pieces in a photo, then recognise each one with BrickSort's
// own model (onnxruntime-web, on this device) or Brickognize (online). The piece finder is the same
// as bricksort/cut.py find_pieces and square_crop, written again in JavaScript.
"use strict";

const BRICKOGNIZE = "https://api.brickognize.com/predict/parts/?predict_color=true&top_k_items=3&top_k_colors=3";
const $ = (id) => document.getElementById(id);
const canvas = $("canvas"), video = $("video"), list = $("list"), statusLine = $("status");

let session = null, labels = null, photo = null, run = 0;
const modelChoice = () => document.querySelector("input[name=model]:checked").value;

// ------------------------------------------------------------------ the model
async function loadModel() {
  try {
    labels = await (await fetch("model/labels.json")).json();
    ort.env.wasm.wasmPaths = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/";
    session = await ort.InferenceSession.create("model/model.onnx", { executionProviders: ["wasm"] });
    const when = labels.trained ? `, trained ${labels.trained}` : "";
    statusLine.textContent = `Model ready: knows ${labels.parts.length} parts and ${labels.colours.length} colours${when}.`;
  } catch (e) {
    console.error(e);
    statusLine.textContent = "BrickSort's own model couldn't be loaded here; Brickognize still works.";
    document.querySelector("input[value=brickognize]").checked = true;
  }
}

function softmax(a) {
  const m = Math.max(...a), e = a.map((v) => Math.exp(v - m)), s = e.reduce((x, y) => x + y, 0);
  return e.map((v) => v / s);
}
const topK = (pairs, k) => pairs.sort((a, b) => b[1] - a[1]).slice(0, k);

async function predictMine(square) {
  const size = labels.size, c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  g.drawImage(square, 0, 0, size, size);
  const px = g.getImageData(0, 0, size, size).data, n = size * size, x = new Float32Array(3 * n);
  for (let i = 0; i < n; i++)
    for (let ch = 0; ch < 3; ch++) x[ch * n + i] = (px[i * 4 + ch] / 255 - labels.mean[ch]) / labels.std[ch];
  const out = await session.run({ image: new ort.Tensor("float32", x, [1, 3, size, size]) });
  const parts = softmax(Array.from(out.parts.data)).map((p, i) => [labels.parts[i], p]);
  const merged = new Map();   // look-alike colours (Light Gray / Light Bluish Gray) count as one
  softmax(Array.from(out.colours.data)).forEach((p, i) => {
    const id = labels.colours[i].counts_as;
    merged.set(id, (merged.get(id) || 0) + p);
  });
  const byId = new Map(labels.colours.map((c) => [c.id, c]));
  return {
    parts: topK(parts, 3).map(([p, s]) => ({ id: p.id, name: p.name, score: s })),
    colours: topK([...merged], 3).map(([id, s]) => ({ name: byId.get(id).name, rgb: byId.get(id).rgb, score: s })),
  };
}

async function predictBrickognize(square) {
  const blob = await new Promise((ok) => square.toBlob(ok, "image/jpeg", 0.92));
  const form = new FormData();
  form.append("query_image", blob, "piece.jpg");
  const r = await fetch(BRICKOGNIZE, { method: "POST", body: form });
  if (!r.ok) throw new Error(`Brickognize answered ${r.statusLine}`);
  const a = await r.json();
  const rgbOf = (name) => labels?.colours.find((c) => c.name.toLowerCase() === name.toLowerCase())?.rgb;
  return {
    parts: (a.items || []).slice(0, 3).map((i) => ({ id: i.id, name: i.name, score: i.score, img: i.img_url })),
    colours: (a.colors || []).slice(0, 3).map((c) => ({ name: c.name, rgb: rgbOf(c.name), score: c.score })),
  };
}

// ------------------------------------------------------------------ finding the pieces (as cut.py)
function median(values) {
  const v = Float32Array.from(values).sort();
  return v.length ? v[v.length >> 1] : 0;
}

function findPieces(img) {
  const k0 = Math.min(1, 640 / Math.max(img.width, img.height));
  const w = Math.round(img.width * k0), h = Math.round(img.height * k0);
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.imageSmoothingQuality = "high";
  g.drawImage(img, 0, 0, w, h);
  const a = g.getImageData(0, 0, w, h).data;
  const at = (x, y, ch) => a[(y * w + x) * 4 + ch];

  // The surface the pieces lie on: the most common colour in the middle of the photo
  const count = new Map(), groups = new Map();
  for (let y = h >> 2; y < (3 * h) >> 2; y++)
    for (let x = w >> 2; x < (3 * w) >> 2; x++) {
      const key = ((at(x, y, 0) / 40) | 0) * 49 + ((at(x, y, 1) / 40) | 0) * 7 + ((at(x, y, 2) / 40) | 0);
      count.set(key, (count.get(key) || 0) + 1);
      if (!groups.has(key)) groups.set(key, [[], [], []]);
      for (let ch = 0; ch < 3; ch++) groups.get(key)[ch].push(at(x, y, ch));
    }
  const best = [...count].sort((p, q) => q[1] - p[1])[0][0];
  const surface = groups.get(best).map(median);

  // Light changes across a table: follow the surface colour cell by cell (surface-like pixels only)
  const cell = 40, gw = Math.ceil(w / cell), gh = Math.ceil(h / cell), grid = [];
  for (let i = 0; i < gh; i++)
    for (let j = 0; j < gw; j++) {
      const like = [[], [], []];
      for (let y = i * cell; y < Math.min(h, (i + 1) * cell); y++)
        for (let x = j * cell; x < Math.min(w, (j + 1) * cell); x++) {
          const p = [at(x, y, 0), at(x, y, 1), at(x, y, 2)];
          if (Math.max(...p.map((v, ch) => Math.abs(v - surface[ch]))) < 70) p.forEach((v, ch) => like[ch].push(v));
        }
      grid.push(like[0].length > 50 ? like.map(median) : surface);
    }
  const bgAt = (x, y, ch) => {   // smooth (bilinear) surface colour between cell centres
    const fy = Math.min(gh - 1, Math.max(0, (y + 0.5) / cell - 0.5)), fx = Math.min(gw - 1, Math.max(0, (x + 0.5) / cell - 0.5));
    const i0 = Math.floor(fy), j0 = Math.floor(fx), i1 = Math.min(gh - 1, i0 + 1), j1 = Math.min(gw - 1, j0 + 1);
    const ty = fy - i0, tx = fx - j0, G = (i, j) => grid[i * gw + j][ch];
    return (G(i0, j0) * (1 - tx) + G(i0, j1) * tx) * (1 - ty) + (G(i1, j0) * (1 - tx) + G(i1, j1) * tx) * ty;
  };

  // Compare 4x4 blocks with the surface (as sorter/detector.py, threshold 40, shadows don't count)
  const S = 4, bw = Math.floor(w / S), bh = Math.floor(h / S);
  let m = new Uint8Array(bw * bh);
  for (let by = 0; by < bh; by++)
    for (let bx = 0; bx < bw; bx++) {
      const f = [0, 0, 0], b = [0, 0, 0];
      for (let y = by * S; y < by * S + S; y++)
        for (let x = bx * S; x < bx * S + S; x++)
          for (let ch = 0; ch < 3; ch++) { f[ch] += at(x, y, ch) / 16; b[ch] += bgAt(x, y, ch) / 16; }
      const diff = Math.max(...f.map((v, ch) => Math.abs(v - b[ch])));
      const lf = (f[0] + f[1] + f[2]) / 3 + 1, lb = (b[0] + b[1] + b[2]) / 3 + 1, ratio = lf / lb;
      const chroma = Math.max(...f.map((v, ch) => Math.abs(v / lf - b[ch] / lb)));
      const shadow = ratio > 0.35 && ratio < 0.97 && chroma < 0.12;
      m[by * bw + bx] = diff > 40 && !shadow ? 1 : 0;
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
  const tidy = new Uint8Array(bw * bh);   // drop lonely blocks, then close small gaps
  for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) tidy[y * bw + x] = m[y * bw + x] && around(m, x, y) >= 2;
  m = new Uint8Array(bw * bh);
  for (let y = 0; y < bh; y++) for (let x = 0; x < bw; x++) m[y * bw + x] = tidy[y * bw + x] || around(tidy, x, y) > 0;

  // Touching blocks make one piece
  const seen = new Uint8Array(bw * bh), k = img.width / w, boxes = [];
  for (let start = 0; start < bw * bh; start++) {
    if (!m[start] || seen[start]) continue;
    let x0 = bw, y0 = bh, x1 = 0, y1 = 0, n = 0;
    const stack = [start];
    seen[start] = 1;
    while (stack.length) {
      const p = stack.pop(), x = p % bw, y = (p - x) / bw;
      n++; x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx, yy = y + dy, q = yy * bw + xx;
          if (xx >= 0 && yy >= 0 && xx < bw && yy < bh && m[q] && !seen[q]) { seen[q] = 1; stack.push(q); }
        }
    }
    if (n * S * S < 120) continue;
    const box = [x0 * S, y0 * S, x1 * S + S, y1 * S + S];
    const touchesEdge = box[0] <= 4 || box[1] <= 4 || box[2] >= w - 4 || box[3] >= h - 4;
    const tooBig = (box[2] - box[0]) * (box[3] - box[1]) > 0.2 * w * h;
    if (!touchesEdge && !tooBig) boxes.push(box.map((v) => Math.round(v * k)));   // else: things around the table
  }
  return boxes;
}

function squareCrop(img, [x0, y0, x1, y1], margin = 0.05) {
  // What's inside the box (plus a hair), made square with the surface colour so neighbours stay out
  const mx = (x1 - x0) * margin, my = (y1 - y0) * margin;
  const sx = Math.max(0, Math.floor(x0 - mx)), sy = Math.max(0, Math.floor(y0 - my));
  const pw = Math.min(img.width, Math.ceil(x1 + mx)) - sx, ph = Math.min(img.height, Math.ceil(y1 + my)) - sy;
  const piece = document.createElement("canvas");
  piece.width = pw; piece.height = ph;
  const pg = piece.getContext("2d", { willReadFrequently: true });
  pg.drawImage(img, sx, sy, pw, ph, 0, 0, pw, ph);
  const d = pg.getImageData(0, 0, pw, ph).data, edge = [[], [], []];
  const add = (x, y) => { for (let ch = 0; ch < 3; ch++) edge[ch].push(d[(y * pw + x) * 4 + ch]); };
  for (let x = 0; x < pw; x++) { add(x, 0); add(x, ph - 1); }
  for (let y = 0; y < ph; y++) { add(0, y); add(pw - 1, y); }
  const side = Math.max(pw, ph), sq = document.createElement("canvas");
  sq.width = sq.height = side;
  const sg = sq.getContext("2d");
  sg.fillStyle = `rgb(${edge.map(median).join(",")})`;
  sg.fillRect(0, 0, side, side);
  sg.drawImage(piece, (side - pw) >> 1, (side - ph) >> 1);
  return sq;
}

// ------------------------------------------------------------------ showing the answers
const pct = (s) => `${Math.round(s * 100)}%`;
const css = (rgb) => (rgb ? `rgb(${rgb.join(",")})` : "#888");
const textOn = (rgb) => (rgb && 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 150 ? "#000" : "#fff");

function drawPhoto(results) {
  const g = canvas.getContext("2d");
  canvas.width = photo.width; canvas.height = photo.height;
  g.drawImage(photo, 0, 0);
  const lw = Math.max(2, Math.round(Math.max(photo.width, photo.height) / 300));
  g.font = `600 ${lw * 7}px system-ui, sans-serif`;
  for (const r of results) {
    const [x0, y0, x1, y1] = r.box, colour = r.answer?.colours[0], part = r.answer?.parts[0];
    g.lineWidth = lw;
    g.strokeStyle = css(colour?.rgb);   // the box in the colour the piece is thought to be
    g.strokeRect(x0, y0, x1 - x0, y1 - y0);
    const tag = r.answer ? (part ? `${part.id} ${colour ? colour.name : ""}` : "?") : `${r.n} …`;
    const tw = g.measureText(tag).width + lw * 3, th = lw * 9;
    const ty = y0 - th >= 0 ? y0 - th : y1;
    g.fillStyle = css(colour?.rgb);
    g.fillRect(x0 - lw / 2, ty, tw, th);
    g.fillStyle = textOn(colour?.rgb);
    g.fillText(tag, x0 + lw, ty + th - lw * 2.2);
  }
}

function showItem(r, square) {
  const li = document.createElement("li"), img = document.createElement("img"), div = document.createElement("div");
  img.src = square.toDataURL("image/jpeg", 0.85);
  img.alt = `piece ${r.n}`;
  li.append(img, div);
  list.append(li);
  r.show = (answer, error) => {
    if (error) { div.innerHTML = `<span class="alt">${r.n}. ${error}</span>`; return; }
    const [p, ...others] = answer.parts, c = answer.colours[0];
    const name = (x) => `${x.id}${x.name ? ` <span class="alt">${esc(x.name)}</span>` : ""}`;
    div.innerHTML = p
      ? `<div class="guess">${r.n}. ${name(p)} · ${pct(p.score)}</div>` +
        (c ? `<div><span class="swatch" style="background:${css(c.rgb)}"></span>${esc(c.name)} · ${pct(c.score)}</div>` : "") +
        (others.length ? `<div class="alt">or ${others.map((o) => `${o.id} (${pct(o.score)})`).join(", ")}</div>` : "") +
        (answer.colours.length > 1 ? `<div class="alt">or ${answer.colours.slice(1).map((o) => `${esc(o.name)} (${pct(o.score)})`).join(", ")}</div>` : "")
      : `<div class="guess">${r.n}. No answer</div>`;
  };
}
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

async function recognise() {
  if (!photo) return;
  const mine = modelChoice() === "mine", me = ++run;
  if (mine && !session) { statusLine.textContent = "The model is still loading …"; return; }
  canvas.hidden = false; $("hint").hidden = true; list.innerHTML = "";
  const boxes = findPieces(photo);
  if (!boxes.length) {
    statusLine.textContent = "No pieces found. Use a plain surface that differs from the pieces, and keep them a little apart.";
    drawPhoto([]);
    return;
  }
  const results = boxes.map((box, i) => ({ box, n: i + 1 }));
  drawPhoto(results);
  statusLine.textContent = `Found ${boxes.length} piece${boxes.length > 1 ? "s" : ""}; recognising …`;
  for (const r of results) {
    const square = squareCrop(photo, r.box);
    showItem(r, square);
    try {
      r.answer = mine ? await predictMine(square) : await predictBrickognize(square);
      if (me !== run) return;   // a new photo or model was chosen meanwhile
      r.show(r.answer);
    } catch (e) {
      if (me !== run) return;
      console.error(e);
      r.answer = { parts: [], colours: [] };
      r.show(null, mine ? "The model failed on this piece." : "Brickognize couldn't be reached.");
    }
    drawPhoto(results);
  }
  statusLine.textContent = `Found ${boxes.length} piece${boxes.length > 1 ? "s" : ""}` +
    (mine ? ", recognised on this device." : ", recognised by Brickognize.");
}

// ------------------------------------------------------------------ photos and the webcam
function usePicture(source) {
  const c = document.createElement("canvas"), k = Math.min(1, 2000 / Math.max(source.width, source.height));
  c.width = Math.round(source.width * k); c.height = Math.round(source.height * k);
  c.getContext("2d").drawImage(source, 0, 0, c.width, c.height);
  photo = c;
  recognise();
}

async function loadImage(url) {
  const img = new Image();
  img.src = url;
  await img.decode();
  return img;
}

$("file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  stopCamera();
  const url = URL.createObjectURL(f);
  usePicture(await loadImage(url));
  URL.revokeObjectURL(url);
  e.target.value = "";
});
$("example").addEventListener("click", async () => { stopCamera(); usePicture(await loadImage("example.png")); });
document.querySelectorAll("input[name=model]").forEach((r) => r.addEventListener("change", recognise));

let stream = null;
function stopCamera() {
  if (stream) stream.getTracks().forEach((t) => t.stop());
  stream = null; video.hidden = true; $("snap").hidden = true; $("camera").textContent = "Use the webcam";
}
$("camera").addEventListener("click", async () => {
  if (stream) { stopCamera(); return; }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 } } });
  } catch (e) {
    statusLine.textContent = "The camera couldn't be opened (no camera, or permission was not given).";
    return;
  }
  video.srcObject = stream;
  await video.play();
  video.hidden = false; canvas.hidden = true; $("hint").hidden = true; list.innerHTML = "";
  $("snap").hidden = false; $("camera").textContent = "Stop the webcam";
  statusLine.textContent = "Point the camera straight down at the pieces and take a picture.";
});
$("snap").addEventListener("click", () => {
  const c = document.createElement("canvas");
  c.width = video.videoWidth; c.height = video.videoHeight;
  c.getContext("2d").drawImage(video, 0, 0);
  stopCamera();
  usePicture(c);
});

loadModel();
