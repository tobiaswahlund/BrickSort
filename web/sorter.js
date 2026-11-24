// The sorting machine, simulated live in your browser: pieces are dropped onto a moving belt (the same
// MuJoCo physics as the desktop app's virtual sorting machine), the camera above the belt takes a
// picture every frame, the sorter finds the pieces in it, photographs each as it crosses the middle
// line, the model guesses, the bin is chosen with the same rules as bricksort/sorter/rules.py (the
// default bins), and at the end of the belt a flap sends the piece to that bin, as on the machine.
// Nothing here knows what a piece is except the simulation itself (used only to score the guesses).
"use strict";

const statusLine = $("status"), cam = $("camera"), g = cam.getContext("2d");
const BIN_COLOURS = ["#d95a4c", "#4d8cd9", "#f2bf40", "#73bf66", "#b373cc", "#f28c33", "#66cccc", "#999", "#4d4d4d"];
const RES = 1080;              // the camera picture, in pixels (the machine's own camera has 720)
const BRICKOGNIZE_GAP = 1.1;   // seconds between requests to brickognize.com (it's someone else's free service)

let cat = null, M = null, machine = null, detector = null, tracker = null, K = 1, pxPerMm = 1;
let rules = null, running = false, run = 0;   // run goes up on Reset: answers from before are dropped
const counts = {}, score = {};
function clearScore() {
  Object.assign(score, { sorted: 0, right: 0, rest: 0, wrong: 0, known: 0, part: 0, colour: 0 });
  for (const b of Object.keys(counts)) counts[b] = 0;
}
clearScore();

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
  const modelText = statusLine.textContent;
  if (labels) {
    labels.parts.forEach((p) => facts.set(p.id, p));
    const byId = new Map(labels.colours.map((c) => [c.id, c.name]));
    labels.colours.forEach((c) => countsAs.set(c.name.toLowerCase(), byId.get(c.counts_as) || c.name));
  }
  setRules();
  try {
    statusLine.textContent = `${modelText} Loading the sorting machine (the physics engine is about 11 MB) …`;
    cat = await (await fetch("machine/catalogue.json", { cache: "no-cache" })).json();
    M = cat.machine;
    cam.width = cam.height = RES;
    K = RES / M.machine_camera;
    pxPerMm = M.machine_camera / (2 * M.camera_height * Math.tan((M.fovy / 2) * Math.PI / 180) * 100);
    machine = new Machine3D(M, await loadImage("machine/belt.png"), RES, $("overview"));
    machine.setBins(binNames(), BIN_COLOURS);
    await machine.loadPhysics();
    setupFilters();
    newDeck();
    await nextPool(true);
    statusLine.textContent = `${modelText} Learning what the empty belt looks like …`;
    await new Promise((ok) => setTimeout(ok, 0));
    detector = new Detector(K);
    detector.learnBackground(machine.emptyFrames());
    tracker = new Tracker(M.machine_camera);
    statusLine.textContent = `${modelText} Press Start.`;
    draw(null);
    $("go").disabled = false;
  } catch (e) {
    console.error(e);
    statusLine.textContent = `${modelText} The sorting machine couldn't start in this browser (${e.message}). ` +
      "It needs WebGL and WebAssembly, and a computer rather than a phone works best.";
  }
}

function setRules() {
  const base = labels?.rules || { confidence_needed: 0.85, confidence_needed_brickognize: 0.75, not_lego_bin: "Not Lego",
    rest_bin: "Rest", bins: [{ name: "Other Lego", when: {} }] };
  rules = JSON.parse(JSON.stringify(base));
  rules.confidence_needed = $("sure").value / 100;
  binNames().forEach((b) => (counts[b] ??= 0));
}

// ------------------------------------------------------------------ which pieces come
// The machine holds a set of pieces at a time (as the desktop app: a fresh random set every so many
// pieces). deck: every part allowed by the filters, shuffled; sets are dealt from it, so each part
// comes once before any part comes twice.
let deck = [], upcoming = null, swapping = false, nextGap = 0, nextSlot = null;
const shapes = new Map();   // file -> part shape (kept: a part that comes again needs no loading)

