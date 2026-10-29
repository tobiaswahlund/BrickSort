// The virtual sorting machine in the browser. Pieces (pictures made by bricksort/export_sim.py from
// the 3D sorting machine) ride the belt under the camera. As a piece crosses the middle line the
// camera picture is cropped around it, the model guesses, the bin is chosen with the same rules as
// bricksort/sorter/rules.py (the default bins), and at the end of the belt it drops into that bin.
"use strict";

const cam = $("camera"), view = $("overview"), statusLine = $("status");
const g = cam.getContext("2d", { willReadFrequently: true }), o = view.getContext("2d");
const BELT_HALF_LEN = 2.0, SPEED = 0.22, SPACING_MIN = 0.4, SPACING_EXTRA = 0.3;   // as sorter/conveyor.py
const BIN_COLOURS = ["#d95a4c", "#4d8cd9", "#f2bf40", "#73bf66", "#b373cc", "#f28c33", "#66cccc", "#999", "#4d4d4d"];

let sim = null, ppu = 0, belt = null, light = null, empty = null, sprites = [];
let rules = null, running = false, beltPos = 0, last = null, pieces = [], nextGap = 0, falling = [];
const counts = {}, score = { sorted: 0, right: 0, rest: 0, wrong: 0, known: 0, part: 0, colour: 0 };

// ------------------------------------------------------------------ the sorting rules (as rules.py)
const lower = (v) => (typeof v === "string" ? [v.toLowerCase()] : v.map((x) => String(x).toLowerCase()));
let countsAs = new Map();   // colour name -> the name it counts as (Light Gray -> Light Bluish Gray)
const sameColour = (name) => countsAs.get((name || "").toLowerCase()) || (name || "");
const facts = new Map();
const binNeed = (b) => b.confidence ?? rules.confidence_needed;

function matches(when, partId, colour, printed = null) {
  const p = facts.get(partId) || {};
  for (const [key, want] of Object.entries(when)) {
    if (key === "printed") {
      if (printed === null || (printed >= 0.5) !== Boolean(want)) return false;
    } else if (key === "part") {
      if (!lower(Array.isArray(want) ? want : [want]).includes(partId.toLowerCase())) return false;
    } else if (key === "category" || key === "name") {
      const have = (p[key] || "").toLowerCase();
      if (!lower(want).some((t) => have.includes(t))) return false;
    } else if (key === "color") {
      if (!lower(want).map(sameColour).map((s) => s.toLowerCase()).includes(sameColour(colour).toLowerCase())) return false;
    } else if (key === "flat") {
      if (p.flat === undefined || Boolean(p.flat) !== Boolean(want)) return false;
    } else if (key.startsWith("min_") || key.startsWith("max_")) {
      const v = p[key.slice(4)];
      if (v === undefined || (key.startsWith("min_") ? v < want : v > want)) return false;
    } else return false;   // tags etc.: the website has no custom pieces
  }
  return true;
}

function mightMatch(when, category, colour, sureColour) {
  if (when.category && !lower(when.category).some((t) => category.toLowerCase().includes(t))) return false;
  if (when.color && sureColour && !matches({ color: when.color }, "", colour)) return false;
  return true;
}

function byCategory(category, catConf, colour, colourConf) {
  if (!category) return null;
  const sureColour = colourConf >= rules.confidence_needed;
  for (const b of rules.bins) {
    const when = b.when, need = binNeed(b);
    if (!when.category || Object.keys(when).some((k) => k !== "category" && k !== "color")) {
      if (mightMatch(when, category, colour, sureColour)) return null;
      continue;
    }
    if (!lower(when.category).some((t) => category.toLowerCase().includes(t)) || catConf < need) continue;
    if (when.color) {
      if (colourConf < need) return [rules.rest_bin, `a ${category} piece, but only ${pct(colourConf)} sure it's ${colour}`];
      if (!matches({ color: when.color }, "", colour)) continue;
    }
    return [b.name, `unknown part, but ${pct(catConf)} sure it's a ${category} piece`];
  }
  return null;
}

