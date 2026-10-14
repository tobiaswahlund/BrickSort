"""The virtual world: a tray, one Lego part, physics, lights and a camera.

The part is dropped with a random spin so it lands in a random way, then a
camera takes a picture. The picture is cropped around the part, the same way
a real sorting machine would crop its camera image.

To make the model cope with real photos, the world is deliberately messy:
lights of different number, strength, colour and angle, matte-to-glossy
plastic, varied backgrounds, tilted camera angles, and (in messy.py) blur,
noise, colour casts, scratches and dirt.
"""
import numpy as np
import mujoco
from PIL import Image

from . import machine_setup, messy, surfaces
from . import wear as wear_mod

CAM_RES = 480
N_LIGHTS = 5
# The sorting machine's camera: 720 px across 2*2.1*tan(22.5 deg) units. Our camera is CAM_RES px with
# the same 45 deg view, so this distance gives the same pixels per mm (pieces look just as small).
SORTER_CAM_DIST = machine_setup.camera_height() * 480 / 720   # your machine's camera height (2.1 = 210 mm)


def close_renderer(r):
    """Close a MuJoCo renderer safely when several are open.

    mujoco.Renderer.close() frees its drawing buffers *after* dropping its own OpenGL
    context, so they get freed in whichever other renderer's context is current, wiping
    that one's buffers (it then draws black). Free them in the right context first."""
    if r is None:
        return
    if getattr(r, "_gl_context", None) and getattr(r, "_mjr_context", None):
        r._gl_context.make_current()
        r._mjr_context.free()
        r._mjr_context = None
    r.close()


def _fmt(arr):
    return " ".join(f"{x:.6g}" for x in np.asarray(arr).ravel())