const knownOnly = () => $("known").checked;
let colourOk = new Set();   // colour ids ticked in the colour menu
const coloursOf = (p) => p.colours.filter(([c]) => colourOk.has(c));
const allowed = (p) => (!knownOnly() || p.known) && coloursOf(p).length > 0;

function newDeck() {
  deck = cat.parts.map((p, i) => i).filter((i) => allowed(cat.parts[i]));
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  showPool();
}

async function shapeOf(file) {
  if (!shapes.has(file)) {
    shapes.set(file, fetch("machine/parts/" + file).then((r) => {
      if (!r.ok) throw new Error(`no ${file}`);
      return r.arrayBuffer();
    }).then(partShape).catch(() => null));
  }
  return shapes.get(file);
}

function deal() {
  // the next set of parts, their 3D models loading in the background
  const n = cat.parts.filter(allowed).length;
  if (!n) return null;
  const picked = [];
  while (picked.length < Math.min(M.pool, n)) {
    if (!deck.length) newDeck();
    const i = deck.pop();
    if (!picked.includes(i)) picked.push(i);
  }
  const ready = Promise.all(picked.map(async (i) => ({ part: cat.parts[i], shape: await shapeOf(cat.parts[i].file) })))
    .then((list) => list.filter((s) => s.shape));
  return { picked, ready };
}

async function nextPool(first = false) {
  // the waiting set goes into the machine (loading it first if needed); the one after starts loading
  if (swapping) return;
  swapping = true;
  try {
    const b = upcoming || deal();
    upcoming = null;
    if (!b) { showPool(); return; }
    if (!first) $("pieces_status").textContent = "Loading the next set of pieces …";
    const slots = (await b.ready).filter((s) => allowed(s.part)).map((s) => ({ ...s.shape, part: s.part }));
    if (slots.length) machine.build(slots);
    nextSlot = null;
    upcoming = deal();
    showPool();
  } finally { swapping = false; }
}

function showPool() {
  const n = cat.parts.filter(allowed).length;
  $("pieces_status").textContent = !n ? "No pieces match: tick more colours, or untick \"only pieces the model knows\"."
    : `${n} of ${cat.parts.length} LEGO parts can come (${cat.parts.filter((p) => p.known && allowed(p)).length} the model knows); ` +
      `the machine holds a random set of ${M.pool} at a time.`;
}

function filtersChanged() {
  newDeck();
  if (upcoming && !upcoming.picked.every((i) => allowed(cat.parts[i]))) upcoming = deal();
  nextSlot = null;
}

function setupFilters() {
  const n = new Map();
  cat.parts.forEach((p) => p.colours.forEach(([c]) => n.set(c, (n.get(c) || 0) + 1)));
  const ids = [...n.keys()].sort((a, b) => n.get(b) - n.get(a) || cat.colours[a][0].localeCompare(cat.colours[b][0]));
  colourOk = new Set(ids);
  $("colour_list").innerHTML = ids.map((c) => {
    const [name, rgb] = cat.colours[c];
    return `<label><input type="checkbox" value="${c}" checked><span class="swatch" style="background:${css(rgb)}"></span>` +
      `${esc(name)} <span class="muted">(${n.get(c)})</span></label>`;
  }).join("");
  const boxes = () => [...$("colour_list").querySelectorAll("input")];
  const update = () => {
    colourOk = new Set(boxes().filter((b) => b.checked).map((b) => Number(b.value)));
    const names = [...colourOk].map((c) => cat.colours[c][0]);
    $("colours_text").textContent = colourOk.size === ids.length ? "all" : colourOk.size === 0 ? "none"
      : colourOk.size <= 3 ? names.join(", ") : `${colourOk.size} of ${ids.length}`;
    filtersChanged();
  };
  $("colour_list").addEventListener("change", update);
  $("colours_all").addEventListener("click", () => { boxes().forEach((b) => (b.checked = true)); update(); });
  $("colours_none").addEventListener("click", () => { boxes().forEach((b) => (b.checked = false)); update(); });
  $("known").addEventListener("change", filtersChanged);
}

