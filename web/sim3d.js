// The sorting machine, simulated live in the browser: the same MuJoCo physics as the desktop app's
// virtual sorting machine (bricksort/sorter/conveyor.py: the belt, its rails and covers, pieces as
// LDraw part models dropped onto the moving belt), drawn with three.js. The camera above the belt
// is a three.js camera with the same height and angle; its picture is what the sorter looks at.
//
// World units as on the desktop: 1 unit = 100 mm, +Z up, the belt runs towards +X, camera above x = 0.
"use strict";

const MUJOCO_URL = "https://cdn.jsdelivr.net/npm/@mujoco/mujoco@3.17.0/mujoco.js";
const TIMESTEP = 0.002;
const HIDDEN = [-40, 0];   // where pieces wait, out of sight, when they aren't on the belt
const LIGHT = 0.88;        // three.js lamps a little dimmer, so the camera picture matches the desktop's MuJoCo picture

class Machine3D {
  // m: catalogue.machine (sizes, belt, lamps), res: the camera picture's size in pixels
  constructor(m, beltImage, res, overviewCanvas) {
    this.m = m;
    this.res = res;
    this.slide = 2 * m.belt.span * Math.ceil((2 * m.belt_slide) / (2 * m.belt.span)) / 2;   // as conveyor.py
    this.pieces = [];          // slots: {part, file, geo, verts, mesh, state: parked/belt, truth, r}
    this.renderer = new THREE.WebGLRenderer({ canvas: overviewCanvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.target = new THREE.WebGLRenderTarget(res, res);
    this.pixels = new Uint8Array(res * res * 4);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0.75, 0.78, 0.82);
    this.buildStatic(beltImage);
  }

  async loadPhysics() {
    const load = (await import(MUJOCO_URL)).default;
    this.mj = await load();
  }

  // ---------------------------------------------------------------- the machine itself (drawn)
  buildStatic(beltImage) {
    const m = this.m, bl = m.belt_half_len, bw = m.belt_half_width, s = this.scene;
    // the lamps: spotlights above the belt, a little to one side (as conveyor.py), plus MuJoCo's
    // ambient light of 0.3; no light from the viewer
    s.add(new THREE.AmbientLight(0xffffff, 0.3));
    m.lamps.forEach((l, i) => {
      // (penumbra 1: the light fades from the middle of its cone outwards, close to MuJoCo's spot exponent 1)
      const light = new THREE.SpotLight(new THREE.Color(...l.rgb), l.power * LIGHT, 0, (70 * Math.PI) / 180, 1, 0);
      light.position.set(...l.pos);
      light.target.position.set(l.pos[0], l.pos[1] - l.pos[1] / Math.max(l.pos[2], 0.1), l.pos[2] - 1);
      if (i < 3) {
        light.castShadow = true;
        light.shadow.mapSize.set(2048, 2048);
        light.shadow.camera.near = 0.5;
        light.shadow.camera.far = 12;
        light.shadow.bias = -0.0004;
      }
      s.add(light, light.target);
    });
    // the belt: its surface picture moves with the belt (texture offset), the box itself stays put
    const tex = new THREE.Texture(beltImage);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.needsUpdate = true;
    this.beltTex = tex;
    const len = 2 * bl + 2 * this.slide + 0.2, period = 2 * m.belt.span;
    tex.repeat.set(len / period, (2 * bw) / period);
    const beltMat = new THREE.MeshPhongMaterial({ map: tex, specular: new THREE.Color().setScalar(m.belt.specular),
      shininess: Math.max(1, m.belt.shininess * 128) });
    const beltBox = new THREE.Mesh(new THREE.BoxGeometry(len, 2 * bw, 0.04), beltMat);
    beltBox.position.set(0, 0, -0.02);
    beltBox.receiveShadow = true;
    s.add(beltBox);
    const grey = (v) => new THREE.MeshPhongMaterial({ color: new THREE.Color(v, v, v + 0.02), specular: 0x333333, shininess: 40 });
    const box = (size, pos, mat, onCamera = true) => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
      b.position.set(...pos);
      b.castShadow = b.receiveShadow = true;
      if (!onCamera) b.layers.set(1);   // the camera's own stand: the camera doesn't see it
      s.add(b);
      return b;
    };
    const cover = 2 * this.slide + 0.15;
    box([cover, 2 * (bw + 0.03), 0.18], [-bl - cover / 2, 0, 0.06], grey(0.22));
    box([cover, 2 * (bw + 0.03), 0.18], [bl + cover / 2, 0, 0.06], grey(0.22));
    box([2 * bl, 0.02, 0.1], [0, bw + 0.01, 0.03], grey(0.3));
    box([2 * bl, 0.02, 0.1], [0, -bw - 0.01, 0.03], grey(0.3));
    box([2 * bl * 0.9, 2 * bw * 0.7, 0.54], [0, 0, -0.33], grey(0.35));
    const H = m.camera_height;
    box([0.03, 0.03, H + 0.6], [0, -bw - 0.12, H / 2], grey(0.2), false);
    box([0.03, bw + 0.12, 0.03], [0, (-bw - 0.12) / 2, H + 0.06], grey(0.2), false);
    box([0.14, 0.1, 0.08], [0, 0, H + 0.06], grey(0.15), false);
    // the floor (a light checker) and the bins at the end of the belt (only drawn: as on the desktop,
    // a piece that reaches the end is counted into its bin)
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const cg = c.getContext("2d");
    cg.fillStyle = "rgb(209,209,204)"; cg.fillRect(0, 0, 64, 64);
    cg.fillStyle = "rgb(191,191,186)"; cg.fillRect(0, 0, 32, 32); cg.fillRect(32, 32, 32, 32);
    const floorTex = new THREE.CanvasTexture(c);
    floorTex.wrapS = floorTex.wrapT = THREE.RepeatWrapping;
    floorTex.repeat.set(60, 60);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(120, 120), new THREE.MeshPhongMaterial({ map: floorTex }));
    floor.position.z = -0.6;
    floor.receiveShadow = true;
    s.add(floor);
    this.binGroup = new THREE.Group();
    s.add(this.binGroup);
    // the cameras: the sorter's camera straight down; the overview from the front left
    this.cam = new THREE.PerspectiveCamera(m.fovy, 1, 0.01, 200);
    this.cam.position.set(0, 0, H);
    this.cam.up.set(0, 1, 0);
    this.cam.lookAt(0, 0, 0);
    this.view = new THREE.PerspectiveCamera(55, 16 / 9, 0.05, 200);
    this.view.position.set(-0.8, -5.4, 4.2);
    this.view.up.set(0, 0, 1);
    this.view.lookAt(bl * 0.55, 0, -0.3);
    this.view.layers.enable(1);
  }

  setBins(names, colours) {
    // the bins in a row across the end of the belt (as conveyor.py: 0.6 wide, 0.08 apart)
    this.binGroup.clear();
    const W = 0.6, GAP = 0.08, n = names.length, span = n * W + (n - 1) * GAP;
    const x = this.m.belt_half_len + 2 * this.slide + 0.55;
    names.forEach((name, i) => {
      const y = -span / 2 + W / 2 + i * (W + GAP);
      const mat = new THREE.MeshPhongMaterial({ color: colours[i % colours.length] });
      const parts = [[[W, W, 0.02], [0, 0, 0]], [[0.024, W, 0.24], [W / 2, 0, 0.12]], [[0.024, W, 0.24], [-W / 2, 0, 0.12]],
        [[W, 0.024, 0.24], [0, W / 2, 0.12]], [[W, 0.024, 0.24], [0, -W / 2, 0.12]]];
      for (const [size, pos] of parts) {
        const b = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
        b.position.set(x + pos[0], y + pos[1], -0.6 + pos[2]);
        b.receiveShadow = true;
        this.binGroup.add(b);
      }
    });
  }

  // ---------------------------------------------------------------- the physics world
  // build(slots): slots = [{part, colours, geo (three.js geometry, world units), verts (Float32Array)}]
  build(slots) {
    for (const p of this.pieces) this.scene.remove(p.mesh);
    if (this.data) { this.data.delete(); this.model.delete(); }
    const m = this.m, bl = m.belt_half_len, bw = m.belt_half_width, f = (a) => Array.from(a, (v) => +v.toFixed(5)).join(" ");
    const assets = [], bodies = [];
    slots.forEach((p, k) => {
      assets.push(`<mesh name="m${k}" vertex="${f(p.verts)}" face="${p.faces.join(" ")}" inertia="convex"/>`);
      bodies.push(`<body name="p${k}" pos="${HIDDEN[0]} ${HIDDEN[1] + k * 2} 0.3"><freejoint/>` +
        `<geom name="g${k}" type="mesh" mesh="m${k}" density="1000" friction="0.8 0.01 0.002" condim="6" solref="0.004 1"/></body>`);
    });
    const xml = `<mujoco><option timestep="${TIMESTEP}"/><asset>${assets.join("")}</asset><worldbody>
      <geom name="floor" type="plane" pos="0 0 -0.6" size="60 60 0.1"/>
      <body name="beltbody" pos="0 0 -0.02"><joint name="beltslide" type="slide" axis="1 0 0"/>
        <geom name="belt" type="box" size="${bl + this.slide + 0.1} ${bw} 0.02" density="100000" friction="1.0"/></body>
      <geom name="rail1" type="box" pos="0 ${bw + 0.01} 0.03" size="${bl} 0.01 0.05"/>
      <geom name="rail2" type="box" pos="0 ${-bw - 0.01} 0.03" size="${bl} 0.01 0.05"/>
      ${bodies.join("")}</worldbody></mujoco>`;
    const mj = this.mj;
    this.model = mj.MjModel.from_xml_string(xml);
    this.data = new mj.MjData(this.model);
    const id = (type, name) => mj.mj_name2id(this.model, mj.mjtObj[type].value, name);
    const bj = id("mjOBJ_JOINT", "beltslide");
    this.beltQ = this.model.jnt_qposadr[bj];
    this.beltV = this.model.jnt_dofadr[bj];
    this.pieces = slots.map((p, k) => {
      const body = id("mjOBJ_BODY", `p${k}`), jnt = this.model.body_jntadr[body];
      const mat = new THREE.MeshPhongMaterial({ color: 0x888888, specular: new THREE.Color().setScalar(0.4),
        shininess: 0.85 * 128, flatShading: true });
      const mesh = new THREE.Mesh(p.geo, mat);
      mesh.castShadow = mesh.receiveShadow = true;
      mesh.matrixAutoUpdate = false;
      mesh.visible = false;
      this.scene.add(mesh);
      return { ...p, body, q: this.model.jnt_qposadr[jnt], v: this.model.jnt_dofadr[jnt], mesh, state: "parked",
        truth: null, r: p.radius };
    });
    this.mj.mj_forward(this.model, this.data);
    this.since = 0;
  }

  place(k, pos, quat) {
    const p = this.pieces[k], q = this.data.qpos, v = this.data.qvel;
    let n = Math.hypot(...quat);
    q[p.q] = pos[0]; q[p.q + 1] = pos[1]; q[p.q + 2] = pos[2];
    for (let i = 0; i < 4; i++) q[p.q + 3 + i] = quat[i] / n;
    for (let i = 0; i < 6; i++) v[p.v + i] = 0;
  }

  hide(k) {
    const p = this.pieces[k];
    this.place(k, [HIDDEN[0], HIDDEN[1] + k * 2, 0], [1, 0, 0, 0]);
    p.mesh.visible = false;
    p.state = "parked";
  }

  // a piece onto the start of the belt, at a random spot across it, turned any way, as conveyor.spawn
  spawn(k, colour, truth) {
    const p = this.pieces[k], m = this.m;
    const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
    const x = -m.belt_half_len + 0.2 + p.r, room = Math.max(0, m.belt_half_width - p.r - 0.05);
    this.place(k, [x, (Math.random() * 2 - 1) * room * 0.85, 0.05 + p.r], [gauss(), gauss(), gauss(), gauss()]);
    const clear = /^trans/i.test(colour.name);
    p.mesh.material.color.setRGB(...colour.rgb.map((c) => c / 255));
    p.mesh.material.transparent = clear;
    p.mesh.material.opacity = clear ? 0.55 : 1;
    p.mesh.material.needsUpdate = true;
    p.mesh.visible = true;
    p.state = "belt";
    p.truth = truth;
    this.since++;
  }

  // the belt's start is free: every piece on it at least gap behind where the new one would go
  roomFor(r, gap) {
    const xNew = -this.m.belt_half_len + 0.2 + r;
    for (const p of this.pieces) {
      if (p.state !== "belt") continue;
      if (this.backEnd(p) < xNew + r + gap) return false;
    }
    return true;
  }

  backEnd(p) {
    // the piece's back end along the belt, from the corners of its box as it lies now
    const x = this.data.xpos[3 * p.body], R = this.data.xmat.subarray(9 * p.body, 9 * p.body + 9);
    let lo = Infinity;
    for (const c of p.corners) lo = Math.min(lo, x + R[0] * c[0] + R[1] * c[1] + R[2] * c[2]);
    return lo;
  }

  get time() { return this.data.time; }
  onBelt() { return this.pieces.filter((p) => p.state === "belt").length; }

  // advance the world by `seconds`; returns the pieces that reached the end of the belt
  step(seconds, speed) {
    const n = Math.round(seconds / TIMESTEP), out = [], q = this.data.qpos, mj = this.mj;
    for (let i = 0; i < n; i++) {
      if (q[this.beltQ] > this.slide) q[this.beltQ] -= 2 * this.slide;   // the belt jumps back unseen
      this.data.qvel[this.beltV] = speed;
      if (i % 4 === 0) {
        this.pieces.forEach((p, k) => {
          if (p.state !== "belt") return;
          if (q[p.q] > this.m.belt_half_len) { out.push(p); this.hide(k); }
          else if (q[p.q + 2] < -0.3) this.hide(k);   // fell off somewhere: put away
        });
      }
      const t = this.data.time;
      mj.mj_step(this.model, this.data);
      if (this.data.time < t) {   // the physics broke down (jammed pieces): take them off, keep the clock
        this.pieces.forEach((p, k) => this.hide(k));
        this.data.time = t + TIMESTEP;
        mj.mj_forward(this.model, this.data);
      }
    }
    return out;
  }

  // what's really at this spot of the camera picture (only a simulation knows this)
  pieceAt(xPx, yPx) {
    const ppu = this.res / (2 * this.m.camera_height * Math.tan((this.m.fovy / 2) * Math.PI / 180));
    const x = (xPx - this.res / 2) / ppu, y = -(yPx - this.res / 2) / ppu;
    let best = null, dist = 0.25;
    for (const p of this.pieces) {
      if (p.state !== "belt") continue;
      const d = Math.hypot(this.data.qpos[p.q] - x, this.data.qpos[p.q + 1] - y);
      if (d < dist) { best = p; dist = d; }
    }
    return best?.truth || null;
  }

  // ---------------------------------------------------------------- drawing
  sync() {
    const xp = this.data.xpos, xm = this.data.xmat, M = new THREE.Matrix4();
    for (const p of this.pieces) {
      if (!p.mesh.visible) continue;
      const b = p.body, R = xm.subarray(9 * b, 9 * b + 9);
      M.set(R[0], R[1], R[2], xp[3 * b], R[3], R[4], R[5], xp[3 * b + 1], R[6], R[7], R[8], xp[3 * b + 2], 0, 0, 0, 1);
      p.mesh.matrix.copy(M);
    }
    this.beltTex.offset.x = -this.data.qpos[this.beltQ] / (2 * this.m.belt.span);
  }

  // the camera's picture: rendered, then read back (RGBA, top row first) for the sorter to look at
  photographBelt() {
    this.sync();
    const r = this.renderer;
    r.setRenderTarget(this.target);
    r.render(this.scene, this.cam);
    r.readRenderTargetPixels(this.target, 0, 0, this.res, this.res, this.pixels);
    r.setRenderTarget(null);
    const w = this.res * 4, out = new Uint8ClampedArray(this.pixels.length);   // WebGL rows are bottom first
    for (let y = 0; y < this.res; y++) out.set(this.pixels.subarray((this.res - 1 - y) * w, (this.res - y) * w), y * w);
    return new ImageData(out, this.res, this.res);
  }

  drawOverview() {
    this.renderer.render(this.scene, this.view);
  }

  // empty belt pictures at different belt positions, so the piece finder learns the bare belt
  emptyFrames(n = 24) {
    const hidden = this.pieces.map((p) => p.mesh.visible);
    this.pieces.forEach((p) => (p.mesh.visible = false));
    const q = this.data.qpos, keep = q[this.beltQ], frames = [];
    for (let k = 0; k < n; k++) {
      q[this.beltQ] = -this.slide + (2 * this.slide * k) / Math.max(n - 1, 1);
      frames.push(this.photographBelt());
    }
    q[this.beltQ] = keep;
    this.pieces.forEach((p, i) => (p.mesh.visible = hidden[i]));
    return frames;
  }
}

// a part's .bin file (see bricksort/export_parts3d.py) -> what the machine needs: the three.js
// geometry and the physics mesh, in world units (1 = 100 mm), +Z up
function partShape(buf) {
  const head = new DataView(buf), nv = head.getUint32(0, true), nf = head.getUint32(4, true);
  const scale = head.getFloat32(8, true) / 100;
  const q = new Int16Array(buf, 12, nv * 3), verts = new Float32Array(nv * 3);
  for (let i = 0; i < nv * 3; i++) verts[i] = q[i] * scale;
  const start = 12 + nv * 6 + ((4 - ((nv * 6) % 4)) % 4);
  const faces = nv < 65536 ? new Uint16Array(buf, start, nf * 3) : new Uint32Array(buf, start, nf * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(verts, 3));
  geo.setIndex(new THREE.BufferAttribute(faces, 1));
  geo.computeBoundingBox();
  const { min, max } = geo.boundingBox, corners = [];
  for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) corners.push([x, y, z]);
  const radius = max.clone().sub(min).length() / 2;
  return { geo, verts, faces: Array.from(faces), corners, radius };
}
