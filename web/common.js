// Shared by the website's pages: the model (BrickSort's own, in the browser, or Brickognize online),
// and how answers are drawn (boxes in the colour each piece is thought to be, RebrickNet style).
"use strict";

const BRICKOGNIZE = "https://api.brickognize.com/predict/parts/?predict_color=true&top_k_items=3&top_k_colors=3";
const $ = (id) => document.getElementById(id);
let session = null, labels = null;
const modelChoice = () => document.querySelector("input[name=model]:checked").value;

// ------------------------------------------------------------------ the model
async function loadModel(statusLine) {
  try {
    labels = await (await fetch("model/labels.json", { cache: "no-cache" })).json();
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
    categories: topK(softmax(Array.from(out.categories.data)).map((p, i) => [labels.categories[i], p]), 3)
      .map(([name, s]) => ({ name, score: s })),
    printed: 1 / (1 + Math.exp(-out.printed.data[0])),
  };
}

async function predictBrickognize(square) {
  const blob = await new Promise((ok) => square.toBlob(ok, "image/jpeg", 0.92));
  const form = new FormData();
  form.append("query_image", blob, "piece.jpg");
  const r = await fetch(BRICKOGNIZE, { method: "POST", body: form });
  if (!r.ok) throw new Error(`Brickognize answered ${r.status}`);
  const a = await r.json();
  const rgbOf = (name) => labels?.colours.find((c) => c.name.toLowerCase() === name.toLowerCase())?.rgb;
  return {
    parts: (a.items || []).slice(0, 3).map((i) => ({ id: i.id, name: i.name, score: i.score, img: i.img_url })),
    colours: (a.colors || []).slice(0, 3).map((c) => ({ name: c.name, rgb: rgbOf(c.name), score: c.score })),
    categories: [], printed: null,   // Brickognize doesn't say
  };
}

function median(values) {
  const v = Float32Array.from(values).sort();
  return v.length ? v[v.length >> 1] : 0;
}
const pct = (s) => `${Math.round(s * 100)}%`;
const css = (rgb) => (rgb ? `rgb(${rgb.join(",")})` : "#888");
const textOn = (rgb) => (rgb && 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 150 ? "#000" : "#fff");
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

// The box around a piece in the colour it's thought to be, tagged "part colour" (RebrickNet style).
// tag: text for a piece that has no answer yet.
function drawTag(g, [x0, y0, x1, y1], answer, lw, tag = "…") {
  const colour = answer?.colours[0], part = answer?.parts[0];
  g.lineWidth = lw;
  g.strokeStyle = answer ? css(colour?.rgb) : "#fff";
  g.strokeRect(x0, y0, x1 - x0, y1 - y0);
  if (answer) tag = part ? `${part.id} ${colour ? colour.name : ""}` : "?";
  g.font = `600 ${lw * 7}px system-ui, sans-serif`;
  const tw = g.measureText(tag).width + lw * 3, th = lw * 9;
  const ty = y0 - th >= 0 ? y0 - th : y1;
  g.fillStyle = answer ? css(colour?.rgb) : "rgba(0,0,0,.55)";
  g.fillRect(x0 - lw / 2, ty, tw, th);
  g.fillStyle = answer ? textOn(colour?.rgb) : "#fff";
  g.fillText(tag, x0 + lw, ty + th - lw * 2.2);
}