function pickColour(part) {
  // one of the colours this part is really made in (common ones more often), among those ticked
  const options = coloursOf(part), total = options.reduce((s, [, w]) => s + w, 0);
  let r = Math.random() * total;
  for (const [c, w] of options) if ((r -= w) <= 0) return c;
  return options[options.length - 1][0];
}

function maybeSpawn() {
  // the next piece as soon as there's room behind the last one (as conveyor.maybe_spawn)
  if (swapping) return;
  if (machine.since >= M.refresh_after || !machine.pieces.some((p) => allowed(p.part))) {
    if (!machine.onBelt()) nextPool();   // a fresh set once the belt has run empty
    return;
  }
  if (nextSlot === null) {
    const free = machine.pieces.map((p, k) => k).filter((k) => machine.pieces[k].state === "parked" && allowed(machine.pieces[k].part));
    if (!free.length) return;
    nextSlot = free[Math.floor(Math.random() * free.length)];
    nextGap = M.spacing_min + Math.min(-Math.log(1 - Math.random()) * M.spacing_extra, 4 * M.spacing_extra);
  }
  const p = machine.pieces[nextSlot];
  if (!machine.roomFor(p.r, nextGap)) return;
  const c = pickColour(p.part), [name, rgb] = cat.colours[c];
  machine.spawn(nextSlot, { name, rgb }, { part: p.part.id, colour: name, category: p.part.category, known: p.part.known });
  nextSlot = null;
}

// ------------------------------------------------------------------ the camera and the sorter
const clean = document.createElement("canvas");   // the latest camera picture, without boxes drawn on it
clean.width = clean.height = RES;
let lastBlobs = [], orders = [];

function photograph(blob) {
  // a square around the object, as sorter/detector.py crop(): longest side + 15%, from the full picture
  const cx = ((blob.x0 + blob.x1) / 2) * K, cy = ((blob.y0 + blob.y1) / 2) * K;
  const half = (longSide(blob) / 2 * 1.15 + 6) * K, c = document.createElement("canvas");
  c.width = c.height = Math.round(2 * half);
  const cg = c.getContext("2d");
  cg.fillStyle = "#000";
  cg.fillRect(0, 0, c.width, c.height);
  cg.drawImage(clean, cx - half, cy - half, 2 * half, 2 * half, 0, 0, c.width, c.height);
  return c;
}

function forModel(picture) {
  // the photo as the machine's own camera would have taken it (the model learned on those)
  if (K === 1) return picture;
  const c = document.createElement("canvas");
  c.width = c.height = Math.max(1, Math.round(picture.width / K));
  const cg = c.getContext("2d");
  cg.imageSmoothingQuality = "high";
  cg.drawImage(picture, 0, 0, c.width, c.height);
  return c;
}

// One request to brickognize.com at a time, at most one about every BRICKOGNIZE_GAP seconds. A piece
// that has reached the end of the belt while waiting isn't sent at all (it went to Rest: no answer in time).
let brickognizeQueue = Promise.resolve(), lastAsked = 0;
function askBrickognize(d) {
  const late = () => d.run !== run || machine.time > d.arriveAt;
  const turn = brickognizeQueue.then(async () => {
    if (late()) throw new Error("reached the end of the belt before its turn");
    const wait = lastAsked + BRICKOGNIZE_GAP * 1000 - performance.now();
    if (wait > 0) await new Promise((ok) => setTimeout(ok, wait));
    if (late()) throw new Error("reached the end of the belt before its turn");
    lastAsked = performance.now();
    return predictBrickognize(d.picture);
  });
  brickognizeQueue = turn.catch(() => {});
  return turn;
}

const MM_PER_STUD = 8, MM_PER_PLATE = 3.2;

