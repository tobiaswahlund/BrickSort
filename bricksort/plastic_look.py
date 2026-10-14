"""Learn how real LEGO plastic looks from your real photos, so the training pictures match it.

Two things are measured on your photos of single pieces on a plain background (my_photos/<part>/<colour>/,
not the dataset renders):
  - gloss: how much of a piece is highlight, and how bright its highlights are compared with its
    plain colour. Renders are then made with different shine settings, and the setting whose
    renders look most like your photos is kept (fit_gloss).
  - surface texture: the fine pattern on flat faces of real pieces (tiny bumps, scratches, the
    camera's own grain). Small patches of it are kept and later laid over the 3D piece's wear
    texture, so renders get real-looking surface detail instead of perfectly smooth plastic.

Run:  python -m bricksort.plastic_look      (or "Learn from my photos" in the Model training window)
Results: <data folder>/plastic_look.json and plastic_patches.npy. Machine setup decides whether
the training pictures use them.
"""
import json
import random
import sys
import time

import numpy as np
from PIL import Image, ImageFilter

from . import config

RESULT = config.BIG_DIR / "plastic_look.json"
PATCHES = config.BIG_DIR / "plastic_patches.npy"
PATCH = 32
DATASET_FILES = ("d02_", "b200_")   # renders and scene cut-outs: not real single-piece photos


def _real_photos(n, seed=0):
    """Up to n of your photos of single pieces with a known colour (not dataset renders)."""
    out = []
    root = config.MY_PHOTOS
    if not root.exists():
        return out
    for part in root.iterdir():
        if not part.is_dir() or part.name.startswith("_") or part.name in ("unknown", "multiple", "not_lego"):
            continue
        for colour in part.iterdir():
            if colour.is_dir():
                out += [f for f in colour.iterdir() if f.suffix.lower() in config.PHOTO_TYPES
                        and not f.name.startswith(DATASET_FILES)]
    random.Random(seed).shuffle(out)
    return out[:n]


def _piece_mask(img):
    """Pixels that clearly differ from the background (the photo's border is mostly background)."""
    border = np.concatenate([img[:3].reshape(-1, 3), img[-3:].reshape(-1, 3),
                             img[:, :3].reshape(-1, 3), img[:, -3:].reshape(-1, 3)])
    bg = np.median(border, 0)
    spread = np.median(np.abs(border - bg), 0).max()
    return np.abs(img - bg).max(2) > max(30, 4 * spread)


def gloss_stats(img, mask):
    """(highlight share, highlight strength) of a piece. A shine highlight is the lamp's own light
    reflected: much brighter than the piece's usual brightness AND whiter (less coloured) than the
    plastic. Strength: how close the brightest 2% get to white (0..1). None for pieces that are too
    light or too dark to tell (white, black) and for nearly grey colours."""
    px = img[mask]
    if len(px) < 300:
        return None
    lum = px @ np.array([0.299, 0.587, 0.114])
    sat = (px.max(1) - px.min(1)) / np.maximum(px.max(1), 1)
    m, s = np.median(lum), np.median(sat)
    if not 40 < m < 190 or s < 0.25:
        return None
    hl = (lum > m + 0.4 * (255 - m)) & (sat < 0.6 * s)
    return float(hl.mean()), float((np.percentile(lum, 98) - m) / (255 - m))


