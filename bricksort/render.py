"""Make the training pictures: drop every part many times and photograph it.

Run:  python -m bricksort.render [images_per_part]
Parts that already have enough pictures are skipped, so it's safe to re-run.
"""
import json
import re
import sys
import time

import mujoco
import numpy as np

from . import catalog, config, junk, machine_setup, wear
from .ldraw import Library
from .scene import DropScene

# Everyday Lego colours (Rebrickable colour ids), used besides each part's own common colours:
# black, blue, green, red, yellow, white, tan, orange, lime, dark pink, reddish brown,
# light bluish gray, dark bluish gray, dark red, dark tan, medium azure, dark blue, bright pink
EXTRA_COLORS = [0, 1, 2, 4, 14, 15, 19, 25, 27, 5, 70, 71, 72, 320, 28, 322, 272, 29]
# The most common see-through colours: clear, light blue, red, orange, yellow, dark blue, brown,
# neon green, green
TRANS_COLORS = [47, 41, 36, 182, 46, 33, 40, 42, 34]
TRANS_SHARE = 0.12   # share of training pictures in a see-through colour
SORTER_SHARE = machine_setup.load()["machine_share"] / 100   # share of pictures taken like your machine


def _quat(axis, deg):
    a = np.radians(deg) / 2
    return np.r_[np.cos(a), np.sin(a) * np.asarray(axis, float)]


def reference_image(scene, rgb, size=224):
    """A clear catalogue-style picture: the part at a 3/4 angle on a dark background,
    lit from the side so edges and studs show. Very light or very dark colours are
    shown in a mid grey, so the shape stands out."""
    if min(rgb) > 200:
        rgb = (165, 170, 175)          # white and near-white -> light grey
    elif max(rgb) < 45:
        rgb = (110, 112, 108)          # black -> dark grey
    m = scene.model
    # fixed, soft studio lighting instead of the random training lights
    dirs = [(-0.5, 0.6, -0.65), (0.7, 0.3, -0.6), (0, -0.6, -0.8)]
    power = [0.55, 0.25, 0.15]
    for i in range(len(m.light_dir)):
        if i >= len(dirs):
            m.light_diffuse[i] = m.light_specular[i] = 0
            continue
        d = np.array(dirs[i]) / np.linalg.norm(dirs[i])
        m.light_dir[i] = d
        m.light_pos[i] = -d * scene.cam_h * 2
        m.light_diffuse[i] = power[i]
        m.light_specular[i] = 0.3
    m.geom_matid[scene.floor] = scene.tray
    m.vis.headlight.ambient[:] = 0.3
    m.vis.headlight.diffuse[:] = 0.25
    m.mat_specular[scene.plastic] = 0.4
    m.mat_shininess[scene.plastic] = 0.85
    m.mat_rgba[scene.tray, :3] = (0.16, 0.17, 0.19)   # dark slate background
    q = np.zeros(4)
    mujoco.mju_mulQuat(q, _quat([0, 0, 1], 30), _quat([1, 0, 0], -50))
    mujoco.mj_resetData(scene.model, scene.data)
    scene.data.qpos[:3] = [0, 0, scene.radius + 0.02]
    scene.data.qpos[3:7] = q
    mujoco.mj_forward(scene.model, scene.data)
    scene.set_color(rgb)
    _, crop = scene.snapshot(size, margin=0.18)
    return crop


