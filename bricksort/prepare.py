"""Check before training: which pieces should be learned but have no 3D model?

Run:  python -m bricksort.prepare
Lists every photo folder (and custom/category part) without an LDraw 3D model, with
suggestions for a look-alike that does have one (Rebrickable's mold variants / alternates,
and LDraw files with a similar number). Go through the list before each training: when a
suggestion has the same shape, add it to catalog.MODEL_ALIASES; otherwise the piece is learned
from your photos only.
"""
import re

from . import catalog, config
from .ldraw import Library


def _photos(folder):
    return sum(1 for p in folder.rglob("*") if p.suffix.lower() in config.PHOTO_TYPES)


def missing_models(lib=None):
    lib = lib or Library()
    known_custom = {p["id"] for p in catalog.load_parts() if p.get("custom")}
    names = {r["part_num"]: r["name"] for r in catalog.read_csv("parts")}
    twins = catalog.twins()
    out = []
    for root in (config.MY_PHOTOS, config.CORRECTIONS):
        if not root.exists():
            continue
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            pid = catalog.folder_part(folder.name)
            if pid is None or pid in catalog.SPECIAL or pid in known_custom or lib.has_part(pid):
                continue
            ideas = [f"{o} ({kind}, {names.get(o, '')})" for o, kind in twins.get(pid, []) if lib.has_part(o)]
            stem = re.match(r"\d+", pid)
            if stem:
                ideas += [f"{k[:-4]} ({lib.title(k[:-4])})" for k in lib.index
                          if k.startswith(stem.group()) and k.endswith(".dat")][:5]
            out.append({"folder": f"{root.name}/{folder.name}", "part": pid, "name": names.get(pid, "not on Rebrickable"),
                        "photos": _photos(folder), "ideas": ideas})
    return out


if __name__ == "__main__":
    rows = missing_models()
    if not rows:
        print("Every piece to be trained has a 3D model (or is one of your custom pieces).")
    for r in rows:
        print(f"{r['folder']}: {r['part']} {r['name']} ({r['photos']} photos)")
        for i in r["ideas"]:
            print("   possible substitute:", i)