def _flat_patches(img, mask, k=4):
    """Up to k PATCHxPATCH patches of the surface pattern on flat, evenly lit parts of the piece:
    the photo divided by a blurred copy of itself, so only the fine detail is left (1 = no change)."""
    grey = Image.fromarray(img.astype(np.uint8)).convert("L")
    g = np.asarray(grey, np.float32) + 1
    smooth = np.asarray(grey.filter(ImageFilter.GaussianBlur(4)), np.float32) + 1
    detail = g / smooth
    edges = np.asarray(grey.filter(ImageFilter.FIND_EDGES), np.float32)
    out = []
    h, w = g.shape
    for y in range(0, h - PATCH, PATCH // 2):
        for x in range(0, w - PATCH, PATCH // 2):
            if not mask[y:y + PATCH, x:x + PATCH].all():
                continue
            if edges[y:y + PATCH, x:x + PATCH].mean() > 6 or smooth[y:y + PATCH, x:x + PATCH].mean() > 235:
                continue   # an edge, a stud outline or a burnt-out highlight: not plain surface
            out.append(detail[y:y + PATCH, x:x + PATCH])
            if len(out) >= k:
                return out
    return out


def measure_real(n=600, log=print):
    stats, patches = [], []
    for k, f in enumerate(_real_photos(n), 1):
        try:
            img = np.asarray(Image.open(f).convert("RGB").resize((224, 224)), np.float32)
        except OSError:
            continue
        mask = _piece_mask(img)
        s = gloss_stats(img, mask)
        if s:
            stats.append(s)
        patches += _flat_patches(img, mask)
        if k % 100 == 0:
            log(f"  looked at {k} photos ({len(stats)} usable for gloss, {len(patches)} surface patches)")
    return np.array(stats), np.array(patches, np.float32)


LAMP_SPECULAR = 0.3   # the lamps' own shine in the training scenes (scene.py); the fit keeps it fixed


def _photo_like_scenes(rng):
    """Common pieces in strong colours, dropped once on a white tray under two lamps from the
    sides, like the photos they're compared with. The same poses are reused for every setting."""
    from . import catalog, ldraw
    from .scene import DropScene, N_LIGHTS
    lib = ldraw.Library()
    table = catalog.colors()
    names = ["Red", "Blue", "Yellow", "Green", "Orange", "Dark Bluish Gray", "Medium Azure", "Lime",
             "Reddish Brown", "Dark Red"]
    cols = [cid for cid, (n, _) in table.items() if n in names]
    scenes = []
    for k, pid in enumerate(("3001", "3003", "3020", "3039", "3062b", "2420", "3004", "3022")):
        for d in range(3):
            try:
                sc = DropScene(*lib.part_mesh(pid))
            except ValueError:
                break
            sc.set_color(table[cols[(k * 3 + d) % len(cols)]][1])
            sc.settle(rng)
            m = sc.model
            m.geom_matid[sc.floor] = sc.tray
            for i in range(N_LIGHTS):
                pos = np.array([(1 if i == 0 else -1) * np.cos(np.radians(50)), 0.3, np.sin(np.radians(50))])
                pos *= sc.cam_h * 2
                m.light_pos[i], m.light_dir[i] = pos, -pos / np.linalg.norm(pos)
                m.light_diffuse[i] = 0.45 if i < 2 else 0
                m.light_specular[i] = LAMP_SPECULAR if i < 2 else 0
            m.vis.headlight.ambient[:] = 0.25
            m.vis.headlight.diffuse[:] = 0.1
            scenes.append(sc)
    return scenes


def render_stats(scenes, specular, shininess):
    """The gloss numbers of these scenes rendered with this shine."""
    out = []
    for sc in scenes:
        sc.model.mat_specular[sc.plastic], sc.model.mat_shininess[sc.plastic] = specular, shininess
        _, crop = sc.snapshot(224, rng=None)
        if crop is not None:
            img = np.asarray(crop, np.float32)
            s = gloss_stats(img, _piece_mask(img))
            if s:
                out.append(s)
    return np.array(out)


def fit_gloss(real, log=print):
    """The shine setting whose renders' highlights are most like your photos'. (Tried 2026-10-14:
    the numbers move smoothly with the setting, and your photos fall inside the range renders can make.)"""
    target = real.mean(0)
    scenes = _photo_like_scenes(np.random.default_rng(3))
    best = None
    try:
        for spec in (0.2, 0.3, 0.45, 0.6, 0.8, 1.0):
            for shin in (0.1, 0.2, 0.3, 0.4, 0.55, 0.7, 0.85):
                r = render_stats(scenes, spec, shin)
                if not len(r):
                    continue
                got = r.mean(0)
                err = abs(got[0] - target[0]) / max(target[0], 0.01) + abs(got[1] - target[1]) / max(target[1], 0.05)
                if best is None or err < best[0]:
                    best = (err, spec, shin, got)
            log(f"  tried specular {spec}: best so far {best[1]} / {best[2]} "
                f"(highlights {best[3][0]:.1%}, strength {best[3][1]:.2f})")
    finally:
        for sc in scenes:
            sc.close()
    return best


def learn(n=600, log=print):
    t0 = time.time()
    log(f"Measuring your photos ({n} at most) …")
    real, patches = measure_real(n, log)
    if len(real) < 30:
        log("Not enough usable photos of single pieces on a plain background (need 30).")
        return None
    log(f"Your photos: highlights cover {real[:, 0].mean():.1%} of a piece, strength {real[:, 1].mean():.2f}.")
    log("Trying shine settings on renders …")
    err, spec, shin, got = fit_gloss(real, log)
    detail = float(np.std(patches)) if len(patches) else 0.0
    result = {"specular": spec, "shininess": shin, "photo_highlights": float(real[:, 0].mean()),
              "photo_strength": float(real[:, 1].mean()), "render_highlights": float(got[0]),
              "render_strength": float(got[1]), "surface_detail": detail, "photos": int(len(real)),
              "patches": int(len(patches)), "learned": time.strftime("%Y-%m-%d %H:%M")}
    config.BIG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if len(patches):
        np.save(PATCHES, patches)
    log(f"Best shine: specular {spec}, shininess {shin}. {len(patches)} surface patches kept "
        f"(fine detail ±{detail:.1%}). Took {time.time() - t0:.0f} s.")
    return result


def learned():
    """What was learned last time, or None."""
    try:
        return json.loads(RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


TEXTURE_STRENGTH = 0.45  # the photos' detail also holds some camera grain; renders add their own later


def gloss(rng, dull):
    """(specular, shininess) for the plastic in a training picture: learned from your photos if
    'Shine from my photos' is on in the machine setup, else None (scene.py keeps its own values)."""
    from . import machine_setup
    a, b = rng.uniform(0.85, 1.15), rng.uniform(-0.05, 0.05)   # drawn either way: the switch changes nothing else
    got = learned() if machine_setup.load().get("real_gloss") else None
    if not got:
        return None
    return float(np.clip(got["specular"] * a * (1 - dull), 0, 1)), float(np.clip(got["shininess"] + b, 0, 1))


def use_texture():
    from . import machine_setup
    return bool(machine_setup.load().get("real_texture")) and PATCHES.exists()


_patches = None


def surface_texture(rng, size):
    """A size x size multiplicative pattern (around 1) tiled from real surface patches."""
    global _patches
    if _patches is None:
        _patches = np.load(PATCHES) if PATCHES.exists() else np.zeros((0, PATCH, PATCH), np.float32)
    if not len(_patches):
        return np.ones((size, size), np.float32)
    scale = 2   # real photos show a piece at about half the texture's pixels per mm
    step = PATCH * scale
    out = np.ones((size, size), np.float32)
    for y in range(0, size, step):
        for x in range(0, size, step):
            p = _patches[rng.integers(len(_patches))]
            p = np.rot90(p, rng.integers(4))
            if rng.random() < 0.5:
                p = p[:, ::-1]
            p = np.kron(p, np.ones((scale, scale), np.float32))
            out[y:y + step, x:x + step] = p[:size - y, :size - x]
    return out


if __name__ == "__main__":
    learn(int(sys.argv[1]) if len(sys.argv) > 1 else 600)
