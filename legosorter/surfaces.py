"""Real-looking surfaces for the training pictures: table tops, a dark grey conveyor belt,
stone floors and a few others. They're drawn once as pictures (textures) and put
on the floor of the virtual world, so the piece casts a real shadow on them.

Made with code (no downloads) and saved in LegoSorterData/surfaces/.
"""
import numpy as np
from PIL import Image, ImageFilter

from . import belts, config

FOLDER = config.BIG_DIR / "surfaces"
SIZE = 512


def _noise(rng, scale, size=SIZE):
    """Smooth random noise 0..1 that tiles reasonably."""
    small = rng.random((max(2, size // scale), max(2, size // scale)))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((size, size), Image.BICUBIC)
    return np.asarray(img, np.float32) / 255


def _save(name, arr):
    FOLDER.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(FOLDER / f"{name}.png")


def wood(rng, base, ring_width, name):
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    warp = _noise(rng, 64) * 18 + _noise(rng, 16) * 4
    grain = np.sin((yy + warp * 3) / ring_width) * 0.5 + 0.5
    streaks = _noise(rng, 4)[:, :1].repeat(SIZE, 1)  # long fibres along the board
    shade = 0.82 + 0.12 * grain + 0.08 * streaks + 0.05 * _noise(rng, 128)
    # boards: a thin darker seam every ~170 px
    seams = (np.abs((yy % 170) - 0) < 1.5) * 0.25
    _save(name, np.asarray(base)[None, None, :] * (shade - seams)[..., None])


def belt(rng, base, name):
    fine = _noise(rng, 2) * 0.10 + _noise(rng, 8) * 0.06
    lines = (np.sin(np.mgrid[0:SIZE, 0:SIZE][0] / 1.6) * 0.5 + 0.5) * 0.04  # faint woven ribs
    _save(name, np.asarray(base)[None, None, :] * (0.9 + fine + lines)[..., None])


def stone(rng, base, tile, name, speckle=0.15):
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    blotch = 0.85 + 0.15 * _noise(rng, 48) + 0.08 * _noise(rng, 6)
    spots = (rng.random((SIZE, SIZE)) < 0.05) * rng.uniform(-1, 1, (SIZE, SIZE)) * speckle
    img = np.asarray(base)[None, None, :] * (blotch + spots)[..., None]
    if tile:  # grout lines between floor tiles
        grout = (xx % tile < 4) | (yy % tile < 4)
        img[grout] = np.asarray(base) * 0.55
    img = np.asarray(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)))
    _save(name, img)


def laminate(rng, base, name):
    _save(name, np.asarray(base)[None, None, :] * (0.94 + 0.06 * _noise(rng, 32) + 0.03 * _noise(rng, 4))[..., None])


# name -> how many world units one copy of the picture covers (world unit = 10 cm real size)
SURFACES = {
    "wood_oak": 4.0, "wood_walnut": 4.0, "wood_birch": 4.0,
    "belt_dark_grey": 2.0, "belt_grey": 2.0,
    "stone_concrete": 5.0, "stone_tiles": 6.0, "stone_granite": 3.0,
    "table_white": 4.0, "table_grey": 4.0,
}
# the sorting machine's belts (belts.py), at the same scale as on the machine
SORTER_BELTS = {f"sorter_belt_{b['file'][:-4]}": name for name, b in belts.BELTS.items()}
SURFACES.update({n: belts.BELTS[name]["span"] for n, name in SORTER_BELTS.items()})


def material(name):
    """Shine of a surface: the sorter belts keep their own (matte or glossy), the rest are dull."""
    if name in SORTER_BELTS:
        b = belts.BELTS[SORTER_BELTS[name]]
        return f'specular="{b["specular"]}" shininess="{b["shininess"]}" reflectance="{b["reflectance"]}"'
    return 'reflectance="0" specular="0.1"'


def make_all(force=False):
    if not force and all((FOLDER / f"{n}.png").exists() for n in SURFACES):
        return
    rng = np.random.default_rng(7)
    wood(rng, (196, 152, 98), 9, "wood_oak")
    wood(rng, (112, 76, 48), 7, "wood_walnut")
    wood(rng, (222, 196, 158), 11, "wood_birch")
    belt(rng, (58, 60, 63), "belt_dark_grey")
    belt(rng, (92, 95, 98), "belt_grey")
    stone(rng, (150, 148, 142), 0, "stone_concrete")
    stone(rng, (168, 160, 150), 256, "stone_tiles")
    stone(rng, (120, 118, 116), 0, "stone_granite", speckle=0.45)
    laminate(rng, (232, 232, 228), "table_white")
    laminate(rng, (150, 152, 155), "table_grey")
    for name, menu_name in SORTER_BELTS.items():
        Image.open(belts.path(menu_name)).convert("RGB").resize((SIZE, SIZE)).save(FOLDER / f"{name}.png")


def paths():
    make_all()
    return {n: str(FOLDER / f"{n}.png") for n in SURFACES}