function decide(blob, near) {
  // as machine.py _decide: one picture of the object (and anything too close to separate from it);
  // the answer comes later (the model or Brickognize take a moment), the belt keeps running meanwhile
  if (near.length > 1) blob = mergeAll(near);
  const mmPast = (blob.cx - M.machine_camera / 2) / pxPerMm;
  const d = { run, picture: photograph(blob), blob, truth: machine.pieceAt(blob.cx * K, blob.cy * K),
    arriveAt: machine.time + (M.belt_half_len * 100 - mmPast) / (M.speed * 100) };
  answer(d);
  return d;
}

async function answer(d) {
  const blob = d.blob, brickognize = modelChoice() === "brickognize";
  try {
    if (!brickognize && !session) throw new Error("no model");
    d.answer = brickognize ? await askBrickognize(d) : await predictMine(forModel(d.picture));
  } catch (e) {
    if (!/before its turn/.test(e.message)) console.error(e);
    d.answer = { parts: [], colours: [], categories: [], printed: null };
  }
  if (d.run !== run) return;
  const a = d.answer, part = a.parts[0], colour = a.colours[0], cat_ = a.categories[0];
  d.ready = true;
  [d.bin, d.reason] = part
    ? chooseBin(part.id, part.score, colour?.name || "?", colour?.score || 0, cat_?.name || "", cat_?.score || 0, a.printed)
    : [rules.rest_bin, brickognize ? "Brickognize couldn't be reached in time" : "no answer"];
  const rest = rules.rest_bin;
  const bigBits = blob.bits.filter((x) => x >= 0.2 * blob.area);
  if (d.bin !== rest && bigBits.length >= 2) [d.bin, d.reason] = [rest, `${bigBits.length} pieces lying close together`];
  const pr = part && facts.get(part.id);
  if (d.bin !== rest && pr?.length) {
    const diag = Math.hypot(pr.length * MM_PER_STUD, pr.width * MM_PER_STUD, pr.height * MM_PER_PLATE);
    if (longSide(blob) / pxPerMm > diag * 1.25 + 4) [d.bin, d.reason] = [rest, `too big to be one ${part.id}: pieces stuck together?`];
  }
  if (machine.time < d.arriveAt + 0.6) orders.push(d);   // the flap is told (if it isn't too late)
  check(d);
  showLast(d);
}

function binFor(t) {
  // as the desktop's flap: whatever reaches the end close to an announced time goes to that bin
  orders = orders.filter((o) => o.arriveAt > t - 5);
  let best = null;
  for (const o of orders) if (!best || Math.abs(o.arriveAt - t) < Math.abs(best.arriveAt - t)) best = o;
  if (best && Math.abs(best.arriveAt - t) < 0.6) { orders.splice(orders.indexOf(best), 1); return best; }
  return null;
}

function check(d) {
  // what the piece really was (only the simulation knows) against the guess
  const t = d.truth, a = d.answer;
  if (t && t.known && a.parts[0]) {
    score.known++;
    d.partOk = samePiece(a.parts[0].id, t.part);
    d.colourOk = sameColour(a.colours[0]?.name).toLowerCase() === sameColour(t.colour).toLowerCase();
    score.part += d.partOk;
    score.colour += d.colourOk;
  }
}

// ------------------------------------------------------------------ the guesses, one at a time
// Every guess is kept (the newest 200); ◀ ▶ step through them, "Latest guess" shows the newest and
// keeps following new ones.
const MAX_GUESSES = 200;
let guesses = [], shown = -1, following = true, viewer = null;

function showLast(d) {
  guesses.push({ picture: d.picture.toDataURL("image/png"), html: guessText(d), part: d.answer.parts[0]?.id,
    colour: d.answer.colours[0] });
  if (guesses.length > MAX_GUESSES) { guesses.shift(); shown--; }
  if (following) showGuess(guesses.length - 1);
  else updateNav();
}