function chooseBin(part, partConf, colour, colourConf, category = "", catConf = 0, printed = null) {
  const rest = rules.rest_bin;
  if (part === "multiple") return [rest, `looks like several pieces together (${pct(partConf)} sure)`];
  if (part === "not_lego") return partConf >= rules.confidence_needed
    ? [rules.not_lego_bin, `not a Lego piece (${pct(partConf)} sure)`]
    : [rest, `probably not Lego, but only ${pct(partConf)} sure`];
  const lowest = Math.min(rules.confidence_needed, ...rules.bins.map(binNeed));
  if (partConf < lowest) {
    return byCategory(category, catConf, colour, colourConf) ||
      [rest, `only ${pct(partConf)} sure it's ${part} (needs ${pct(lowest)})`];
  }
  for (const b of rules.bins) {
    const shape = Object.fromEntries(Object.entries(b.when).filter(([k]) => k !== "color" && k !== "printed"));
    if (!matches(shape, part, colour)) continue;
    const need = binNeed(b), usesColour = "color" in b.when;
    if (usesColour && !matches({ color: b.when.color }, part, colour) && colourConf >= Math.min(need, rules.confidence_needed)) continue;
    if (partConf < need) return [rest, `only ${pct(partConf)} sure it's ${part} ('${b.name}' needs ${pct(need)})`];
    if ("printed" in b.when) {
      if (printed === null || need > Math.max(printed, 1 - printed)) return [rest, `${part}, but not sure whether it has a print`];
      if (!matches({ printed: b.when.printed }, part, colour, printed)) continue;
    }
    if (usesColour) {
      if (colourConf < need) return [rest, `${part}, but only ${pct(colourConf)} sure it's ${colour}`];
      if (!matches({ color: b.when.color }, part, colour)) continue;
    }
    return [b.name, `${part} ${colour} (${pct(partConf)} sure)`];
  }
  return [rest, `${part} ${colour} matches no bin`];
}

const binNames = () => [...rules.bins.map((b) => b.name), rules.not_lego_bin, rules.rest_bin];
const samePiece = (a, b) => a.replace(/[a-z]+$/, "") === b.replace(/[a-z]+$/, "");   // 3062a = 3062b

// ------------------------------------------------------------------ loading
async function loadImage(url) {
  const img = new Image();
  await new Promise((ok, fail) => { img.onload = ok; img.onerror = () => fail(new Error(`couldn't load ${url}`)); img.src = url; });
  return img;
}

async function setup() {
  await loadModel(statusLine);
  if (labels) {
    labels.parts.forEach((p) => facts.set(p.id, p));
    const byId = new Map(labels.colours.map((c) => [c.id, c.name]));
    labels.colours.forEach((c) => countsAs.set(c.name.toLowerCase(), byId.get(c.counts_as) || c.name));
  }
  sim = await (await fetch("sim/sim.json", { cache: "no-cache" })).json();
  ppu = sim.px_per_mm * 100;
  [belt, light, empty] = await Promise.all(["sim/belt.png", "sim/light.png", "sim/empty.jpg"].map(loadImage));
  sprites = await Promise.all(sim.pieces.map((p) => loadImage("sim/" + p.file)));
  setRules();
  draw();
  $("go").disabled = false;
  statusLine.textContent += " Press Start.";
}

function setRules() {
  const base = labels?.rules || { confidence_needed: 0.85, confidence_needed_brickognize: 0.75, not_lego_bin: "Not Lego",
    rest_bin: "Rest", bins: [{ name: "Other Lego", when: {} }] };
  rules = JSON.parse(JSON.stringify(base));
  rules.confidence_needed = $("sure").value / 100;
  binNames().forEach((b) => (counts[b] ??= 0));
}