def make_references(only=None):
    """(Re)make the reference picture of every part (custom pieces use your photos instead)."""
    lib = Library()
    color_table = catalog.colors(include_trans=True)
    config.REFERENCE.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    parts = [p for p in catalog.load_parts() if not p.get("custom") and (not only or p["id"] in only)]
    no_model = []
    for k, part in enumerate(parts, 1):
        try:
            if part["id"] == junk.NOT_LEGO:
                scene = DropScene(*junk.random_mesh(rng, 0.15))
                rgb = (150, 140, 120)
            else:
                scene = DropScene(*lib.part_mesh(part["id"]))
                own = [c for c in part.get("colors", []) if c in color_table]
                rgb = color_table[own[0]][1] if own else (160, 165, 169)
            try:
                reference_image(scene, rgb).save(config.REFERENCE / f"{part['id']}.png")
            finally:
                scene.close()
        except ValueError:   # no 3D model: the part is learned from photos only, and shown with one
            no_model.append(part["id"])
        except Exception as e:
            print(f"  ! {part['id']}: {e}", flush=True)
        if k % 50 == 0:
            print(f"{k}/{len(parts)} reference pictures", flush=True)
    if no_model:
        print(f"{len(no_model)} parts have no 3D model, so no reference picture (they're learned from "
              f"photos only): {', '.join(no_model)}")


WEAR_VARIANTS = 4   # differently worn copies of each part (each gets its own dents and scratches)
_real_colors = None


def real_colors(part, color_table):
    """[(colour id, weight)] for the colours this exact part was really made in (Rebrickable's
    lists of what's in every set). Common colours get picked more often, rare ones still appear."""
    global _real_colors
    if _real_colors is None:
        cache = config.BIG_DIR / "part_color_counts.json"
        if cache.exists():
            _real_colors = {p: {int(c): n for c, n in d.items()}
                            for p, d in json.loads(cache.read_text(encoding="utf-8")).items()}
        else:
            _, _, counts = catalog._rebrickable_info()
            _real_colors = {p: dict(c) for p, c in counts.items()}
            cache.write_text(json.dumps(_real_colors), encoding="utf-8")
    counts = {c: n for c, n in _real_colors.get(part["id"], {}).items() if c in color_table}
    # a model standing in for look-alikes (e.g. 970c00 for all 970cNN hips+legs): their colours count too
    for pattern, model in catalog.MODEL_ALIASES:
        if model == part["id"]:
            for pid, cc in _real_colors.items():
                if re.fullmatch(pattern, pid):
                    for c, k in cc.items():
                        if c in color_table:
                            counts[c] = counts.get(c, 0) + k
    if not counts:  # no record (e.g. a model used for a look-alike): its listed colours, else grey
        counts = {c: 1 for c in part.get("colors", []) if c in color_table} or {71: 1, 72: 1}
    ids = list(counts)
    w = np.sqrt(np.array([counts[c] for c in ids], float))
    return ids, w / w.sum()


def worn_scene(verts, faces, rng, tex_path):
    """A DropScene of this part with its own random wear: dents in the shape, scratches/dust texture."""
    level = wear.pick_level(rng)
    lo, hi = wear.WEAR_LEVELS[level]["dents"]
    v, f = wear.subdivide(verts, faces)
    v = wear.dent(v, f, rng, int(rng.integers(lo, hi + 1)))
    wear.texture(rng, level, tex_path)
    scene = DropScene(v, f, wear_texture=tex_path, texcoord=wear.texcoords(v, f))
    scene.dull = wear.dullness(level, rng)
    return scene


