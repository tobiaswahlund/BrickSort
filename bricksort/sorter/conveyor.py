"""A virtual conveyor belt with a camera and a row of bins, built in the physics engine.

It provides the same Clock / Camera / Belt / Diverter pieces as real hardware
would (see hardware.py), so the sorting logic can't tell the difference.

World units: 1 unit = 100 mm real size (the parts are modelled 10x, see ldraw.py).
"""
import numpy as np
import mujoco

from .. import belts, config, junk, machine_setup
from ..belts import BELTS, DEFAULT_BELT
from ..render import real_colors
from ..scene import _fmt, close_renderer
from . import hardware

MM_PER_UNIT = 100.0
BELT_HALF_LEN, BELT_HALF_WIDTH = 2.0, 0.75   # wide enough for big plates (a 2x16 plate is 128 mm)
CAM_RES, FOVY = 720, 45.0
CAM_H = machine_setup.camera_height()      # 2.1 (210 mm) sees the whole belt width; see machine_setup
OVERVIEW = (960, 540)   # rendered this big so it still looks sharp in a maximised window
POOL = 40                 # different pieces in the world at once (38 Lego + 2 non-Lego)...
REFRESH_AFTER = 60        # ...swapped for a new random set after this many pieces, so it keeps changing
MAX_PIECE = 1.4           # longest piece (units) that fits on the belt
BIN_W, BIN_GAP = 0.6, 0.08
HIDDEN = (-40.0, 0.0)     # where pieces wait (invisible) when not on the belt
SPACING_MIN = 0.4         # free belt between two pieces: at least 40 mm (the flap needs 10 mm, pieces roll a bit)...
SPACING_EXTRA = 0.3       # ...plus up to 30 mm extra at random, so it doesn't look machine-perfect
BELT_SLIDE = 0.2          # the belt really moves this far, then quietly jumps back (it looks endless)
BELT_RGB = (0.47, 0.69, 0.55)   # mint green: stands out from most Lego colours


class SimClock(hardware.Clock):
    def __init__(self, world):
        self.world = world

    def now(self):
        return self.world.data.time


class SimCamera(hardware.Camera):
    def __init__(self, world):
        self.world = world
        view_mm = 2 * CAM_H * np.tan(np.radians(FOVY / 2)) * MM_PER_UNIT
        self.px_per_mm = CAM_RES / view_mm
        self.belt_direction = +1

    def frame(self):
        return self.world.render("cam")


class SimBelt(hardware.Belt):
    def __init__(self, world):
        self.world = world
        self.speed_mm_s = world.speed * MM_PER_UNIT
        self.camera_to_end_mm = BELT_HALF_LEN * MM_PER_UNIT


class SimDiverter(hardware.Diverter):
    """Like a real flap: whatever reaches the end close to the announced time goes to that bin."""

    def __init__(self, world, rest_bin):
        self.world, self.rest_bin = world, rest_bin
        self.orders = []          # [(arrive_at, bin)]

    def send(self, bin_name, arrive_at):
        self.orders.append((arrive_at, bin_name))

    def bin_for(self, t, tolerance=0.6):
        self.orders = [o for o in self.orders if o[0] > t - 5]
        best = min(self.orders, key=lambda o: abs(o[0] - t), default=None)
        if best and abs(best[0] - t) < tolerance:
            return best[1]
        return self.rest_bin      # nobody announced it: the camera missed it


class NoPieces(Exception):
    """None of the chosen pieces can be put on the belt."""


SPAWN_TRAINED, SPAWN_ALL = "Pieces the model knows", "All LEGO pieces"
SPAWN_CHOSEN = "Choose pieces…"

def _tile(name):
    """The belt picture, 2x2 copies in one tile (it wraps around without seams, see belts.py).
    The tile is 2 x span long, which is the pattern length the belt's jump-back relies on."""
    from PIL import Image, ImageOps
    src = belts.path(name)
    out = config.BIG_DIR / "belt_tiles" / src.name
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        out.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src).convert("RGB")
        w, h = img.size
        tile = Image.new("RGB", (2 * w, 2 * h))
        # a photo doesn't wrap around by itself: mirrored copies meet without a visible seam
        photo = belts.spec(name).get("photo")
        copies = (img, ImageOps.mirror(img), ImageOps.flip(img), ImageOps.flip(ImageOps.mirror(img))) if photo \
            else (img,) * 4
        for (x, y), copy in zip(((0, 0), (w, 0), (0, h), (w, h)), copies):
            tile.paste(copy, (x, y))
        tile.save(out)
    return out.as_posix()