// ------------------------------------------------------------------ the belt
function spawn() {
  // the next piece as soon as there's room behind the last one (as conveyor.py maybe_spawn)
  const k = Math.floor(Math.random() * sim.pieces.length), p = sim.pieces[k];
  const halfW = p.w / 2 / ppu, halfH = p.h / 2 / ppu, x = -BELT_HALF_LEN + 0.2 + halfW;
  const newest = pieces[pieces.length - 1];
  if (newest && newest.x - newest.halfW < x + halfW + nextGap) return;
  const room = Math.max(0, (sim.belt_bottom - sim.belt_top) / 2 / ppu - halfH - 0.05);
  pieces.push({ k, p, x, y: (Math.random() * 2 - 1) * room * 0.85, halfW, halfH });
  nextGap = SPACING_MIN + Math.min(-Math.log(1 - Math.random()) * SPACING_EXTRA, 4 * SPACING_EXTRA);
}

// where a piece's picture goes in the camera picture (camera above x = 0)
const camX = (pc) => sim.camera / 2 + pc.x * ppu - pc.p.w / 2;
const camY = (pc) => sim.camera / 2 - pc.y * ppu - pc.p.h / 2;
const solidBox = (pc) => [camX(pc) + pc.p.solid[0], camY(pc) + pc.p.solid[1], camX(pc) + pc.p.solid[2], camY(pc) + pc.p.solid[3]];

function drawCamera() {
  g.globalCompositeOperation = "source-over";
  g.drawImage(empty, 0, 0);
  const top = sim.belt_top, h = sim.belt_bottom - sim.belt_top, P = sim.period;
  const shift = ((beltPos * ppu) % P + P) % P;
  for (let x = shift - P; x < sim.camera; x += P) g.drawImage(belt, Math.round(x), top);
  g.globalCompositeOperation = "multiply";   // the lamps' light stays put while the belt moves under it
  g.drawImage(light, 0, top, sim.camera, h);
  g.globalCompositeOperation = "source-over";
  for (const pc of pieces) {
    const x = camX(pc);
    if (x < sim.camera && x + pc.p.w > 0) g.drawImage(sprites[pc.k], Math.round(x), Math.round(camY(pc)));
  }
}

function photograph(pc) {
  // a square around the piece, as sorter/detector.py crop(): longest side + 15%
  const [x0, y0, x1, y1] = solidBox(pc), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const half = Math.max(x1 - x0, y1 - y0) / 2 * 1.15 + 6, c = document.createElement("canvas");
  c.width = c.height = Math.round(2 * half);
  c.getContext("2d").drawImage(cam, cx - half, cy - half, 2 * half, 2 * half, 0, 0, c.width, c.height);
  return c;
}

async function decide(pc) {
  pc.picture = photograph(pc);
  const brickognize = modelChoice() === "brickognize";
  try {
    if (!brickognize && !session) throw new Error("no model");
    pc.answer = brickognize ? await predictBrickognize(pc.picture) : await predictMine(pc.picture);
  } catch (e) {
    console.error(e);
    pc.answer = { parts: [], colours: [], categories: [], printed: null };
  }
  const a = pc.answer, part = a.parts[0], colour = a.colours[0], cat = a.categories[0];
  [pc.bin, pc.reason] = part
    ? chooseBin(part.id, part.score, colour?.name || "?", colour?.score || 0, cat?.name || "", cat?.score || 0, a.printed)
    : [rules.rest_bin, brickognize ? "Brickognize couldn't be reached" : "no answer"];
  if (pc.gone) return;   // already fell off the end before the answer came: it went to Rest
  check(pc);
  showLast(pc);
}

function check(pc) {
  // what the piece really is (only a simulation knows) and which bin it should have gone to
  const t = pc.p, a = pc.answer;
  const right = t.part === "not_lego" ? rules.not_lego_bin : chooseBin(t.part, 1, t.colour, 1, t.category, 1)[0];
  pc.rightBin = right;
  if (t.part !== "not_lego" && t.known && a.parts[0]) {
    score.known++;
    pc.partOk = samePiece(a.parts[0].id, t.part);
    pc.colourOk = sameColour(a.colours[0]?.name).toLowerCase() === sameColour(t.colour).toLowerCase();
    score.part += pc.partOk;
    score.colour += pc.colourOk;
  }
}

