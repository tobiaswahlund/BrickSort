"""Pictures for the website's sorting machine (web/sim/): pieces and the belt, as the virtual
sorting machine's camera sees them.

Run:  python -m bricksort.export_sim            (needs the 3D parts; the pictures are kept in git)
      python -m bricksort.export_sim 300        (how many pieces, default 240)

A browser can't run the 3D physics, so each piece is dropped on the belt here, under the camera,
and photographed once it has settled. The website then slides these pictures along a moving belt,
crops each piece as it passes the camera's middle line and lets the model guess, like the real
sorter does. Writes:
  belt.png     a strip of the belt's surface (repeats along the belt), lighting taken out
  light.png    the lamps' light on the belt (multiplied in, so the strip can move under it)
  empty.jpg    the whole empty camera picture (rails and edges, which don't move)
  pieces/N.webp  each piece with its shadow, see-through around it
  sim.json     sizes, and what each piece really is (to show right / wrong)
"""
import json
import shutil
import sys

import mujoco
import numpy as np
from PIL import Image, ImageFilter

from . import catalog, config
from .ldraw import Library
from .sorter import properties
from .sorter.conveyor import BELT_HALF_WIDTH, CAM_H, CAM_RES, FOVY, ConveyorWorld

OUT = config.PROJECT_DIR / "web" / "sim"
BELT = "Green, matte"
MAX_LONG = 0.6   # longest piece shown (units, 60 mm): bigger ones would fill the camera picture


def _settle(world, k, steps=900):
    """Let the piece fall and come to rest, with the belt standing still."""
    ba, bv = world.model.jnt_qposadr[world.belt_joint], world.model.jnt_dofadr[world.belt_joint]
    for _ in range(steps):
        world.data.qvel[bv] = 0
        world._physics_step()
    world.data.qpos[ba] = 0
    world.data.qvel[:] = 0
    mujoco.mj_forward(world.model, world.data)


def _cutout(frame, empty):
    """The piece and its shadow, see-through elsewhere: a shadow is stored as black with the
    amount it darkens the belt, so it darkens whatever belt it later lies on."""
    f, b = frame.astype(np.float32), empty.astype(np.float32)
    diff = np.abs(f - b).max(2)
    lf, lb = f.mean(2) + 1, b.mean(2) + 1
    chroma = np.abs(f / lf[..., None] - b / lb[..., None]).max(2)
    darker = np.clip(1 - lf / lb, 0, 1)
    solid = (diff > 30) & ~((lf < lb) & (chroma < 0.12))     # the piece itself
    solid = np.asarray(Image.fromarray(solid.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
    edge = np.asarray(Image.fromarray(solid.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(0.7)),
                      np.float32) / 255
    shadow = np.where(darker > 0.04, darker, 0)
    alpha = np.maximum(edge, shadow * (1 - edge))
    rgb = f * edge[..., None]      # shadow pixels are black (premultiplied below)
    rgba = np.zeros((*f.shape[:2], 4), np.float32)
    rgba[..., :3] = np.where(alpha[..., None] > 0, rgb / np.maximum(alpha, 1e-3)[..., None], 0)
    rgba[..., 3] = alpha * 255
    return rgba.clip(0, 255).astype(np.uint8), solid


def main(n=240):
    rng = np.random.default_rng(7)
    lib = Library()
    colors = catalog.colors(include_trans=True)
    parts = catalog.load_parts()
    props = properties.load_all(lib)
    small = [p for p in parts if props.get(p["id"], {}).get("length", 99) * 0.08 <= MAX_LONG]
    world = ConveyorWorld(lib, small, colors, ["a", "b"], rng, belt=BELT)
    world.junk_chance = 0.05
    ppu = CAM_RES / (2 * CAM_H * np.tan(np.radians(FOVY / 2)))    # camera pixels per world unit

    if OUT.exists():
        shutil.rmtree(OUT)   # pictures made by this script only
    (OUT / "pieces").mkdir(parents=True)
    empty = world.render("cam")
    Image.fromarray(empty).save(OUT / "empty.jpg", quality=90)
    # Lighting: the belt picture smoothed out (its grain averages away); what's left is the belt's grain
    top, bottom = int(CAM_RES / 2 - BELT_HALF_WIDTH * ppu) + 3, int(CAM_RES / 2 + BELT_HALF_WIDTH * ppu) - 3
    band = empty[top:bottom].astype(np.float32)
    light = np.stack([np.asarray(Image.fromarray(band[..., c].astype(np.uint8)).filter(ImageFilter.GaussianBlur(25)),
                                 np.float32) for c in range(3)], 2) + 1
    peak = light.max()
    Image.fromarray((light / peak * 255).clip(0, 255).astype(np.uint8)).save(OUT / "light.png")
    period = int(round(2 * 0.5 * ppu))   # the belt picture repeats every 2 x span (span 0.5 for the green belts)
    x0 = CAM_RES // 2 - period // 2
    grain = band[:, x0:x0 + period] / light[:, x0:x0 + period] * peak
    Image.fromarray(grain.clip(0, 255).astype(np.uint8)).save(OUT / "belt.png")

    pieces, made = [], 0
    while made < n:
        k = world._free_slot(rng.random() < world.junk_chance)
        if k is None:   # every piece of this set used: a new random set
            world.build()
            continue
        v = world.meshes[k][1][0]
        if (v.max(0) - v.min(0)).max() > MAX_LONG:
            world._hide(k)
            world.state[k] = "used"
            continue
        world.spawn(x=0.0, y=0.0, k=k, z=0.05)
        _settle(world, k)
        a = world._qadr(k)
        if abs(world.data.qpos[a]) > 0.3 or abs(world.data.qpos[a + 1]) > 0.3:   # rolled away
            world._hide(k)
            world.state[k] = "used"
            continue
        frame = world.render("cam")
        part, colour, category, known = world.truth[k]
        world._hide(k)
        world.state[k] = "used"
        rgba, solid = _cutout(frame, empty)
        ys, xs = np.nonzero(rgba[..., 3] > 8)
        sy, sx = np.nonzero(solid)
        if len(sx) < 30 or xs.min() <= 0 or ys.min() <= 0 or xs.max() >= CAM_RES - 1 or ys.max() >= CAM_RES - 1:
            continue
        box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        Image.fromarray(rgba[box[1]:box[3], box[0]:box[2]]).save(OUT / "pieces" / f"{made}.webp",
                                                                 quality=88, method=6)
        pieces.append({"file": f"pieces/{made}.webp", "w": box[2] - box[0], "h": box[3] - box[1],
                       # the piece itself (no shadow) inside the picture: what the camera finds
                       "solid": [int(sx.min()) - box[0], int(sy.min()) - box[1],
                                 int(sx.max()) + 1 - box[0], int(sy.max()) + 1 - box[1]],
                       "part": part, "colour": colour, "category": category, "known": bool(known)})
        made += 1
        print(f"\r{made}/{n} pieces", end="", flush=True)
    print()
    sim = {"camera": CAM_RES, "px_per_mm": ppu / 100, "belt_top": top, "belt_bottom": bottom,
           "period": period, "belt": BELT, "pieces": pieces}
    (OUT / "sim.json").write_text(json.dumps(sim), encoding="utf-8")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"Wrote {len(pieces)} pieces to {OUT} ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 240)
