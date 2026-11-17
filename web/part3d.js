// A 3D model of a guessed part, in the guessed colour, that you spin by dragging (three.js).
// The models are LDraw parts, turned into small files by bricksort/export_parts3d.py when the
// website is built: parts/index.json says which file each part number uses.
"use strict";

class Part3D {
  constructor(canvas, note) {
    this.canvas = canvas;
    this.note = note;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 1, 2000);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x666677, 0.75));
    const sun = new THREE.DirectionalLight(0xffffff, 0.7);
    sun.position.set(1, 2, 1.5);
    this.camera.add(sun);   // the light turns with the view, so the side you look at is lit
    this.scene.add(this.camera);
    this.spin = new THREE.Group();
    this.scene.add(this.spin);
    this.mesh = null;
    this.models = new Map();   // file -> geometry (or a promise of it)
    this.index = null;
    this.auto = true;          // turns slowly by itself until it's dragged
    this.wanted = null;
    this.drag();
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
    const loop = () => {
      if (this.auto && this.mesh) this.spin.rotation.y += 0.008;
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  resize() {
    const w = this.canvas.clientWidth || 200;
    this.renderer.setSize(w, w, false);
  }

  drag() {
    let at = null;
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => { at = [e.clientX, e.clientY]; this.auto = false; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", (e) => {
      if (!at) return;
      const [dx, dy] = [e.clientX - at[0], e.clientY - at[1]];
      at = [e.clientX, e.clientY];
      this.spin.rotation.y += dx * 0.01;
      this.spin.rotation.x = Math.max(-1.5, Math.min(1.5, this.spin.rotation.x + dy * 0.01));
    });
    const stop = () => (at = null);
    c.addEventListener("pointerup", stop);
    c.addEventListener("pointercancel", stop);
  }

  async file(partId) {
    if (!this.index) {
      this.index = fetch("parts/index.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
    }
    const index = await this.index;
    return index[partId] || index[partId.replace(/[a-z]+$/, "")] || null;
  }

  geometry(file) {
    if (!this.models.has(file)) {
      this.models.set(file, fetch("parts/" + file).then((r) => {
        if (!r.ok) throw new Error(`no ${file}`);
        return r.arrayBuffer();
      }).then(decode));
    }
    return this.models.get(file);
  }

  clear(text = "") {
    if (this.mesh) { this.spin.remove(this.mesh); this.mesh = null; }
    this.note.textContent = text;
  }

  // show(part id, [r,g,b], see-through?) — later calls win over earlier ones still loading
  async show(partId, rgb, clear = false) {
    const want = (this.wanted = {});
    if (!partId || partId === "not_lego" || partId === "multiple") return this.clear(partId ? "No single LEGO part to show" : "");
    this.note.textContent = "Loading the 3D model …";
    let geo = null;
    try {
      const file = await this.file(partId);
      if (file) geo = await this.geometry(file);
    } catch (e) { console.error(e); }
    if (want !== this.wanted) return;
    if (!geo) return this.clear(`No 3D model of ${partId} here`);
    this.clear();
    const colour = new THREE.Color(...(rgb || [160, 160, 160]).map((v) => v / 255));
    const mat = new THREE.MeshStandardMaterial({ color: colour, roughness: 0.35, metalness: 0, flatShading: true,
      transparent: clear, opacity: clear ? 0.6 : 1, side: THREE.DoubleSide });
    this.mesh = new THREE.Mesh(geo, mat);
    this.spin.add(this.mesh);
    if (this.auto) this.spin.rotation.set(0.5, 0.6, 0);
    const r = geo.boundingSphere.radius;
    this.camera.position.set(0, 0, r / Math.sin((this.camera.fov / 2) * Math.PI / 180) * 1.05);
    this.camera.near = r / 20;
    this.camera.far = r * 20;
    this.camera.updateProjectionMatrix();
  }
}

// a part's .bin file (see bricksort/export_parts3d.py) -> a three.js geometry, +Y up, in mm
function decode(buf) {
  const head = new DataView(buf), nv = head.getUint32(0, true), nf = head.getUint32(4, true), scale = head.getFloat32(8, true);
  const q = new Int16Array(buf, 12, nv * 3), pos = new Float32Array(nv * 3);
  for (let i = 0; i < nv; i++) {   // the file is +Z up; three.js is +Y up
    pos[3 * i] = q[3 * i] * scale;
    pos[3 * i + 1] = q[3 * i + 2] * scale;
    pos[3 * i + 2] = -q[3 * i + 1] * scale;
  }
  const start = 12 + nv * 6 + ((4 - ((nv * 6) % 4)) % 4);
  const idx = nv < 65536 ? new Uint16Array(buf, start, nf * 3) : new Uint32Array(buf, start, nf * 3);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeBoundingSphere();
  return geo;
}
