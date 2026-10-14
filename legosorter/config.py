"""Where things live and the main knobs.

Code, the trained model and your corrections stay in the LegoSorter folder
(so OneDrive backs them up). Big, re-creatable things (downloads, rendered
training pictures) go to C:\\Users\\<you>\\LegoSorterData so OneDrive doesn't
have to sync thousands of files.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
BIG_DIR = Path(os.environ.get("LEGOSORTER_DATA", Path.home() / "LegoSorterData"))

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
