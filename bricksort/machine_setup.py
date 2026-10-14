"""Your sorting machine's set-up: belt, lamps and camera. Saved in machine_setup.json.

Both the virtual sorting machine and the training pictures that look like the machine use it, so
the model learns what your machine's camera will really see. Change it in the Model training
window (Machine setup), then make the training pictures again and train.

Sizes are in mm, like on a real machine. (Inside the simulation 1 unit = 100 mm.)
"""
import json

import numpy as np

from . import config

FILE = config.PROJECT_DIR / "machine_setup.json"
OWN_BELT = "My own belt photo"
OWN_BELT_FILE = config.BIG_DIR / "belts" / "own_belt.png"

DEFAULTS = {
    "belt": "Black, matte",         # one of belts.BELTS, or OWN_BELT
    "own_belt_mm": 50,               # how many mm of belt your photo shows (its width)
    "all_belts_in_training": True,   # train on every belt (sturdier) or only on yours
    "camera_height_mm": 210,         # camera lens above the belt
    "lamps": 3,                      # how many lamps
    "lamp_height_mm": 300,           # lamps above the belt
    "lamp_side_mm": 130,             # how far to the side of the camera the lamps hang
    "brightness": 1.0,               # 1 = as bright as the built-in machine
    "warmth": 0.0,                   # 0 = white daylight lamps, 1 = warm yellowish bulbs
    "machine_share": 50,             # % of training pictures taken like your machine (the rest: tables, floors...)
}
LIMITS = {"own_belt_mm": (10, 500), "camera_height_mm": (100, 600), "lamps": (1, 5), "lamp_height_mm": (100, 1000),
          "lamp_side_mm": (0, 500), "brightness": (0.3, 2.0), "warmth": (0.0, 1.0), "machine_share": (0, 100)}

_current = None


def load():
    """The saved set-up (defaults for anything not set)."""
    global _current
    if _current is None:
        saved = {}
        try:
            saved = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        _current = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    return _current


def load_saved():
    """The set-up as saved in the file (forgetting any not-saved preview settings)."""
    global _current
    _current = None
    return load()


def use(setup):
    """Use these settings in this program from now on (e.g. for a preview), without saving."""
    global _current
    _current = {**DEFAULTS, **setup}


def save(setup):
    use(setup)
    FILE.write_text(json.dumps(_current, indent=2), encoding="utf-8")


def set_own_belt(photo_path):
    """Copy a photo of your belt into the data folder (the original can then be moved or deleted)."""
    from PIL import Image, ImageOps
    OWN_BELT_FILE.parent.mkdir(parents=True, exist_ok=True)
    img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")   # new file: no camera/location data
    side = min(img.size)                                                 # the middle square
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                    (img.width + side) // 2, (img.height + side) // 2)).resize((512, 512))
    img.save(OWN_BELT_FILE)


def has_own_belt():
    return OWN_BELT_FILE.exists()


# ---------------------------------------------------------------- in simulation units (1 = 100 mm)
def camera_height():
    return load()["camera_height_mm"] / 100


def lamps(spread=1.2, rng=None):
    """[(position (x, y, z), brightness, colour rgb)] of the lamps; spread: how far apart along the belt.
    With rng, a little variety (for training pictures)."""
    s = load()
    n = int(s["lamps"])
    xs = np.linspace(-spread, spread, n) if n > 1 else np.zeros(1)
    each = 1.11 * s["brightness"] / n          # the built-in three lamps give 1.11 together
    w = s["warmth"]
    colour = np.array([1.0, 1.0 - 0.07 * w, 1.0 - 0.22 * w])
    out = []
    for x in xs:
        pos = np.array([x, -s["lamp_side_mm"] / 100, s["lamp_height_mm"] / 100])
        power = each
        if rng is not None:
            pos = pos + rng.normal(0, 0.1, 3)
            power *= rng.uniform(0.9, 1.1)
        out.append((pos, power, colour))
    return out
