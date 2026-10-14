"""Bring downloaded datasets into my_photos.

Dataset_01  "Images of LEGO bricks" (Gdańsk University of Technology, CC BY 4.0, doi:10.34808/arsb-4268)
            <category>/<part>/*.jpg, single pieces, colour not given
            -> my_photos/<part>/colour_not_specified/
Dataset_03  "B200 LEGO Detection Dataset" (Korra P, Kaggle, CC BY-SA 4.0), synthetic scenes of many pieces
            -> the whole pictures to my_photos/_multiple/dataset_03/
            -> and, for a sample of the pictures, every piece cut out using the dataset's boxes, with
               part and colour: my_photos/<part>/<colour>/

Run:  python -m legosorter.import_datasets 01        (move Dataset_01)
      python -m legosorter.import_datasets 03 [N]    (cut pieces from the first N scenes, then move all scenes)
"""
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from PIL import Image

from . import catalog, config
from .cut import square_crop

NO_COLOUR = "colour_not_specified"

# Dataset_03 colour codes (LEGO's 2016 moulding palette, see Dataset_03/color-scheme.png) -> Rebrickable names
B200_COLOURS = {
    "m0": "Yellow", "m1": "Orange", "m2": "Red", "m3": "Dark Pink", "m4": "Blue", "m5": "Dark Azure",
    "m6": "Yellowish Green", "m7": "Bright Green", "m8": "Lime", "m9": "Reddish Brown", "m10": "Nougat",
    "m11": "White", "m13": "Bright Light Yellow", "m14": "Bright Pink", "m15": "Medium Lavender",
    "m16": "Medium Blue", "m17": "Medium Azure", "m18": "Light Aqua", "m19": "Tan", "m20": "Light Nougat",
    "m21": "Bright Light Orange", "m22": "Magenta", "m23": "Lavender", "m24": "Bright Light Blue",
    "m25": "Sand Green", "m26": "Dark Tan", "m27": "Light Bluish Gray", "m28": "Dark Purple", "m29": "Sand Blue",
    "m30": "Green", "m31": "Olive Green", "m32": "Medium Nougat", "m33": "Dark Orange", "m34": "Dark Bluish Gray",
    "m35": "Dark Red", "m36": "Dark Blue", "m37": "Dark Green", "m38": "Dark Brown", "m39": "Black",
}


# Dataset_02 render file names use LEGO's own colour names -> Rebrickable names
LEGO_COLOURS = {
    "Black": "Black", "White": "White", "Bright Red": "Red", "Bright Blue": "Blue", "Bright Yellow": "Yellow",
    "Dark Green": "Green", "Bright Green": "Bright Green", "Earth Green": "Dark Green", "Bright Orange": "Orange",
    "Dark Orange": "Dark Orange", "Flame Yellowish Orange": "Bright Light Orange", "Cool Yellow": "Bright Light Yellow",
    "Brick Yellow": "Tan", "Sand Yellow": "Dark Tan", "Nougat": "Nougat", "Medium Nougat": "Medium Nougat",
    "Light Nougat": "Light Nougat", "Reddish Brown": "Reddish Brown", "Dark Brown": "Dark Brown", "Dark Red": "Dark Red",
    "Medium Stone Grey": "Light Bluish Gray", "Dark Stone Grey": "Dark Bluish Gray",
    "Light Stone Grey": "Very Light Bluish Gray", "Earth Blue": "Dark Blue", "Medium Blue": "Medium Blue",
    "Medium Azur": "Medium Azure", "Dark Azur": "Dark Azure", "Light Royal Blue": "Bright Light Blue",
    "Sand Blue": "Sand Blue", "Aqua": "Light Aqua", "Bright Bluish Green": "Dark Turquoise", "Sand Green": "Sand Green",
    "Olive Green": "Olive Green", "Bright Yellowish-Green": "Lime", "Medium-Yellowish green": "Medium Lime",
    "Spring Yellowish Green": "Yellowish Green", "Light Purple": "Bright Pink", "Bright Purple": "Dark Pink",
    "Bright Reddish Violet": "Magenta", "Medium Lavender": "Medium Lavender", "Lavender": "Lavender",
    "Medium Lilac": "Dark Purple", "White Glow": "Glow in Dark White",
}


def _dataset_01_names():
    """File names of every Dataset_01 photo, wherever it is now (checked, unchecked or thrown away)."""
    names = set()
    for root in (config.PROJECT_DIR / "_check" / "dataset_01_colours", config.MY_PHOTOS,
                 config.PROJECT_DIR / "_check" / "_deleted"):
        if root.exists():
            names.update(p.name for p in root.rglob("*") if p.suffix.lower() in config.PHOTO_TYPES)
    return names