function showGuess(i) {
  shown = i;
  const e = guesses[i];
  $("shot").hidden = !e;
  if (e) $("shot").src = e.picture;
  $("last").innerHTML = e ? e.html : "Nothing photographed yet.";
  $("last").classList.toggle("muted", !e);
  try {
    viewer ??= new Part3D($("part3d"), $("part3d_note"));
    if (e) viewer.show(e.part, e.colour?.rgb, /^trans/i.test(e.colour?.name || ""));
    else viewer.clear();
  } catch (err) {   // no WebGL, or three.js didn't load
    console.error(err);
    $("part3d_note").textContent = "3D view not available in this browser";
  }
  updateNav();
}

function updateNav() {
  $("prev").disabled = shown <= 0;
  $("next").disabled = shown < 0 || shown >= guesses.length - 1;
  $("latest").setAttribute("aria-pressed", String(following));
  $("guess_pos").textContent = !guesses.length ? "" : `Guess ${shown + 1} of ${guesses.length}` +
    (following ? " (following the newest)" : shown < guesses.length - 1 ? ` · ${guesses.length - 1 - shown} newer` : "");
}

$("prev").addEventListener("click", () => { following = false; if (shown > 0) showGuess(shown - 1); });
$("next").addEventListener("click", () => { following = false; if (shown < guesses.length - 1) showGuess(shown + 1); });
$("latest").addEventListener("click", () => { following = true; showGuess(guesses.length - 1); });


function guessText(d) {
  const a = d.answer, part = a.parts[0], colour = a.colours[0], t = d.truth;
  const truth = t ? `${t.part} ${t.colour}${t.known ? "" : " (a part the model doesn't know)"}` : "";
  const verdict = !t ? "" : d.partOk === undefined ? `It was ${esc(truth)}.`
    : d.partOk && d.colourOk ? `<span class="right">✓ Right: it was ${esc(truth)}.</span>`
    : `<span class="wrong">✗ It was ${esc(truth)}.</span>`;
  const name = part ? `${part.id} ${esc(part.name || "")}` : "no answer";
  return `<div class="bin">→ ${esc(d.bin)}</div><div>${esc(d.reason)}</div>` +
    (part ? `<div class="alt">Guess: ${name} · ${pct(part.score)}` +
      (colour ? `, <span class="swatch" style="background:${css(colour.rgb)}"></span>${esc(colour.name)} · ${pct(colour.score)}` : "") + "</div>" : "") +
    `<div>${verdict}</div>`;
}

function arrived(p) {
  // a piece reached the end of the belt: the flap sends it where it was told, else to Rest
  const o = binFor(machine.time), t = p.truth, rest = rules.rest_bin;
  const bin = o ? o.bin : rest, reason = o ? o.reason : "the camera missed it, or no answer in time";
  counts[bin] = (counts[bin] || 0) + 1;
  score.sorted++;
  const right = chooseBin(t.part, 1, t.colour, 1, t.category, 1)[0];
  let result = "";
  if (bin === right) { score.right++; result = "✓"; }
  else if (bin === rest) { score.rest++; result = "set aside"; }
  else { score.wrong++; result = `✗ should be ${right}`; }
  const li = document.createElement("li");
  li.textContent = `${t.part} ${t.colour} → ${bin}: ${reason}  ${result}`;
  $("log").prepend(li);
  while ($("log").children.length > 100) $("log").lastChild.remove();
  showScore();
}

function showScore() {
  showBins();
  if (!score.sorted) { $("score").innerHTML = "No pieces sorted yet."; return; }
  const p = (x) => `${x} (${Math.round((100 * x) / score.sorted)}%)`;
  const acc = score.known ? `<br>Model right about the part ${p2(score.part, score.known)}, the colour ${p2(score.colour, score.known)}` +
    " <span class=\"muted\">(pieces it knows)</span>" : "";
  $("score").innerHTML = `${score.sorted} pieces sorted<br>Right bin: ${p(score.right)}<br>` +
    `Set aside in ${esc(rules.rest_bin)}: ${p(score.rest)}<br>Wrong bin: ${p(score.wrong)}${acc}`;
}
const p2 = (x, n) => `${x}/${n} (${Math.round((100 * x) / n)}%)`;