function showLast(pc) {
  const a = pc.answer, part = a.parts[0], colour = a.colours[0], t = pc.p;
  const truth = t.part === "not_lego" ? "not a LEGO piece" : `${t.part} ${t.colour}`;
  const verdict = pc.partOk === undefined ? `It was ${truth}.`
    : pc.partOk && pc.colourOk ? `<span class="right">✓ Right: it was ${truth}.</span>`
    : `<span class="wrong">✗ It was ${truth}.</span>`;
  const name = part ? `${part.id} ${esc(part.name || "")}` : "no answer";
  $("last").innerHTML = `<img alt="" src="${pc.picture.toDataURL("image/jpeg", 0.85)}">` +
    `<div class="bin">→ ${esc(pc.bin)}</div><div>${esc(pc.reason)}</div>` +
    (part ? `<div class="alt">Guess: ${name} · ${pct(part.score)}` +
      (colour ? `, <span class="swatch" style="background:${css(colour.rgb)}"></span>${esc(colour.name)} · ${pct(colour.score)}` : "") + "</div>" : "") +
    `<div>${verdict}</div>`;
}

function arrived(pc) {
  if (!pc.bin) { pc.bin = rules.rest_bin; pc.reason = "no answer in time"; }
  counts[pc.bin] = (counts[pc.bin] || 0) + 1;
  score.sorted++;
  const right = pc.rightBin ?? (pc.p.part === "not_lego" ? rules.not_lego_bin : null);
  let result = "";
  if (pc.bin === right) { score.right++; result = "✓"; }
  else if (pc.bin === rules.rest_bin) { score.rest++; result = "set aside"; }
  else { score.wrong++; result = `✗ should be ${right}`; }
  const li = document.createElement("li");
  const t = pc.p.part === "not_lego" ? "a non-LEGO object" : `${pc.p.part} ${pc.p.colour}`;
  li.textContent = `${t} → ${pc.bin}: ${pc.reason}  ${result}`;
  $("log").prepend(li);
  while ($("log").children.length > 100) $("log").lastChild.remove();
  const p = (x) => `${x} (${Math.round((100 * x) / score.sorted)}%)`;
  const acc = score.known ? `<br>Model right about the part ${p2(score.part, score.known)}, the colour ${p2(score.colour, score.known)}` : "";
  $("score").innerHTML = `${score.sorted} pieces sorted<br>Right bin: ${p(score.right)}<br>` +
    `Set aside in ${esc(rules.rest_bin)}: ${p(score.rest)}<br>Wrong bin: ${p(score.wrong)}${acc}`;
}
const p2 = (x, n) => `${x}/${n} (${Math.round((100 * x) / n)}%)`;

// ------------------------------------------------------------------ drawing the machine from above
function drawOverview() {
  const W = view.width, H = view.height, names = binNames();
  const left = 20, beltEnd = W - 250, s = (beltEnd - left) / (2 * BELT_HALF_LEN);   // px per unit
  const X = (x) => left + (x + BELT_HALF_LEN) * s, mid = H / 2;
  const bh = (sim.belt_bottom - sim.belt_top) / ppu / 2 * s;
  o.clearRect(0, 0, W, H);
  o.fillStyle = "#2e7a43";
  o.fillRect(left, mid - bh, beltEnd - left, 2 * bh);
  o.fillStyle = "#444";
  o.fillRect(left, mid - bh - 4, beltEnd - left, 4);
  o.fillRect(left, mid + bh, beltEnd - left, 4);
  const half = sim.camera / 2 / ppu;
  o.setLineDash([6, 4]); o.strokeStyle = "#fff"; o.lineWidth = 2;
  o.strokeRect(X(-half), mid - bh - 8, 2 * half * s, 2 * bh + 16);
  o.setLineDash([]);
  o.beginPath(); o.moveTo(X(0), mid - bh); o.lineTo(X(0), mid + bh); o.stroke();
  o.fillStyle = "#fff"; o.font = "12px system-ui"; o.fillText("camera", X(-half) + 4, mid - bh - 12);
  for (const pc of pieces) {
    o.drawImage(sprites[pc.k], X(pc.x) - pc.halfW * s, mid - pc.y * s - pc.halfH * s, pc.p.w / ppu * s, pc.p.h / ppu * s);
    if (pc.answer && pc.answer.parts[0]) {   // the box follows the piece to the end of the belt
      const r = [X(pc.x) - pc.halfW * s - 2, mid - pc.y * s - pc.halfH * s - 2, X(pc.x) + pc.halfW * s + 2, mid - pc.y * s + pc.halfH * s + 2];
      drawTag(o, r, pc.answer, 2);
    }
  }
  // the bins, one under the other at the end of the belt
  const bx = beltEnd + 70, gap = 3, each = (H - 10 - gap * (names.length - 1)) / names.length;
  const binY = (i) => 5 + i * (each + gap);
  names.forEach((n, i) => {
    o.fillStyle = BIN_COLOURS[i % BIN_COLOURS.length];
    o.fillRect(bx, binY(i), W - bx - 5, each);
    o.fillStyle = "#fff"; o.font = "600 13px system-ui";
    o.fillText(`${n}: ${counts[n] || 0}`, bx + 8, binY(i) + each / 2 + 5);
  });
  o.fillStyle = "#555";
  o.fillRect(beltEnd, mid - 3, 40, 6);   // the flap
  for (const f of falling) {
    const i = names.indexOf(f.bin), t = Math.min(1, f.t / 0.6);
    const x = beltEnd + t * (bx + 20 - beltEnd), y = mid + t * (binY(i) + each / 2 - mid);
    o.drawImage(sprites[f.k], x - 10, y - 10, 20, 20);
  }
}