RIG = ("camera_pole", "camera_arm", "camera_box")  # the camera's stand: shown, but casts no shadow


class ConveyorWorld:
    def __init__(self, lib, parts, colors, bin_names, rng, speed=0.22, all_parts=(), spawn_mode=SPAWN_TRAINED,
                 belt=None, chosen=()):
        self.lib, self.colors, self.rng, self.speed = lib, colors, rng, speed
        belt = belt or machine_setup.load()["belt"]   # your machine's belt (machine setup)
        self.belt_name = belt if belt in belts.available() else DEFAULT_BELT
        # The belt surface moves, and every so often jumps back by exactly a whole number of
        # pattern lengths, so the jump can't be seen: it looks like one endless, smooth belt.
        # (with texuniform, MuJoCo repeats the picture every 2 x span; measured: a shift of 2 x span
        #  gives an identical camera picture, any other shift doesn't)
        period = 2 * belts.spec(self.belt_name)["span"]
        self.slide = period * np.ceil(2 * BELT_SLIDE / period) / 2
        self.bin_names = list(bin_names)
        self.candidates = [p for p in parts if p["id"] != junk.NOT_LEGO and not p.get("custom")]  # need a 3D model
        self.known = {p["id"] for p in self.candidates}
        self.category_of = {p["id"]: p.get("category", "") for p in parts}
        # every Lego part with a 3D model (for "All pieces"); most the model doesn't know by number
        self.all_parts = list(all_parts or [])
        self.category_of.update({p["id"]: p["category"] for p in self.all_parts if p["id"] not in self.category_of})
        self.part_colors = {p["id"]: p.get("colors", []) for p in self.all_parts}
        self.part_colors.update({p["id"]: p.get("colors", []) for p in parts})
        self.spawn_mode = spawn_mode
        everything = {p["id"]: p for p in self.all_parts + self.candidates}
        self.chosen = [everything[i] for i in sorted(chosen) if i in everything]  # for "Pieces I choose"
        self.junk_chance, self.pair_chance = 0.0, 0.0
        self.spawn_every = 4.0
        self.renderers = {}
        self.build()

    # ---------------------------------------------------------- building the world
    def _pick_meshes(self):
        meshes = []
        pool = self.all_parts if self.spawn_mode == SPAWN_ALL and self.all_parts else self.candidates
        if self.spawn_mode == SPAWN_CHOSEN and self.chosen:
            pool = self.chosen
        # every piece once before any piece twice (matters for a short chosen list)
        order = [pool[i] for i in self.rng.permutation(len(pool))]
        unusable = set()   # no 3D model, too big for the belt or too detailed
        tries = 0
        while order and len(meshes) < POOL - 2 and tries < 1000 and len(unusable) < len(order):
            part = order[tries % len(order)]
            tries += 1
            if part["id"] in unusable:
                continue
            try:
                v, f = self.lib.part_mesh(part["id"])
            except Exception:
                unusable.add(part["id"])
                continue
            if (v.max(0) - v.min(0)).max() > MAX_PIECE or len(f) > 60000:
                unusable.add(part["id"])
                continue
            meshes.append((part["id"], (v, f)))
        if not meshes:
            raise NoPieces("None of these pieces can go on the belt (no 3D model, or too big). "
                           "Choose other pieces.")
        for _ in range(2):   # always a couple of non-Lego objects in the pool
            meshes.append(("junk", junk.random_mesh(self.rng, self.rng.uniform(0.06, 0.18))))
        return meshes

    def build(self):
        for r in self.renderers.values():
            close_renderer(r)
        self.meshes = self._pick_meshes()
        n_bins = len(self.bin_names)
        bins_x = BELT_HALF_LEN + 2 * self.slide + 0.55
        span = n_bins * BIN_W + (n_bins - 1) * BIN_GAP
        self.bin_y = [-span / 2 + BIN_W / 2 + i * (BIN_W + BIN_GAP) for i in range(n_bins)]
        self.bins_x = bins_x
        assets, bodies, bins = [], [], []
        for k, (pid, (v, f)) in enumerate(self.meshes):
            assets.append(f'<mesh name="m{k}" vertex="{_fmt(v)}" face="{_fmt(f)}" inertia="convex"/>')
            bodies.append(f'<body name="p{k}" pos="{HIDDEN[0]} {HIDDEN[1] + k * 2} 0.3"><freejoint/>'
                          f'<geom name="g{k}" type="mesh" mesh="m{k}" rgba="0.5 0.5 0.5 0" density="1000" '
                          f'friction="0.8 0.01 0.002" condim="6" solref="0.004 1" material="plastic"/></body>')
        palette = [(0.85, 0.35, 0.3), (0.3, 0.55, 0.85), (0.95, 0.75, 0.25), (0.45, 0.75, 0.4),
                   (0.7, 0.45, 0.8), (0.95, 0.55, 0.2), (0.4, 0.8, 0.8), (0.6, 0.6, 0.6), (0.3, 0.3, 0.3)]
        for i, y in enumerate(self.bin_y):
            c = palette[i % len(palette)]
            hw, wall = BIN_W / 2, 0.012
            bins.append(f"""
    <body name="bin{i}" pos="{bins_x} {y} -0.6">
      <geom type="box" size="{hw} {hw} 0.01" rgba="{c[0]} {c[1]} {c[2]} 1"/>
      <geom type="box" pos="{hw} 0 0.12" size="{wall} {hw} 0.12" rgba="{c[0]} {c[1]} {c[2]} 1"/>
      <geom type="box" pos="{-hw} 0 0.12" size="{wall} {hw} 0.12" rgba="{c[0]} {c[1]} {c[2]} 1"/>
      <geom type="box" pos="0 {hw} 0.12" size="{hw} {wall} 0.12" rgba="{c[0]} {c[1]} {c[2]} 1"/>
      <geom type="box" pos="0 {-hw} 0.12" size="{hw} {wall} 0.12" rgba="{c[0]} {c[1]} {c[2]} 1"/>
    </body>""")
        bl, bw = BELT_HALF_LEN, BELT_HALF_WIDTH
        belt = belts.spec(self.belt_name)
        # they point down and towards the belt's middle line; shadows from the three strongest at most
        lamps = "\n".join(
            f'<light name="lamp{i}" pos="{p[0]:.3f} {p[1]:.3f} {p[2]:.3f}" dir="0 {-p[1] / max(p[2], 0.1):.3f} -1" '
            f'diffuse="{power * c[0]:.3f} {power * c[1]:.3f} {power * c[2]:.3f}" specular="0.3 0.3 0.3" '
            f'cutoff="70" exponent="1" castshadow="{"true" if i < 3 else "false"}"/>'
            for i, (p, power, c) in enumerate(machine_setup.lamps(spread=bl * 0.6)))
        xml = f"""
<mujoco>
  <option timestep="0.002"/>
  <visual>
    <global offwidth="{max(CAM_RES, OVERVIEW[0])}" offheight="{max(CAM_RES, OVERVIEW[1])}"/>
    <map znear="0.01" zfar="200"/>
    <quality shadowsize="2048"/>
    <!-- no light attached to the viewer: the scene is lit only by the fixed lamps above the belt -->
    <headlight ambient="0.3 0.3 0.3" diffuse="0 0 0" specular="0 0 0"/>
  </visual>
  <asset>
    <texture name="floor" type="2d" builtin="checker" rgb1="0.82 0.82 0.8" rgb2="0.75 0.75 0.73" width="256" height="256"/>
    <material name="floor" texture="floor" texrepeat="8 8"/>
    <material name="plastic" specular="0.4" shininess="0.85"/>
    <texture name="belt" type="2d" file="{_tile(self.belt_name)}"/>
    <material name="belt" texture="belt" texuniform="true" texrepeat="{1 / belt['span']:.4f} {1 / belt['span']:.4f}"
              specular="{belt['specular']}" shininess="{belt['shininess']}" reflectance="{belt['reflectance']}"/>
    {"".join(assets)}
  </asset>
  <worldbody>
    <!-- the lamps of your machine setup, above the belt and a little to one side so shadows show -->
    {lamps}
    <geom name="floor" type="plane" pos="0 0 -0.6" size="60 60 0.1" material="floor"/>
    <body name="beltbody" pos="0 0 -0.02">
      <joint name="beltslide" type="slide" axis="1 0 0"/>
      <geom name="belt" type="box" size="{bl + self.slide + 0.1} {bw} 0.02" density="100000"
            material="belt" friction="1.0"/>
    </body>
    <!-- covers over both ends of the belt, where a real belt turns around its rollers
         (they also hide the belt's ends, so the belt looks endless) -->
    <geom name="cover1" type="box" pos="{-bl - (2 * self.slide + 0.15) / 2} 0 0.06" size="{(2 * self.slide + 0.15) / 2} {bw + 0.03} 0.09"
          rgba="0.22 0.22 0.24 1" contype="0" conaffinity="0"/>
    <geom name="cover2" type="box" pos="{bl + (2 * self.slide + 0.15) / 2} 0 0.06" size="{(2 * self.slide + 0.15) / 2} {bw + 0.03} 0.09"
          rgba="0.22 0.22 0.24 1" contype="0" conaffinity="0"/>
    <geom name="rail1" type="box" pos="0 {bw + 0.01} 0.03" size="{bl} 0.01 0.05" rgba="0.3 0.3 0.32 1"/>
    <geom name="rail2" type="box" pos="0 {-bw - 0.01} 0.03" size="{bl} 0.01 0.05" rgba="0.3 0.3 0.32 1"/>
    <geom name="legs" type="box" pos="0 0 -0.33" size="{bl * 0.9} {bw * 0.7} 0.27" rgba="0.35 0.35 0.38 1"
          contype="0" conaffinity="0"/>
    <camera name="cam" pos="0 0 {CAM_H}" xyaxes="1 0 0 0 1 0" fovy="{FOVY}"/>
    <body name="look" pos="{bl * 0.55} 0 -0.3"/>
    <camera name="overview" pos="-0.8 -5.4 4.2" mode="targetbody" target="look" fovy="55"/>
    <geom name="camera_pole" type="box" pos="0 {-bw - 0.12} {CAM_H / 2}" size="0.015 0.015 {CAM_H / 2 + 0.3}"
          rgba="0.2 0.2 0.22 1" contype="0" conaffinity="0" group="1"/>
    <geom name="camera_arm" type="box" pos="0 {(-bw - 0.12) / 2} {CAM_H + 0.06}" size="0.015 {(bw + 0.12) / 2} 0.015"
          rgba="0.2 0.2 0.22 1" contype="0" conaffinity="0" group="1"/>
    <geom name="camera_box" type="box" pos="0 0 {CAM_H + 0.06}" size="0.07 0.05 0.04" rgba="0.15 0.15 0.15 1"
          contype="0" conaffinity="0" group="1"/>
    {"".join(bins)}
    {"".join(bodies)}
  </worldbody>
</mujoco>"""
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.belt_joint = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "beltslide")
        self.body_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"p{k}") for k in range(len(self.meshes))]
        self.geom_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, f"g{k}") for k in range(len(self.meshes))]
        self.state = ["parked"] * len(self.meshes)      # parked / belt / binned
        self.truth = [None] * len(self.meshes)          # (part, colour name) of what's on each slot
        self.binned_at = [0.0] * len(self.meshes)
        self.last_spawn = -10.0
        self.spawned = getattr(self, "spawned", 0)
        self.since_build = 0
        mujoco.mj_forward(self.model, self.data)
        self.renderers = {"cam": mujoco.Renderer(self.model, CAM_RES, CAM_RES),
                          "overview": mujoco.Renderer(self.model, OVERVIEW[1], OVERVIEW[0])}
        # the camera must not see its own housing
        self.cam_opt = mujoco.MjvOption()
        self.cam_opt.geomgroup[1] = 0
        self.rig_geoms = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, n) for n in RIG]

    def close(self):
        for r in self.renderers.values():
            close_renderer(r)
        self.renderers = {}

    # ---------------------------------------------------------- running it
    def _qadr(self, k):
        return self.model.jnt_qposadr[self.model.body_jntadr[self.body_ids[k]]]

    def _vadr(self, k):
        return self.model.jnt_dofadr[self.model.body_jntadr[self.body_ids[k]]]

    def _place(self, k, pos, quat=None):
        a, v = self._qadr(k), self._vadr(k)
        q = self.rng.normal(size=4) if quat is None else quat
        self.data.qpos[a:a + 3] = pos
        self.data.qpos[a + 3:a + 7] = q / np.linalg.norm(q)
        self.data.qvel[v:v + 6] = 0

    def _free_slot(self, want_junk):
        options = [k for k in range(len(self.meshes)) if self.state[k] == "parked" and (self.meshes[k][0] == "junk") == want_junk]
        return options[self.rng.integers(len(options))] if options else None

    def _hide(self, k):
        """Take a piece out of the world (it 'vanishes' into its bin): invisible and far away."""
        self._place(k, [HIDDEN[0], HIDDEN[1] + k * 2, 0.0])
        self.model.geom_rgba[self.geom_ids[k], 3] = 0
        self.state[k] = "parked"

    def piece_at(self, x_px, y_px):
        """What's really at this spot of the camera picture (only the simulation can know this)."""
        px_per_unit = CAM_RES / (2 * CAM_H * np.tan(np.radians(FOVY / 2)))
        x, y = (x_px - CAM_RES / 2) / px_per_unit, -(y_px - CAM_RES / 2) / px_per_unit
        best, dist = None, 0.25
        for k in range(len(self.meshes)):
            if self.state[k] != "belt":
                continue
            a = self._qadr(k)
            d = np.hypot(self.data.qpos[a] - x, self.data.qpos[a + 1] - y)
            if d < dist:
                best, dist = k, d
        return self.truth[best] if best is not None else None

    def _radius(self, k):
        v = self.meshes[k][1][0]
        return float(np.linalg.norm(v.max(0) - v.min(0)) / 2)

    def _room_for(self, r_new, gap):
        """Is the start of the belt free: every piece already on it at least `gap` past the new one?"""
        x_new = -BELT_HALF_LEN + 0.2 + r_new
        for k in range(len(self.meshes)):
            if self.state[k] == "belt":
                # the back end of that piece, as it lies now
                b = self.body_ids[k]
                pts = self.meshes[k][1][0] @ self.data.xmat[b].reshape(3, 3).T + self.data.xpos[b]
                if pts[:, 0].min() < x_new + r_new + gap:
                    return False
        return True

    def spawn(self, x=None, y=None, k=None, z=None):
        if k is None:
            k = self._free_slot(self.rng.random() < self.junk_chance)
        if k is None:
            return None
        pid = self.meshes[k][0]
        if pid == "junk":
            rgb, cname = np.array(junk.random_color(self.rng)) / 255, "-"
            pid = junk.NOT_LEGO
        else:
            # only colours this part really comes in (as in training)
            ids, w = real_colors({"id": pid, "colors": self.part_colors.get(pid, [])}, self.colors)
            cid = ids[self.rng.choice(len(ids), p=w)]
            cname, rgb = self.colors[cid][0], np.array(self.colors[cid][1]) / 255
            if cname.startswith("Trans"):
                rgb = np.r_[rgb, 0.55]
        self.model.geom_rgba[self.geom_ids[k]] = [*rgb, 1] if len(rgb) == 3 else rgb
        v = self.meshes[k][1][0]
        r = float(np.linalg.norm(v.max(0) - v.min(0)) / 2)
        x = -BELT_HALF_LEN + 0.2 + r if x is None else x
        room = max(0.0, BELT_HALF_WIDTH - r - 0.05)
        y = self.rng.uniform(-room, room) * 0.85 if y is None else y   # anywhere across most of the belt
        self._place(k, [x, y, 0.05 + r if z is None else z + r])
        self.state[k] = "belt"
        self.truth[k] = (pid, cname, self.category_of.get(pid, "not lego"), pid in self.known)
        self.spawned += 1
        self.since_build += 1
        return k

    def maybe_spawn(self):
        """Put the next piece on the belt as soon as there's room: far enough behind the previous
        piece that the camera and flap see them as separate (unless 'two pieces together' says so)."""
        if self.since_build >= REFRESH_AFTER:  # time for a new random set of pieces
            if any(s == "belt" for s in self.state):
                return  # let the belt run empty first
            t = self.data.time
            self.build()
            self.data.time = t  # the clock keeps running (the sorter's timing depends on it)
            self._next = None
        if getattr(self, "_next", None) is None:  # choose the next piece and a random extra gap
            self._next = self._free_slot(self.rng.random() < self.junk_chance)
            # mostly short gaps, now and then a long one, like pieces trickling off a real feeder
            self._next_gap = SPACING_MIN + min(self.rng.exponential(SPACING_EXTRA), 4 * SPACING_EXTRA)
            if self._next is None:
                return
        if not self._room_for(self._radius(self._next), self._next_gap):
            return
        k, self._next = self.spawn(k=self._next), None
        self.last_spawn = self.data.time
        if k is not None and self.rng.random() < self.pair_chance:   # two pieces close together
            # dropped from just above the first piece (never inside it: overlapping pieces push each
            # other apart so hard that the physics breaks down)
            a = self._qadr(k)
            self.spawn(x=self.data.qpos[a] + self.rng.uniform(-0.12, 0.12),
                       y=self.data.qpos[a + 1] + self.rng.uniform(-0.12, 0.12),
                       z=self.data.qpos[a + 2] + self._radius(k) + 0.02)

    def step(self, diverter, n=33):
        """Advance the world by n physics steps. Returns [(slot, bin, truth)] for pieces that left the belt."""
        arrivals = []
        ba, bv = self.model.jnt_qposadr[self.belt_joint], self.model.jnt_dofadr[self.belt_joint]
        qadr = [self._qadr(k) for k in range(len(self.meshes))]
        for step in range(n):
            # the belt surface really moves (friction carries the pieces); now and then it
            # jumps back unnoticed so it never runs out
            if self.data.qpos[ba] > self.slide:   # jump back exactly one pattern length: looks seamless
                self.data.qpos[ba] -= 2 * self.slide
            self.data.qvel[bv] = self.speed
            if step % 4:  # checking every 4th step is plenty (pieces move < 2 mm in between)
                self._physics_step()
                continue
            for k in range(len(self.meshes)):
                if self.state[k] != "belt":
                    continue
                a = qadr[k]
                if self.data.qpos[a] > BELT_HALF_LEN:         # reached the end: the diverter decides
                    b = diverter.bin_for(self.data.time)
                    arrivals.append((k, b, self.truth[k]))
                    self._hide(k)                             # it drops into the bin and is counted
                elif self.data.qpos[a + 2] < -0.3:            # fell off somewhere: put it away
                    self._hide(k)
            self._physics_step()
        return arrivals

    def _physics_step(self):
        """One physics step. If the physics breaks down (pieces jammed into each other can make it
        blow up), MuJoCo starts the whole world over at time 0; then the pieces on the belt are taken
        off and the clock is put back, so the sorter's timing keeps working."""
        t = self.data.time
        mujoco.mj_step(self.model, self.data)
        if self.data.time < t:
            print(f"Physics became unstable at {t:.1f}s: the pieces on the belt were taken off.")
            for k in range(len(self.meshes)):
                self._hide(k)
            self.data.time = t + self.model.opt.timestep
            mujoco.mj_forward(self.model, self.data)

    def render(self, camera):
        r = self.renderers[camera]
        if camera == "cam":
            r.update_scene(self.data, camera=camera, scene_option=self.cam_opt)
            return r.render().copy()
        # Overview: draw the world without the camera stand (so the stand casts no shadow),
        # then paste the stand itself in from a second picture.
        r.update_scene(self.data, camera=camera, scene_option=self.cam_opt)
        img = r.render().copy()
        r.update_scene(self.data, camera=camera)
        with_rig = r.render().copy()
        r.enable_segmentation_rendering()
        seg = r.render()
        r.disable_segmentation_rendering()
        rig = np.isin(seg[:, :, 0], self.rig_geoms) & (seg[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM))
        img[rig] = with_rig[rig]
        return img

    def empty_belt_frames(self, n=24):
        """Pictures of the empty belt at different positions, so the piece finder learns what the
        (moving, textured) belt itself looks like."""
        ba = self.model.jnt_qposadr[self.belt_joint]
        frames = []
        for k in range(n):
            self.data.qpos[ba] = -self.slide + 2 * self.slide * k / max(n - 1, 1)
            mujoco.mj_forward(self.model, self.data)
            frames.append(self.render("cam"))
        self.data.qpos[ba] = 0
        mujoco.mj_forward(self.model, self.data)
        return frames