function showBins() {
  $("bins").innerHTML = binNames().map((n, i) =>
    `<span class="bin_count"><span class="swatch" style="background:${BIN_COLOURS[i % BIN_COLOURS.length]}"></span>${esc(n)}: <b>${counts[n] || 0}</b></span>`).join("");
}

// ------------------------------------------------------------------ drawing
const decided = new Map();   // track id -> decision, for the boxes on the camera picture

function draw(frame) {
  if (frame) clean.getContext("2d").putImageData(frame, 0, 0);
  else clean.getContext("2d").putImageData(machine.photographBelt(), 0, 0);
  g.drawImage(clean, 0, 0);
  g.font = `${12 * K}px system-ui`; g.strokeStyle = "rgba(255,255,255,.7)"; g.lineWidth = K;
  g.beginPath(); g.moveTo(RES / 2, 0); g.lineTo(RES / 2, RES); g.stroke();
  for (const [id, b] of lastBlobs) {
    const box = [b.x0 * K, b.y0 * K, b.x1 * K, b.y1 * K], d = decided.get(id);
    if (d?.ready) drawTag(g, box, d.answer, 3 * K);   // after the guess: box in the guessed colour, "part colour"
    else { g.strokeStyle = "rgba(255,255,255,.85)"; g.lineWidth = 2 * K; g.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]); }
  }
  machine.drawOverview();
}

// ------------------------------------------------------------------ running
let then = 0;
function tick(now) {
  if (!running) return;
  const dt = Math.max(0, Math.min(0.1, (now - (then || now)) / 1000)) * Number($("speed").value);
  then = now;
  for (const p of machine.step(dt, M.speed)) arrived(p);
  maybeSpawn();
  const frame = machine.photographBelt();
  const blobs = detector.find(frame);
  for (const [b, near, ids] of tracker.step(blobs, pxPerMm)) {
    const d = decide(b, near);
    ids.forEach((id) => decided.set(id, d));
  }
  lastBlobs = tracker.tracked;
  for (const id of [...decided.keys()]) if (!tracker.tracks.has(id)) decided.delete(id);
  draw(frame);
  requestAnimationFrame(tick);
}

$("go").addEventListener("click", () => {
  running = !running;
  $("go").textContent = running ? "Pause" : "Start";
  then = 0;
  if (running) requestAnimationFrame(tick);
});
$("reset").addEventListener("click", () => {
  // start again at once: the belt and the bins emptied, the same set of pieces and settings;
  // keeps running if it was running
  run++;
  machine.pieces.forEach((p, k) => machine.hide(k));
  machine.since = 0;
  tracker = new Tracker(M.machine_camera);
  orders = []; lastBlobs = []; nextSlot = null;
  decided.clear();
  clearScore();
  showScore();
  $("log").replaceChildren();
  guesses = []; following = true;
  showGuess(-1);
  newDeck();
  draw(null);
});
$("back").addEventListener("click", (e) => {
  // back to the page you came from (keeps its place), or the start page when you came from elsewhere
  let same = false;
  try { same = new URL(document.referrer).origin === location.origin; } catch { /* no referrer */ }
  if (same && history.length > 1) { e.preventDefault(); history.back(); }
});
$("sure").addEventListener("input", () => {
  $("sure_text").textContent = `${$("sure").value}%`;
  if (rules) rules.confidence_needed = $("sure").value / 100;
});
document.querySelectorAll("input[name=model]").forEach((r) => r.addEventListener("change", () => {
  const bk = modelChoice() === "brickognize";
  $("sure").value = Math.round(100 * (bk ? rules.confidence_needed_brickognize : labels?.rules?.confidence_needed ?? 0.85));
  $("sure").dispatchEvent(new Event("input"));
}));
updateNav();
$("go").disabled = $("reset").disabled = true;
setup().then(() => ($("reset").disabled = !machine?.model));