function drawCameraBoxes() {
  g.font = "12px system-ui"; g.strokeStyle = "rgba(255,255,255,.7)"; g.lineWidth = 1;
  g.beginPath(); g.moveTo(sim.camera / 2, 0); g.lineTo(sim.camera / 2, sim.camera); g.stroke();
  for (const pc of pieces) {
    const box = solidBox(pc);
    if (box[2] < 0 || box[0] > sim.camera) continue;
    if (pc.answer) drawTag(g, box, pc.answer, 3);   // after the guess: box in the guessed colour, "part colour"
    else { g.strokeStyle = "rgba(255,255,255,.8)"; g.lineWidth = 2; g.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]); }
  }
}

function draw() {
  drawCamera();
  // photograph pieces that crossed the middle line (from the clean picture, before boxes are drawn)
  for (const pc of pieces) if (!pc.asked && pc.x >= 0) { pc.asked = true; decide(pc); }
  drawCameraBoxes();
  drawOverview();
}

// ------------------------------------------------------------------ running
let then = 0;
function tick(now) {
  if (!running) return;
  const dt = Math.max(0, Math.min(0.1, (now - (then || now)) / 1000)) * Number($("speed").value);
  then = now;
  beltPos += SPEED * dt;
  for (const pc of pieces) pc.x += SPEED * dt;
  for (const pc of pieces.filter((p) => p.x - p.halfW > BELT_HALF_LEN)) {   // off the end: into its bin
    pc.gone = true;
    arrived(pc);
    falling.push({ k: pc.k, bin: pc.bin, t: 0 });
  }
  pieces = pieces.filter((p) => !p.gone);
  falling.forEach((f) => (f.t += dt));
  falling = falling.filter((f) => f.t < 0.6);
  spawn();
  draw();
  requestAnimationFrame(tick);
}

$("go").addEventListener("click", () => {
  running = !running;
  $("go").textContent = running ? "Pause" : "Start";
  then = 0;
  if (running) requestAnimationFrame(tick);
});
$("sure").addEventListener("input", () => {
  $("sure_text").textContent = `${$("sure").value}%`;
  rules.confidence_needed = $("sure").value / 100;
});
document.querySelectorAll("input[name=model]").forEach((r) => r.addEventListener("change", () => {
  const bk = modelChoice() === "brickognize";
  $("sure").value = Math.round(100 * (bk ? rules.confidence_needed_brickognize : labels?.rules?.confidence_needed ?? 0.85));
  $("sure").dispatchEvent(new Event("input"));
}));
$("go").disabled = true;
setup();