def render_part(lib, part, color_table, n, rng, root=None, reference=True):
    out_dir = (root or config.RENDERS) / part["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    have = len(list(out_dir.glob("*.png")))
    ref_path = config.REFERENCE / f"{part['id']}.png"
    if have >= n and (ref_path.exists() or not reference):
        return
    verts, faces = lib.part_mesh(part["id"])
    ids, weights = real_colors(part, color_table)
    if reference and not ref_path.exists():
        scene = DropScene(verts, faces)
        try:
            config.REFERENCE.mkdir(parents=True, exist_ok=True)
            best = ids[int(np.argmax(weights))]
            reference_image(scene, color_table[best][1]).save(ref_path)
        finally:
            scene.close()
    tex_path = config.BIG_DIR / "wear_textures" / f"{part['id']}.png"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    per_variant = max(1, -(-(n - have) // WEAR_VARIANTS))
    # numbers not in use yet: a picture taken out in the viewer leaves a gap, and the new picture
    # must not overwrite one that's still there
    used = {int(p.name[:4]) for p in out_dir.glob("*.png") if p.name[:4].isdigit()}
    free = (k for k in range(100000) if k not in used)
    scene = None
    try:
        for i in range(have, n):
            if (i - have) % per_variant == 0:  # next worn copy of the piece
                if scene:
                    scene.close()
                scene = worn_scene(verts, faces, rng, tex_path)
            cid = ids[rng.choice(len(ids), p=weights)]   # only colours the part really comes in
            rgb = wear.aged_colour(color_table[cid][1], rng)
            scene.set_color(rgb, transparent=color_table[cid][0].startswith("Trans"))
            sorter = rng.random() < SORTER_SHARE   # half the pictures: as on the sorting machine
            scene.sorter_look(rng) if sorter else scene.randomize_look(rng)
            crop = None
            for _ in range(5):  # retry the rare drop where the part ends up out of view
                scene.settle(rng)
                _, crop = scene.snapshot(config.IMAGE_SIZE, rng=rng, sorter=sorter)
                if crop is not None:
                    break
            if crop is None:
                raise RuntimeError("part keeps ending up out of the camera's view")
            crop.save(out_dir / f"{next(free):04d}_c{cid}.png")  # file name carries the colour
    finally:
        if scene:
            scene.close()


def preview(lib, part, color_table, n, rng):
    """n pictures of a part taken like your machine (machine setup), without saving them."""
    from . import surfaces
    surfaces.refresh()   # pick up a belt photo added since the program started
    verts, faces = lib.part_mesh(part["id"])
    ids, weights = real_colors(part, color_table)
    tex_path = config.BIG_DIR / "wear_textures" / "_preview.png"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    scene, out = worn_scene(verts, faces, rng, tex_path), []
    try:
        for _ in range(n):
            cid = ids[rng.choice(len(ids), p=weights)]
            scene.set_color(wear.aged_colour(color_table[cid][1], rng),
                            transparent=color_table[cid][0].startswith("Trans"))
            scene.sorter_look(rng)
            scene.settle(rng)
            _, crop = scene.snapshot(config.IMAGE_SIZE, rng=rng, sorter=True)
            if crop is not None:
                out.append(crop)
    finally:
        scene.close()
    return out


def render_multiple(lib, parts, color_table, n, rng):
    """Pictures for 'several pieces': two pieces clicked together, or lying right next to each other."""
    out_dir = config.RENDERS / catalog.MULTIPLE
    out_dir.mkdir(parents=True, exist_ok=True)
    have = len(list(out_dir.glob("*.png")))
    pool = [p for p in parts if not p.get("custom") and p["id"] != junk.NOT_LEGO]
    i, tries = have, 0
    while i < n:
        # most picks work; if almost none do (e.g. only big parts), stop instead of looping forever
        tries += 1
        if tries > 50 * (n - have) + 1000:
            print(f"render_multiple: gave up after {tries - 1} tries, made {i - have} of {n - have} pictures")
            break
        count = 3 if rng.random() < 0.3 else 2   # mostly two pieces, sometimes three
        if len(pool) < count:
            print("render_multiple: not enough parts with a 3D model for several-pieces pictures")
            break
        picked = [pool[k] for k in rng.choice(len(pool), count, replace=False)]
        try:
            meshes = [lib.part_mesh(p["id"]) for p in picked]
        except ValueError:
            continue
        if max((v.max(0) - v.min(0)).max() for v, _ in meshes) > 0.6:
            continue  # keep to pieces a sorter sees together
        mode = "stuck" if rng.random() < 0.5 else "loose"
        (va, fa), rest = meshes[0], meshes[1:]
        # a third piece is always loose next to them (stuck or not, the first two decide the name)
        scene = DropScene(va, fa, others=[(v, f, mode if k == 0 else "loose") for k, (v, f) in enumerate(rest)])
        try:
            colours = []
            for p in picked:
                ids, w = real_colors(p, color_table)
                cid = ids[rng.choice(len(ids), p=w)]
                colours.append((color_table[cid][1], color_table[cid][0].startswith("Trans")))
            scene.set_color(*colours[0])
            scene.set_other_colors(colours[1:])
            sorter = rng.random() < SORTER_SHARE
            scene.sorter_look(rng) if sorter else scene.randomize_look(rng)
            scene.settle(rng)
            _, crop = scene.snapshot(config.IMAGE_SIZE, rng=rng, sorter=sorter)
            if crop is not None:
                crop.save(out_dir / f"{i:04d}_{mode}.png")  # no colour label: it's two pieces
                i += 1
        finally:
            scene.close()


def render_junk(n, rng):
    """Pictures of random non-Lego objects, for the 'not_lego' class (a new object every picture)."""
    out_dir = config.RENDERS / junk.NOT_LEGO
    out_dir.mkdir(parents=True, exist_ok=True)
    have = len(list(out_dir.glob("*.png")))
    ref_path = config.REFERENCE / f"{junk.NOT_LEGO}.png"
    for i in range(have, n):
        scene = DropScene(*junk.random_mesh(rng, size=rng.uniform(0.05, 0.3)))
        try:
            if not ref_path.exists():
                reference_image(scene, (150, 140, 120)).save(ref_path)
            scene.set_color(junk.random_color(rng))
            scene.randomize_look(rng)
            scene.settle(rng)
            _, crop = scene.snapshot(config.IMAGE_SIZE, rng=rng)
            if crop is not None:
                crop.save(out_dir / f"{i:04d}.png")  # no colour label: colour doesn't matter here
        finally:
            scene.close()


def main(n=config.IMAGES_PER_PART, only=None):
    # when this run started: the "watch training pictures" window shows and counts only newer pictures
    config.RENDER_RUN.parent.mkdir(parents=True, exist_ok=True)
    config.RENDER_RUN.write_text(str(time.time()), encoding="utf-8")
    lib = Library()
    color_table = catalog.colors(include_trans=True)
    parts = catalog.add_parts_from_folders(lib)
    if only:
        parts = [p for p in parts if p["id"] in only]
    rng = np.random.default_rng()
    t0 = time.time()
    for k, part in enumerate(parts, 1):
        try:
            if part["id"] == catalog.MULTIPLE:
                render_multiple(lib, parts, color_table, n * 10, rng)  # simulated pairs + your photos
                continue
            if part.get("custom") or part.get("photos_only"):
                continue  # your own pieces / pieces without a 3D model: learned from your photos only
            if part["id"] == junk.NOT_LEGO:
                render_junk(n * 3, rng)  # lots of variety for "anything that isn't Lego"
            else:
                render_part(lib, part, color_table, n, rng)
        except Exception as e:  # one broken part shouldn't stop the rest
            print(f"  ! {part['id']}: {e}", flush=True)
        print(f"[{k}/{len(parts)}] {part['id']} {part['name']}  ({time.time() - t0:.0f}s)", flush=True)


def main_categories(n=10):
    """Pictures of the extra parts that are learned by category only."""
    lib = Library()
    color_table = catalog.colors(include_trans=True)
    parts = catalog.load_category_parts()
    rng = np.random.default_rng()
    t0 = time.time()
    for k, part in enumerate(parts, 1):
        try:
            render_part(lib, part, color_table, n, rng, root=config.CATEGORY_RENDERS, reference=False)
        except Exception as e:
            print(f"  ! {part['id']}: {e}", flush=True)
        if k % 25 == 0 or k == len(parts):
            print(f"[{k}/{len(parts)}] category pictures ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["references"]:
        make_references(sys.argv[2:] or None)
    elif sys.argv[1:2] == ["categories"]:
        main_categories(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else config.IMAGES_PER_PART)