def import_02(root=None):
    """Renders (part + colour known) -> my_photos/<part>/<colour>/d02_<name>.
    Photos that aren't copies of Dataset_01 photos -> colour guessed -> _check/dataset_01_colours,
    so they turn up in Check colours. Duplicates are left where they are."""
    from . import guess_colours
    root = root or config.PROJECT_DIR / "Dataset_02" / "second"
    known = catalog.color_by_name()
    moved, unknown_part, unknown_colour = 0, set(), set()
    for part_dir in sorted(p for p in (root / "renders").iterdir() if p.is_dir()):
        pid = catalog.folder_part(part_dir.name)
        if not pid:
            unknown_part.add(part_dir.name)
            continue
        for f in part_dir.iterdir():
            bits = f.name.split("_")
            colour = LEGO_COLOURS.get(bits[1]) if len(bits) >= 4 else None
            if colour is None or catalog.find_color(colour, known) is None:
                unknown_colour.add(bits[1] if len(bits) > 1 else f.name)
                continue
            dest = config.MY_PHOTOS / pid / colour
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / f"d02_{f.name}"
            if not target.exists():
                os.replace(f, target)
                moved += 1
        print(f"renders {pid}: {moved} moved so far", flush=True)
    print(f"Dataset_02 renders: moved {moved}. Parts not recognised: {sorted(unknown_part) or 'none'}. "
          f"Colours not recognised: {sorted(unknown_colour) or 'none'}", flush=True)

    seen = _dataset_01_names()
    table = catalog.colors(include_trans=True)
    new = dupes = 0
    for part_dir in sorted(p for p in (root / "photos").iterdir() if p.is_dir()):
        pid = catalog.folder_part(part_dir.name)
        if not pid:
            unknown_part.add(part_dir.name)
            continue
        for f in sorted(part_dir.iterdir()):
            if f.suffix.lower() not in config.PHOTO_TYPES:
                continue
            if f.name in seen:
                dupes += 1
                continue
            try:
                a, b = guess_colours.guess(f, pid, table), guess_colours.guess_with_model(f, pid, table)
                colour = a if a == b else f"_check - {a} or {b}"
            except Exception:
                colour = NO_COLOUR
            dest = guess_colours.OUT / pid / colour
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest / f.name))
            new += 1
        print(f"photos {pid}: {new} new so far", flush=True)
    print(f"Dataset_02 photos: {new} new ones added to Check colours, {dupes} duplicates of Dataset_01 left in place")


def _move(src, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        dst = dst_dir / f"{src.stem}_{abs(hash(str(src))) % 10**6}{src.suffix}"
    shutil.move(str(src), str(dst))


def import_01(root=None):
    root = root or config.PROJECT_DIR / "Dataset_01"
    moved, parts = 0, set()
    for part_dir in sorted(p for cat in root.iterdir() if cat.is_dir() for p in cat.iterdir() if p.is_dir()):
        pid = catalog.folder_part(re.split(r"[_ ]", part_dir.name)[0])  # "3003_6223" -> 3003
        if not pid:
            continue
        for f in sorted(part_dir.iterdir()):
            if f.suffix.lower() in config.PHOTO_TYPES:
                _move(f, config.MY_PHOTOS / pid / NO_COLOUR)
                moved += 1
        parts.add(pid)
        print(f"{pid}: done ({moved} photos so far)", flush=True)
    print(f"Dataset_01: moved {moved} photos of {len(parts)} parts")


def _crowding(boxes, i):
    """Share of box i that other pieces' boxes cover (0 = alone, 1 = completely covered)."""
    x0, y0, x1, y1 = boxes[i]
    covered = 0
    for j, (a0, b0, a1, b1) in enumerate(boxes):
        if j != i:
            covered += max(0, min(x1, a1) - max(x0, a0)) * max(0, min(y1, b1) - max(y0, b0))
    return min(1.0, covered / max(1, (x1 - x0) * (y1 - y0)))


MAX_CROWDING = 0.25   # skip cut-outs where other pieces cover more than this share of the picture


def import_03(sample=100, root=None, min_box=24, log=None, start=0, images_dir=None, move=True):
    """log: list that gets (crowding, size, saved path) for every cut-out (to find the worst ones).
    start/images_dir/move: cut scenes start..start+sample from where they are now, without moving them."""
    root = root or config.PROJECT_DIR / "Dataset_03"
    known_colours = catalog.color_by_name()
    images = sorted((images_dir or root / "images").glob("*.png"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
    cut = skipped = crowded = 0
    for img_path in images[start:start + sample]:
        ann = root / "annotations" / f"{img_path.stem}.xml"
        if not ann.exists():
            continue
        img = Image.open(img_path).convert("RGB")
        objs = list(ET.parse(ann).getroot().iter("object"))
        boxes = [[int(float(o.find("bndbox").findtext(k))) for k in ("xmin", "ymin", "xmax", "ymax")] for o in objs]
        for i, obj in enumerate(objs):
            pid = catalog.folder_part(obj.findtext("name", "").strip())
            colour = B200_COLOURS.get(obj.findtext("color", "").strip())
            box = boxes[i]
            if not pid or box[2] - box[0] < min_box or box[3] - box[1] < min_box:
                skipped += 1
                continue
            crowding = _crowding(boxes, i)
            if crowding > MAX_CROWDING:
                crowded += 1
                continue
            if colour is None or catalog.find_color(colour, known_colours) is None:
                colour = NO_COLOUR
            out = config.MY_PHOTOS / pid / colour
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"b200_{img_path.stem}_{i}.png"
            square_crop(img, box).save(path)
            if log is not None:
                log.append((crowding, min(box[2] - box[0], box[3] - box[1]), path))
            cut += 1
        print(f"scene {img_path.stem}: {cut} pieces cut out so far", flush=True)
    print(f"Dataset_03: cut out {cut} pieces from {len(images[start:start + sample])} scenes "
          f"({skipped} too small/unknown, {crowded} skipped as too crowded)")
    if not move:
        return
    dest = config.MY_PHOTOS / "_multiple" / "dataset_03"
    for img_path in images:
        _move(img_path, dest)
    print(f"Dataset_03: moved {len(images)} scene pictures to {dest}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "01":
        import_01()
    elif which == "02":
        import_02()
    elif which == "03":
        import_03(int(sys.argv[2]) if len(sys.argv) > 2 else 100)
    elif which == "03rest":  # the scenes are already in my_photos/_multiple/dataset_03: cut the rest there
        import_03(10**6, start=int(sys.argv[2]) if len(sys.argv) > 2 else 100,
                  images_dir=config.MY_PHOTOS / "_multiple" / "dataset_03", move=False)
