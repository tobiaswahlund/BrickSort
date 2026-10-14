"""Where things live and the main knobs.

Code, the trained model and your corrections stay in the project folder
(so a cloud folder like OneDrive backs them up). Big, re-creatable things
(Python, downloads, rendered training pictures) go to the data folder,
C:\\Users\\<you>\\BrickSortData, so the cloud doesn't have to sync thousands of files.
Set BRICKSORT_DATA to put it somewhere else. (Folders made before the rename,
LegoSorterData or LEGOSORTER_DATA, keep working.)
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _data_dir():
    for var in ("BRICKSORT_DATA", "LEGOSORTER_DATA"):
        if os.environ.get(var):
            return Path(os.environ[var])
    old = Path.home() / "LegoSorterData"
    return old if old.exists() else Path.home() / "BrickSortData"


BIG_DIR = _data_dir()

DOWNLOADS = BIG_DIR / "downloads"
LDRAW_ZIP = DOWNLOADS / "ldraw_complete.zip"
RENDERS = BIG_DIR / "renders"            # renders/<part>/<n>.png

MODEL_DIR = PROJECT_DIR / "model"
MODEL_FILE = MODEL_DIR / "lego_model.pt"
PARTS_FILE = PROJECT_DIR / "parts.json"  # the parts the model knows + names
CATEGORY_PARTS_FILE = PROJECT_DIR / "category_parts.json"  # extra parts, learned by category only
CATEGORY_RENDERS = BIG_DIR / "renders_category"           # their pictures
REFERENCE = PROJECT_DIR / "reference"     # reference/<part>.png
CORRECTIONS = PROJECT_DIR / "corrections" # corrections/<part>/<time>.png (saved by the review window)
REST_LOG = PROJECT_DIR / "rest_bin"       # pictures of pieces the sorter put in the rest bin, to review
SORTED_LOG = PROJECT_DIR / "sorted_log"   # pictures of pieces the sorter did sort, for spot checks
SORTED_LOG_MAX = 500                      # keep only the newest this many
MY_PHOTOS = PROJECT_DIR / "my_photos"     # my_photos/<part>/*.jpg, my_photos/unknown/*.jpg (your own photos)
PHOTO_TYPES = (".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".webp")

# The part lists ship in defaults/ and are copied to the project folder the first time: the app
# changes the copies as you work (new parts, measurements), so those stay out of git.
# To publish your current lists, copy them back into defaults/.
DEFAULTS = PROJECT_DIR / "defaults"
WORKING_COPIES = ("parts.json", "category_parts.json", "custom_parts.json", "part_properties.json")


def _copy_defaults():
    import shutil
    for name in WORKING_COPIES:
        if not (PROJECT_DIR / name).exists() and (DEFAULTS / name).exists():
            shutil.copyfile(DEFAULTS / name, PROJECT_DIR / name)


_copy_defaults()

URLS = {
    "ldraw": "https://library.ldraw.org/library/updates/complete.zip",
    "parts": "https://cdn.rebrickable.com/media/downloads/parts.csv.gz",
    "inventory_parts": "https://cdn.rebrickable.com/media/downloads/inventory_parts.csv.gz",
    "colors": "https://cdn.rebrickable.com/media/downloads/colors.csv.gz",
    "part_categories": "https://cdn.rebrickable.com/media/downloads/part_categories.csv.gz",
    "part_relationships": "https://cdn.rebrickable.com/media/downloads/part_relationships.csv.gz",
}

TOP_N = 300            # how many of the most common parts to learn
IMAGES_PER_PART = 60   # simulated training pictures per part
IMAGE_SIZE = 224       # pixels fed to the model