class DropScene:
    def __init__(self, verts, faces, wear_texture=None, texcoord=None, others=()):
        """wear_texture + texcoord: a picture of scratches/dust wrapped on the piece (see wear.py).
        others: extra pieces [(verts, faces, "stuck" | "loose")] for 'several pieces' pictures:
        stuck = clicked onto the main piece, loose = dropped right next to it."""
        self.texture_base = wear_mod.TEXTURE_BASE if wear_texture else 1.0
        self.dull = 0.0   # 0 = glossy new plastic, higher = worn and less shiny
        wear_asset = ""
        mesh_tex = ""
        plastic_tex = ""
        if wear_texture is not None:
            wear_asset = f'<texture name="wear" type="2d" file="{str(wear_texture).replace(chr(92), "/")}"/>'
            mesh_tex = f' texcoord="{_fmt(texcoord)}"'
            plastic_tex = ' texture="wear"'
        extent = verts.max(0) - verts.min(0)
        self.radius = float(np.linalg.norm(extent) / 2)
        self.others = [(v, f, mode, float(np.linalg.norm(v.max(0) - v.min(0)) / 2)) for v, f, mode in others]
        other_assets, stuck_geoms, loose_bodies = "", "", ""
        for i, (v, f, mode, ro) in enumerate(self.others):
            other_assets += f'<mesh name="om{i}" vertex="{_fmt(v)}" face="{_fmt(f)}" inertia="convex"/>'
            look = 'friction="0.6 0.01 0.002" condim="6" solref="0.004 1" material="plastic_plain" density="1000"'
            if mode == "stuck":  # sitting on top of the main piece, studs pushed in a little
                top = verts[:, 2].max() - v[:, 2].min() - 0.016
                dx, dy = (np.random.default_rng().uniform(-0.5, 0.5, 2) * extent[:2])
                yaw = np.random.default_rng().choice([0, 90, 180, 270])
                stuck_geoms += (f'<geom name="o{i}" type="mesh" mesh="om{i}" pos="{dx:.4f} {dy:.4f} {top:.4f}" '
                                f'euler="0 0 {yaw}" rgba="0.5 0.5 0.5 1" {look}/>')
            else:
                loose_bodies += (f'<body name="ob{i}" pos="{(i + 1) * 3 * ro} 0 {ro + 0.1}"><freejoint/>'
                                 f'<geom name="o{i}" type="mesh" mesh="om{i}" rgba="0.5 0.5 0.5 1" {look}/></body>')
        r = self.radius + sum(ro for *_, ro in self.others)
        cam_h = max(0.5, 6.0 * r)    # camera distance, scaled to the part
        side = max(0.6, 7.0 * r)
        lights = "\n".join(
            # lamps: wide, soft cones (no bright circles); the 3 strongest cast shadows
            f'<light name="l{i}" pos="0 0 {cam_h * 2}" dir="0 0 -1" diffuse="0.5 0.5 0.5" cutoff="75" exponent="1" '
            f'specular="0.2 0.2 0.2" castshadow="{"true" if i < 3 else "false"}"/>' for i in range(N_LIGHTS))
        surface_assets = "\n".join(
            f'<texture name="t_{n}" type="2d" file="{p.replace(chr(92), "/")}"/>'
            f'<material name="s_{n}" texture="t_{n}" texuniform="true" '
            f'texrepeat="{1 / surfaces.SURFACES[n]:.4f} {1 / surfaces.SURFACES[n]:.4f}" {surfaces.material(n)}/>'
            for n, p in surfaces.paths().items())

        xml = f"""
<mujoco>
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="{CAM_RES}" offheight="{CAM_RES}"/>
    <quality shadowsize="2048"/>
    <headlight ambient="0.3 0.3 0.3" diffuse="0.3 0.3 0.3" specular="0 0 0"/>
    <map znear="0.01"/>
  </visual>
  <asset>
    <texture name="tray" type="2d" builtin="flat" rgb1="0.85 0.85 0.85" rgb2="0.8 0.8 0.8"
             mark="random" random="0.02" markrgb="0.6 0.6 0.6" width="512" height="512"/>
    <material name="tray" texture="tray" texrepeat="4 4" reflectance="0"/>
    {surface_assets}
    {wear_asset}
    <material name="plastic" specular="0.2" shininess="0.3"{plastic_tex}/>
    <material name="plastic_plain" specular="0.3" shininess="0.8"/>
    <mesh name="part" vertex="{_fmt(verts)}" face="{_fmt(faces)}"{mesh_tex} inertia="convex"/>
    {other_assets}
  </asset>
  <worldbody>
    {lights}
    <geom name="floor" type="plane" size="{side * 4} {side * 4} 0.1" material="tray" friction="0.8"/>
    <camera name="top" pos="0 0 {cam_h}" xyaxes="1 0 0 0 1 0" fovy="45"/>
    <camera name="side" pos="0 {-side * 1.1} {side * 0.8}" mode="targetbody" target="part" fovy="45"/>
    <body name="part" pos="0 0 {2 * r + 0.1}">
      <freejoint/>
      <geom name="part" type="mesh" mesh="part" rgba="0.8 0.1 0.1 1" density="1000"
            friction="0.6 0.01 0.002" condim="6" solref="0.004 1" material="plastic"/>
      {stuck_geoms}
    </body>
    {loose_bodies}
  </worldbody>
</mujoco>"""
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        self.part_geom = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "part")
        self.part_body = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "part")
        self.other_geoms = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, f"o{i}") for i in range(len(self.others))]
        self.loose = [i for i, o in enumerate(self.others) if o[2] != "stuck"]
        self.loose_bodies = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"ob{i}") for i in self.loose]
        self.all_geoms = [None] + self.other_geoms  # filled in below (part geom id is known after this)
        self.top_cam = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, "top")
        self.plastic = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_MATERIAL, "plastic")
        self.tray = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_MATERIAL, "tray")
        self.floor = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.surface_mats = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_MATERIAL, f"s_{n}")
                             for n in surfaces.SURFACES]
        self.all_geoms[0] = self.part_geom
        self.renderer = mujoco.Renderer(self.model, CAM_RES, CAM_RES)
        self.cam_h = cam_h
        self.rng = None

    def set_other_colors(self, colours):
        """Colours of the extra pieces (rgb 0..255, transparent?)."""
        for g, (rgb, trans) in zip(self.other_geoms, colours):
            self.model.geom_rgba[g] = [*(np.asarray(rgb) / 255.0), 0.55 if trans else 1.0]

    def close(self):
        close_renderer(self.renderer)

    def set_color(self, rgb, transparent=False):
        """Plastic colour; see-through ('Trans-') colours are drawn partly transparent."""
        # with a wear texture the colour is lifted a little, so the texture's base brings it back
        # to the true colour and scratches in the texture can be slightly lighter than the plastic
        c = np.clip(np.asarray(rgb) / 255.0 / self.texture_base, 0, 1)
        self.model.geom_rgba[self.part_geom] = [*c, 0.55 if transparent else 1.0]

    def randomize_look(self, rng):
        """A real-looking surface and 1 to 5 lamps, different every picture."""
        m, h = self.model, self.cam_h
        self.rng = rng
        # Surface: table tops, dark grey belt, stone floors... (the part casts its shadow on it)
        m.geom_matid[self.floor] = self.surface_mats[rng.integers(len(self.surface_mats))]
        # Lamps: 1 to 5, warm-yellowish to white, at different heights, sides and distances
        n_on = int(rng.integers(1, N_LIGHTS + 1))
        total = rng.uniform(0.75, 1.05)                # overall brightness: never very dark or blown out
        share = rng.dirichlet(np.ones(n_on) * 2)      # how the light is shared between the lamps
        for i in range(N_LIGHTS):
            if i >= n_on:
                m.light_diffuse[i] = 0
                m.light_specular[i] = 0
                continue
            elev = np.radians(rng.uniform(30, 85))
            azim = rng.uniform(0, 2 * np.pi)
            dist = h * rng.uniform(1.2, 3.0)            # nearer lamp = brighter and sharper shadow
            pos = dist * np.array([np.cos(elev) * np.cos(azim), np.cos(elev) * np.sin(azim), np.sin(elev)])
            m.light_pos[i] = pos
            m.light_dir[i] = -pos / np.linalg.norm(pos)
            warm = rng.uniform(0, 1)                    # 0 = white daylight, 1 = light yellowish bulb
            colour = np.array([1.0, 1.0 - 0.07 * warm, 1.0 - 0.22 * warm])
            falloff = (1.8 * h / dist) ** 2 / (1 + (1.8 * h / dist) ** 2) * 2  # about 1 at a medium distance
            m.light_diffuse[i] = np.clip(colour * total * share[i] * falloff, 0, 1)
            m.light_specular[i] = rng.uniform(0.15, 0.3)   # lamps give shiny highlights on the plastic
        # Some soft fill light from the room, so no side of a part goes pitch black
        m.vis.headlight.ambient[:] = rng.uniform(0.15, 0.25)
        m.vis.headlight.diffuse[:] = rng.uniform(0.05, 0.15)
        # Shiny ABS plastic like real Lego: mostly glossy, a few a bit worn, never a mirror
        # (stronger than this washes out the colour, e.g. red turns pink)
        m.mat_specular[self.plastic] = rng.uniform(0.2, 0.45) * (1 - self.dull)  # worn plastic shines less
        m.mat_shininess[self.plastic] = rng.uniform(0.7, 0.9)

    def sorter_look(self, rng):
        """Like your sorting machine (machine setup): its belt underneath, its lamps above and a little
        to the side (with a little variety), no light from the camera."""
        m, h = self.model, self.cam_h
        self.rng = rng
        setup = machine_setup.load()
        belts = [self.surface_mats[i] for i, n in enumerate(surfaces.SURFACES) if n in surfaces.SORTER_BELTS]
        if not setup["all_belts_in_training"]:   # only your own belt
            belts = [self.surface_mats[i] for i, n in enumerate(surfaces.SURFACES)
                     if surfaces.SORTER_BELTS.get(n) == setup["belt"]] or belts
        m.geom_matid[self.floor] = belts[rng.integers(len(belts))]
        lamps = machine_setup.lamps(spread=1.2, rng=rng)   # simulation units: 1 = 100 mm
        shift = rng.uniform(-2.0, 2.0)   # where along the belt the piece is, relative to the lamps
        for i in range(N_LIGHTS):
            if i >= len(lamps):
                m.light_diffuse[i] = m.light_specular[i] = 0
                continue
            pos, power, colour = lamps[i]
            pos = pos + np.array([shift, 0, 0])
            m.light_pos[i] = pos
            m.light_dir[i] = -pos / np.linalg.norm(pos)
            m.light_diffuse[i] = np.clip(colour * power, 0, 1)
            m.light_specular[i] = 0.3
        m.vis.headlight.ambient[:] = rng.uniform(0.27, 0.33)
        m.vis.headlight.diffuse[:] = 0
        m.mat_specular[self.plastic] = rng.uniform(0.3, 0.45) * (1 - self.dull)
        m.mat_shininess[self.plastic] = rng.uniform(0.75, 0.9)

    def drop(self, rng, frame_every=0, camera="side"):
        """Drop the part with a random spin. Yields picture frames if frame_every>0."""
        mujoco.mj_resetData(self.model, self.data)
        q = rng.normal(size=4)
        self.data.qpos[:3] = [rng.uniform(-0.3, 0.3) * self.radius,
                              rng.uniform(-0.3, 0.3) * self.radius,
                              2 * self.radius + rng.uniform(0.05, 0.3)]
        self.data.qpos[3:7] = q / np.linalg.norm(q)
        self.data.qvel[:3] = rng.normal(0, 0.05, 3)
        self.data.qvel[3:6] = rng.normal(0, 8, 3)
        # loose extra pieces fall right next to the main one (may land touching it, or just apart)
        for i, b in zip(self.loose, self.loose_bodies):
            ro = self.others[i][3]
            a = self.model.jnt_qposadr[self.model.body_jntadr[b]]
            v = self.model.jnt_dofadr[self.model.body_jntadr[b]]
            ang = rng.uniform(0, 2 * np.pi)
            dist = (self.radius + ro) * rng.uniform(0.5, 1.0)
            qo = rng.normal(size=4)
            self.data.qpos[a:a + 3] = [self.data.qpos[0] + dist * np.cos(ang), self.data.qpos[1] + dist * np.sin(ang),
                                       self.data.qpos[2] + rng.uniform(0.0, 0.2)]
            self.data.qpos[a + 3:a + 7] = qo / np.linalg.norm(qo)
            self.data.qvel[v + 3:v + 6] = rng.normal(0, 8, 3)
        still = 0
        for step in range(2500):
            mujoco.mj_step(self.model, self.data)
            if frame_every and step % frame_every == 0:
                yield self.render(camera)
            moving = np.abs(self.data.qvel).max()
            still = still + 1 if moving < 0.02 else 0
            if step > 100 and still > 50:
                break
        if frame_every:
            yield self.render(camera)

    def settle(self, rng):
        for _ in self.drop(rng):
            pass

    def render(self, camera="top"):
        self.renderer.update_scene(self.data, camera=camera)
        return self.renderer.render().copy()

    def _aim_camera(self, rng, sorter=False):
        """Point the camera at the part. With rng: a random tilt like a hand-held phone photo.
        sorter=True: straight down from as far as the sorting machine's camera (pieces look as
        small and as sharp as they do there)."""
        target = np.mean([self.data.xpos[b] for b in [self.part_body] + self.loose_bodies], axis=0)
        target[2] = 0
        if sorter:
            elev, azim, dist = np.pi / 2, 0.0, machine_setup.camera_height() * 480 / 720   # see SORTER_CAM_DIST
            rng = None
        elif rng is None:
            elev, azim, dist = np.pi / 2, 0.0, self.cam_h
        else:
            elev = np.radians(rng.uniform(35, 90))
            azim = rng.uniform(0, 2 * np.pi)
            dist = self.cam_h * rng.uniform(0.8, 1.25)
        back = np.array([np.cos(elev) * np.cos(azim), np.cos(elev) * np.sin(azim), np.sin(elev)])
        z = back                               # camera looks along -z
        up = np.array([0.0, 1.0, 0.0]) if abs(z[2]) > 0.99 else np.array([0.0, 0.0, 1.0])
        x = np.cross(up, z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        if rng is not None:  # roll the camera too
            a = rng.uniform(0, 2 * np.pi)
            x, y = np.cos(a) * x + np.sin(a) * y, -np.sin(a) * x + np.cos(a) * y
        quat = np.zeros(4)
        mujoco.mju_mat2Quat(quat, np.column_stack([x, y, z]).ravel())
        self.model.cam_pos[self.top_cam] = target + dist * back
        self.model.cam_quat[self.top_cam] = quat
        mujoco.mj_forward(self.model, self.data)

    def snapshot(self, size=224, margin=0.12, rng=None, sorter=False):
        """Camera picture, plus a square crop around the part.

        With rng the camera angle is random and the picture gets camera effects (blur, noise,
        colour cast). sorter=True: taken like the sorting machine's camera, clean.
        """
        self._aim_camera(rng, sorter)
        if sorter:
            rng = None
        self.renderer.update_scene(self.data, camera="top")
        full = self.renderer.render().copy()
        self.renderer.enable_segmentation_rendering()
        seg = self.renderer.render()
        self.renderer.disable_segmentation_rendering()
        mask = np.isin(seg[:, :, 0], self.all_geoms) & (seg[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM))
        if rng is not None:
            full = messy.photo_effects(full, mask, rng)
        return full, crop_to_mask(full, mask, size, margin)


def crop_to_mask(img, mask, size=224, margin=0.12):
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:  # part not (really) in view
        return None
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 * (1 + margin) + 4
    pad = int(half) + 2  # pad with edge colour so crops near the border don't get black bars
    big = np.pad(img, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    box = (int(cx - half) + pad, int(cy - half) + pad, int(cx + half) + pad, int(cy + half) + pad)
    return Image.fromarray(big).crop(box).resize((size, size), Image.LANCZOS)
