"""The conveyor belt surfaces: green or black, matte or glossy.

Drawn with code (no photos, so nothing to credit or licence) and saved once in
LegoSorterData/belts/. Used by the virtual sorting machine and, so the model
sees the same belts, for some of the training pictures.

Matte = fine rubbery grain that scatters light. Glossy = smooth PVC with a few
faint lengthwise streaks; the shine itself comes from the material settings
(specular/shininess/reflectance), not from the picture.
"""
import numpy as np
from PIL import Image

from . import config

FOLDER = config.BIG_DIR / "belts"
SIZE = 512

# name shown in the menu -> picture colour, finish, material shine, and span
# (span = how many world units (10 cm) one copy of the picture covers)
BELTS = {
    "Green, matte":  {"file": "green_matte.png",  "rgb": (36, 104, 58), "finish": "matte",
                      "specular": 0.05, "shininess": 0.1, "reflectance": 0.0, "span": 0.5},
    "Green, glossy": {"file": "green_glossy.png", "rgb": (30, 116, 66), "finish": "glossy",
                      "specular": 0.6, "shininess": 0.85, "reflectance": 0.05, "span": 0.5},
    "Black, matte":  {"file": "black_matte.png",  "rgb": (44, 44, 46), "finish": "matte",
                      "specular": 0.05, "shininess": 0.1, "reflectance": 0.0, "span": 0.6},
    "Black, glossy": {"file": "black_glossy.png", "rgb": (30, 31, 33), "finish": "glossy",
                      "specular": 0.6, "shininess": 0.85, "reflectance": 0.05, "span": 0.6},
}
DEFAULT_BELT = "Black, matte"


def _tiling_noise(rng, blur, size=SIZE):
    """Random bumps about `blur` pixels across, scaled to -1..1. Made by blurring white noise
    in the frequency domain, so the picture wraps around: no seam where copies meet."""
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f)
    soft = np.exp(-(fx ** 2 + fy ** 2) * (np.pi * blur) ** 2 * 2)
    n = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((size, size))) * soft))
    return n / (np.abs(n).max() + 1e-9)


def _relief(height, strength):
    """Light the bumps from one side (top-left), like a lamp would: makes the grain look 3D."""
    slope = (np.roll(height, 1, 0) - np.roll(height, -1, 0)) + (np.roll(height, 1, 1) - np.roll(height, -1, 1))
    return 1 + strength * slope


def draw(belt, rng):
    if belt["finish"] == "matte":
        height = _tiling_noise(rng, 1.5) * 0.6 + _tiling_noise(rng, 4) * 0.4  # fine grain + coarser lumps
        shade = _relief(height, 0.9) + 0.06 * _tiling_noise(rng, 40)
    else:
        streaks = _tiling_noise(rng, 6)[:, :1].repeat(SIZE, 1)  # faint lines along the belt
        shade = 1 + 0.03 * streaks + 0.02 * _tiling_noise(rng, 60) + 0.01 * _tiling_noise(rng, 1)
    img = np.asarray(belt["rgb"], np.float32)[None, None, :] * shade[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def path(name):
    """The belt's picture (drawn the first time it's needed)."""
    belt = BELTS[name]
    out = FOLDER / belt["file"]
    if not out.exists():
        FOLDER.mkdir(parents=True, exist_ok=True)
        draw(belt, np.random.default_rng(list(BELTS).index(name) + 11)).save(out)
    return out
